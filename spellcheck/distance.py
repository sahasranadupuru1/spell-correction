"""Levenshtein edit distance implemented from scratch.

The distance is the minimum number of single-character insertions, deletions,
and substitutions needed to turn one string into the other.  Every edit costs
1 and a matching character costs 0.  This is the standard Levenshtein metric;
adjacent transpositions are *not* one edit (that would be Damerau-Levenshtein).
"""

from __future__ import annotations

from typing import Optional


def levenshtein_distance(source: str, target: str) -> int:
    """Return the Levenshtein distance between two strings.

    Dynamic programming recurrence used by the implementation::

        D[i][0] = i
        D[0][j] = j
        D[i][j] = min(
            D[i - 1][j] + 1,          # delete source[i - 1]
            D[i][j - 1] + 1,          # insert target[j - 1]
            D[i - 1][j - 1] + cost,   # match / substitute
        )

    where ``cost`` is 0 when the two characters match and 1 otherwise.
    Only the previous row is retained, so the memory complexity is
    ``O(min(len(source), len(target)))``.  Time complexity is
    ``O(len(source) * len(target))``.
    """

    if source == target:
        return 0
    if not source:
        return len(target)
    if not target:
        return len(source)

    # Keep the second row as short as possible.
    if len(source) < len(target):
        source, target = target, source

    previous = list(range(len(target) + 1))

    for row, source_char in enumerate(source, start=1):
        current = [row]
        for column, target_char in enumerate(target, start=1):
            insertion = current[column - 1] + 1
            deletion = previous[column] + 1
            substitution = previous[column - 1] + (
                0 if source_char == target_char else 1
            )
            current.append(min(insertion, deletion, substitution))
        previous = current

    return previous[-1]


def bounded_levenshtein_distance(
    source: str, target: str, max_distance: int
) -> Optional[int]:
    """Return the distance if it is at most ``max_distance``, else ``None``.

    This is a banded variant of the same dynamic program.  Any edit path whose
    cost is at most ``d`` can never move more than ``d`` cells away from the
    main diagonal, because every insertion/deletion changes the row/column
    difference by one and already costs one.  Cells outside that band are
    therefore irrelevant and are left as infinity.

    The result is exact for every distance up to and including
    ``max_distance``.  ``None`` means the real distance is greater than
    ``max_distance``.
    """

    if max_distance < 0:
        raise ValueError("max_distance must be non-negative")

    if source == target:
        return 0

    if abs(len(source) - len(target)) > max_distance:
        return None

    if not source:
        return len(target) if len(target) <= max_distance else None
    if not target:
        return len(source) if len(source) <= max_distance else None

    source_length = len(source)
    target_length = len(target)

    # A value larger than any distance we care about.  It also acts as the
    # "outside the band" sentinel.
    infinity = max_distance + 1

    previous = [infinity] * (target_length + 1)
    for column in range(min(target_length, max_distance) + 1):
        previous[column] = column

    for row in range(1, source_length + 1):
        current = [infinity] * (target_length + 1)
        if row <= max_distance:
            current[0] = row

        first_column = max(1, row - max_distance)
        last_column = min(target_length, row + max_distance)

        for column in range(first_column, last_column + 1):
            substitution = previous[column - 1] + (
                0 if source[row - 1] == target[column - 1] else 1
            )
            insertion = current[column - 1] + 1
            deletion = previous[column] + 1
            current[column] = min(substitution, insertion, deletion)

        previous = current

    result = previous[target_length]
    return result if result <= max_distance else None
