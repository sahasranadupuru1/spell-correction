"""A small, dependency-free local web interface for the spell checker.

The server uses only the Python standard library.  It binds to loopback by
default and exposes:

    GET  /               the single-page UI
    POST /api/check      JSON: {word, max_distance?, suggestions?}
    GET  /api/health     simple health check

The UI and API share the same :class:`~spellcheck.suggest.SpellChecker` and
therefore the same ranking and normalization behavior as the CLI.
"""

from __future__ import annotations

import json
import sys
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlsplit

from .suggest import SpellChecker

MAX_WEB_DISTANCE = 5
MAX_WEB_SUGGESTIONS = 20
MAX_WORD_LENGTH = 256
MAX_BODY_BYTES = 64 * 1024


INDEX_HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Spell Checker</title>
<style>
  :root {
    color-scheme: light dark;
    --bg: #f4f6fb;
    --bg-accent: #e8eefb;
    --card: #ffffff;
    --ink: #172033;
    --muted: #61708a;
    --line: #dbe2ef;
    --accent: #315efb;
    --accent-ink: #ffffff;
    --valid: #0f8a5f;
    --valid-bg: #e5f7ef;
    --unknown: #9a5b00;
    --unknown-bg: #fff3dc;
    --invalid: #b42318;
    --invalid-bg: #fee9e7;
    --shadow: 0 24px 70px rgba(30, 48, 90, 0.13);
  }
  @media (prefers-color-scheme: dark) {
    :root {
      --bg: #0d1320;
      --bg-accent: #131c2d;
      --card: #151e30;
      --ink: #eef3ff;
      --muted: #96a4bd;
      --line: #26334c;
      --accent: #7c9cff;
      --accent-ink: #0c1424;
      --valid: #5fe0b0;
      --valid-bg: #103a2f;
      --unknown: #ffc46b;
      --unknown-bg: #3a2a10;
      --invalid: #ff8c85;
      --invalid-bg: #3d1717;
      --shadow: 0 28px 80px rgba(0, 0, 0, 0.42);
    }
  }
  * { box-sizing: border-box; }
  [hidden] { display: none !important; }
  body {
    margin: 0;
    min-height: 100vh;
    font-family: ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif;
    color: var(--ink);
    background:
      radial-gradient(900px 500px at 10% -10%, var(--bg-accent), transparent 60%),
      radial-gradient(700px 420px at 110% 10%, var(--bg-accent), transparent 55%),
      var(--bg);
    display: grid;
    place-items: start center;
    padding: 48px 18px 72px;
  }
  main {
    width: min(780px, 100%);
    background: var(--card);
    border: 1px solid var(--line);
    border-radius: 24px;
    box-shadow: var(--shadow);
    overflow: hidden;
  }
  header {
    padding: 30px 30px 12px;
  }
  h1 {
    margin: 0;
    font-size: clamp(1.7rem, 4vw, 2.35rem);
    letter-spacing: -0.035em;
  }
  header p {
    margin: 8px 0 0;
    color: var(--muted);
    line-height: 1.5;
    font-size: 0.97rem;
  }
  form { padding: 18px 30px 8px; }
  label { font-size: 0.82rem; font-weight: 650; color: var(--muted); }
  .row { display: flex; gap: 10px; margin-top: 7px; }
  input, button { font: inherit; }
  #word {
    flex: 1;
    min-width: 0;
    padding: 14px 16px;
    border: 1px solid var(--line);
    border-radius: 13px;
    background: transparent;
    color: var(--ink);
    font-size: 1.08rem;
  }
  #word:focus, input[type="number"]:focus, button:focus-visible {
    outline: 3px solid color-mix(in srgb, var(--accent) 32%, transparent);
    outline-offset: 2px;
  }
  button {
    cursor: pointer;
    border: 0;
    border-radius: 13px;
    background: var(--accent);
    color: var(--accent-ink);
    font-weight: 700;
    padding: 0 24px;
  }
  button:disabled { cursor: progress; opacity: 0.72; }
  .settings {
    display: flex;
    flex-wrap: wrap;
    align-items: end;
    gap: 16px;
    margin-top: 14px;
  }
  .settings label { display: grid; gap: 5px; }
  input[type="number"] {
    width: 88px;
    padding: 9px 10px;
    border: 1px solid var(--line);
    border-radius: 10px;
    background: transparent;
    color: var(--ink);
  }
  .hint { color: var(--muted); font-size: 0.82rem; padding-bottom: 9px; }
  .status {
    margin: 14px 30px 0;
    padding: 13px 15px;
    border-radius: 12px;
    font-weight: 600;
    line-height: 1.4;
  }
  .status.valid { color: var(--valid); background: var(--valid-bg); }
  .status.unknown { color: var(--unknown); background: var(--unknown-bg); }
  .status.invalid { color: var(--invalid); background: var(--invalid-bg); }
  #results { padding: 18px 30px 12px; }
  .result-head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
  }
  #result-title {
    margin: 0;
    font-size: 1.02rem;
    font-weight: 700;
    overflow-wrap: anywhere;
  }
  .badge {
    flex: none;
    font-size: 0.72rem;
    font-weight: 800;
    letter-spacing: 0.06em;
    text-transform: uppercase;
    padding: 5px 9px;
    border-radius: 999px;
    background: var(--bg-accent);
    color: var(--muted);
  }
  .badge.valid { background: var(--valid-bg); color: var(--valid); }
  .badge.unknown { background: var(--unknown-bg); color: var(--unknown); }
  .badge.invalid { background: var(--invalid-bg); color: var(--invalid); }
  ol {
    list-style: none;
    margin: 14px 0 0;
    padding: 0;
    display: grid;
    gap: 8px;
  }
  li {
    display: grid;
    grid-template-columns: 28px minmax(0, 1fr) auto auto;
    align-items: center;
    gap: 12px;
    padding: 11px 13px;
    border: 1px solid var(--line);
    border-radius: 12px;
  }
  .rank { color: var(--muted); font-size: 0.82rem; font-variant-numeric: tabular-nums; }
  .suggestion-word {
    justify-self: start;
    padding: 2px 0;
    background: none;
    color: var(--accent);
    font-weight: 750;
    font-size: 1.02rem;
    border-radius: 6px;
    text-align: left;
    overflow-wrap: anywhere;
  }
  .suggestion-word:hover { text-decoration: underline; }
  .distance, .frequency {
    color: var(--muted);
    font-size: 0.78rem;
    white-space: nowrap;
    font-variant-numeric: tabular-nums;
  }
  .frequency:empty { display: none; }
  #empty-state {
    margin: 18px 30px 28px;
    padding: 20px;
    border: 1px dashed var(--line);
    border-radius: 14px;
    color: var(--muted);
    line-height: 1.6;
  }
  #empty-state strong { color: var(--ink); }
  .examples { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 10px; }
  .examples button {
    background: var(--bg-accent);
    color: var(--ink);
    font-size: 0.82rem;
    font-weight: 650;
    padding: 7px 11px;
  }
  footer {
    padding: 0 30px 26px;
    color: var(--muted);
    font-size: 0.78rem;
    line-height: 1.6;
  }
  code {
    font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
    font-size: 0.9em;
  }
  @media (max-width: 560px) {
    body { padding: 18px 10px 40px; }
    header { padding: 24px 20px 8px; }
    form { padding: 14px 20px 6px; }
    .status { margin-left: 20px; margin-right: 20px; }
    #results { padding-left: 20px; padding-right: 20px; }
    #empty-state { margin-left: 20px; margin-right: 20px; }
    footer { padding-left: 20px; padding-right: 20px; }
    .row { flex-direction: column; }
    button[type="submit"] { padding: 13px 24px; }
    li { grid-template-columns: 24px minmax(0, 1fr); }
    .distance, .frequency { grid-column: 2; }
  }
