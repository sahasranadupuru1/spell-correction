"""Tests for checking, ranking, and suggestion behavior."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from spellcheck.dictionary import Dictionary
from spellcheck.paths import DEFAULT_DICTIONARY, DEFAULT_FREQUENCIES
from spellcheck.suggest import SpellChecker


def make_checker(
    words,
    frequencies=None,
    max_distance: int = 2,
    max_suggestions: int = 5,
) -> SpellChecker:
    return SpellChecker(
        Dictionary(words, frequencies=frequencies),
        max_distance=max_distance,
        max_suggestions=max_suggestions,
    )


def words_of(checker: SpellChecker, query: str) -> list[str]:
    return [suggestion.word for suggestion in checker.check(query).suggestions]


class AssignmentExampleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if not DEFAULT_DICTIONARY.exists():
            raise unittest.SkipTest(
                "bundled dictionary is missing; run scripts/build_dictionary.py"
            )
        frequency_path = (
            DEFAULT_FREQUENCIES if DEFAULT_FREQUENCIES.exists() else None
        )
        cls.dictionary = Dictionary.from_files(
            [DEFAULT_DICTIONARY], frequency_path=frequency_path
        )
        cls.checker = SpellChecker(
            cls.dictionary, max_distance=2, max_suggestions=5
        )

    def test_recieve_is_not_a_dictionary_word(self) -> None:
        self.assertFalse(self.dictionary.contains("recieve"))

    def test_recieve_suggests_receive_at_distance_two(self) -> None:
        result = self.checker.check("recieve")

        self.assertEqual(result.status, "unknown")
        pairs = {(suggestion.word, suggestion.distance) for suggestion in result.suggestions}
        self.assertIn(("receive", 2), pairs)

    def test_ranking_is_distance_frequency_alphabetical(self) -> None:
        result = self.checker.check("recieve")

        keys = [
            (suggestion.distance, -suggestion.frequency, suggestion.word)
            for suggestion in result.suggestions
        ]
        self.assertEqual(keys, sorted(keys))

    def test_correctly_spelled_words_are_unchanged(self) -> None:
        for word in ["receive", "Hello", "colour", "color", "realise", "realize"]:
            with self.subTest(word=word):
                result = self.checker.check(word)
                self.assertEqual(result.status, "valid")
                self.assertEqual(result.original, word)

    def test_uncommon_words_are_recognized(self) -> None:
        for word in [
            "flibbertigibbet",
            "antidisestablishmentarianism",
            "pneumonoultramicroscopicsilicovolcanoconiosis",
        ]:
            with self.subTest(word=word):
                self.assertEqual(self.checker.check(word).status, "valid")

    def test_full_dictionary_lookup_is_responsive(self) -> None:
        import time

        # Warm up any lazy OS caches, then time a real unknown-word lookup.
        self.checker.check("recieve")
        started = time.perf_counter()
        self.checker.check("recieve")
        elapsed = time.perf_counter() - started

        self.assertLess(
            elapsed,
            2.0,
            f"lookup took {elapsed:.3f}s on a {len(self.dictionary):,}-word dictionary",
        )


class EditOperationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.checker = make_checker(["hello"], max_distance=1)

    def test_insertion_typo(self) -> None:
        # "helloo" -> "hello" by deleting the extra "o".
        self.assertIn(("hello", 1), _pairs(self.checker.check("helloo")))

    def test_deletion_typo(self) -> None:
        # "helo" -> "hello" by inserting an "l".
        self.assertIn(("hello", 1), _pairs(self.checker.check("helo")))

    def test_replacement_typo(self) -> None:
        # "jello" -> "hello" by substituting "j" with "h".
        self.assertIn(("hello", 1), _pairs(self.checker.check("jello")))

    def test_matching_word_is_valid(self) -> None:
        result = self.checker.check("hello")
        self.assertEqual(result.status, "valid")


class CustomDictionaryTests(unittest.TestCase):
    def test_user_dictionary_entries_are_valid(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            main = directory / "main.txt"
            main.write_text("hello\n", encoding="utf-8")
            user = directory / "user.txt"
            user.write_text(
                "# names and technical terms\n"
                "kubernetes\n"
                "jonathan\n"
                "c++\n"
                "well-known\n",
                encoding="utf-8",
            )

            dictionary = Dictionary.from_files([main], [user])
            checker = SpellChecker(dictionary)

            for word in ["kubernetes", "Kubernetes", "Jonathan", "C++", "well-known"]:
                with self.subTest(word=word):
                    self.assertEqual(checker.check(word).status, "valid")

    def test_custom_dictionary_can_fix_unknown_word(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            main = directory / "main.txt"
            main.write_text("hello\n", encoding="utf-8")
            user = directory / "user.txt"
            user.write_text("kubernetes\n", encoding="utf-8")

            dictionary = Dictionary.from_files([main], [user])
            checker = SpellChecker(dictionary, max_distance=1)

            self.assertIn("kubernetes", words_of(checker, "kubernetis"))


class RankingTests(unittest.TestCase):
    def test_ties_are_alphabetical_without_frequencies(self) -> None:
        checker = make_checker(["bat", "cat", "dat", "eat", "fat"], max_distance=1)
        self.assertEqual(
            words_of(checker, "aat"),
            ["bat", "cat", "dat", "eat", "fat"],
        )

    def test_frequency_breaks_distance_ties(self) -> None:
        checker = make_checker(
            ["bat", "cat", "dat", "eat", "fat"],
            frequencies={"fat": 9.0},
            max_distance=1,
        )
        self.assertEqual(
            words_of(checker, "aat"),
            ["fat", "bat", "cat", "dat", "eat"],
        )

    def test_distance_is_primary(self) -> None:
        checker = make_checker(
            ["cat", "cats"],
            frequencies={"cats": 100.0},
            max_distance=2,
        )
        result = checker.check("ca")
        self.assertEqual(
            [
                (suggestion.word, suggestion.distance)
                for suggestion in result.suggestions
            ],
            [("cat", 1), ("cats", 2)],
        )

    def test_suggestion_limit(self) -> None:
        words = ["aaa", "aab", "aac", "aad", "aae", "aaf", "aag", "aah"]
        checker = make_checker(words, max_distance=1, max_suggestions=3)
        self.assertEqual(len(checker.check("aax").suggestions), 3)

    def test_zero_suggestions_configuration(self) -> None:
        checker = make_checker(["hello"], max_distance=2, max_suggestions=0)
        result = checker.check("helo")
        self.assertEqual(result.status, "unknown")
        self.assertEqual(result.suggestions, ())


class NoCloseMatchTests(unittest.TestCase):
    def test_no_suggestions_within_limit(self) -> None:
        checker = make_checker(["hello"], max_distance=1)
        result = checker.check("qqqqq")
        self.assertEqual(result.status, "unknown")
        self.assertEqual(result.suggestions, ())

    def test_no_suggestions_at_distance_zero(self) -> None:
        checker = make_checker(["hello"], max_distance=0)
        result = checker.check("helo")
        self.assertEqual(result.status, "unknown")
        self.assertEqual(result.suggestions, ())


class CapitalizationTests(unittest.TestCase):
    def test_valid_word_keeps_original_case(self) -> None:
        checker = make_checker(["hello"])
        result = checker.check("HeLLo")
        self.assertEqual(result.status, "valid")
        self.assertEqual(result.original, "HeLLo")

    def test_title_case_suggestion_is_title_cased(self) -> None:
        checker = make_checker(["hello"])
        suggestion = checker.check("Helo").suggestions[0]
        self.assertEqual(suggestion.display_word, "Hello")
        self.assertEqual(suggestion.word, "hello")

    def test_uppercase_suggestion_is_uppercased(self) -> None:
        checker = make_checker(["hello"])
        suggestion = checker.check("HELO").suggestions[0]
        self.assertEqual(suggestion.display_word, "HELLO")


class ApostropheTests(unittest.TestCase):
    def setUp(self) -> None:
        self.checker = make_checker(["don't"], max_distance=1)

    def test_ascii_and_curly_apostrophes_are_valid(self) -> None:
        self.assertEqual(self.checker.check("don't").status, "valid")
        self.assertEqual(self.checker.check("don’t").status, "valid")

    def test_missing_apostrophe_is_suggested(self) -> None:
        self.assertIn(("don't", 1), _pairs(self.checker.check("dont")))

    def test_suggestion_preserves_title_case(self) -> None:
        suggestion = self.checker.check("Dont").suggestions[0]
        self.assertEqual(suggestion.display_word, "Don't")


class HyphenTests(unittest.TestCase):
    def setUp(self) -> None:
        self.checker = make_checker(["well", "known"], max_distance=2)

    def test_hyphenated_compound_of_known_parts_is_valid(self) -> None:
        self.assertEqual(self.checker.check("well-known").status, "valid")
        self.assertEqual(self.checker.check("well–known").status, "valid")

    def test_bad_component_is_corrected_in_compound(self) -> None:
        pairs = _pairs(self.checker.check("well-knwon"))
        self.assertIn(("well-known", 2), pairs)


class InputValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.checker = make_checker(["hello"])

    def test_empty_and_whitespace_are_empty(self) -> None:
        self.assertEqual(self.checker.check("").status, "empty")
        self.assertEqual(self.checker.check("   ").status, "empty")
        self.assertEqual(self.checker.check("\t\n").status, "empty")

    def test_multiple_words_are_invalid(self) -> None:
        result = self.checker.check("hello world")
        self.assertEqual(result.status, "invalid")
        self.assertEqual(result.suggestions, ())


class UnicodeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.checker = make_checker(["café", "naïve"], max_distance=1)

    def test_unicode_words_are_valid(self) -> None:
        self.assertEqual(self.checker.check("café").status, "valid")
        self.assertEqual(self.checker.check("CAFÉ").status, "valid")
        self.assertEqual(self.checker.check("naïve").status, "valid")

    def test_diacritic_difference_is_one_edit(self) -> None:
        self.assertIn(("café", 1), _pairs(self.checker.check("cafe")))
        self.assertIn(("naïve", 1), _pairs(self.checker.check("naive")))


def _pairs(result) -> set[tuple[str, int]]:
    return {
        (suggestion.word, suggestion.distance)
        for suggestion in result.suggestions
    }


if __name__ == "__main__":
    unittest.main()
