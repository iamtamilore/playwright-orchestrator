from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from .locks import LockManager, ProfileBusy
from .runner import Runner, auth_waiting


def _print(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, indent=2))


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="playwright-profile",
        description="Run Playwright CLI steps under a named profile lock",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="run ordered Playwright CLI steps")
    run.add_argument("--profile", required=True)
    run.add_argument(
        "--step",
        action="append",
        required=True,
        help="one shell-quoted Playwright CLI step; repeat in execution order",
    )
    run.add_argument("--headed", action="store_true")
    run.add_argument("--display", default=None)
    run.add_argument("--ephemeral", action="store_true")

    snapshot = sub.add_parser("snapshot", help="save a snapshot and print its refs")
    snapshot.add_argument("--profile", required=True)
    snapshot.add_argument("--selector", default=None)
    snapshot.add_argument("--url", default=None)
    snapshot.add_argument("--depth", type=int, default=None)
    snapshot.add_argument("--find", default=None)
    snapshot.add_argument("--fill-ref", default=None)
    snapshot.add_argument("--fill-value", default="")
    snapshot.add_argument("--headed", action="store_true")
    snapshot.add_argument("--display", default=None)
    snapshot.add_argument("--ephemeral", action="store_true")

    locks = sub.add_parser("locks", help="list profile lock owners")
    locks.add_argument("--json", action="store_true")

    acquire = sub.add_parser("acquire", help="acquire a named profile lock")
    acquire.add_argument("--profile", required=True)
    acquire.add_argument("--session", required=True)
    acquire.add_argument("--display", default=None)

    release = sub.add_parser("release", help="release an owned named profile lock")
    release.add_argument("--profile", required=True)

    args = parser.parse_args()
    runner = Runner()
    if args.command == "run":
        result = runner.run(
            args.profile,
            args.step,
            headless=not args.headed,
            display=args.display,
            ephemeral=args.ephemeral,
        )
        _print(result.to_dict())
        return 0 if result.status == "ok" else 2
    if args.command == "snapshot":
        fill_ref = None
        if args.fill_ref:
            fill_ref = {"ref": args.fill_ref, "value": args.fill_value}
        result = runner.snapshot(
            args.profile,
            selector=args.selector,
            url=args.url,
            depth=args.depth,
            find=args.find,
            fill_ref=fill_ref,
            headless=not args.headed,
            display=args.display,
            ephemeral=args.ephemeral,
        )
        _print(result.to_dict())
        return 0 if result.status == "ok" else 2
    if args.command == "locks":
        _print({"locks": LockManager().status(), "auth_waiting": auth_waiting()})
        return 0
    if args.command == "acquire":
        try:
            owner = LockManager().acquire(
                args.profile,
                session=args.session,
                display=args.display,
            )
        except ProfileBusy as exc:
            _print({"ok": False, "error": str(exc), "owner": exc.owner})
            return 2
        _print({"ok": True, "owner": owner.to_dict()})
        return 0
    if args.command == "release":
        _print({"ok": LockManager().release(args.profile)})
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