</style>
</head>
<body>
<main>
  <header>
    <h1>Spell Checker</h1>
    <p>Levenshtein suggestions from a 170,152-word SCOWL dictionary, with US and UK spellings. Runs locally and offline.</p>
  </header>

  <form id="check-form" novalidate>
    <label for="word">Word</label>
    <div class="row">
      <input id="word" name="word" placeholder="Try recieve" autocomplete="off" autocapitalize="off" spellcheck="false" autofocus>
      <button type="submit">Check</button>
    </div>
    <div class="settings">
      <label>Max distance <input id="max-distance" type="number" min="0" max="5" step="1" value="2"></label>
      <label>Suggestions <input id="suggestions" type="number" min="0" max="20" step="1" value="5"></label>
      <span class="hint">Distance 0–5, suggestions 0–20</span>
    </div>
  </form>

  <div id="status" class="status" role="status" aria-live="polite" hidden></div>

  <section id="results" hidden aria-live="polite">
    <div class="result-head">
      <h2 id="result-title"></h2>
      <span id="result-badge" class="badge"></span>
    </div>
    <ol id="suggestion-list"></ol>
  </section>

  <section id="empty-state">
    <strong>Check a word.</strong> Enter a word above to see whether it is in the dictionary and, if not, the closest ranked suggestions with their edit distances.
    <div class="examples">
      <button type="button" data-example="recieve">recieve</button>
      <button type="button" data-example="hello">hello</button>
      <button type="button" data-example="well-knwon">well-knwon</button>
      <button type="button" data-example="café">café</button>
    </div>
  </section>

  <footer>
    Ranking: smallest Levenshtein distance, then frequency, then alphabetical.
    This local UI uses <code>POST /api/check</code>.
  </footer>
