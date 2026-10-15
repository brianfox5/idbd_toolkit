"""Command-line account management for server mode.

Run on the server (as the user the service runs as), pointing at the same data
directory as the web app::

    idbd-admin create-user alice --role admin      # prompts for a password
    idbd-admin list
    idbd-admin set-password alice
    idbd-admin disable alice | enable alice

The first admin must be created here; after that, admins can manage accounts in
the browser (Administration page).
"""

from __future__ import annotations

import argparse
import getpass
import os
import sys
from pathlib import Path

from .auth import ROLES, AuthError, UserStore


def _store(args: argparse.Namespace) -> UserStore:
    data_dir = args.data_dir or os.environ.get("IDBD_DATA_DIR")
    if not data_dir:
        sys.exit("set IDBD_DATA_DIR or pass --data-dir (the web app's data directory)")
    return UserStore(Path(data_dir))


def _new_password(username: str) -> str:
    while True:
        first = getpass.getpass(f"New password for {username}: ")
        if first == getpass.getpass("Repeat it: "):
            return first
        print("The passwords did not match; try again.")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="idbd-admin", description=__doc__.split("\n\n")[0])
    parser.add_argument("--data-dir", help="data directory (default: $IDBD_DATA_DIR)")
    sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser("create-user", help="add an account")
    create.add_argument("username")
    create.add_argument("--role", choices=ROLES, default="researcher")
    create.add_argument("--name", default="", help="display name")
    sub.add_parser("list", help="list accounts")
    for cmd in ("set-password", "disable", "enable"):
        sub.add_parser(cmd).add_argument("username")
    args = parser.parse_args(argv)
    users = _store(args)
    try:
        if args.command == "create-user":
            user = users.create(args.username, _new_password(args.username),
                                role=args.role, display_name=args.name)
            print(f"created {user.username} ({user.role})")
        elif args.command == "list":
            for u in users.list():
                print(f"{u.username:24} {u.role:11} {'active' if u.active else 'DISABLED':9} {u.display_name}")
        elif args.command == "set-password":
            users.update(args.username, password=_new_password(args.username))
            print("password changed; existing sessions were signed out")
        else:
            users.update(args.username, active=args.command == "enable")
            print(f"{args.username} {args.command}d")
    except AuthError as e:
        sys.exit(f"error: {e}")


if __name__ == "__main__":  # pragma: no cover
    main()
