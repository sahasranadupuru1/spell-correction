#!/usr/bin/env python3
"""Build the bundled English dictionary from SCOWL's Hunspell releases.

The script downloads two large SCOWL dictionaries (US and British), expands
their affix rules into surface forms (plurals, verb forms, comparatives,
possessives, and so on), merges them, normalizes case, and writes:

    spellcheck/data/words.txt
    spellcheck/data/frequencies.tsv   (when wordfreq is installed)

The downloads are pinned by SHA-256 so a rebuild is reproducible.  Runtime
spell checking never downloads anything: it only reads the generated files.

Usage:
    python scripts/build_dictionary.py
    python scripts/build_dictionary.py --skip-frequency
    python scripts/build_dictionary.py --data-dir /tmp/my-data
"""

from __future__ import annotations

import argparse
import hashlib
import re
import shutil
import sys
import tempfile
import unicodedata
import urllib.request
import zipfile
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator, Pattern

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATA_DIR = PROJECT_ROOT / "spellcheck" / "data"
LICENSE_SOURCE = PROJECT_ROOT / "scripts" / "licenses" / "SCOWL-Copyright.txt"
RELEASE = "rel-2026.02.25"


@dataclass(frozen=True)
class Source:
    name: str
    url: str
    sha256: str
    dic_name: str
    aff_name: str
    readme_name: str


SOURCES = (
    Source(
        name="en_US-large",
        url=(
            "https://github.com/en-wl/wordlist/releases/download/"
            f"{RELEASE}/hunspell-en_US-large-2026.02.25.zip"
        ),
        sha256="06ab5a2a12c29033f100988d3b0a5e53dcad40bf2473ccb78270619d1da99321",
        dic_name="en_US-large.dic",
        aff_name="en_US-large.aff",
        readme_name="README_en_US-large.txt",
    ),
    Source(
        name="en_GB-large",
        url=(
            "https://github.com/en-wl/wordlist/releases/download/"
            f"{RELEASE}/hunspell-en_GB-large-2026.02.25.zip"
        ),
        sha256="704a49438a3a9d4f11cd76db433a6b230b9ce8770ee13fa28700052c4517ddc1",
        dic_name="en_GB-large.dic",
        aff_name="en_GB-large.aff",
        readme_name="README_en_GB-large.txt",
    ),
)


@dataclass(frozen=True)
class AffixRule:
    strip: str
    add: str
    condition: str
    regex: Pattern[str]


def _compile_condition(condition: str, at_end: bool) -> Pattern[str]:
    if not condition or condition == ".":
        return re.compile(r"^" if not at_end else r"$")
    expression = f"(?:{condition})"
    anchored = f"{expression}$" if at_end else f"^{expression}"
    try:
        return re.compile(anchored)
    except re.error:
        # SCOWL's conditions are simple; an unknown extension should not make
        # the whole build fail.  Treat it as "always matches".
        return re.compile(r"^" if not at_end else r"$")


def parse_affix_file(text: str) -> tuple[
    dict[str, list[AffixRule]],
    dict[str, list[AffixRule]],
    dict[str, bool],
    dict[str, bool],
]:
    """Parse PFX/SFX blocks from a Hunspell ``.aff`` file."""

    prefixes: dict[str, list[AffixRule]] = defaultdict(list)
    suffixes: dict[str, list[AffixRule]] = defaultdict(list)
    prefix_cross: dict[str, bool] = {}
    suffix_cross: dict[str, bool] = {}

    lines = text.splitlines()
    index = 0

    while index < len(lines):
        line = lines[index].split("#", 1)[0].strip()
        index += 1
        if not line:
            continue

        fields = line.split()
        if (
            len(fields) < 4
            or fields[0] not in {"PFX", "SFX"}
            or not fields[3].isdigit()
        ):
            continue

        kind, flag, cross_product, count_text = fields[:4]
        count = int(count_text)
        bucket = prefixes if kind == "PFX" else suffixes
        cross_bucket = prefix_cross if kind == "PFX" else suffix_cross
        cross_bucket[flag] = cross_product == "Y"

        for _ in range(count):
            while index < len(lines):
                rule_line = lines[index].split("#", 1)[0].strip()
                index += 1
                if not rule_line:
                    continue
                rule_fields = rule_line.split()
                if (
                    len(rule_fields) < 4
                    or rule_fields[0] != kind
                    or rule_fields[1] != flag
                ):
                    raise ValueError(
                        f"malformed {kind} block for flag {flag!r}: "
                        f"{rule_line!r}"
                    )
                strip = rule_fields[2]
                add = rule_fields[3]
                condition = rule_fields[4] if len(rule_fields) > 4 else "."
                bucket[flag].append(
                    AffixRule(
                        strip=strip,
                        add=add,
                        condition=condition,
                        regex=_compile_condition(
                            condition, at_end=(kind == "SFX")
                        ),
                    )
                )
                break

    return prefixes, suffixes, prefix_cross, suffix_cross


