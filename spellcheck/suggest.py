"""Spell-checking service: validity checks, suggestions, and ranking."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .dictionary import Candidate, Dictionary
from .distance import bounded_levenshtein_distance
from .text import apply_input_case, is_single_token, normalize_word

CheckStatus = Literal["valid", "unknown", "empty", "invalid"]


@dataclass(frozen=True)
class Suggestion:
    """A ranked spelling suggestion."""

    word: str
    distance: int
    frequency: float
    display_word: str


@dataclass(frozen=True)
class CheckResult:
    """The outcome of checking one input word."""

    original: str
    normalized: str
    status: CheckStatus
    suggestions: tuple[Suggestion, ...]
    max_distance: int

    @property
    def is_valid(self) -> bool:
        return self.status == "valid"

    @property
    def has_suggestions(self) -> bool:
        return bool(self.suggestions)


class SpellChecker:
    """Check words and produce ranked suggestions.

    Ranking is deterministic: smallest edit distance first, then highest
    frequency (when a frequency is available), then alphabetical order.
    """

    def __init__(
        self,
        dictionary: Dictionary,
        max_distance: int = 2,
        max_suggestions: int = 5,
    ) -> None:
        if max_distance < 0:
            raise ValueError("max_distance must be non-negative")
        if max_suggestions < 0:
            raise ValueError("max_suggestions must be non-negative")

        self.dictionary = dictionary
        self.max_distance = max_distance
        self.max_suggestions = max_suggestions

    def check(self, raw_word: str) -> CheckResult:
        """Check one input token and return a structured result."""

        original = raw_word.strip()

        if not original:
            return CheckResult(
                original="",
                normalized="",
                status="empty",
                suggestions=(),
                max_distance=self.max_distance,
            )

        if not is_single_token(original):
            return CheckResult(
                original=original,
                normalized=normalize_word(original),
                status="invalid",
                suggestions=(),
                max_distance=self.max_distance,
            )

        normalized = normalize_word(original)

        if self.dictionary.contains(normalized):
            return CheckResult(
                original=original,
                normalized=normalized,
                status="valid",
                suggestions=(),
                max_distance=self.max_distance,
            )

        # A hyphenated compound is valid when every component is a known word.
        if "-" in normalized and self._is_valid_hyphenated_compound(normalized):
            return CheckResult(
                original=original,
                normalized=normalized,
                status="valid",
                suggestions=(),
                max_distance=self.max_distance,
            )

        if self.max_suggestions == 0:
            return CheckResult(
                original=original,
                normalized=normalized,
                status="unknown",
                suggestions=(),
                max_distance=self.max_distance,
            )

        distance_by_word: dict[str, int] = {
            candidate.word: candidate.distance
            for candidate in self.dictionary.candidates(
                normalized, self.max_distance
            )
        }

        # Add corrections that operate on the components of a hyphenated word,
        # e.g. "well-knwon" -> "well-known", even though the dictionary rarely
        # contains the compound itself.
        if "-" in normalized:
            for word, distance in self._hyphenated_corrections(normalized).items():
                existing = distance_by_word.get(word)
                if existing is None or distance < existing:
                    distance_by_word[word] = distance

        ranked = sorted(
            (
                Suggestion(
                    word=word,
                    distance=distance,
                    frequency=self.dictionary.frequency(word),
                    display_word=apply_input_case(original, word),
                )
                for word, distance in distance_by_word.items()
                if distance <= self.max_distance
            ),
            key=lambda suggestion: (
                suggestion.distance,
                -suggestion.frequency,
                suggestion.word,
            ),
        )

        return CheckResult(
            original=original,
            normalized=normalized,
            status="unknown",
            suggestions=tuple(ranked[: self.max_suggestions]),
            max_distance=self.max_distance,
        )

    def _is_valid_hyphenated_compound(self, normalized: str) -> bool:
        parts = normalized.split("-")
        if len(parts) < 2:
            return False
        return all(
            part and self.dictionary.contains(part) for part in parts
        )

    def _hyphenated_corrections(self, normalized: str) -> dict[str, int]:
        """Suggest corrected hyphenated compounds by fixing unknown parts."""

        parts = normalized.split("-")
        if len(parts) < 2 or any(not part for part in parts):
            return {}

        unknown_indices = [
            index
            for index, part in enumerate(parts)
            if not self.dictionary.contains(part)
        ]
        if not unknown_indices:
            return {}

        variants: set[tuple[str, ...]] = {tuple(parts)}
        replacement_budget = max(1, self.max_suggestions) * 2

        for index in unknown_indices:
            part_candidates: list[Candidate] = self.dictionary.candidates(
                parts[index], self.max_distance
            )
            part_candidates.sort(
                key=lambda candidate: (
                    candidate.distance,
                    -self.dictionary.frequency(candidate.word),
                    candidate.word,
                )
            )
            replacements = [
                candidate.word
                for candidate in part_candidates[:replacement_budget]
            ]
            if not replacements:
                continue

            expanded: set[tuple[str, ...]] = set()
            for variant in variants:
                if index >= len(variant):
                    continue
                for replacement in replacements:
                    pieces = list(variant)
                    pieces[index] = replacement
                    expanded.add(tuple(pieces))
            variants.update(expanded)

            # Defensive cap for pathological inputs with many bad components.
            if len(variants) > 256:
                variants = set(sorted(variants)[:256])

        corrections: dict[str, int] = {}
        for variant in variants:
            if len(variant) < 2:
                continue
            word = "-".join(variant)
            if word == normalized:
                continue
            distance = bounded_levenshtein_distance(
                normalized, word, self.max_distance
            )
            if distance is not None:
                corrections[word] = distance
        return corrections
