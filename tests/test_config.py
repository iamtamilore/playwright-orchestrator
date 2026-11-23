from __future__ import annotations

import json
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_template_handshakes_cover_agents_skills_commands_and_mcp():
    opencode_agent = (REPO_ROOT / "templates/opencode/agent/playwright-worker.md").read_text(encoding="utf-8")
    opencode_skill = (REPO_ROOT / "templates/opencode/skills/playwright-orchestrator/SKILL.md").read_text(encoding="utf-8")
    opencode_command = (REPO_ROOT / "templates/opencode/command/playwright.md").read_text(encoding="utf-8")
    claude_agent = (REPO_ROOT / "templates/claude/agents/playwright-worker.md").read_text(encoding="utf-8")
    claude_skill = (REPO_ROOT / "templates/claude/skills/playwright-orchestrator/SKILL.md").read_text(encoding="utf-8")
    claude_command = (REPO_ROOT / "templates/claude/commands/playwright.md").read_text(encoding="utf-8")

    assert "nvidia/minimaxai/minimax-m3.1-flash" in opencode_agent
    assert "webfetch: deny" in opencode_agent
    assert "websearch: deny" in opencode_agent
    assert "subagent: deny" in opencode_agent
    assert "browser: deny" in opencode_agent
    assert "browser_*: allow" not in opencode_agent
    assert "playwright-profile" in opencode_skill
    assert "agent: playwright-worker" in opencode_command
    assert "mcp__playwright-orchestrator__pw_run_session" in claude_agent
    assert "disallowedTools: Bash" in claude_agent
    assert "playwright-cli *" not in opencode_agent
    assert "playwright-profile" in claude_skill
    assert "argument-hint" in claude_command


def test_live_global_handshakes_when_installed():
    opencode_path = Path.home() / ".config/opencode/opencode.jsonc"
    claude_path = Path.home() / ".claude.json"
    if not opencode_path.exists() or not claude_path.exists():
        return
    opencode = json.loads(opencode_path.read_text(encoding="utf-8"))
    servers = opencode.get("mcp", {}).get("servers", {})
    if "playwright-orchestrator" not in servers:
        pytest.skip("global MCP server is not installed yet")
    assert "playwright-orchestrator" in servers
    permissions = opencode.get("permissions", [])
    assert {"action": "browser", "resource": "*", "effect": "deny"} in permissions
    for tool in (
        "browser_close_all",
        "browser_close_profile",
        "browser_preview",
        "browser_profiles",
    ):
        assert {"action": tool, "resource": "*", "effect": "deny"} in permissions
    assert not any(rule.get("action") == "browser_*" for rule in permissions)
    claude = json.loads(claude_path.read_text(encoding="utf-8"))
    assert "playwright-orchestrator" in claude.get("mcpServers", {})
