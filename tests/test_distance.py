"""Tests for the from-scratch Levenshtein implementation."""

from __future__ import annotations

import unittest

from spellcheck.distance import (
    bounded_levenshtein_distance,
    levenshtein_distance,
)


class LevenshteinDistanceTests(unittest.TestCase):
    def test_assignment_example(self) -> None:
        self.assertEqual(levenshtein_distance("recieve", "receive"), 2)

    def test_identical_words_have_distance_zero(self) -> None:
        self.assertEqual(levenshtein_distance("spelling", "spelling"), 0)
        self.assertEqual(levenshtein_distance("", ""), 0)

    def test_insertion_costs_one(self) -> None:
        self.assertEqual(levenshtein_distance("cat", "cats"), 1)
        self.assertEqual(levenshtein_distance("hello", "hellos"), 1)

    def test_deletion_costs_one(self) -> None:
        self.assertEqual(levenshtein_distance("cats", "cat"), 1)
        self.assertEqual(levenshtein_distance("hellos", "hello"), 1)

    def test_replacement_costs_one(self) -> None:
        self.assertEqual(levenshtein_distance("cat", "cut"), 1)
        self.assertEqual(levenshtein_distance("kitten", "sitten"), 1)

    def test_empty_string_needs_one_edit_per_character(self) -> None:
        self.assertEqual(levenshtein_distance("", "abc"), 3)
        self.assertEqual(levenshtein_distance("abc", ""), 3)

    def test_distance_is_symmetric(self) -> None:
        pairs = [
            ("kitten", "sitting"),
            ("recieve", "receive"),
            ("", "word"),
            ("café", "cafe"),
        ]
        for first, second in pairs:
            with self.subTest(first=first, second=second):
                self.assertEqual(
                    levenshtein_distance(first, second),
                    levenshtein_distance(second, first),
                )

    def test_standard_example_kitten_sitting(self) -> None:
        self.assertEqual(levenshtein_distance("kitten", "sitting"), 3)

    def test_transposition_is_two_edits_not_one(self) -> None:
        # Standard Levenshtein has no adjacent-transposition primitive.
        self.assertEqual(levenshtein_distance("ab", "ba"), 2)

    def test_unicode_characters_are_single_symbols(self) -> None:
        self.assertEqual(levenshtein_distance("café", "cafe"), 1)
        self.assertEqual(levenshtein_distance("naïve", "naive"), 1)
        self.assertEqual(levenshtein_distance("😀cat", "cat"), 1)

    def test_bounded_matches_full_distance_within_limit(self) -> None:
        pairs = [
            ("recieve", "receive", 2),
            ("kitten", "sitting", 3),
            ("cat", "cats", 1),
            ("", "abc", 3),
            ("café", "cafe", 1),
        ]
        for first, second, limit in pairs:
            with self.subTest(first=first, second=second):
                self.assertEqual(
                    bounded_levenshtein_distance(first, second, limit),
                    levenshtein_distance(first, second),
                )

    def test_bounded_returns_none_above_limit(self) -> None:
        self.assertIsNone(bounded_levenshtein_distance("kitten", "sitting", 2))
        self.assertIsNone(bounded_levenshtein_distance("abc", "", 2))
        self.assertIsNone(bounded_levenshtein_distance("recieve", "receive", 1))

    def test_bounded_handles_negative_limit(self) -> None:
        with self.assertRaises(ValueError):
            bounded_levenshtein_distance("a", "b", -1)


if __name__ == "__main__":
    unittest.main()
