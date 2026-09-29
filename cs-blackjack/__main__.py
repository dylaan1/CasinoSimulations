from __future__ import annotations

import argparse
from pathlib import Path

from .ui import run


def main() -> None:
    parser = argparse.ArgumentParser(prog="cs-blackjack", description="Terminal blackjack for practice and card counting.")
    parser.add_argument(
        "--db",
        metavar="FILE",
        type=Path,
        help="use this history database file instead of ~/.cs-blackjack/blackjack.db "
        "(it is created if it doesn't exist) -- the way to start with a clean slate without deleting anything",
    )
    args = parser.parse_args()
    run(args.db.expanduser() if args.db else None)


if __name__ == "__main__":
    main()