def parse_dictionary_file(text: str) -> Iterator[tuple[str, str]]:
    """Yield ``(stem, flags)`` pairs from a Hunspell ``.dic`` file."""

    lines = text.splitlines()
    if lines and lines[0].strip().isdigit():
        lines = lines[1:]

    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue

        # Morphological fields follow whitespace and are not part of the word.
        token = line.split()[0]
        if "/" in token:
            stem, flags = token.split("/", 1)
        else:
            stem, flags = token, ""

        # Escaped slashes occur in a few Hunspell dictionaries.
        stem = stem.replace("\\/", "/")
        yield stem, flags


def _apply_prefix(word: str, rule: AffixRule) -> str | None:
    if not rule.regex.search(word):
        return None
    if rule.strip and rule.strip != "0":
        if not word.startswith(rule.strip):
            return None
        word = word[len(rule.strip) :]
    return rule.add + word


def _apply_suffix(word: str, rule: AffixRule) -> str | None:
    if not rule.regex.search(word):
        return None
    if rule.strip and rule.strip != "0":
        if not word.endswith(rule.strip):
            return None
        word = word[: -len(rule.strip)]
    return word + rule.add


def _normalize_form(value: str) -> str:
    value = unicodedata.normalize("NFC", value)
    value = value.translate(
        str.maketrans(
            {
                "\u2018": "'",
                "\u2019": "'",
                "\u02bb": "'",
                "\u02bc": "'",
                "\u00b4": "'",
                "\u2010": "-",
                "\u2011": "-",
                "\u2012": "-",
                "\u2013": "-",
                "\u2014": "-",
                "\u2212": "-",
            }
        )
    )
    return value.strip().lower()


def _is_word_token(word: str) -> bool:
    if not word or len(word) > 64:
        return False
    if not any(character.isalpha() for character in word):
        return False
    for character in word:
        if character.isalpha() or character in "'-":
            continue
        return False
    return True


def expand_dictionary(
    dictionary_text: str, affix_text: str
) -> set[str]:
    """Expand one Hunspell dictionary into normalized surface forms."""

    prefixes, suffixes, prefix_cross, suffix_cross = parse_affix_file(affix_text)
    forms: set[str] = set()

    for stem, flag_text in parse_dictionary_file(dictionary_text):
        stem = _normalize_form(stem)
        if not _is_word_token(stem):
            continue
        forms.add(stem)

        flags = list(flag_text)
        prefix_forms: list[tuple[AffixRule, str, bool]] = []
        suffix_forms: list[tuple[AffixRule, str, bool]] = []

        for flag in flags:
            for rule in prefixes.get(flag, ()):
                form = _apply_prefix(stem, rule)
                if form is not None:
                    prefix_forms.append((rule, form, prefix_cross.get(flag, False)))
            for rule in suffixes.get(flag, ()):
                form = _apply_suffix(stem, rule)
                if form is not None:
                    suffix_forms.append((rule, form, suffix_cross.get(flag, False)))

        for _, form, _ in prefix_forms:
            normalized = _normalize_form(form)
            if _is_word_token(normalized):
                forms.add(normalized)
        for _, form, _ in suffix_forms:
            normalized = _normalize_form(form)
            if _is_word_token(normalized):
                forms.add(normalized)

        # Hunspell applies at most one prefix and one suffix, and only when
        # both flags permit cross-product affixation.
        for prefix_rule, _, prefix_allows_cross in prefix_forms:
            for suffix_rule, _, suffix_allows_cross in suffix_forms:
                if not (prefix_allows_cross and suffix_allows_cross):
                    continue

                core = stem
                if prefix_rule.strip and prefix_rule.strip != "0":
                    if not core.startswith(prefix_rule.strip):
                        continue
                    core = core[len(prefix_rule.strip) :]
                if suffix_rule.strip and suffix_rule.strip != "0":
                    if not core.endswith(suffix_rule.strip):
                        continue
                    core = core[: -len(suffix_rule.strip)]

                combined = _normalize_form(
                    prefix_rule.add + core + suffix_rule.add
                )
                if _is_word_token(combined):
                    forms.add(combined)

    return forms


