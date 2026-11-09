"""Command-line interface for the spell checker."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Sequence

from .dictionary import Dictionary, DictionaryError
from .paths import DEFAULT_DICTIONARY, DEFAULT_FREQUENCIES, DEFAULT_USER_DICTIONARY
from .suggest import CheckResult, SpellChecker

EXIT_VALID = 0
EXIT_UNKNOWN = 1
EXIT_USAGE = 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="spellcheck",
        description=(
            "Check an English word and rank spelling suggestions by "
            "Levenshtein distance, frequency, and alphabetical order."
        ),
    )
    parser.add_argument(
        "word",
        nargs="?",
        help="word to check; omit it (or use -i) for interactive mode",
    )
    parser.add_argument(
        "-i",
        "--interactive",
        action="store_true",
        help="read words from standard input, one per line",
    )
    parser.add_argument(
        "--web",
        action="store_true",
        help="start the local web interface instead of checking a single word",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        metavar="ADDRESS",
        help="web server bind address (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        metavar="PORT",
        help="web server port (default: 8000; use 0 for an ephemeral port)",
    )
    parser.add_argument(
        "--open-browser",
        action="store_true",
        help="open the web interface in the default browser after starting",
    )
    parser.add_argument(
        "-d",
        "--max-distance",
        type=int,
        default=2,
        metavar="N",
        help="maximum Levenshtein distance for suggestions (default: 2)",
    )
    parser.add_argument(
        "-n",
        "--suggestions",
        type=int,
        default=5,
        metavar="N",
        help="maximum number of suggestions to show (default: 5)",
    )
    parser.add_argument(
        "--dictionary",
        action="append",
        metavar="PATH",
        help=(
            "main word-list file; may be repeated. Defaults to the bundled "
            "SCOWL dictionary."
        ),
    )
    parser.add_argument(
        "--user-dictionary",
        action="append",
        metavar="PATH",
        help=(
            "user word-list file layered on top of the main dictionary; may "
            "be repeated."
        ),
    )
    parser.add_argument(
        "--no-user-dictionary",
        action="store_true",
        help="do not load the bundled user dictionary",
    )
    parser.add_argument(
        "--frequency-file",
        metavar="PATH",
        help="optional word<TAB>frequency file used for tie-breaking",
    )
    parser.add_argument(
        "--no-frequency",
        action="store_true",
        help="disable frequency-based tie-breaking",
    )
    parser.add_argument(
        "--version",
        action="version",
        version="spellcheck 1.0.0",
    )
    return parser


def format_result(result: CheckResult, max_distance: int) -> str:
    """Render a :class:`CheckResult` as CLI text."""

    if result.status == "valid":
        return f"'{result.original}' is spelled correctly."

    if result.status == "empty":
        return "Please enter a word."

    if result.status == "invalid":
        return "Please enter a single word without spaces."

    lines = [f"'{result.original}' is not in the dictionary."]

    if result.suggestions:
        lines.append(f"Suggestions (max distance {max_distance}):")
        for index, suggestion in enumerate(result.suggestions, start=1):
            lines.append(
                f"  {index}. {suggestion.display_word} "
                f"(distance {suggestion.distance})"
            )
    else:
        lines.append(f"No suggestions within edit distance {max_distance}.")

    return "\n".join(lines)


def _load_checker(args: argparse.Namespace) -> SpellChecker:
    main_paths = (
        [Path(path) for path in args.dictionary]
        if args.dictionary
        else [DEFAULT_DICTIONARY]
    )

    if args.user_dictionary:
        user_paths = [Path(path) for path in args.user_dictionary]
    elif not args.no_user_dictionary and DEFAULT_USER_DICTIONARY.exists():
        user_paths = [DEFAULT_USER_DICTIONARY]
    else:
        user_paths = []

    if args.no_frequency:
        frequency_path = None
    elif args.frequency_file:
        frequency_path = Path(args.frequency_file)
    elif DEFAULT_FREQUENCIES.exists():
        frequency_path = DEFAULT_FREQUENCIES
    else:
        frequency_path = None

    dictionary = Dictionary.from_files(
        dictionary_paths=main_paths,
        user_dictionary_paths=user_paths,
        frequency_path=frequency_path,
    )
    return SpellChecker(
        dictionary=dictionary,
        max_distance=args.max_distance,
        max_suggestions=args.suggestions,
    )


def _run_interactive(checker: SpellChecker) -> int:
    print("Interactive spell checker. Enter one word per line.")
    print("Commands: :help, :quit (or Ctrl-D).")
    print(
        f"Settings: max distance {checker.max_distance}, "
        f"up to {checker.max_suggestions} suggestions."
    )

    while True:
        try:
            line = input("Word> ")
        except (EOFError, KeyboardInterrupt):
            print()
            return EXIT_VALID

        command = line.strip().lower()
        if command in {":q", ":quit", "quit", "exit"}:
            return EXIT_VALID
        if command in {":help", "help"}:
            print("Enter one word per line. Commands: :help, :quit.")
            continue

        print(format_result(checker.check(line), checker.max_distance))


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.max_distance < 0:
        parser.error("--max-distance must be non-negative")
    if args.suggestions < 0:
        parser.error("--suggestions must be non-negative")
    if args.web and args.interactive:
        parser.error("--web cannot be combined with --interactive")
    if args.web and args.word is not None:
        parser.error("--web does not take a word argument")
    if args.web and not (0 <= args.port <= 65535):
        parser.error("--port must be between 0 and 65535")
    if args.web:
        from .web import MAX_WEB_DISTANCE, MAX_WEB_SUGGESTIONS

        if args.max_distance > MAX_WEB_DISTANCE:
            parser.error(
                f"--max-distance for --web must be between 0 and {MAX_WEB_DISTANCE}"
            )
        if args.suggestions > MAX_WEB_SUGGESTIONS:
            parser.error(
                "--suggestions for --web must be between 0 and "
                f"{MAX_WEB_SUGGESTIONS}"
            )

    try:
        checker = _load_checker(args)
    except (OSError, DictionaryError, ValueError) as exc:
        print(f"spellcheck: {exc}", file=sys.stderr)
        if not DEFAULT_DICTIONARY.exists():
            print(
                "spellcheck: the bundled dictionary is missing; run "
                "'python scripts/build_dictionary.py' to create it.",
                file=sys.stderr,
            )
        return EXIT_USAGE

    if args.web:
        from .web import run_server

        return run_server(
            checker,
            host=args.host,
            port=args.port,
            default_max_distance=args.max_distance,
            default_max_suggestions=args.suggestions,
            open_browser=args.open_browser,
        )

    if args.interactive or args.word is None:
        return _run_interactive(checker)

    result = checker.check(args.word)
    print(format_result(result, checker.max_distance))

    if result.status == "valid":
        return EXIT_VALID
    if result.status in {"empty", "invalid"}:
        return EXIT_USAGE
    return EXIT_UNKNOWN
