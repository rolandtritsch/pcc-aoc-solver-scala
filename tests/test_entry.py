from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "skills/aoc-runtime/scripts"))
from common import Blocked
import entry


class FakeApi:
    def __init__(self, docs=None):
        self.docs = dict(docs or {})
        self.finished = []

    def document(self, task, key):
        return self.docs.get((task, key)), "revision"

    def put_document(self, task, key, value):
        self.docs[task, key] = value

    def finish(self, task, agent, company, status="done"):
        self.finished.append((task, agent, company, status))


class MainErrorHandlingTests(unittest.TestCase):
    def context(self, api, spec):
        return (api, "control-1", {"id": "control-1"}, spec, {"company": "company", "generation": "gen"}, Path("/workspaces/aoc"))

    def test_cto_transient_failure_leaves_retryable_breadcrumb(self):
        api = FakeApi()
        spec = {"schema": "aoc-task-v1", "stage": "control", "part": 1, "attempt": 0}
        with patch("entry.run", side_effect=Blocked("Another company mutation is active; retry later")), \
             patch("entry.runtime_context", return_value=self.context(api, spec)), \
             patch.dict("os.environ", {"AOC_ROLE": "cto"}, clear=False):
            code = entry.main()
        self.assertEqual(code, 2)
        self.assertEqual(api.docs[("control-1", "state")]["outcome"], "blocked")

    def test_cto_breadcrumb_never_overwrites_a_semantic_outcome(self):
        api = FakeApi(docs={("control-1", "state"): {"part": 1, "attempt": 0, "outcome": "rejected"}})
        spec = {"schema": "aoc-task-v1", "stage": "control", "part": 1, "attempt": 0}
        with patch("entry.run", side_effect=Blocked("transient")), \
             patch("entry.runtime_context", return_value=self.context(api, spec)), \
             patch.dict("os.environ", {"AOC_ROLE": "cto"}, clear=False):
            entry.main()
        self.assertEqual(api.docs[("control-1", "state")]["outcome"], "rejected")

    def test_specialist_failure_keeps_existing_non_cto_behavior(self):
        api = FakeApi()
        spec = {"schema": "aoc-task-v1", "stage": "gather", "part": 1, "attempt": 0}
        with patch("entry.run", side_effect=Blocked("boom")), \
             patch("entry.runtime_context", return_value=self.context(api, spec)), \
             patch.dict("os.environ", {"AOC_ROLE": "problem-gatherer",
                 "PAPERCLIP_AGENT_ID": "Problem Gatherer", "PAPERCLIP_COMPANY_ID": "company"}, clear=False):
            entry.main()
        self.assertEqual(api.docs[("control-1", "result")]["outcome"], "blocked")
        self.assertEqual(api.finished, [("control-1", "Problem Gatherer", "company", "done")])


if __name__ == "__main__":
    unittest.main()
