from __future__ import annotations

import argparse
import sys

from kimai_everyday import config as config_module
from kimai_everyday import wizard


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="kimai-everyday",
        description="Create recurring Kimai timesheet entries from a natural-language pattern.",
        epilog=(
            "Subcommands:\n"
            "  config        Re-run the setup wizard to update saved settings.\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "sentence",
        nargs="?",
        help=(
            "The full one-liner pattern, including project/activity hints. "
            "If omitted you'll be prompted interactively."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run the wizard and show the preview, but skip the POST step.",
    )
    parser.add_argument(
        "--classic",
        action="store_true",
        help=(
            "Use the original multi-step wizard (Project → Activity → Description → "
            "Pattern). Useful when the LLM is unavailable or you want manual control."
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    raw = list(argv) if argv is not None else sys.argv[1:]

    # Carve out the `config` subcommand before argparse runs. An optional positional
    # `sentence` argument can't coexist with a subparser — argparse would route any
    # positional into the subparser. So we handle the one subcommand we have manually.
    if raw and raw[0] == "config":
        existing = config_module.load()
        config_module.run_setup(existing)
        return 0

    args = build_parser().parse_args(raw)
    config = config_module.load_or_setup()
    if args.classic:
        if args.sentence:
            print(
                "Note: --classic ignores the positional sentence; you'll be prompted.",
                file=sys.stderr,
            )
        return wizard.run_classic(config, dry_run=args.dry_run)
    return wizard.run(config, dry_run=args.dry_run, sentence=args.sentence)


if __name__ == "__main__":
    sys.exit(main())
