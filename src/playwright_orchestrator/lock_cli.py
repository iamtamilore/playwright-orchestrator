from __future__ import annotations

import argparse
import json
from pathlib import Path

from .locks import LockManager, run_lock_daemon


def main() -> int:
    parser = argparse.ArgumentParser(description="Playwright profile lock control")
    sub = parser.add_subparsers(dest="command", required=True)

    daemon = sub.add_parser("daemon")
    daemon.add_argument("--profile", required=True)
    daemon.add_argument("--session", required=True)
    daemon.add_argument("--owner", required=True)
    daemon.add_argument("--server-pid", type=int, required=True)
    daemon.add_argument("--display", default="")
    daemon.add_argument("--result", required=True)
    daemon.add_argument("--ephemeral", action="store_true")

    acquire = sub.add_parser("acquire")
    acquire.add_argument("--profile", required=True)
    acquire.add_argument("--session", required=True)
    acquire.add_argument("--owner", default=None)
    acquire.add_argument("--server-pid", type=int, default=None)
    acquire.add_argument("--display", default=None)

    release = sub.add_parser("release")
    release.add_argument("--profile", required=True)
    release.add_argument("--server-pid", type=int, default=None)

    status = sub.add_parser("status")

    args = parser.parse_args()
    if args.command == "daemon":
        return run_lock_daemon(
            args.profile,
            session=args.session,
            owner=args.owner,
            server_pid=args.server_pid,
            display=args.display,
            result_path=Path(args.result),
            ephemeral=args.ephemeral,
        )

    manager = LockManager(
        server_pid=args.server_pid,
        owner=getattr(args, "owner", None),
    )
    if args.command == "acquire":
        try:
            owner = manager.acquire(
                args.profile,
                session=args.session,
                display=args.display,
            )
        except Exception as exc:
            print(json.dumps({"ok": False, "error": str(exc)}))
            return 2
        print(json.dumps({"ok": True, "owner": owner.to_dict()}))
        return 0
    if args.command == "release":
        print(json.dumps({"ok": manager.release(args.profile)}))
        return 0
    if args.command == "status":
        print(json.dumps({"locks": manager.status()}, indent=2))
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