def _download(url: str, destination: Path) -> None:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "scowl-spellcheck-builder/1.0"},
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        destination.write_bytes(response.read())


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _extract_archive(archive: Path, destination: Path) -> None:
    with zipfile.ZipFile(archive) as bundle:
        bundle.extractall(destination)


def _write_word_list(path: Path, words: Iterable[str]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(
            "# English word list generated by scripts/build_dictionary.py\n"
            "# Source: SCOWL (https://wordlist.aspell.net), "
            f"release {RELEASE}\n"
            "# License: see data/licenses/SCOWL-Copyright.txt\n"
        )
        for word in sorted(words):
            handle.write(f"{word}\n")


def _build_frequencies(words: Iterable[str], path: Path) -> int:
    try:
        from wordfreq import zipf_frequency
    except ImportError:
        print(
            "warning: wordfreq is not installed; writing no frequency file. "
            "Install it with 'pip install -r requirements-build.txt' and "
            "rebuild to enable frequency tie-breaking.",
            file=sys.stderr,
        )
        return 0

    count = 0
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(
            "# word<TAB>zipf_frequency for the English language.\n"
            "# Generated with wordfreq (https://pypi.org/project/wordfreq/).\n"
        )
        for word in sorted(words):
            frequency = zipf_frequency(word, "en")
            if frequency > 0:
                handle.write(f"{word}\t{frequency:.3f}\n")
                count += 1
    return count


def build(data_dir: Path, skip_frequency: bool, quiet: bool) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    license_dir = data_dir / "licenses"
    license_dir.mkdir(parents=True, exist_ok=True)

    all_words: set[str] = set()

    with tempfile.TemporaryDirectory(prefix="scowl-spellcheck-") as temporary:
        temporary_path = Path(temporary)

        for source in SOURCES:
            archive = temporary_path / f"{source.name}.zip"
            if not quiet:
                print(f"Downloading {source.name} ...")
            _download(source.url, archive)

            actual_hash = _sha256(archive)
            if actual_hash != source.sha256:
                raise SystemExit(
                    f"hash mismatch for {source.name}: expected "
                    f"{source.sha256}, got {actual_hash}"
                )

            extracted = temporary_path / source.name
            extracted.mkdir()
            _extract_archive(archive, extracted)

            dictionary_text = (extracted / source.dic_name).read_text(
                encoding="utf-8"
            )
            affix_text = (extracted / source.aff_name).read_text(
                encoding="utf-8"
            )
            forms = expand_dictionary(dictionary_text, affix_text)
            all_words.update(forms)

            readme = extracted / source.readme_name
            if readme.exists():
                shutil.copy2(readme, license_dir / source.readme_name)

            if not quiet:
                print(f"  {source.name}: {len(forms):,} surface forms")

    copyright_source = LICENSE_SOURCE
    if copyright_source.exists():
        shutil.copy2(copyright_source, license_dir / "SCOWL-Copyright.txt")

    if not quiet:
        print(f"Merging {len(all_words):,} unique words ...")

    _write_word_list(data_dir / "words.txt", all_words)
    if not quiet:
        print(f"Wrote {data_dir / 'words.txt'}")

    if skip_frequency:
        if not quiet:
            print("Skipping frequency file (--skip-frequency).")
    else:
        frequency_count = _build_frequencies(
            all_words, data_dir / "frequencies.tsv"
        )
        if not quiet:
            if frequency_count:
                print(
                    f"Wrote {data_dir / 'frequencies.tsv'} "
                    f"({frequency_count:,} entries)"
                )
            else:
                print("Frequency file skipped.")

    user_dictionary = data_dir / "user_words.txt"
    if not user_dictionary.exists():
        user_dictionary.write_text(
            "# One word per line. Lines beginning with # are ignored.\n"
            "# Add names, technical terms, and words missing from the main list.\n"
            "kubernetes\n"
            "postgresql\n"
            "typescript\n",
            encoding="utf-8",
        )
        if not quiet:
            print(f"Created example user dictionary {user_dictionary}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=DEFAULT_DATA_DIR,
        help=f"output directory (default: {DEFAULT_DATA_DIR})",
    )
    parser.add_argument(
        "--skip-frequency",
        action="store_true",
        help="do not generate frequencies.tsv",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="suppress progress output",
    )
    args = parser.parse_args(argv)

    build(args.data_dir, args.skip_frequency, args.quiet)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
