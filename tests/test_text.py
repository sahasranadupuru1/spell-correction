"""Tests for normalization and case-preserving display."""

from __future__ import annotations

import unittest

from spellcheck.text import apply_input_case, is_single_token, normalize_word


class NormalizationTests(unittest.TestCase):
    def test_lowercases_and_trims(self) -> None:
        self.assertEqual(normalize_word("  HeLLo  "), "hello")

    def test_curly_apostrophe_matches_ascii(self) -> None:
        self.assertEqual(normalize_word("Don’t"), "don't")
        self.assertEqual(normalize_word("Don't"), "don't")

    def test_unicode_dash_matches_hyphen(self) -> None:
        self.assertEqual(normalize_word("well–known"), "well-known")
        self.assertEqual(normalize_word("well—known"), "well-known")

    def test_nfc_composition(self) -> None:
        decomposed = "cafe\u0301"  # e + combining acute accent
        self.assertEqual(normalize_word(decomposed), "café")

    def test_diacritics_are_preserved(self) -> None:
        self.assertEqual(normalize_word("CAFÉ"), "café")
        self.assertNotEqual(normalize_word("café"), normalize_word("cafe"))

    def test_single_token(self) -> None:
        self.assertTrue(is_single_token("hello"))
        self.assertTrue(is_single_token("  hello  "))
        self.assertTrue(is_single_token("don't"))
        self.assertFalse(is_single_token(""))
        self.assertFalse(is_single_token("   "))
        self.assertFalse(is_single_token("two words"))


class CaseDisplayTests(unittest.TestCase):
    def test_lowercase_input_keeps_lowercase_suggestion(self) -> None:
        self.assertEqual(apply_input_case("recieve", "receive"), "receive")

    def test_title_case_input_title_cases_suggestion(self) -> None:
        self.assertEqual(apply_input_case("Recieve", "receive"), "Receive")
        self.assertEqual(apply_input_case("Don’t", "don't"), "Don't")

    def test_uppercase_input_uppercases_suggestion(self) -> None:
        self.assertEqual(apply_input_case("RECIEVE", "receive"), "RECEIVE")

    def test_mixed_case_input_uses_canonical_form(self) -> None:
        self.assertEqual(apply_input_case("ReCiEvE", "receive"), "receive")


if __name__ == "__main__":
    unittest.main()