</main>

<script>
  const form = document.getElementById('check-form');
  const input = document.getElementById('word');
  const distanceInput = document.getElementById('max-distance');
  const suggestionsInput = document.getElementById('suggestions');
  const statusEl = document.getElementById('status');
  const resultsEl = document.getElementById('results');
  const titleEl = document.getElementById('result-title');
  const badgeEl = document.getElementById('result-badge');
  const listEl = document.getElementById('suggestion-list');
  const emptyEl = document.getElementById('empty-state');
  const submitButton = form.querySelector('button[type="submit"]');

  function setBusy(busy) {
    submitButton.disabled = busy;
    submitButton.textContent = busy ? 'Checking…' : 'Check';
  }

  function showMessage(message, kind) {
    statusEl.textContent = message;
    statusEl.className = 'status ' + kind;
    statusEl.hidden = false;
  }

  function clearSuggestions() {
    while (listEl.firstChild) listEl.removeChild(listEl.firstChild);
  }

  function suggestionItem(suggestion, index) {
    const item = document.createElement('li');

    const rank = document.createElement('span');
    rank.className = 'rank';
    rank.textContent = String(index + 1);

    const word = document.createElement('button');
    word.type = 'button';
    word.className = 'suggestion-word';
    word.textContent = suggestion.display_word;
    word.title = 'Check this word';
    word.addEventListener('click', () => {
      input.value = suggestion.display_word;
      form.requestSubmit();
    });

    const distance = document.createElement('span');
    distance.className = 'distance';
    distance.textContent = 'distance ' + suggestion.distance;

    const frequency = document.createElement('span');
    frequency.className = 'frequency';
    frequency.textContent = suggestion.frequency > 0
      ? 'freq ' + suggestion.frequency.toFixed(2)
      : '';

    item.append(rank, word, distance, frequency);
    return item;
  }

  function render(data) {
    emptyEl.hidden = true;
    resultsEl.hidden = false;
    clearSuggestions();

    titleEl.textContent = data.word || '(empty)';
    badgeEl.className = 'badge';

    if (data.status === 'valid') {
      badgeEl.textContent = 'valid';
      badgeEl.classList.add('valid');
      showMessage("'" + data.word + "' is spelled correctly.", 'valid');
      return;
    }

    if (data.status === 'empty') {
      badgeEl.textContent = 'empty';
      badgeEl.classList.add('invalid');
      showMessage('Please enter a word.', 'invalid');
      return;
    }

    if (data.status === 'invalid') {
      badgeEl.textContent = 'invalid';
      badgeEl.classList.add('invalid');
      showMessage('Please enter a single word without spaces.', 'invalid');
      return;
    }

    badgeEl.textContent = 'unknown';
    badgeEl.classList.add('unknown');
    if (data.suggestions.length === 0) {
      showMessage('No suggestions within edit distance ' + data.max_distance + '.', 'unknown');
      return;
    }

    showMessage("'" + data.word + "' is not in the dictionary.", 'unknown');
    data.suggestions.forEach((suggestion, index) => {
      listEl.appendChild(suggestionItem(suggestion, index));
    });
  }

  async function check(word) {
    const maxDistance = Number(distanceInput.value);
    const suggestions = Number(suggestionsInput.value);

    if (!Number.isInteger(maxDistance) || maxDistance < 0 || maxDistance > 5) {
      showMessage('Max distance must be an integer from 0 to 5.', 'invalid');
      return;
    }
    if (!Number.isInteger(suggestions) || suggestions < 0 || suggestions > 20) {
      showMessage('Suggestions must be an integer from 0 to 20.', 'invalid');
      return;
    }

    setBusy(true);
    try {
      const response = await fetch('/api/check', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          word,
          max_distance: maxDistance,
          suggestions,
        }),
      });
      const data = await response.json();
      if (!response.ok) {
        throw new Error(data.error || 'Request failed');
      }
      render(data);
    } catch (error) {
      resultsEl.hidden = true;
      showMessage(error.message || 'Could not reach the spell checker.', 'invalid');
    } finally {
      setBusy(false);
    }
  }

  form.addEventListener('submit', (event) => {
    event.preventDefault();
    check(input.value);
  });

  document.querySelectorAll('[data-example]').forEach((button) => {
    button.addEventListener('click', () => {
      input.value = button.dataset.example;
      form.requestSubmit();
    });
  });
