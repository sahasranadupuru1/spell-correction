"""Dictionary loading and lossless candidate generation.

The candidate search is designed so that it cannot discard a word that is
within the requested edit-distance limit:

1. Only words whose length differs by at most ``max_distance`` are visited.
2. A character-multiset lower bound is applied.  An insertion or deletion
   changes the L1 distance between character counts by 1; a substitution
   changes it by 2.  Therefore any word within distance ``d`` satisfies
   ``L1(counts(query), counts(word)) <= 2 * d``.
3. The banded Levenshtein implementation verifies every surviving word and
   returns its exact distance.

The filter is conservative; the final distance calculation is the authority.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping, Sequence

from .distance import bounded_levenshtein_distance
from .text import normalize_word


@dataclass(frozen=True)
class Candidate:
    """A dictionary word within the configured edit distance."""

    word: str
    distance: int


class DictionaryError(ValueError):
    """Raised when a dictionary file is malformed."""


def _read_words(path: Path) -> Iterable[str]:
    """Yield normalized entries from a word-list file.

    Blank lines and lines whose first non-whitespace character is ``#`` are
    comments.  A ``#`` inside a line is part of the word (so ``c#`` works).
    Internal whitespace is an error because every entry must be one word.
    """

    try:
        with path.open("r", encoding="utf-8") as handle:
            for line_number, raw_line in enumerate(handle, start=1):
                line = raw_line.strip()
                if not line or line.startswith("#"):
                    continue
                if any(character.isspace() for character in line):
                    raise DictionaryError(
                        f"{path}:{line_number}: expected one word, got {line!r}"
                    )
                yield normalize_word(line)
    except FileNotFoundError as exc:
        raise FileNotFoundError(f"dictionary file not found: {path}") from exc


def _read_frequencies(path: Path) -> dict[str, float]:
    """Read ``word<TAB>frequency`` lines.

    Whitespace-separated files are also accepted.  Invalid numeric values are
    reported with the file name and line number.
    """

    frequencies: dict[str, float] = {}
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line_number, raw_line in enumerate(handle, start=1):
                line = raw_line.strip()
                if not line or line.startswith("#"):
                    continue
                fields = line.split("\t") if "\t" in line else line.split()
                if len(fields) != 2:
                    raise DictionaryError(
                        f"{path}:{line_number}: expected 'word<TAB>frequency', "
                        f"got {line!r}"
                    )
                word, value = fields
                try:
                    frequency = float(value)
                except ValueError as exc:
                    raise DictionaryError(
                        f"{path}:{line_number}: invalid frequency {value!r}"
                    ) from exc
                frequencies[normalize_word(word)] = frequency
    except FileNotFoundError as exc:
        raise FileNotFoundError(f"frequency file not found: {path}") from exc
    return frequencies


def _sorted_intersection_size(first: str, second: str) -> int:
    """Return the size of the multiset intersection of two sorted strings."""

    index_first = 0
    index_second = 0
    matches = 0
    first_length = len(first)
    second_length = len(second)

    while index_first < first_length and index_second < second_length:
        first_char = first[index_first]
        second_char = second[index_second]
        if first_char == second_char:
            matches += 1
            index_first += 1
            index_second += 1
        elif first_char < second_char:
            index_first += 1
        else:
            index_second += 1

    return matches


class Dictionary:
    """An immutable collection of normalized words and optional frequencies."""

    def __init__(
        self,
        words: Iterable[str],
        frequencies: Mapping[str, float] | None = None,
    ) -> None:
        normalized_words = set()
        for raw_word in words:
            word = normalize_word(raw_word)
            if word and not any(character.isspace() for character in word):
                normalized_words.add(word)

        self._words: tuple[str, ...] = tuple(sorted(normalized_words))
        self._word_set = frozenset(self._words)

        # Each bucket holds (word, sorted_characters).  Sorting the characters
        # once makes the character-multiset filter a linear two-pointer scan.
        self._by_length: dict[int, list[tuple[str, str]]] = defaultdict(list)
        for word in self._words:
            self._by_length[len(word)].append((word, "".join(sorted(word))))

        normalized_frequencies: dict[str, float] = {}
        if frequencies:
            for raw_word, value in frequencies.items():
                word = normalize_word(raw_word)
                if word:
                    try:
                        normalized_frequencies[word] = float(value)
                    except (TypeError, ValueError):
                        continue
        self._frequencies = normalized_frequencies

    @classmethod
    def from_files(
        cls,
        dictionary_paths: Sequence[Path],
        user_dictionary_paths: Sequence[Path] = (),
        frequency_path: Path | None = None,
    ) -> "Dictionary":
        """Load one or more word lists and an optional frequency file."""

        if not dictionary_paths and not user_dictionary_paths:
            raise ValueError("at least one dictionary path is required")

        words: list[str] = []
        for path in dictionary_paths:
            words.extend(_read_words(Path(path)))
        for path in user_dictionary_paths:
            words.extend(_read_words(Path(path)))

        frequencies = _read_frequencies(Path(frequency_path)) if frequency_path else {}
        return cls(words, frequencies=frequencies)

    def __len__(self) -> int:
        return len(self._words)

    def __contains__(self, raw_word: object) -> bool:
        if not isinstance(raw_word, str):
            return False
        return normalize_word(raw_word) in self._word_set

    @property
    def words(self) -> tuple[str, ...]:
        """The sorted, normalized words in this dictionary."""

        return self._words

    def contains(self, raw_word: str) -> bool:
        """Return whether *raw_word* is present, ignoring normalization."""

        return normalize_word(raw_word) in self._word_set

    def frequency(self, raw_word: str) -> float:
        """Return the stored frequency, or ``0.0`` when unavailable."""

        return self._frequencies.get(normalize_word(raw_word), 0.0)

    def candidates(self, raw_word: str, max_distance: int) -> list[Candidate]:
        """Return every dictionary word within ``max_distance`` edits.

        The returned list is not ranked; callers apply frequency and
        alphabetical tie-breaking as appropriate.
        """

        if max_distance < 0:
            raise ValueError("max_distance must be non-negative")

        query = normalize_word(raw_word)
        if not query:
            # The empty string is at distance len(word) from every word.
            return [
                Candidate(word=word, distance=len(word))
                for word in self._words
                if len(word) <= max_distance
            ]

        query_length = len(query)
        query_signature = "".join(sorted(query))
        candidates: list[Candidate] = []
        length_limit = query_length + max_distance
        minimum_length = max(0, query_length - max_distance)

        for length in range(minimum_length, length_limit + 1):
            for word, signature in self._by_length.get(length, ()):
                common = _sorted_intersection_size(query_signature, signature)
                # Equivalent to L1(char counts) > 2 * max_distance.
                if query_length + length - 2 * common > 2 * max_distance:
                    continue

                distance = bounded_levenshtein_distance(
                    query, word, max_distance
                )
                if distance is not None:
                    candidates.append(Candidate(word=word, distance=distance))

        return candidates
