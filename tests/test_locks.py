from __future__ import annotations

import os
import time

from playwright_orchestrator.locks import LockManager, ProfileBusy


def test_profile_lock_rejects_second_owner(isolated_runtime):
    first = LockManager(server_pid=os.getpid(), owner="first")
    second = LockManager(server_pid=os.getpid() + 100000, owner="second")
    owner = first.acquire("linkedin_main", session="session-one")
    try:
        assert owner.profile == "linkedin_main"
        try:
            second.acquire("linkedin_main", session="session-two")
        except ProfileBusy as exc:
            assert exc.owner["session"] == "session-one"
        else:
            raise AssertionError("second owner acquired the same profile")
    finally:
        first.release("linkedin_main")
    assert first.status() == []


def test_lock_cli_release_accepts_a_release_only_namespace(isolated_runtime):
    from playwright_orchestrator.lock_cli import main

    manager = LockManager(server_pid=os.getpid(), owner="cli")
    manager.acquire("release_cli", session="release-session")
    try:
        import sys

        old_argv = sys.argv
        sys.argv = [
            "lock_cli",
            "release",
            "--profile",
            "release_cli",
            "--server-pid",
            str(os.getpid()),
        ]
        assert main() == 0
    finally:
        sys.argv = old_argv
    assert manager.status() == []


def test_registry_is_atomic_json(isolated_runtime):
    manager = LockManager(server_pid=os.getpid(), owner="writer")
    manager.acquire("mail", session="mail-session")
    try:
        text = isolated_runtime["state"].joinpath("live_browsers.json").read_text(encoding="utf-8")
        assert text.startswith("{")
        assert "mail-session" in text
    finally:
        manager.release("mail")
