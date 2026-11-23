from __future__ import annotations

import os
from pathlib import Path


HOME = Path.home()
STATE_ROOT = Path(
    os.environ.get(
        "PLAYWRIGHT_ORCHESTRATOR_HOME",
        HOME / ".local/share/playwright-orchestrator",
    )
)
LOCK_ROOT = STATE_ROOT / "locks"
REGISTRY_PATH = STATE_ROOT / "live_browsers.json"
REGISTRY_LOCK_PATH = STATE_ROOT / "registry.lock"
CONFIG_ROOT = STATE_ROOT / "configs"
ARTIFACT_LOCK_PATH = STATE_ROOT / "artifacts.lock"
ARTIFACT_FALLBACK = STATE_ROOT / "artifacts"
TWO_TB_ARTIFACTS = Path("/mnt/2tb/browser-artifacts/playwright-orchestrator")
PROFILE_ROOT = Path(
    os.environ.get(
        "PLAYWRIGHT_MCP_PROFILE_ROOT",
        HOME / ".local/share/playwright-mcp/profiles",
    )
)
PROFILE_CONFIG_PATH = Path(
    os.environ.get(
        "PLAYWRIGHT_MCP_PROFILE_CONFIG",
        HOME / ".local/share/playwright-mcp/profiles.json",
    )
)
CHROMIUM_HEALTH_PATH = Path(
    os.environ.get(
        "PLAYWRIGHT_MCP_CHROMIUM_HEALTH",
        HOME / ".local/share/playwright-mcp/chromium_health.json",
    )
)
AUTH_MARKER = Path(os.environ.get("PLAYWRIGHT_AUTH_MARKER", "/dev/shm/.auth_pw"))


def artifact_root() -> Path:
    configured = os.environ.get("PLAYWRIGHT_ORCHESTRATOR_ARTIFACTS")
    if configured:
        return Path(configured)
    if TWO_TB_ARTIFACTS.parent.exists():
        return TWO_TB_ARTIFACTS
    return ARTIFACT_FALLBACK
