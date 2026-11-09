# English Spell Correction (Levenshtein + SCOWL)

A complete, runnable Python 3 spell corrector. It implements standard
Levenshtein distance from scratch, searches a large SCOWL-derived dictionary
without dropping valid candidates, and ranks suggestions by edit distance,
word frequency, then alphabetical order.

Runtime has **no third-party dependencies**. The dictionary and frequency file
are installed in `spellcheck/data/`, so checking works offline.

## Quick start

```bash
cd /Users/likki/Downloads/daa_project

python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .        # optional: installs the `spellcheck` command

python -m spellcheck receive      # correctly spelled
python -m spellcheck recieve      # unknown word with ranked suggestions
python -m spellcheck              # interactive mode
python -m spellcheck --web        # local web UI at http://127.0.0.1:8000/
```

If you prefer not to install the package, every command below also works as
`python -m spellcheck ...` from the project root.

Check the assignment example in Python directly:

```bash
python -c "from spellcheck import levenshtein_distance; print(levenshtein_distance('recieve', 'receive'))"
```

Output:

```text
2
```

### Actual CLI output for `recieve`

```text
$ python -m spellcheck recieve
'recieve' is not in the dictionary.
Suggestions (max distance 2):
  1. relieve (distance 1)
  2. believe (distance 2)
  3. receive (distance 2)
  4. recipe (distance 2)
  5. relieved (distance 2)
```

`receive` is present at **distance 2**, as required. `relieve` is legitimately
distance 1 from `recieve` (`c` -> `l`), and the required ranking rule puts
smaller distance first, so it appears above `receive`.

More examples:

```text
$ python -m spellcheck hello
'hello' is spelled correctly.

$ python -m spellcheck Hello
'Hello' is spelled correctly.

$ python -m spellcheck zzzzzzzz
'zzzzzzzz' is not in the dictionary.
No suggestions within edit distance 2.

$ python -m spellcheck recieve -d 1 -n 2
'recieve' is not in the dictionary.
Suggestions (max distance 1):
  1. relieve (distance 1)
```

Interactive mode:

```text
$ python -m spellcheck
Interactive spell checker. Enter one word per line.
Commands: :help, :quit (or Ctrl-D).
Settings: max distance 2, up to 5 suggestions.
Word> hello
'hello' is spelled correctly.
Word> recieve
'recieve' is not in the dictionary.
Suggestions (max distance 2):
  1. relieve (distance 1)
  2. believe (distance 2)
  3. receive (distance 2)
  ...
Word> :quit
```

## Web interface

A zero-dependency local web UI is included. It uses the same dictionary,
normalization, candidate search, and ranking code as the CLI.

```bash
python -m spellcheck --web
```

```text
Spell checker web UI: http://127.0.0.1:8000/
Press Ctrl-C to stop.
```

Open the printed URL. The page has a word input, configurable maximum distance
and suggestion count, ranked suggestions with edit distances, and clickable
suggestions. It uses no external CDNs or assets, so it also works offline.

Useful variants:

```bash
python -m spellcheck --web --port 8080
python -m spellcheck --web --host 127.0.0.1 --port 8000 --open-browser
python -m spellcheck --web --max-distance 2 --suggestions 5
```

Security note: the server binds to `127.0.0.1` by default and has no
authentication. Keep it on loopback, or put it behind your own trusted proxy if
you bind it to a public interface.

### JSON API

```bash
curl -s http://127.0.0.1:8000/api/check \
  -H 'Content-Type: application/json' \
  -d '{"word":"recieve","max_distance":2,"suggestions":5}'
```

Response shape (actual fields and values for `recieve`):

```json
{
  "word": "recieve",
  "normalized": "recieve",
  "status": "unknown",
  "max_distance": 2,
  "suggestions": [
    {
      "word": "relieve",
      "display_word": "relieve",
      "distance": 1,
      "frequency": 3.77
    },
    {
      "word": "believe",
      "display_word": "believe",
      "distance": 2,
      "frequency": 5.51
    },
    {
      "word": "receive",
      "display_word": "receive",
      "distance": 2,
      "frequency": 4.85
    }
  ]
}
```

