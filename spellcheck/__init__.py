"""A dependency-free English spell checker.

The package exposes the Levenshtein implementation, dictionary loader, and
suggestion service.  The command-line interface lives in :mod:`spellcheck.cli`.
"""

from .distance import bounded_levenshtein_distance, levenshtein_distance
from .dictionary import Candidate, Dictionary
from .suggest import CheckResult, SpellChecker, Suggestion
from .text import normalize_word

__all__ = [
    "Candidate",
    "CheckResult",
    "Dictionary",
    "SpellChecker",
    "Suggestion",
    "bounded_levenshtein_distance",
    "levenshtein_distance",
    "normalize_word",
]

__version__ = "1.0.0"
