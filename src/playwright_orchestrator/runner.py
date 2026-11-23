from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from .artifacts import artifact_root, new_artifact_path, prune_artifacts
from .locks import LockManager, ProfileBusy, valid_profile_name
from .paths import (
    AUTH_MARKER,
    CHROMIUM_HEALTH_PATH,
    CONFIG_ROOT,
    PROFILE_CONFIG_PATH,
    PROFILE_ROOT,
)


REF_PATTERN = re.compile(r"\[ref=(e\d+)\]")
SESSION_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")
EXPECTED_CLI_VERSION = "0.1.25"

ALLOWED_STEP_COMMANDS = frozenset(
    {
        "open",
        "close",
        "goto",
        "type",
        "click",
        "dblclick",
        "fill",
        "drag",
        "drop",
        "hover",
        "select",
        "upload",
        "check",
        "uncheck",
        "snapshot",
        "find",
        "eval",
        "dialog-accept",
        "dialog-dismiss",
        "resize",
        "go-back",
        "go-forward",
        "reload",
        "press",
        "keydown",
        "keyup",
        "mousemove",
        "mousedown",
        "mouseup",
        "mousewheel",
        "screenshot",
        "pdf",
        "tab-list",
        "tab-new",
        "tab-close",
        "tab-select",
        "cookie-list",
        "cookie-get",
        "localstorage-list",
        "localstorage-get",
        "sessionstorage-list",
        "sessionstorage-get",
        "set-color-scheme",
        "clear-color-scheme",
        "set-reduced-motion",
        "clear-reduced-motion",
        "set-forced-colors",
        "clear-forced-colors",
        "set-contrast",
        "clear-contrast",
        "set-media",
        "clear-media",
        "requests",
        "request",
        "request-headers",
        "request-body",
        "response-headers",
        "response-body",
        "route",
        "route-list",
        "unroute",
        "network-state-set",
        "console",
        "run-code",
        "recording-start",
        "recording-stop",
        "video-start",
        "video-stop",
        "video-chapter",
        "generate-locator",
        "highlight",
        "pause-at",
        "resume",
        "step-over",
        "webmcp-list",
        "webmcp-call",
    }
)

FORBIDDEN_OPEN_OPTIONS = {"--persistent", "--profile", "--config", "--headed"}


def valid_session_name(session: str) -> bool:
    return bool(SESSION_PATTERN.fullmatch(session))


def validate_step(step: list[str]) -> None:
    if not step:
        raise ValueError("browser step cannot be empty")
    command = step[0]
    if command not in ALLOWED_STEP_COMMANDS:
        raise ValueError(f"unsupported browser operation: {command}")
    if command == "open":
        for value in step[1:]:
            option = value.split("=", 1)[0]
            if option in FORBIDDEN_OPEN_OPTIONS:
                raise ValueError(f"open option is managed by the orchestrator: {option}")
    if command == "close" and len(step) != 1:
        raise ValueError("close accepts no arguments")


@dataclass
class StepResult:
    step: list[str]
    returncode: int
    stdout: str
    stderr: str
    duration_ms: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "step": self.step,
            "returncode": self.returncode,
            "stdout": self.stdout[-8000:],
            "stderr": self.stderr[-4000:],
            "duration_ms": self.duration_ms,
        }


@dataclass
class RunResult:
    profile: str
    session: str
    status: str
    steps: list[StepResult] = field(default_factory=list)
    snapshot_path: str | None = None
    refs: list[str] = field(default_factory=list)
    message: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "profile": self.profile,
            "session": self.session,
            "status": self.status,
            "steps": [step.to_dict() for step in self.steps],
            "snapshot_path": self.snapshot_path,
            "refs": self.refs,
            "message": self.message,
        }


def parse_steps(steps: Iterable[str | list[str]]) -> list[list[str]]:
    parsed: list[list[str]] = []
    for step in steps:
        if isinstance(step, str):
            values = shlex.split(step)
        else:
            values = [str(value) for value in step]
        if values:
            validate_step(values)
            parsed.append(values)
    return parsed


