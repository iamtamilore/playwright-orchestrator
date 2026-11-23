from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from .artifacts import prune_artifacts
from .locks import LockManager, ProfileBusy
from .runner import Runner, auth_waiting, display_available
from .paths import AUTH_MARKER


SERVER_NAME = "playwright-orchestrator"
SERVER_VERSION = "0.1.0"


TOOLS = [
    {
        "name": "pw_run_session",
        "description": "Run ordered Playwright CLI steps against one named profile.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "profile": {"type": "string"},
                "steps": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Shell-quoted Playwright CLI steps, run in order.",
                },
                "headless": {"type": "boolean", "default": True},
                "display": {"type": "string"},
                "keep_open": {"type": "boolean", "default": False},
                "session": {"type": "string"},
            },
            "required": ["profile", "steps"],
            "additionalProperties": False,
        },
    },
    {
        "name": "pw_parallel_batch",
        "description": "Run independent browser jobs concurrently and report each result.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "jobs": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string"},
                            "profile": {"type": "string"},
                            "steps": {"type": "array", "items": {"type": "string"}},
                            "headless": {"type": "boolean", "default": True},
                            "display": {"type": "string"},
                            "ephemeral": {"type": "boolean", "default": True},
                        },
                        "required": ["id", "steps"],
                        "additionalProperties": False,
                    },
                }
            },
            "required": ["jobs"],
            "additionalProperties": False,
        },
    },
    {
        "name": "pw_snapshot",
        "description": "Save a page snapshot, return its path and element refs, and optionally fill a ref.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "profile": {"type": "string"},
                "selector": {"type": "string"},
                "url": {"type": "string"},
                "depth": {"type": "integer", "minimum": 1},
                "find": {"type": "string"},
                "fill_ref": {
                    "type": "object",
                    "properties": {
                        "ref": {"type": "string"},
                        "value": {"type": "string"},
                    },
                    "required": ["ref", "value"],
                    "additionalProperties": False,
                },
                "headless": {"type": "boolean", "default": True},
                "display": {"type": "string"},
                "ephemeral": {"type": "boolean", "default": False},
            },
            "required": ["profile"],
            "additionalProperties": False,
        },
    },
    {
        "name": "pw_profile_locks",
        "description": "List persistent profile lock owners and live browser sessions.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "pw_dashboard_status",
        "description": "Report Playwright Dashboard availability, live sessions, and auth pause state.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "display": {"type": "string"},
                "start": {"type": "boolean", "default": False},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "pw_interactive_handoff",
        "description": "Open a headed persistent profile for human takeover and return its session handle.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "profile": {"type": "string"},
                "url": {"type": "string"},
                "display": {"type": "string", "default": ":0"},
            },
            "required": ["profile"],
            "additionalProperties": False,
        },
    },
]


