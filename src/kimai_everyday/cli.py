from __future__ import annotations

import argparse
import sys

from kimai_everyday import config as config_module
from kimai_everyday import wizard


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="kimai-everyday",
        description="Create recurring Kimai timesheet entries from a natural-language pattern.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run the wizard and show the preview, but skip the POST step.",
    )
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("config", help="Re-run the setup wizard to update saved settings.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "config":
        existing = config_module.load()
        config_module.run_setup(existing)
        return 0

    config = config_module.load_or_setup()
    return wizard.run(config, dry_run=args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
