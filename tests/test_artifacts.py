from __future__ import annotations

import os
import time
from pathlib import Path

from playwright_orchestrator.artifacts import prune_artifacts


def test_artifact_ttl_and_size_bounds(tmp_path):
    root = tmp_path / "artifacts"
    root.mkdir()
    old = root / "old.txt"
    old.write_text("old", encoding="utf-8")
    now = time.time()
    os.utime(old, (now - 49 * 60 * 60, now - 49 * 60 * 60))
    current = root / "current.txt"
    current.write_text("x" * 100, encoding="utf-8")

    result = prune_artifacts(root, ttl_seconds=48 * 60 * 60, max_bytes=50)
    assert not old.exists()
    assert result["removed_files"] >= 1
    assert result["remaining_bytes"] <= 50


def test_active_artifact_directory_is_not_pruned(tmp_path):
    root = tmp_path / "artifacts"
    active = root / "live-session"
    active.mkdir(parents=True)
    path = active / "snapshot.yml"
    path.write_text("active", encoding="utf-8")

    result = prune_artifacts(root, ttl_seconds=1, max_bytes=1, active_roots=[active])

    assert path.exists()
    assert result["remaining_bytes"] == len("active")
