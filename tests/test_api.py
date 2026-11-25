import io
from pathlib import Path
import sys
import unittest
import urllib.error
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "skills/aoc-runtime/scripts"))
from common import Blocked
from api import Api


def http_error(code):
    return urllib.error.HTTPError("https://example.test/api/x", code, "status", {}, io.BytesIO(b"{}"))


class ApiRetryTests(unittest.TestCase):
    def setUp(self):
        self.api = Api("https://example.test", "token", run_id="run")

    def open(self, responses):
        calls = []

        def opener_open(request, timeout=None):
            calls.append(request)
            outcome = responses[len(calls) - 1]
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

        return calls, opener_open

    class Response:
        def __init__(self, body=b"{}"):
            self.body = body

        def read(self, *_args):
            return self.body

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def test_mutation_retries_on_retryable_status(self):
        calls, opener_open = self.open([http_error(503), self.Response()])
        with patch.object(self.api.opener, "open", side_effect=opener_open), patch("api.time.sleep"):
            result = self.api.request("PATCH", "/issues/1", {"status": "done"})
        self.assertEqual(len(calls), 2)
        self.assertEqual(result, {})

    def test_mutation_does_not_retry_on_validation_error(self):
        calls, opener_open = self.open([http_error(422)])
        with patch.object(self.api.opener, "open", side_effect=opener_open), patch("api.time.sleep"):
            with self.assertRaises(Blocked) as context:
                self.api.request("PATCH", "/issues/1", {"status": "done"})
        self.assertEqual(len(calls), 1)
        self.assertIn("HTTP 422", str(context.exception))

    def test_mutation_eventually_gives_up_on_persistent_5xx(self):
        calls, opener_open = self.open([http_error(503), http_error(503), http_error(503)])
        with patch.object(self.api.opener, "open", side_effect=opener_open), patch("api.time.sleep"):
            with self.assertRaises(Blocked):
                self.api.request("POST", "/issues/1/comments", {"body": "hi"})
        self.assertEqual(len(calls), self.api.ATTEMPTS)

    def test_get_404_never_retries(self):
        calls, opener_open = self.open([http_error(404)])
        with patch.object(self.api.opener, "open", side_effect=opener_open), patch("api.time.sleep"):
            with self.assertRaises(Blocked) as context:
                self.api.request("GET", "/issues/missing")
        self.assertEqual(len(calls), 1)
        self.assertIn("HTTP 404", str(context.exception))


if __name__ == "__main__":
    unittest.main()
