from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from playwright_orchestrator.runner import Runner, validate_step


def test_three_ephemeral_workers_run_in_parallel(profile_runtime):
    runner = Runner(cli_bin=profile_runtime["cli"])
    markers = []

    def work(index):
        marker = profile_runtime["tmp"] / f"parallel-{index}.json"
        markers.append(marker)
        return runner.run(
            f"example_{index}",
            [["eval", "0.25", str(marker)]],
            ephemeral=True,
        )

    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(work, range(3)))

    assert all(result.status == "ok" for result in results)
    intervals = []
    for marker in markers:
        data = json.loads(marker.read_text(encoding="utf-8"))
        intervals.append((data["start"], data["end"]))
    latest_start = max(start for start, _ in intervals)
    earliest_end = min(end for _, end in intervals)
    assert latest_start < earliest_end


def test_persistent_profile_collision(profile_runtime):
    runner = Runner(cli_bin=profile_runtime["cli"])

    def work(index):
        return runner.run(
            profile_runtime["profile"],
            [["eval", "0.25", str(profile_runtime["tmp"] / f"collision-{index}.json")]],
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(work, range(2)))

    statuses = sorted(result.status for result in results)
    assert statuses == ["ok", "profile_busy"]


def test_snapshot_returns_refs_and_fills_ref(profile_runtime):
    runner = Runner(cli_bin=profile_runtime["cli"])
    result = runner.snapshot(
        profile_runtime["profile"],
        fill_ref={"ref": "e7", "value": "hello"},
    )
    assert result.status == "ok"
    assert result.snapshot_path
    assert "e7" in result.refs
    assert (profile_runtime["artifacts"]).exists()
    log = (profile_runtime["tmp"] / "fake-cli.log").read_text(encoding="utf-8")
    assert "fill" in log
    assert "e7" in log
    assert "hello" in log
    open_command = next(
        json.loads(line)
        for line in log.splitlines()
        if "open" in json.loads(line)
    )
    assert open_command[-1].startswith("--config=")
    assert open_command.index("-s=" + result.session) < open_command.index("open")


def test_destructive_and_profile_bypass_steps_are_rejected():
    for step in (
        ["close-all"],
        ["kill-all"],
        ["open", "--profile=/tmp/other-profile"],
        ["open", "--persistent"],
        ["open", "--config=/tmp/other.json"],
    ):
        try:
            validate_step(step)
        except ValueError:
            pass
        else:
            raise AssertionError(f"unsafe step was accepted: {step}")


def test_invalid_session_names_are_rejected(profile_runtime):
    runner = Runner(cli_bin=profile_runtime["cli"])
    for session in ("/tmp/pwn", "../../outside", "../config"):
        with pytest.raises(ValueError, match="invalid session name"):
            runner.run(
                profile_runtime["profile"],
                [["snapshot"]],
                session=session,
            )


def test_wrong_cli_version_fails_closed(profile_runtime, tmp_path):
    wrong = tmp_path / "wrong-cli"
    wrong.write_text("#!/usr/bin/env python3\nprint('0.1.24')\n", encoding="utf-8")
    wrong.chmod(0o755)
    runner = Runner(cli_bin=str(wrong))
    try:
        runner.run(profile_runtime["profile"], [["snapshot"]])
    except RuntimeError as exc:
        assert "expected 0.1.25" in str(exc)
    else:
        raise AssertionError("wrong CLI version was accepted")