def _profile_metadata() -> dict[str, dict[str, Any]]:
    try:
        data = json.loads(PROFILE_CONFIG_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def chromium_path() -> Path:
    try:
        health = json.loads(CHROMIUM_HEALTH_PATH.read_text(encoding="utf-8"))
        path = Path(str(health.get("path", "")))
        if health.get("healthy") and path.is_file():
            return path
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    preferred = Path.home() / ".cache/ms-playwright/chromium-1234/chrome-linux64/chrome"
    if preferred.is_file():
        return preferred
    raise FileNotFoundError(
        "Chromium 1234 is required for signed-in profiles and was not found. "
        "The orchestrator will not switch signed-in profiles to another build."
    )


def display_available(display: str) -> bool:
    if not display:
        return True
    match = re.fullmatch(r":(\d+)(?:\.\d+)?", display)
    if not match:
        return False
    number = match.group(1)
    return Path(f"/tmp/.X11-unix/X{number}").exists()


def auth_waiting() -> bool:
    return AUTH_MARKER.exists()


class Runner:
    def __init__(
        self,
        *,
        cli_bin: str | None = None,
        timeout: int = 120,
        lock_manager: LockManager | None = None,
        expected_cli_version: str = EXPECTED_CLI_VERSION,
    ):
        self.cli_bin = cli_bin or os.environ.get(
            "PLAYWRIGHT_CLI_BIN",
            str(Path.home() / ".local/bin/playwright-cli"),
        )
        self.timeout = timeout
        self.lock_manager = lock_manager or LockManager()
        self.expected_cli_version = expected_cli_version
        self._verified_cli_version: str | None = None

    def cli_version(self) -> str:
        completed = subprocess.run(
            [self.cli_bin, "--version"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        output = f"{completed.stdout}\n{completed.stderr}"
        match = re.search(r"\b\d+\.\d+\.\d+\b", output)
        if completed.returncode != 0 or not match:
            raise RuntimeError(f"could not determine Playwright CLI version: {output.strip()}")
        return match.group(0)

    def verify_cli_version(self) -> str:
        if self._verified_cli_version is None:
            version = self.cli_version()
            if version != self.expected_cli_version:
                raise RuntimeError(
                    f"Playwright CLI version {version} is not supported; "
                    f"expected {self.expected_cli_version}"
                )
            self._verified_cli_version = version
        return self._verified_cli_version

    def _config(
        self,
        *,
        profile: str,
        session: str,
        headless: bool,
        ephemeral: bool,
    ) -> Path:
        CONFIG_ROOT.mkdir(parents=True, exist_ok=True)
        output_dir = artifact_root() / session
        output_dir.mkdir(parents=True, exist_ok=True)
        browser: dict[str, Any] = {
            "browserName": "chromium",
            "isolated": ephemeral,
            "launchOptions": {
                "headless": headless,
                "executablePath": str(chromium_path()),
                "args": ["--no-sandbox", "--disable-dev-shm-usage"],
            },
        }
        if not ephemeral:
            profile_dir = PROFILE_ROOT / profile
            if not profile_dir.is_dir():
                raise FileNotFoundError(f"profile directory does not exist: {profile_dir}")
            browser["userDataDir"] = str(profile_dir)
        config = {
            "browser": browser,
            "outputDir": str(output_dir),
            "outputMode": "file",
            "console": {"level": "warning"},
        }
        if not valid_session_name(session):
            raise ValueError(f"invalid session name: {session!r}")
        root = CONFIG_ROOT.resolve()
        path = (CONFIG_ROOT / f"{session}.json").resolve()
        if path.parent != root:
            raise ValueError("session config path escaped the config directory")
        path.write_text(json.dumps(config, indent=2), encoding="utf-8")
        path.chmod(0o600)
        return path

    def _run_step(
        self,
        config: Path,
        session: str,
        step: list[str],
        *,
        display: str | None,
    ) -> StepResult:
        validate_step(step)
        env = os.environ.copy()
        if display:
            env["DISPLAY"] = display
        command = [self.cli_bin, f"-s={session}", *step]
        if step and step[0] == "open":
            command.append(f"--config={config}")
        started = time.monotonic()
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=self.timeout,
                env=env,
                check=False,
            )
            return StepResult(
                step=step,
                returncode=completed.returncode,
                stdout=completed.stdout,
                stderr=completed.stderr,
                duration_ms=int((time.monotonic() - started) * 1000),
            )
        except subprocess.TimeoutExpired as exc:
            return StepResult(
                step=step,
                returncode=124,
                stdout=exc.stdout or "",
                stderr=f"timeout after {self.timeout} seconds",
                duration_ms=int((time.monotonic() - started) * 1000),
            )

    def _active_artifact_roots(self) -> list[Path]:
        root = artifact_root()
        roots: list[Path] = []
        for record in self.lock_manager.status():
            session = str(record.get("session", ""))
            if session:
                roots.append(root / session)
        return roots

    def _prune(self, protected_paths: Iterable[Path] = ()) -> dict[str, int | float]:
        return prune_artifacts(
            active_roots=self._active_artifact_roots(),
            protected_paths=list(protected_paths),
        )

    def run(
        self,
        profile: str,
        steps: Iterable[str | list[str]],
        *,
        headless: bool = True,
        display: str | None = None,
        keep_open: bool = False,
        ephemeral: bool = False,
        session: str | None = None,
        allow_auth_waiting: bool = False,
        protected_paths: Iterable[Path] = (),
    ) -> RunResult:
        parsed = parse_steps(steps)
        if not parsed:
            raise ValueError("at least one browser step is required")
        if not ephemeral and not valid_profile_name(profile):
            raise ValueError(f"invalid profile name: {profile!r}")
        if session is not None and not valid_session_name(session):
            raise ValueError(f"invalid session name: {session!r}")
        self.verify_cli_version()
        if not headless and display and not display_available(display):
            return RunResult(
                profile=profile,
                session=session or "",
                status="display_unavailable",
                message=f"display is not available: {display}",
            )
        if auth_waiting() and not allow_auth_waiting:
            return RunResult(
                profile=profile,
                session=session or "",
                status="auth_waiting",
                message=f"authentication marker exists: {AUTH_MARKER}",
            )

        lock_key = profile
        if ephemeral:
            lock_key = f"ephemeral_{uuid.uuid4().hex[:16]}"
        requested_session = session or f"pw-{re.sub(r'[^A-Za-z0-9_-]', '-', profile)}-{uuid.uuid4().hex[:8]}"
        try:
            owner = self.lock_manager.acquire(
                lock_key,
                session=requested_session,
                display=display,
                ephemeral=ephemeral,
            )
        except ProfileBusy as exc:
            return RunResult(
                profile=profile,
                session=requested_session,
                status="profile_busy",
                message=str(exc),
            )
        actual_session = owner.session
        config = self._config(
            profile=profile,
            session=actual_session,
            headless=headless,
            ephemeral=ephemeral,
        )
        self._prune(protected_paths)
        results: list[StepResult] = []
        paused = False
        try:
            for step in parsed:
                if auth_waiting() and not allow_auth_waiting:
                    paused = True
                    break
                result = self._run_step(
                    config,
                    actual_session,
                    step,
                    display=display,
                )
                results.append(result)
                if result.returncode != 0:
                    break
            if not paused and not keep_open:
                if not any(step[:1] == ["close"] for step in parsed):
                    results.append(
                        self._run_step(
                            config,
                            actual_session,
                            ["close"],
                            display=display,
                        )
                    )
            if not paused and not keep_open:
                self.lock_manager.release(lock_key)
            failed = any(step.returncode != 0 for step in results)
            status = "auth_waiting" if paused else ("error" if failed else "ok")
            return RunResult(
                profile=profile,
                session=actual_session,
                status=status,
                steps=results,
                message="authentication marker paused the session" if paused else None,
            )
        finally:
            if not paused and not keep_open:
                self.lock_manager.release(lock_key)
            self._prune(protected_paths)

    def snapshot(
        self,
        profile: str,
        *,
        selector: str | None = None,
        url: str | None = None,
        depth: int | None = None,
        find: str | None = None,
        fill_ref: dict[str, str] | None = None,
        headless: bool = True,
        display: str | None = None,
        ephemeral: bool = False,
    ) -> RunResult:
        target = new_artifact_path(f"pw-{profile}", ".yml")
        step = ["snapshot", f"--filename={target}"]
        if selector:
            step.append(selector)
        if depth is not None:
            step.append(f"--depth={depth}")
        steps: list[list[str]] = [["open", url or "about:blank"]]
        if find:
            steps.append(["find", find])
        else:
            steps.append(step)
            if fill_ref:
                ref = str(fill_ref.get("ref", ""))
                value = str(fill_ref.get("value", ""))
                if not ref:
                    raise ValueError("fill_ref.ref is required")
                steps.append(["fill", ref, value])
        result = self.run(
            profile,
            steps,
            headless=headless,
            display=display,
            ephemeral=ephemeral,
            protected_paths=[target],
        )
        if not find and target.exists():
            text = target.read_text(encoding="utf-8", errors="replace")
            result.snapshot_path = str(target)
            result.refs = list(dict.fromkeys(REF_PATTERN.findall(text)))
        return result
