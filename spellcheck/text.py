"""Text normalization shared by the dictionary, checker, and CLI.

Behavior is deliberately small and deterministic:

* Unicode is normalized to NFC.
* Leading and trailing whitespace is removed.
* Curly/typographic apostrophes are mapped to the ASCII apostrophe (``'``).
* Unicode dash variants are mapped to the ASCII hyphen-minus (``-``).
* Matching is case-insensitive through :meth:`str.lower`.
* Diacritics are significant: ``cafe`` and ``café`` are different words.
* A word may contain any non-whitespace characters, so a user dictionary can
  hold technical terms such as ``c++`` or ``c#``.  Lines containing internal
  whitespace are rejected by the dictionary loader instead of being silently
  split.
"""

from __future__ import annotations

import unicodedata

# Characters that should behave like an ASCII apostrophe.
_APOSTROPHES = {
    "\u2018": "'",  # left single quotation mark
    "\u2019": "'",  # right single quotation mark
    "\u02bb": "'",  # modifier letter turned comma
    "\u02bc": "'",  # modifier letter apostrophe
    "\u00b4": "'",  # acute accent used as an apostrophe
}

# Characters that should behave like an ASCII hyphen-minus.
_DASHES = {
    "\u2010": "-",  # hyphen
    "\u2011": "-",  # non-breaking hyphen
    "\u2012": "-",  # figure dash
    "\u2013": "-",  # en dash
    "\u2014": "-",  # em dash
    "\u2212": "-",  # minus sign
}

_TRANSLATION_TABLE = str.maketrans({**_APOSTROPHES, **_DASHES})


def normalize_word(value: str) -> str:
    """Return the canonical form used for all lookups and distances."""

    normalized = unicodedata.normalize("NFC", value)
    normalized = normalized.strip()
    normalized = normalized.translate(_TRANSLATION_TABLE)
    normalized = normalized.lower()
    return unicodedata.normalize("NFC", normalized)


def is_single_token(value: str) -> bool:
    """Return ``True`` when *value* is non-empty and contains no whitespace."""

    stripped = value.strip()
    return bool(stripped) and not any(character.isspace() for character in stripped)


def apply_input_case(original: str, suggestion: str) -> str:
    """Render *suggestion* in the capitalization style of *original*.

    * All-uppercase input produces an all-uppercase suggestion.
    * Title-case input (an uppercase first letter and no other uppercase
      letters) produces a title-case suggestion.
    * Everything else, including mixed case, keeps the canonical lowercase
      dictionary form.

    Only the display form is changed; ranking and distances always use the
    normalized lowercase form.
    """

    original = original.strip()
    letters = [character for character in original if character.isalpha()]

    if letters and all(character.isupper() for character in letters):
        return suggestion.upper()

    if (
        original
        and original[0].isupper()
        and all(not character.isupper() for character in original[1:])
    ):
        return suggestion[:1].upper() + suggestion[1:]

    return suggestion
