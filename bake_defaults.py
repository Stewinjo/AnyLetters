"""Write bakeable runtime defaults used by the packaged executable."""

from __future__ import annotations

import argparse
import json
import os
import sys

DEFAULTS_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "defaults.json"
)
DIFFICULTIES = ("easy", "medium", "hard", "chaos")
MAX_WORD_LENGTH = 30


def load_defaults(path: str | None = None) -> dict:
    """Load defaults from disk, or return the stock values when missing.

    Args:
        path: Path to ``defaults.json``. Uses ``DEFAULTS_PATH`` when omitted.

    Returns:
        Defaults dictionary. Missing keys are filled from the stock defaults.
    """

    target = DEFAULTS_PATH if path is None else path
    stock = {
        "lang": "en",
        "length": 6,
        "difficulty": "medium",
        "disable_solution_filters": False,
        "exe_name": "AnyLetters",
        "hide_secret": True,
    }
    if not os.path.isfile(target):
        return dict(stock)
    with open(target, "r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"{target} must contain a JSON object.")
    merged = dict(stock)
    merged.update(data)
    return merged


def save_defaults(data: dict, path: str | None = None) -> None:
    """Write defaults as pretty-printed JSON.

    Args:
        data: Defaults to persist.
        path: Destination path. Uses ``DEFAULTS_PATH`` when omitted.
    """

    target = DEFAULTS_PATH if path is None else path
    with open(target, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, sort_keys=True)
        handle.write("\n")


def solutions_path_for(lang: str, length: int) -> str:
    """Return the expected solutions file for a language and length.

    Args:
        lang: Language code.
        length: Word length.

    Returns:
        Relative path under ``solutions/``.
    """

    return os.path.join("solutions", f"{lang.strip().lower()}{length}.txt")


def build_parser() -> argparse.ArgumentParser:
    """Return the CLI used by the build scripts."""

    parser = argparse.ArgumentParser(
        description=(
            "Update defaults.json so the next PyInstaller build starts with "
            "these language, length, and difficulty values."
        )
    )
    parser.add_argument("--lang", help="Default language code (e.g. de, en-gb).")
    parser.add_argument(
        "--length",
        type=int,
        help=f"Default word length (1-{MAX_WORD_LENGTH}).",
    )
    parser.add_argument(
        "--difficulty",
        choices=DIFFICULTIES,
        help="Default difficulty.",
    )
    parser.add_argument(
        "--exe-name",
        dest="exe_name",
        help="Executable base name written into defaults and used by the spec.",
    )
    parser.add_argument(
        "--disable-solution-filters",
        action="store_true",
        help="Bake disable_solution_filters=true into the executable defaults.",
    )
    parser.add_argument(
        "--enable-solution-filters",
        action="store_true",
        help="Bake disable_solution_filters=false into the executable defaults.",
    )
    hide_group = parser.add_mutually_exclusive_group()
    hide_group.add_argument(
        "--hide-secret",
        dest="hide_secret",
        action="store_true",
        help="Bake hide_secret=true (do not log the secret word).",
    )
    hide_group.add_argument(
        "--show-secret",
        dest="hide_secret",
        action="store_false",
        help="Bake hide_secret=false (log the secret word on generation).",
    )
    parser.set_defaults(hide_secret=None)
    parser.add_argument(
        "--require-solutions",
        action="store_true",
        help=(
            "Fail unless solutions/<lang><length>.txt exists so the baked "
            "build ships that word list."
        ),
    )
    parser.add_argument(
        "--print",
        action="store_true",
        dest="print_only",
        help="Print the current defaults and exit without writing.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Update or print bakeable defaults.

    Args:
        argv: Optional argument list. Defaults to ``sys.argv[1:]``.

    Returns:
        Process exit code.
    """

    parser = build_parser()
    args = parser.parse_args(argv)
    defaults = load_defaults()

    if args.print_only:
        print(json.dumps(defaults, indent=2, sort_keys=True))
        return 0

    changed = False
    if args.lang is not None:
        defaults["lang"] = args.lang.strip().lower()
        changed = True
    if args.length is not None:
        if args.length < 1 or args.length > MAX_WORD_LENGTH:
            parser.error(f"--length must be between 1 and {MAX_WORD_LENGTH}.")
        defaults["length"] = args.length
        changed = True
    if args.difficulty is not None:
        defaults["difficulty"] = args.difficulty
        changed = True
    if args.exe_name is not None:
        name = args.exe_name.strip()
        if not name:
            parser.error("--exe-name must not be empty.")
        defaults["exe_name"] = name
        changed = True
    if args.disable_solution_filters and args.enable_solution_filters:
        parser.error(
            "Use only one of --disable-solution-filters or --enable-solution-filters."
        )
    if args.disable_solution_filters:
        defaults["disable_solution_filters"] = True
        changed = True
    if args.enable_solution_filters:
        defaults["disable_solution_filters"] = False
        changed = True
    if args.hide_secret is not None:
        defaults["hide_secret"] = bool(args.hide_secret)
        changed = True

    if args.require_solutions:
        path = solutions_path_for(str(defaults["lang"]), int(defaults["length"]))
        if not os.path.isfile(path):
            print(
                f"ERROR: expected solutions file '{path}' is missing. "
                "Create it before baking, or omit --require-solutions.",
                file=sys.stderr,
            )
            return 1

    if not changed and not args.require_solutions:
        print("No bake flags provided; leaving defaults.json unchanged.")
        print(json.dumps(defaults, indent=2, sort_keys=True))
        return 0

    if changed:
        save_defaults(defaults)
        print(f"Wrote {DEFAULTS_PATH}")
    else:
        print(f"Validated solutions for {defaults['lang']}/{defaults['length']}.")
    print(json.dumps(defaults, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
