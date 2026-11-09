"""End-to-end tests for the command-line interface."""

from __future__ import annotations

import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def run_cli(*arguments: str, input_text: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "spellcheck", *arguments],
        cwd=PROJECT_ROOT,
        input=input_text,
        text=True,
        capture_output=True,
        timeout=60,
    )


class CliTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        dictionary = PROJECT_ROOT / "spellcheck" / "data" / "words.txt"
        if not dictionary.exists():
            raise unittest.SkipTest(
                "bundled dictionary is missing; run scripts/build_dictionary.py"
            )

    def test_assignment_example_output(self) -> None:
        completed = run_cli("recieve")

        self.assertEqual(completed.returncode, 1)
        self.assertIn("'recieve' is not in the dictionary.", completed.stdout)
        self.assertIn("Suggestions (max distance 2):", completed.stdout)
        self.assertIn("receive (distance 2)", completed.stdout)

    def test_valid_word(self) -> None:
        completed = run_cli("hello")

        self.assertEqual(completed.returncode, 0)
        self.assertIn("'hello' is spelled correctly.", completed.stdout)

    def test_valid_word_keeps_capitalization(self) -> None:
        completed = run_cli("Hello")

        self.assertEqual(completed.returncode, 0)
        self.assertIn("'Hello' is spelled correctly.", completed.stdout)

    def test_no_close_match(self) -> None:
        completed = run_cli("-d", "1", "zzzzzz")

        self.assertEqual(completed.returncode, 1)
        self.assertIn(
            "No suggestions within edit distance 1.", completed.stdout
        )

    def test_max_distance_is_configurable(self) -> None:
        completed = run_cli("-d", "1", "recieve")

        self.assertEqual(completed.returncode, 1)
        self.assertNotIn("receive (distance 2)", completed.stdout)

    def test_suggestion_count_is_configurable(self) -> None:
        completed = run_cli("-n", "1", "recieve")

        numbered = re.findall(r"^\s+\d+\. ", completed.stdout, flags=re.MULTILINE)
        self.assertEqual(len(numbered), 1)

    def test_empty_argument(self) -> None:
        completed = run_cli("")

        self.assertEqual(completed.returncode, 2)
        self.assertIn("Please enter a word.", completed.stdout)

    def test_multiple_words_rejected(self) -> None:
        completed = run_cli("hello world")

        self.assertEqual(completed.returncode, 2)
        self.assertIn(
            "Please enter a single word without spaces.", completed.stdout
        )

    def test_interactive_mode(self) -> None:
        completed = run_cli(
            input_text="hello\nrecieve\n:quit\n",
        )

        self.assertEqual(completed.returncode, 0)
        self.assertIn("'hello' is spelled correctly.", completed.stdout)
        self.assertIn("receive (distance 2)", completed.stdout)

    def test_interactive_mode_handles_empty_and_invalid_lines(self) -> None:
        completed = run_cli(input_text="\nhello world\n:quit\n")

        self.assertEqual(completed.returncode, 0)
        self.assertIn("Please enter a word.", completed.stdout)
        self.assertIn(
            "Please enter a single word without spaces.", completed.stdout
        )

    def test_custom_user_dictionary(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            user_dictionary = Path(temporary) / "user.txt"
            user_dictionary.write_text("kubernetes\n", encoding="utf-8")

            completed = run_cli(
                "--user-dictionary", str(user_dictionary), "kubernetes"
            )

        self.assertEqual(completed.returncode, 0)
        self.assertIn("'kubernetes' is spelled correctly.", completed.stdout)

    def test_custom_main_dictionary(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            dictionary = Path(temporary) / "words.txt"
            dictionary.write_text("foobar\n", encoding="utf-8")

            completed = run_cli(
                "--dictionary",
                str(dictionary),
                "--no-frequency",
                "foobar",
            )

        self.assertEqual(completed.returncode, 0)
        self.assertIn("'foobar' is spelled correctly.", completed.stdout)

    def test_missing_dictionary_reports_error(self) -> None:
        completed = run_cli(
            "--dictionary", str(PROJECT_ROOT / "does-not-exist.txt"), "hello"
        )

        self.assertEqual(completed.returncode, 2)
        self.assertIn("dictionary file not found", completed.stderr)

    def test_negative_distance_is_rejected(self) -> None:
        completed = run_cli("-d", "-1", "hello")

        self.assertEqual(completed.returncode, 2)

    def test_web_cannot_be_combined_with_interactive(self) -> None:
        completed = run_cli("--web", "--interactive")

        self.assertEqual(completed.returncode, 2)
        self.assertIn("--web cannot be combined with --interactive", completed.stderr)

    def test_web_does_not_take_a_word(self) -> None:
        completed = run_cli("--web", "hello")

        self.assertEqual(completed.returncode, 2)
        self.assertIn("--web does not take a word argument", completed.stderr)

    def test_web_invalid_port(self) -> None:
        completed = run_cli("--web", "--port", "70000")

        self.assertEqual(completed.returncode, 2)
        self.assertIn("--port must be between 0 and 65535", completed.stderr)

    def test_web_distance_cap(self) -> None:
        completed = run_cli("--web", "-d", "6")

        self.assertEqual(completed.returncode, 2)
        self.assertIn("--max-distance for --web", completed.stderr)

    def test_web_suggestion_cap(self) -> None:
        completed = run_cli("--web", "-n", "21")

        self.assertEqual(completed.returncode, 2)
        self.assertIn("--suggestions for --web", completed.stderr)

    def test_version(self) -> None:
        completed = run_cli("--version")

        self.assertEqual(completed.returncode, 0)
        self.assertIn("spellcheck 1.0.0", completed.stdout)


if __name__ == "__main__":
    unittest.main()