Status values are `valid`, `unknown`, `empty`, and `invalid`. Errors are JSON
objects with an `error` field and an appropriate HTTP status:

| Endpoint | Method | Purpose |
| -------- | ------ | ------- |
| `/` | GET | single-page UI |
| `/api/check` | POST | check a word; accepts `word`, optional `max_distance` (0–5), optional `suggestions` (0–20) |
| `/api/health` | GET | health check |

The web-specific limits (distance 0–5, suggestions 0–20, word length 256) keep
interactive requests responsive. The CLI has no such caps beyond your own
configuration.

## Command-line options

```text
python -m spellcheck [WORD] [options]

  -i, --interactive            read words from standard input, one per line
      --web                    start the local web interface
      --host ADDRESS           web bind address (default: 127.0.0.1)
      --port PORT              web port (default: 8000; 0 = ephemeral)
      --open-browser           open the web UI in the default browser
  -d, --max-distance N         maximum Levenshtein distance (default: 2)
  -n, --suggestions N          maximum suggestions to show (default: 5)
      --dictionary PATH        main word list; may be repeated
      --user-dictionary PATH   user word list layered on top; may be repeated
      --no-user-dictionary     do not load the bundled user dictionary
      --frequency-file PATH    word<TAB>frequency file used for ties
      --no-frequency           disable frequency-based tie-breaking
      --version                print the version
```

Exit codes:

| Code | Meaning |
| ---- | ------- |
| `0` | word is valid, interactive mode ended normally, or web server stopped with Ctrl-C |
| `1` | word is unknown (suggestions may or may not exist) |
| `2` | empty/invalid input, bad option, missing dictionary, or web bind failure |

## How it works

### 1. Levenshtein distance from scratch

`spellcheck/distance.py` implements the standard dynamic program:

```text
D[0][j] = j
D[i][0] = i
D[i][j] = min(
    D[i-1][j] + 1,          # deletion
    D[i][j-1] + 1,          # insertion
    D[i-1][j-1] + cost      # match (cost 0) or substitution (cost 1)
)
```

Only the previous row is kept, so memory is `O(min(m, n))`; time is `O(m * n)`.
There is no transposition primitive: standard Levenshtein only, so `ab` -> `ba`
costs 2.

A banded variant, `bounded_levenshtein_distance`, computes exactly the same
distance when it is at most `max_distance` and returns `None` otherwise. It is
used by the candidate search.

### 2. Lossless candidate search

Scanning all ~170,000 words with a full DP matrix on every keypress would be
unnecessarily slow. `Dictionary.candidates` uses three exact stages:

1. **Length buckets.** A word whose length differs from the query by more than
   `d` cannot be within `d` edits.
2. **Character-multiset lower bound.** For each word, the characters are sorted
   once. A two-pointer scan computes the multiset intersection `common`.
   Then:
   ```text
   L1(character counts) = len(query) + len(word) - 2 * common
   ```
   An insertion or deletion changes that L1 value by 1; a substitution changes
   it by 2. Any word within distance `d` therefore satisfies
   `L1 <= 2 * d`. Words failing this bound are skipped. This is a *necessary*
   condition, so no true match can be discarded.
3. **Banded Levenshtein verification.** Every survivor gets the exact banded
   DP. A cell with `|i - j| > d` cannot lie on a path of cost at most `d`, so
   the band is safe. The returned distance is exact.

The filter is conservative and the final DP is authoritative. The test suite
compares the candidate set against brute-force distance computation on random
dictionaries and queries to verify that the filter is lossless.

On the bundled 170,152-word dictionary, a real lookup takes roughly 0.1–0.2 s
after the dictionary is loaded. Interactive mode loads once and reuses it.

### 3. Ranking

Suggestions are sorted by:

```text
(distance, -frequency, word)
```

