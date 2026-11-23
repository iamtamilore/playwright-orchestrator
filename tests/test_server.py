from __future__ import annotations

from pathlib import Path

from playwright_orchestrator.runner import Runner
from playwright_orchestrator.server import MCPStdioServer, Orchestrator


def test_mcp_handshake_lists_exactly_six_tools():
    server = MCPStdioServer()
    initialized = server.handle(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": "2024-11-05"},
        }
    )
    assert initialized["result"]["serverInfo"]["name"] == "playwright-orchestrator"
    listed = server.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    names = {tool["name"] for tool in listed["result"]["tools"]}
    assert names == {
        "pw_run_session",
        "pw_parallel_batch",
        "pw_snapshot",
        "pw_profile_locks",
        "pw_dashboard_status",
        "pw_interactive_handoff",
    }


def test_interactive_handoff_opens_while_auth_marker_exists(profile_runtime, monkeypatch):
    from playwright_orchestrator import paths, runner, server

    marker = profile_runtime["tmp"] / ".auth_pw"
    marker.write_text("waiting", encoding="utf-8")
    monkeypatch.setattr(paths, "AUTH_MARKER", marker)
    monkeypatch.setattr(runner, "AUTH_MARKER", marker)
    monkeypatch.setattr(server, "display_available", lambda _display: True)
    service = Orchestrator(Runner(cli_bin=profile_runtime["cli"]))
    result = service.pw_interactive_handoff(
        {"profile": "example", "display": ":99", "url": "about:blank"}
    )
    try:
        assert result["status"] == "ok"
        assert result["handoff"] is True
        assert result["resume_session"] == result["session"]
        assert "clear the auth marker" in result["message"]
    finally:
        service.close_owned_sessions()


def test_dashboard_status_reports_auth_pause(profile_runtime, monkeypatch):
    from playwright_orchestrator import paths, runner

    marker = profile_runtime["tmp"] / ".auth_pw"
    marker.write_text("waiting", encoding="utf-8")
    monkeypatch.setattr(paths, "AUTH_MARKER", marker)
    monkeypatch.setattr(runner, "AUTH_MARKER", marker)
    service = Orchestrator(Runner(cli_bin=profile_runtime["cli"]))
    status = service.pw_dashboard_status({"display": ":65432"})
    assert status["auth_waiting"] is True
    assert status["display_available"] is False
    assert status["sessions"] == []
    assert status["dashboard_running"] is False
    assert status["cli_version"] == "0.1.25"