class Orchestrator:
    def __init__(self, runner: Runner | None = None):
        self.runner = runner or Runner()
        self.lock_manager = self.runner.lock_manager

    def _process_command_lines(self) -> list[str]:
        lines: list[str] = []
        proc = "/proc"
        try:
            entries = os.scandir(proc)
        except OSError:
            return lines
        with entries:
            for entry in entries:
                if not entry.name.isdigit():
                    continue
                try:
                    raw = Path(entry.path, "cmdline").read_bytes()
                except OSError:
                    continue
                values = [part.decode(errors="replace") for part in raw.split(b"\0") if part]
                if values:
                    lines.append(" ".join(values))
        return lines

    def pw_run_session(self, params: dict[str, Any]) -> dict[str, Any]:
        result = self.runner.run(
            str(params["profile"]),
            params.get("steps", []),
            headless=bool(params.get("headless", True)),
            display=params.get("display"),
            keep_open=bool(params.get("keep_open", False)),
            session=params.get("session"),
        )
        return result.to_dict()

    def pw_parallel_batch(self, params: dict[str, Any]) -> dict[str, Any]:
        jobs = params.get("jobs", [])
        results: list[dict[str, Any]] = []
        with ThreadPoolExecutor(max_workers=min(8, max(1, len(jobs)))) as pool:
            futures = {}
            for job in jobs:
                profile = str(job.get("profile") or f"ephemeral_{job['id']}")
                future = pool.submit(
                    self.runner.run,
                    profile,
                    job.get("steps", []),
                    headless=bool(job.get("headless", True)),
                    display=job.get("display"),
                    keep_open=False,
                    ephemeral=bool(job.get("ephemeral", True)),
                )
                futures[future] = job
            for future in as_completed(futures):
                job = futures[future]
                try:
                    payload = future.result().to_dict()
                except Exception as exc:
                    payload = {"status": "error", "message": str(exc)}
                payload["id"] = job["id"]
                results.append(payload)
        order = {str(job["id"]): index for index, job in enumerate(jobs)}
        results.sort(key=lambda item: order.get(str(item.get("id")), 0))
        prune_artifacts()
        return {"jobs": results}

    def pw_snapshot(self, params: dict[str, Any]) -> dict[str, Any]:
        result = self.runner.snapshot(
            str(params["profile"]),
            selector=params.get("selector"),
            url=params.get("url"),
            depth=params.get("depth"),
            find=params.get("find"),
            fill_ref=params.get("fill_ref"),
            headless=bool(params.get("headless", True)),
            display=params.get("display"),
            ephemeral=bool(params.get("ephemeral", False)),
        )
        return result.to_dict()

    def pw_profile_locks(self, _params: dict[str, Any]) -> dict[str, Any]:
        return {"locks": self.lock_manager.status()}

    def pw_dashboard_status(self, params: dict[str, Any]) -> dict[str, Any]:
        cli = self.runner.cli_bin
        cli_available = bool(shutil.which(cli) or os.path.isabs(cli) and os.path.exists(cli))
        display = params.get("display")
        dashboard_running = any(
            "playwright-cli.js" in line and " show" in line
            for line in self._process_command_lines()
        )
        sessions: list[str] = []
        version: str | None = None
        version_error: str | None = None
        if cli_available:
            try:
                version = self.runner.cli_version()
            except Exception as exc:
                version_error = str(exc)
            completed = subprocess.run(
                [cli, "--json", "list"],
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
            )
            try:
                payload = json.loads(completed.stdout)
            except json.JSONDecodeError:
                payload = {}
            browsers = payload.get("browsers", []) if isinstance(payload, dict) else []
            if isinstance(browsers, list):
                sessions = [
                    str(item.get("name"))
                    for item in browsers
                    if isinstance(item, dict) and item.get("name")
                ]
        started = False
        if params.get("start") and cli_available and display and display_available(display):
            env = os.environ.copy()
            env["DISPLAY"] = display
            subprocess.Popen(
                [cli, "show"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=env,
                start_new_session=True,
            )
            started = True
        return {
            "cli_available": cli_available,
            "cli_version": version,
            "cli_version_error": version_error,
            "dashboard_running": dashboard_running,
            "dashboard_started": started,
            "display": display,
            "display_available": display_available(display) if display else None,
            "auth_waiting": auth_waiting(),
            "auth_marker": str(AUTH_MARKER),
            "sessions": sessions,
        }

    def pw_interactive_handoff(self, params: dict[str, Any]) -> dict[str, Any]:
        profile = str(params["profile"])
        display = str(params.get("display") or ":0")
        steps: list[str] = ["open"]
        if params.get("url"):
            steps.append(str(params["url"]))
        owner = self.lock_manager.owner_for(profile)
        if owner and int(owner.get("server_pid", 0)) == os.getpid():
            previous_session = str(owner.get("session", ""))
            if previous_session:
                try:
                    subprocess.run(
                        [self.runner.cli_bin, f"-s={previous_session}", "close"],
                        capture_output=True,
                        text=True,
                        timeout=30,
                        check=False,
                    )
                except Exception:
                    pass
            self.lock_manager.release(profile)
        result = self.runner.run(
            profile,
            [steps],
            headless=False,
            display=display,
            keep_open=True,
            allow_auth_waiting=True,
        )
        payload = result.to_dict()
        payload["handoff"] = True
        payload["resume_tool"] = "pw_run_session"
        payload["resume_session"] = payload.get("session")
        if auth_waiting():
            payload["message"] = (
                "Complete authentication in the headed browser, clear the auth marker, "
                "then resume this session with pw_run_session."
            )
        return payload

    def close_owned_sessions(self) -> list[str]:
        closed: list[str] = []
        for record in self.lock_manager.status():
            if int(record.get("server_pid", 0)) != os.getpid():
                continue
            profile = str(record.get("profile", ""))
            session = str(record.get("session", ""))
            if not profile or not session:
                continue
            try:
                subprocess.run(
                    [self.runner.cli_bin, f"-s={session}", "close"],
                    capture_output=True,
                    text=True,
                    timeout=30,
                    check=False,
                )
            except Exception:
                pass
            self.lock_manager.release(profile)
            closed.append(session)
        return closed

    def call(self, name: str, params: dict[str, Any]) -> dict[str, Any]:
        handlers = {
            "pw_run_session": self.pw_run_session,
            "pw_parallel_batch": self.pw_parallel_batch,
            "pw_snapshot": self.pw_snapshot,
            "pw_profile_locks": self.pw_profile_locks,
            "pw_dashboard_status": self.pw_dashboard_status,
            "pw_interactive_handoff": self.pw_interactive_handoff,
        }
        handler = handlers.get(name)
        if handler is None:
            raise ValueError(f"unknown tool: {name}")
        return handler(params)


class MCPStdioServer:
    def __init__(self, orchestrator: Orchestrator | None = None):
        self.orchestrator = orchestrator or Orchestrator()

    def handle(self, message: dict[str, Any]) -> dict[str, Any] | None:
        method = message.get("method")
        request_id = message.get("id")
        params = message.get("params") or {}
        if request_id is None:
            return None
        if method == "initialize":
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "protocolVersion": params.get("protocolVersion", "2024-11-05"),
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
                },
            }
        if method == "ping":
            return {"jsonrpc": "2.0", "id": request_id, "result": {}}
        if method == "tools/list":
            return {"jsonrpc": "2.0", "id": request_id, "result": {"tools": TOOLS}}
        if method == "tools/call":
            try:
                payload = self.orchestrator.call(str(params.get("name", "")), params.get("arguments") or {})
                is_error = payload.get("status") == "error"
                return {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {
                        "content": [{"type": "text", "text": json.dumps(payload, indent=2)}],
                        "isError": is_error,
                    },
                }
            except Exception as exc:
                return {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {
                        "content": [{"type": "text", "text": str(exc)}],
                        "isError": True,
                    },
                }
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": -32601, "message": f"method not found: {method}"},
        }

    def serve(self, stdin=None, stdout=None) -> int:
        stdin = stdin or sys.stdin
        stdout = stdout or sys.stdout
        try:
            for line in stdin:
                line = line.strip()
                if not line:
                    continue
                try:
                    message = json.loads(line)
                except json.JSONDecodeError as exc:
                    response = {
                        "jsonrpc": "2.0",
                        "id": None,
                        "error": {"code": -32700, "message": str(exc)},
                    }
                else:
                    response = self.handle(message)
                if response is not None:
                    stdout.write(json.dumps(response) + "\n")
                    stdout.flush()
        finally:
            self.orchestrator.close_owned_sessions()
            prune_artifacts()
        return 0


def main() -> int:
    return MCPStdioServer().serve()


if __name__ == "__main__":
    raise SystemExit(main())
