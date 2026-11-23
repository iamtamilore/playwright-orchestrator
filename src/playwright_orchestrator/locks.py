from __future__ import annotations

import errno
import fcntl
import json
import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .paths import LOCK_ROOT, REGISTRY_LOCK_PATH, REGISTRY_PATH, STATE_ROOT


PROFILE_NAME_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$"


class ProfileBusy(RuntimeError):
    def __init__(self, profile: str, owner: dict[str, Any] | None):
        self.profile = profile
        self.owner = owner or {}
        super().__init__(f"profile_busy: {profile}")


class InvalidProfile(ValueError):
    pass


@dataclass
class LockOwner:
    profile: str
    daemon_pid: int
    server_pid: int
    owner: str
    session: str
    display: str | None
    started_at: float
    last_activity: float
    ephemeral: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def valid_profile_name(profile: str) -> bool:
    import re

    return bool(re.fullmatch(PROFILE_NAME_PATTERN, profile))


def pid_alive(pid: int | None) -> bool:
    if not pid or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def _read_registry_unlocked() -> dict[str, dict[str, Any]]:
    try:
        data = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _read_registry() -> dict[str, dict[str, Any]]:
    REGISTRY_LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    with REGISTRY_LOCK_PATH.open("a+") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            registry = _read_registry_unlocked()
            changed = False
            for profile, record in list(registry.items()):
                if not pid_alive(int(record.get("daemon_pid", 0))):
                    registry.pop(profile, None)
                    changed = True
            if changed:
                _write_registry_unlocked(registry)
            return registry
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _write_registry_unlocked(registry: dict[str, dict[str, Any]]) -> None:
    REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(
        prefix=f".{REGISTRY_PATH.name}.",
        suffix=".tmp",
        dir=REGISTRY_PATH.parent,
        text=True,
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(registry, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temp_name, 0o600)
        os.replace(temp_name, REGISTRY_PATH)
    finally:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass


def _update_registry(profile: str, record: dict[str, Any] | None) -> None:
    REGISTRY_LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    with REGISTRY_LOCK_PATH.open("a+") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            registry = _read_registry_unlocked()
            for name, old in list(registry.items()):
                if not pid_alive(int(old.get("daemon_pid", 0))):
                    registry.pop(name, None)
            if record is None:
                registry.pop(profile, None)
            else:
                registry[profile] = record
            _write_registry_unlocked(registry)
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _delete_registry_owner(profile: str, daemon_pid: int) -> bool:
    REGISTRY_LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    with REGISTRY_LOCK_PATH.open("a+") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            registry = _read_registry_unlocked()
            current = registry.get(profile)
            if not current or int(current.get("daemon_pid", 0)) != daemon_pid:
                return False
            registry.pop(profile, None)
            _write_registry_unlocked(registry)
            return True
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def lock_path(profile: str) -> Path:
    if not valid_profile_name(profile):
        raise InvalidProfile(f"invalid profile name: {profile!r}")
    return LOCK_ROOT / f"{profile}.lock"


class LockManager:
    def __init__(
        self,
        *,
        server_pid: int | None = None,
        owner: str | None = None,
        state_root: Path | None = None,
    ):
        self.server_pid = server_pid or os.getpid()
        self.owner = owner or f"server:{self.server_pid}"
        self.state_root = state_root or STATE_ROOT

    def acquire(
        self,
        profile: str,
        *,
        session: str,
        display: str | None = None,
        ephemeral: bool = False,
        timeout: float = 3.0,
    ) -> LockOwner:
        if not valid_profile_name(profile):
            raise InvalidProfile(f"invalid profile name: {profile!r}")
        registry = _read_registry()
        current = registry.get(profile)
        if current and pid_alive(int(current.get("daemon_pid", 0))):
            if (
                int(current.get("server_pid", 0)) == self.server_pid
                and str(current.get("session", "")) == session
            ):
                return LockOwner(**current)
            raise ProfileBusy(profile, current)

        LOCK_ROOT.mkdir(parents=True, exist_ok=True)
        token = uuid.uuid4().hex
        result_path = self.state_root / "locks" / f".result-{token}.json"
        command = [
            sys.executable,
            "-m",
            "playwright_orchestrator.lock_cli",
            "daemon",
            "--profile",
            profile,
            "--session",
            session,
            "--owner",
            self.owner,
            "--server-pid",
            str(self.server_pid),
            "--display",
            display or "",
            "--result",
            str(result_path),
        ]
        if ephemeral:
            command.append("--ephemeral")
        subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                result = json.loads(result_path.read_text(encoding="utf-8"))
            except (FileNotFoundError, json.JSONDecodeError):
                time.sleep(0.05)
                continue
            try:
                result_path.unlink()
            except FileNotFoundError:
                pass
            if result.get("ok"):
                return LockOwner(**result["owner"])
            owner = result.get("owner")
            raise ProfileBusy(profile, owner)
        raise TimeoutError(f"timed out acquiring profile lock: {profile}")

    def release(self, profile: str, *, server_pid: int | None = None) -> bool:
        owner_pid = self.server_pid if server_pid is None else server_pid
        registry = _read_registry()
        record = registry.get(profile)
        if not record:
            return False
        if int(record.get("server_pid", 0)) != owner_pid:
            return False
        daemon_pid = int(record.get("daemon_pid", 0))
        if pid_alive(daemon_pid):
            try:
                os.kill(daemon_pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            for _ in range(40):
                if not pid_alive(daemon_pid):
                    break
                time.sleep(0.05)
        _delete_registry_owner(profile, daemon_pid)
        return True

    def status(self) -> list[dict[str, Any]]:
        return list(_read_registry().values())

    def owner_for(self, profile: str) -> dict[str, Any] | None:
        return _read_registry().get(profile)


def run_lock_daemon(
    profile: str,
    *,
    session: str,
    owner: str,
    server_pid: int,
    display: str,
    result_path: Path,
    ephemeral: bool = False,
) -> int:
    LOCK_ROOT.mkdir(parents=True, exist_ok=True)
    lock_file = lock_path(profile).open("a+")
    try:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:
        if exc.errno not in (errno.EACCES, errno.EAGAIN):
            raise
        registry = _read_registry()
        result = {"ok": False, "error": "profile_busy", "owner": registry.get(profile)}
        result_path.parent.mkdir(parents=True, exist_ok=True)
        result_path.write_text(json.dumps(result), encoding="utf-8")
        lock_file.close()
        return 2

    now = time.time()
    record = LockOwner(
        profile=profile,
        daemon_pid=os.getpid(),
        server_pid=server_pid,
        owner=owner,
        session=session,
        display=display or None,
        started_at=now,
        last_activity=now,
        ephemeral=ephemeral,
    ).to_dict()
    _update_registry(profile, record)

    stopping = threading.Event()

    def stop_handler(_signum: int, _frame: Any) -> None:
        stopping.set()

    signal.signal(signal.SIGTERM, stop_handler)
    signal.signal(signal.SIGINT, stop_handler)

    def heartbeat() -> None:
        while not stopping.wait(5):
            current = _read_registry().get(profile)
            if not current or int(current.get("daemon_pid", 0)) != os.getpid():
                break
            if not pid_alive(server_pid):
                stopping.set()
                break
            current["last_activity"] = time.time()
            _update_registry(profile, current)

    thread = threading.Thread(target=heartbeat, daemon=True)
    thread.start()

    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text(
        json.dumps({"ok": True, "owner": record}),
        encoding="utf-8",
    )

    try:
        while not stopping.wait(0.2):
            pass
    finally:
        current = _read_registry().get(profile)
        if current and int(current.get("daemon_pid", 0)) == os.getpid():
            _update_registry(profile, None)
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
        finally:
            lock_file.close()
    return 0
