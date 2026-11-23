from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"


@pytest.fixture
def isolated_runtime(tmp_path, monkeypatch):
    home = tmp_path / "home"
    state = home / ".local/share/playwright-orchestrator"
    artifacts_dir = tmp_path / "artifacts"
    profiles = tmp_path / "profiles"
    state.mkdir(parents=True)
    artifacts_dir.mkdir()
    profiles.mkdir()

    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("PLAYWRIGHT_ORCHESTRATOR_HOME", str(state))
    monkeypatch.setenv("PLAYWRIGHT_ORCHESTRATOR_ARTIFACTS", str(artifacts_dir))
    monkeypatch.setenv("PYTHONPATH", str(SRC_ROOT))

    from playwright_orchestrator import artifacts, locks, paths, runner

    monkeypatch.setattr(locks, "STATE_ROOT", state)
    monkeypatch.setattr(locks, "LOCK_ROOT", state / "locks")
    monkeypatch.setattr(locks, "REGISTRY_PATH", state / "live_browsers.json")
    monkeypatch.setattr(locks, "REGISTRY_LOCK_PATH", state / "registry.lock")
    monkeypatch.setattr(paths, "ARTIFACT_FALLBACK", artifacts_dir)
    monkeypatch.setattr(paths, "TWO_TB_ARTIFACTS", artifacts_dir)
    monkeypatch.setattr(paths, "PROFILE_ROOT", profiles)
    monkeypatch.setattr(paths, "PROFILE_CONFIG_PATH", home / "profiles.json")
    monkeypatch.setattr(paths, "CHROMIUM_HEALTH_PATH", home / "chromium_health.json")
    monkeypatch.setattr(paths, "CONFIG_ROOT", state / "configs")
    monkeypatch.setattr(paths, "AUTH_MARKER", tmp_path / ".auth_pw")
    monkeypatch.setattr(artifacts, "artifact_root", lambda: artifacts_dir)
    monkeypatch.setattr(runner, "PROFILE_ROOT", profiles)
    monkeypatch.setattr(runner, "PROFILE_CONFIG_PATH", home / "profiles.json")
    monkeypatch.setattr(runner, "CHROMIUM_HEALTH_PATH", home / "chromium_health.json")
    monkeypatch.setattr(runner, "CONFIG_ROOT", state / "configs")
    monkeypatch.setattr(runner, "AUTH_MARKER", tmp_path / ".auth_pw")
    return {
        "home": home,
        "state": state,
        "artifacts": artifacts_dir,
        "profiles": profiles,
        "tmp": tmp_path,
    }


@pytest.fixture
def fake_cli(tmp_path, monkeypatch, isolated_runtime):
    script = tmp_path / "fake-playwright-cli"
    log = tmp_path / "fake-cli.log"
    script.write_text(
        """#!/usr/bin/env python3
import json
import os
import pathlib
import sys
import time

args = sys.argv[1:]
log = pathlib.Path(os.environ["PW_FAKE_CLI_LOG"])
with log.open("a", encoding="utf-8") as handle:
    handle.write(json.dumps(args) + "\\n")
steps = []
for index, value in enumerate(args):
    if value.startswith("-s="):
        steps = args[index + 1:]
        break
if not steps:
    steps = args
command = steps[0] if steps else ""
if command == "--version":
    print("0.1.25")
elif command == "snapshot":
    target = None
    for value in steps:
        if value.startswith("--filename="):
            target = pathlib.Path(value.split("=", 1)[1])
    if target is not None:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("- textbox [ref=e7]\\n", encoding="utf-8")
elif command == "eval":
    duration = float(steps[1])
    marker = pathlib.Path(steps[2])
    marker.write_text(json.dumps({"start": time.time(), "end": None}), encoding="utf-8")
    time.sleep(duration)
    data = json.loads(marker.read_text(encoding="utf-8"))
    data["end"] = time.time()
    marker.write_text(json.dumps(data), encoding="utf-8")
elif command == "list":
    if "--json" in steps:
        print(json.dumps({"browsers": []}))
    else:
        print("  (no browsers)")
else:
    print("ok")
""",
        encoding="utf-8",
    )
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setenv("PW_FAKE_CLI_LOG", str(log))
    return script


@pytest.fixture
def profile_runtime(isolated_runtime, fake_cli):
    profile = isolated_runtime["profiles"] / "example"
    profile.mkdir(parents=True)
    chromium = isolated_runtime["tmp"] / "chrome"
    chromium.write_text("fake chromium", encoding="utf-8")
    chromium.chmod(chromium.stat().st_mode | stat.S_IXUSR)
    health = isolated_runtime["home"] / "chromium_health.json"
    health.write_text(json.dumps({"healthy": True, "path": str(chromium)}), encoding="utf-8")
    return {
        "profile": "example",
        "profile_dir": profile,
        "cli": str(fake_cli),
        "artifacts": isolated_runtime["artifacts"],
        "tmp": isolated_runtime["tmp"],
    }