* smallest edit distance first;
* then highest stored frequency (when a frequency is available);
* then alphabetically for deterministic ties.

Frequency never overrides distance. If no frequency file is supplied, all
frequencies are `0.0` and ties are purely alphabetical.

## Input behavior

All matching uses a normalized form; display keeps useful capitalization.

| Input | Behavior |
| ----- | -------- |
| `Hello`, `HELLO`, `hello` | Case-insensitive lookup. A valid word is echoed unchanged. Suggestions copy the input style: title case, uppercase, or lowercase. Mixed case falls back to the dictionary's lowercase form. |
| `don’t`, `don't` | Curly/typographic apostrophes are normalized to ASCII `'`. Both are valid if `don't` is in the dictionary. |
| `well–known`, `well-known` | Unicode dash variants are normalized to `-`. A hyphenated compound is valid when every component is non-empty and known, so `well-known` works even if the compound itself is not stored. An unknown component is corrected part-by-part, e.g. `well-knwon` -> `well-known`. |
| `""`, whitespace | Reported as empty; the CLI prints `Please enter a word.` and exits with code 2. |
| `hello world` | Rejected as more than one token; the CLI prints `Please enter a single word without spaces.` |
| `café`, `naïve` | Unicode is NFC-normalized and lowercased. Diacritics are significant: `café` and `cafe` are different strings, though both may independently exist in the dictionary. |
| `c++`, `c#` | A user dictionary may contain any non-whitespace token. Symbols are preserved for exact lookup and distance calculation. (The generated SCOWL list itself is letters/apostrophes/hyphens only.) |
| no match | `No suggestions within edit distance N.` is printed explicitly. |

A `#` at the start of a dictionary line is a comment; a `#` inside a word is
part of the word, so `c#` is supported.

## Dictionary

### Source and license

The bundled word list is built from **SCOWL (Spell Checker Oriented Word
Lists)**, release **`rel-2026.02.25`**:

* `hunspell-en_US-large-2026.02.25.zip`
* `hunspell-en_GB-large-2026.02.25.zip`

Upstream: <https://wordlist.aspell.net> and
<https://github.com/en-wl/wordlist>.

SCOWL is Copyright 2000–2026 by Kevin Atkinson and is distributed under an
MIT-like license; the Hunspell affix file is covered by Geoff Kuenning's BSD
license. The full notices are installed at:

```text
spellcheck/data/licenses/SCOWL-Copyright.txt
spellcheck/data/licenses/README_en_US-large.txt
spellcheck/data/licenses/README_en_GB-large.txt
```

The build script downloads the two pinned archives, verifies their SHA-256
hashes, expands Hunspell `PFX`/`SFX` affix rules into surface forms (plurals,
verb forms, comparatives, possessives, etc.), merges US and British spellings,
lowercases everything, and removes duplicates.

Pinned hashes:

```text
en_US-large: 06ab5a2a12c29033f100988d3b0a5e53dcad40bf2473ccb78270619d1da99321
en_GB-large: 704a49438a3a9d4f11cd76db433a6b230b9ce8770ee13fa28700052c4517ddc1
```

Result: **170,152 unique words**, including common and uncommon vocabulary,
inflections, and both US and UK spellings (`color`/`colour`,
`realize`/`realise`).

### Rebuilding (only needed if data is removed or you want a refresh)

The data files are committed with the project, so this is optional:

```bash
python -m pip install -r requirements-build.txt   # installs wordfreq
python scripts/build_dictionary.py
```

To rebuild without regenerating frequency data:

```bash
python scripts/build_dictionary.py --skip-frequency
```

`wordfreq==3.1.1` (MIT) is used **only at build time** to generate
`frequencies.tsv` for tie-breaking. Runtime code never imports it or touches
the network. If `wordfreq` is unavailable, the build still succeeds and
suggestions fall back to alphabetical tie-breaking.

### User dictionary

Edit `spellcheck/data/user_words.txt`, or point at your own file:

```bash
python -m spellcheck --user-dictionary ./my_words.txt kubernetes
```

