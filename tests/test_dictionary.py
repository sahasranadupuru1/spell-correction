"""Tests for dictionary loading and lossless candidate generation."""

from __future__ import annotations

import random
import tempfile
import unittest
from pathlib import Path

from spellcheck.dictionary import Dictionary, DictionaryError
from spellcheck.distance import levenshtein_distance


class DictionaryFileTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_loads_comments_blanks_and_user_dictionary(self) -> None:
        main = self.directory / "main.txt"
        main.write_text(
            "# a comment\nHello\nworld\n\nhello\ncafé\ndon't\n",
            encoding="utf-8",
        )
        user = self.directory / "user.txt"
        user.write_text("# names and technical terms\nKubernetes\nC++\n", encoding="utf-8")

        dictionary = Dictionary.from_files([main], [user])

        self.assertEqual(len(dictionary), 6)
        self.assertIn("hello", dictionary)
        self.assertIn("HELLO", dictionary)
        self.assertIn("kubernetes", dictionary)
        self.assertIn("c++", dictionary)
        self.assertIn("café", dictionary)
        self.assertIn("don't", dictionary)

    def test_frequency_file_is_loaded(self) -> None:
        main = self.directory / "main.txt"
        main.write_text("hello\nworld\ncafé\n", encoding="utf-8")
        frequencies = self.directory / "freq.tsv"
        frequencies.write_text(
            "# comment\nhello\t5.0\nworld 3.5\ncafé\t2.25\n",
            encoding="utf-8",
        )

        dictionary = Dictionary.from_files([main], frequency_path=frequencies)

        self.assertEqual(dictionary.frequency("Hello"), 5.0)
        self.assertEqual(dictionary.frequency("world"), 3.5)
        self.assertEqual(dictionary.frequency("CAFÉ"), 2.25)
        self.assertEqual(dictionary.frequency("missing"), 0.0)

    def test_missing_file_has_clear_error(self) -> None:
        with self.assertRaises(FileNotFoundError):
            Dictionary.from_files([self.directory / "missing.txt"])

    def test_internal_whitespace_is_rejected(self) -> None:
        main = self.directory / "main.txt"
        main.write_text("two words\n", encoding="utf-8")

        with self.assertRaises(DictionaryError):
            Dictionary.from_files([main])

    def test_no_paths_is_an_error(self) -> None:
        with self.assertRaises(ValueError):
            Dictionary.from_files([], [])


class CandidateSearchTests(unittest.TestCase):
    @staticmethod
    def _brute_force(
        dictionary: Dictionary, query: str, max_distance: int
    ) -> set[tuple[str, int]]:
        results = set()
        for word in dictionary.words:
            distance = levenshtein_distance(query, word)
            if distance <= max_distance:
                results.add((word, distance))
        return results

    def test_candidates_find_each_edit_operation(self) -> None:
        dictionary = Dictionary(["cat", "cats", "cut", "act", "at", "scat"])

        self.assertIn(("cats", 1), _as_pairs(dictionary.candidates("cat", 1)))
        self.assertIn(("cat", 1), _as_pairs(dictionary.candidates("cats", 1)))
        self.assertIn(("cut", 1), _as_pairs(dictionary.candidates("cat", 1)))
        self.assertIn(("cat", 1), _as_pairs(dictionary.candidates("scat", 1)))

    def test_filter_is_lossless_against_brute_force(self) -> None:
        random_source = random.Random(20261109)
        alphabet = "abc'-é"

        for _ in range(12):
            words = set()
            while len(words) < 30:
                length = random_source.randint(1, 6)
                words.add(
                    "".join(random_source.choice(alphabet) for _ in range(length))
                )
            dictionary = Dictionary(words)

            for _ in range(25):
                length = random_source.randint(0, 6)
                query = "".join(
                    random_source.choice(alphabet) for _ in range(length)
                )
                for max_distance in range(0, 4):
                    expected = self._brute_force(dictionary, query, max_distance)
                    actual = _as_pairs(
                        dictionary.candidates(query, max_distance)
                    )
                    with self.subTest(
                        query=query,
                        max_distance=max_distance,
                        words=words,
                    ):
                        self.assertEqual(actual, expected)

    def test_candidate_distance_is_exact(self) -> None:
        dictionary = Dictionary(["receive", "relieve", "believe", "recede"])
        pairs = _as_pairs(dictionary.candidates("recieve", 2))
        self.assertIn(("receive", 2), pairs)
        for word, distance in pairs:
            self.assertEqual(distance, levenshtein_distance("recieve", word))

    def test_negative_distance_is_rejected(self) -> None:
        dictionary = Dictionary(["cat"])
        with self.assertRaises(ValueError):
            dictionary.candidates("cat", -1)


def _as_pairs(candidates) -> set[tuple[str, int]]:
    return {(candidate.word, candidate.distance) for candidate in candidates}


if __name__ == "__main__":
    unittest.main()
