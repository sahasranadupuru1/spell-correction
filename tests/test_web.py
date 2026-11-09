"""Tests for the local web interface and JSON API."""

from __future__ import annotations

import json
import threading
import unittest
import urllib.error
import urllib.request

from spellcheck.dictionary import Dictionary
from spellcheck.suggest import SpellChecker
from spellcheck.web import create_server

OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


class WebInterfaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        dictionary = Dictionary(
            [
                "hello",
                "receive",
                "relieve",
                "believe",
                "recede",
                "well",
                "known",
                "café",
            ],
            frequencies={
                "relieve": 3.0,
                "believe": 5.0,
                "receive": 4.8,
                "recede": 2.0,
            },
        )
        checker = SpellChecker(dictionary, max_distance=2, max_suggestions=5)
        cls.server = create_server(checker, host="127.0.0.1", port=0)
        cls.thread = threading.Thread(
            target=cls.server.serve_forever,
            kwargs={"poll_interval": 0.05},
            daemon=True,
        )
        cls.thread.start()
        cls.base_url = (
            f"http://127.0.0.1:{cls.server.server_address[1]}"
        )

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)

    def get(self, path: str):
        request = urllib.request.Request(self.base_url + path, method="GET")
        try:
            with OPENER.open(request, timeout=5) as response:
                return response.status, response.headers, response.read()
        except urllib.error.HTTPError as error:
            return error.code, error.headers, error.read()

    def post(
        self,
        payload=None,
        *,
        raw_body: bytes | None = None,
        content_type: str = "application/json",
    ):
        if raw_body is None:
            raw_body = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            self.base_url + "/api/check",
            data=raw_body,
            headers={"Content-Type": content_type},
            method="POST",
        )
        try:
            with OPENER.open(request, timeout=5) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            body = error.read().decode("utf-8")
            try:
                decoded = json.loads(body)
            except json.JSONDecodeError:
                decoded = body
            return error.code, decoded

    def test_index_page(self) -> None:
        status, headers, body = self.get("/")
        decoded = body.decode("utf-8")

        self.assertEqual(status, 200)
        self.assertTrue(headers["Content-Type"].startswith("text/html"))
        self.assertIn("<title>Spell Checker</title>", decoded)
        self.assertIn('id="word"', decoded)
        self.assertIn("POST /api/check", decoded)

    def test_health_endpoint(self) -> None:
        status, headers, body = self.get("/api/health")

        self.assertEqual(status, 200)
        self.assertTrue(headers["Content-Type"].startswith("application/json"))
        self.assertEqual(json.loads(body), {"status": "ok"})

    def test_valid_word(self) -> None:
        status, payload = self.post({"word": "Hello"})

        self.assertEqual(status, 200)
        self.assertEqual(payload["status"], "valid")
        self.assertEqual(payload["word"], "Hello")
        self.assertEqual(payload["suggestions"], [])

    def test_unknown_word_has_ranked_suggestions(self) -> None:
        status, payload = self.post({"word": "recieve"})

        self.assertEqual(status, 200)
        self.assertEqual(payload["status"], "unknown")
        pairs = {
            (suggestion["word"], suggestion["distance"])
            for suggestion in payload["suggestions"]
        }
        self.assertIn(("receive", 2), pairs)
        self.assertIn(("relieve", 1), pairs)

        keys = [
            (suggestion["distance"], -suggestion["frequency"], suggestion["word"])
            for suggestion in payload["suggestions"]
        ]
        self.assertEqual(keys, sorted(keys))

    def test_max_distance_override(self) -> None:
        status, payload = self.post({"word": "recieve", "max_distance": 1})

        self.assertEqual(status, 200)
        self.assertEqual(payload["max_distance"], 1)
        self.assertNotIn(
            "receive",
            {suggestion["word"] for suggestion in payload["suggestions"]},
        )
        self.assertTrue(
            all(suggestion["distance"] <= 1 for suggestion in payload["suggestions"])
        )

    def test_suggestion_limit_override(self) -> None:
        status, payload = self.post({"word": "recieve", "suggestions": 1})

        self.assertEqual(status, 200)
        self.assertEqual(len(payload["suggestions"]), 1)

    def test_no_close_match(self) -> None:
        status, payload = self.post({"word": "zzzz", "max_distance": 1})

        self.assertEqual(status, 200)
        self.assertEqual(payload["status"], "unknown")
        self.assertEqual(payload["suggestions"], [])

    def test_empty_word(self) -> None:
        status, payload = self.post({"word": "   "})

        self.assertEqual(status, 200)
        self.assertEqual(payload["status"], "empty")

    def test_multiple_words_are_invalid(self) -> None:
        status, payload = self.post({"word": "hello world"})

        self.assertEqual(status, 200)
        self.assertEqual(payload["status"], "invalid")

    def test_unicode_word(self) -> None:
        status, payload = self.post({"word": "CAFÉ"})

        self.assertEqual(status, 200)
        self.assertEqual(payload["status"], "valid")

    def test_hyphenated_correction(self) -> None:
        status, payload = self.post({"word": "well-knwon"})

        self.assertEqual(status, 200)
        pairs = {
            (suggestion["word"], suggestion["distance"])
            for suggestion in payload["suggestions"]
        }
        self.assertIn(("well-known", 2), pairs)

    def test_missing_word_is_a_bad_request(self) -> None:
        status, payload = self.post({"max_distance": 2})

        self.assertEqual(status, 400)
        self.assertIn("word", payload["error"])

    def test_word_too_long(self) -> None:
        status, payload = self.post({"word": "a" * 300})

        self.assertEqual(status, 400)
        self.assertIn("at most", payload["error"])

    def test_invalid_distance(self) -> None:
        for value in (-1, 6, "2", True):
            with self.subTest(value=value):
                status, payload = self.post({"word": "hello", "max_distance": value})
                self.assertEqual(status, 400)
                self.assertIn("max_distance", payload["error"])

    def test_invalid_suggestion_count(self) -> None:
        for value in (-1, 21, "5", False):
            with self.subTest(value=value):
                status, payload = self.post({"word": "hello", "suggestions": value})
                self.assertEqual(status, 400)
                self.assertIn("suggestions", payload["error"])

    def test_invalid_json(self) -> None:
        status, payload = self.post(raw_body=b"not json")

        self.assertEqual(status, 400)
        self.assertIn("invalid JSON", payload["error"])

    def test_wrong_content_type(self) -> None:
        status, payload = self.post(
            {"word": "hello"}, content_type="text/plain"
        )

        self.assertEqual(status, 415)
        self.assertIn("application/json", payload["error"])

    def test_get_check_endpoint_is_not_allowed(self) -> None:
        status, headers, body = self.get("/api/check")

        self.assertEqual(status, 405)
        self.assertEqual(headers["Allow"], "POST")
        self.assertIn("use POST", json.loads(body)["error"])

    def test_unknown_path(self) -> None:
        status, _, body = self.get("/nope")

        self.assertEqual(status, 404)
        self.assertIn("not found", json.loads(body)["error"])


if __name__ == "__main__":
    unittest.main()