</script>
</body>
</html>
"""


def _serialize_result(result: Any) -> dict[str, Any]:
    return {
        "word": result.original,
        "normalized": result.normalized,
        "status": result.status,
        "max_distance": result.max_distance,
        "suggestions": [
            {
                "word": suggestion.word,
                "display_word": suggestion.display_word,
                "distance": suggestion.distance,
                "frequency": round(suggestion.frequency, 3),
            }
            for suggestion in result.suggestions
        ],
    }


def _parse_integer(
    value: Any,
    default: int,
    minimum: int,
    maximum: int,
    name: str,
) -> int:
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be an integer")
    if value < minimum or value > maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return value


class SpellCheckRequestHandler(BaseHTTPRequestHandler):
    """HTTP handler carrying the dictionary checker and web defaults."""

    server_version = "SpellCheckWeb/1.0"
    protocol_version = "HTTP/1.1"

    checker: SpellChecker
    default_max_distance: int = 2
    default_max_suggestions: int = 5

    def do_GET(self) -> None:  # noqa: N802 (BaseHTTPRequestHandler API)
        path = urlsplit(self.path).path
        if path in {"/", "/index.html"}:
            self._send_html(INDEX_HTML)
        elif path == "/api/health":
            self._send_json(HTTPStatus.OK, {"status": "ok"})
        elif path == "/api/check":
            self._send_json(
                HTTPStatus.METHOD_NOT_ALLOWED,
                {"error": "use POST for /api/check"},
                extra_headers={"Allow": "POST"},
            )
        else:
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802 (BaseHTTPRequestHandler API)
        path = urlsplit(self.path).path
        if path != "/api/check":
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "not found"})
            return

        content_type = self.headers.get("Content-Type", "")
        if not content_type.lower().startswith("application/json"):
            self._send_json(
                HTTPStatus.UNSUPPORTED_MEDIA_TYPE,
                {"error": "Content-Type must be application/json"},
            )
            return

        length_header = self.headers.get("Content-Length")
        if length_header is None:
            self._send_json(
                HTTPStatus.LENGTH_REQUIRED,
                {"error": "Content-Length is required"},
            )
            return
        try:
            length = int(length_header)
        except ValueError:
            self._send_json(
                HTTPStatus.BAD_REQUEST,
                {"error": "invalid Content-Length"},
            )
            return
        if length <= 0:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": "empty request body"})
            return
        if length > MAX_BODY_BYTES:
            self._send_json(
                HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                {"error": "request body is too large"},
            )
            return

        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": "invalid JSON"})
            return

        if not isinstance(payload, dict):
            self._send_json(
                HTTPStatus.BAD_REQUEST,
                {"error": "JSON body must be an object"},
            )
            return

        word = payload.get("word")
        if not isinstance(word, str):
            self._send_json(
                HTTPStatus.BAD_REQUEST,
                {"error": "word must be a string"},
            )
            return
        if len(word) > MAX_WORD_LENGTH:
            self._send_json(
                HTTPStatus.BAD_REQUEST,
                {"error": f"word must be at most {MAX_WORD_LENGTH} characters"},
            )
            return

        try:
            max_distance = _parse_integer(
                payload.get("max_distance"),
                self.default_max_distance,
                0,
                MAX_WEB_DISTANCE,
                "max_distance",
            )
            max_suggestions = _parse_integer(
                payload.get("suggestions"),
                self.default_max_suggestions,
                0,
                MAX_WEB_SUGGESTIONS,
                "suggestions",
            )
        except ValueError as exc:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
            return

        checker = SpellChecker(
            dictionary=self.checker.dictionary,
            max_distance=max_distance,
            max_suggestions=max_suggestions,
        )
        try:
            result = checker.check(word)
        except Exception:  # pragma: no cover - defensive boundary
            self._send_json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {"error": "internal error while checking the word"},
            )
            return

        self._send_json(HTTPStatus.OK, _serialize_result(result))

    def _send_html(self, body: str) -> None:
        data = body.encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(data)

    def _send_json(
        self,
        status: HTTPStatus | int,
        payload: dict[str, Any],
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        if extra_headers:
            for name, value in extra_headers.items():
                self.send_header(name, value)
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, format: str, *args: Any) -> None:
        sys.stderr.write(
            "[web] %s - %s\n" % (self.address_string(), format % args)
        )


def create_server(
    checker: SpellChecker,
    host: str = "127.0.0.1",
    port: int = 8000,
    default_max_distance: int | None = None,
    default_max_suggestions: int | None = None,
) -> ThreadingHTTPServer:
    """Create (but do not start) a configured web server."""

    resolved_distance = (
        checker.max_distance if default_max_distance is None else default_max_distance
    )
    resolved_suggestions = (
        checker.max_suggestions
        if default_max_suggestions is None
        else default_max_suggestions
    )

    if not 0 <= resolved_distance <= MAX_WEB_DISTANCE:
        raise ValueError(
            f"web max_distance must be between 0 and {MAX_WEB_DISTANCE}"
        )
    if not 0 <= resolved_suggestions <= MAX_WEB_SUGGESTIONS:
        raise ValueError(
            "web suggestions must be between 0 and "
            f"{MAX_WEB_SUGGESTIONS}"
        )

    class Handler(SpellCheckRequestHandler):
        pass

    Handler.checker = checker
    Handler.default_max_distance = resolved_distance
    Handler.default_max_suggestions = resolved_suggestions

    return ThreadingHTTPServer((host, port), Handler)


def run_server(
    checker: SpellChecker,
    host: str = "127.0.0.1",
    port: int = 8000,
    default_max_distance: int | None = None,
    default_max_suggestions: int | None = None,
    open_browser: bool = False,
) -> int:
    """Serve the UI until interrupted.  Returns a process exit code."""

    try:
        server = create_server(
            checker,
            host=host,
            port=port,
            default_max_distance=default_max_distance,
            default_max_suggestions=default_max_suggestions,
        )
    except (OSError, ValueError) as exc:
        print(
            f"spellcheck: cannot start web server on {host}:{port}: {exc}",
            file=sys.stderr,
        )
        return 2

    bound_host, bound_port = server.server_address[:2]
    display_host = (
        "127.0.0.1" if bound_host in {"0.0.0.0", "::"} else str(bound_host)
    )
    if ":" in display_host and not display_host.startswith("["):
        display_host = f"[{display_host}]"
    url = f"http://{display_host}:{bound_port}/"
    print(f"Spell checker web UI: {url}", flush=True)
    print("Press Ctrl-C to stop.", flush=True)
    if open_browser:
        webbrowser.open(url)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping web server.")
    finally:
        server.server_close()
    return 0
