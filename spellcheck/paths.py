"""Default locations for the bundled data files."""

from __future__ import annotations

from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
DATA_DIR = PACKAGE_DIR / "data"

DEFAULT_DICTIONARY = DATA_DIR / "words.txt"
DEFAULT_FREQUENCIES = DATA_DIR / "frequencies.tsv"
DEFAULT_USER_DICTIONARY = DATA_DIR / "user_words.txt"