Example file:

```text
# One word per line. Lines beginning with # are ignored.
kubernetes
postgresql
typescript
jonathan
c++
```

User entries are merged with the main dictionary. They are normalized the same
way as input, so `Kubernetes` and `kubernetes` are the same entry. Internal
whitespace is rejected with a file/line error.

### Configurable dictionaries

```bash
# Replace the main list (the bundled user dictionary is still loaded):
python -m spellcheck --dictionary ./my-words.txt someword

# Add an extra user layer:
python -m spellcheck --user-dictionary ./names.txt --user-dictionary ./tech.txt jonathan

# Use your own frequency file (word<TAB>frequency):
python -m spellcheck --frequency-file ./frequencies.tsv recieve

# Disable frequency ranking:
python -m spellcheck --no-frequency recieve
```

### Coverage caveat

Coverage depends on the installed dictionaries. No word list is complete:
proper nouns, very new coinages, niche jargon, and hyphenated compounds may be
missing. The default SCOWL large union is broad but not exhaustive. Add missing
names/terms to a user dictionary. Main-list words are letters, apostrophes, and
hyphens; symbols such as `c++` belong in a user dictionary.

## Tests

Run the automated suite:

```bash
python -m unittest discover -s tests -v
```

Actual result on this workspace:

```text
Ran 102 tests in 12.629s

OK
```

The suite covers:

* the assignment example (`recieve` -> `receive`, distance 2);
* insertion, deletion, replacement, match, empty-string, symmetry, Unicode,
  transposition, and bounded-distance behavior;
* correctly spelled, uncommon, US, and UK words;
* custom and layered user dictionaries;
* distance/frequency/alphabetical tie-breaking and the suggestion cap;
* no-close-match and zero-distance configurations;
* capitalization, curly apostrophes, hyphenated compounds, empty input,
  multiple-word input, and Unicode normalization;
* CLI single-word and interactive behavior, options, exit codes, and errors;
* the local web UI, JSON API, validation, overrides, and error responses;
* lossless candidate filtering against brute force on random data;
* a full-dictionary responsiveness check.

## Project layout

```text
spellcheck/
  __init__.py          public exports
  __main__.py          python -m spellcheck entry point
  cli.py               argument parsing, output, interactive loop
  dictionary.py        loading, length buckets, lossless candidate search
  distance.py          full and bounded Levenshtein from scratch
  paths.py             bundled data locations
  suggest.py           checking, ranking, hyphen handling
  text.py              normalization and case-preserving display
  web.py               stdlib HTTP server, JSON API, embedded UI
  data/
    words.txt          170,152-word SCOWL-derived list
    frequencies.tsv    optional wordfreq-derived tie-break data
    user_words.txt     example editable user dictionary
    licenses/          SCOWL and affix license notices
scripts/
  build_dictionary.py  pinned download + affix expansion + frequency build
  licenses/
    SCOWL-Copyright.txt
tests/
  test_distance.py
  test_dictionary.py
  test_suggest.py
  test_text.py
  test_cli.py
  test_web.py
```

## Design notes and limitations

* Standard Levenshtein only; transpositions cost 2. No Damerau-Levenshtein.
* Single-word checking only; no grammar, context, or phrase correction.
* `max-distance` is configurable but larger values increase the number of
  candidates and verification work. Default `2` keeps lookups responsive.
* Frequency is a tie-breaker, never a substitute for distance.
* Matching is Unicode NFC + lowercase. Case folding is not used (for example,
  `ß` is not folded to `ss`). Diacritics are not stripped.
* Candidate search is exact; it does not use a heuristic that can silently
  drop a word within the configured distance.
* The web interface is a local convenience UI: it binds to loopback by default,
  has no authentication, and caps distance at 5 and suggestions at 20 to keep
  requests responsive. It uses only `http.server` and an embedded HTML page.
* Loading the 170k-word dictionary takes roughly one second in a fresh
  process; interactive and web modes pay that once.
