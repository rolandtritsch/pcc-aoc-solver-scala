import copy
import json
import os
from pathlib import Path
import sys
import unittest
import tempfile
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "skills/aoc-runtime/scripts"))
from common import Blocked, lock
from workflow import BLOCKED_RETRY_LIMIT, Controller, assignment, complete_stage, stage_notifier


class Api:
    def __init__(self):
        self.rows, self.docs, self.keys, self.comments = {}, {}, {}, []
        self.agents = [{"id": name, "name": name, "status": "idle"} for name in
                       ("CTO", "Problem Gatherer", "Problem Solver", "Problem Submitter")]

    def document(self, task, key):
        return copy.deepcopy(self.docs.get((task, key))), "revision"

    def put_document(self, task, key, value):
        self.docs[task, key] = copy.deepcopy(value)

    def finish(self, task, agent, company, status="done"):
        if self.rows[task]["assigneeAgentId"] != agent or self.rows[task]["companyId"] != company:
            raise Blocked("ownership mismatch")
        self.rows[task]["status"] = status

    def request(self, method, path, body=None):
        if method == "POST" and path == "/companies/company/issues":
            key = body["idempotencyKey"]
            if key in self.keys:
                return copy.deepcopy(self.rows[self.keys[key]])
            task = str(len(self.rows) + 1)
            self.keys[key] = task
            self.rows[task] = {**body, "id": task, "companyId": "company", "identifier": "AOC-" + task}
            return copy.deepcopy(self.rows[task])
        if method == "GET" and path.startswith("/companies/company/issues"):
            return [copy.deepcopy(row) for row in self.rows.values() if row["status"] not in ("done", "cancelled")]
        if method == "GET" and path == "/companies/company/agents":
            return self.agents
        if path.startswith("/issues/"):
            task = path.split("/")[2]
            if path.endswith("/comments"):
                self.comments.append(body)
                return body
            if method == "PATCH":
                self.rows[task].update(body)
            return copy.deepcopy(self.rows[task])
        raise AssertionError((method, path, body))


class Repo:
    def __init__(self):
        self.checks = 0
        self.path = Path("/fake-repo")

    def assert_owner(self):
        pass

    def validate_receipt(self, value):
        self.checks += 1

    def sync(self):
        pass


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.api = Api()
        self.repo = Repo()
        self.site = type("Site", (), {"account": "account", "page": lambda *args: {"complete": 0}})()
        self.controller = Controller(self.api, self.repo, self.site, "company", "generation", "CTO")
        self.spec = {"schema": "aoc-task-v1", "year": 2015, "day": 1, "part": 1,
            "stage": "control", "attempt": 0, "generation": "generation", "authorization": "daily"}
        self.control = self.controller.create(self.spec, "CTO", status="blocked")

    def child(self, stage, part=1, attempt=0):
        return next(row for row in self.api.rows.values() if (a := assignment(row))
                    and a["stage"] == stage and a["part"] == part and a["attempt"] == attempt)

    def complete(self, child, outcome, **extra):
        spec = assignment(child)
        self.api.put_document(child["id"], "result", {"assignment": spec, "outcome": outcome, **extra})
        self.api.rows[child["id"]]["status"] = "done"

    def advance(self, repair=False):
        return self.controller.advance(self.control, self.spec, [], repair)

    def test_duplicate_continuation_does_not_duplicate_gather(self):
        self.assertEqual(self.advance()["stage"], "gather")
        before = len(self.api.rows)
        self.assertEqual(self.advance()["stage"], "gather")
        self.assertEqual(len(self.api.rows), before)

    def test_result_before_disposition_does_not_advance(self):
        self.advance()
        child = self.child("gather")
        self.api.put_document(child["id"], "result", {"assignment": assignment(child), "outcome": "gathered"})
        self.assertIn("disposition", self.advance()["reason"])
        self.assertFalse(any(assignment(r)["stage"] == "solve" for r in self.api.rows.values()))

    def test_only_accepted_part1_starts_part2(self):
        self.advance()
        self.complete(self.child("gather"), "gathered")
        self.advance()
        self.complete(self.child("solve"), "published", receipt={"year": 2015, "day": 1, "part": 1, "answer": "42"})
        self.advance()
        self.complete(self.child("submit"), "accepted", receipt={"year": 2015, "day": 1, "part": 1, "answer": "42"}, site={"account": "account", "complete": 1})
        progress = {"schema": 1, "account": "account", "parts": {}}
        with patch("workflow.load_progress", return_value=progress), patch("workflow.save_progress") as save:
            result = self.advance()
            self.assertEqual(result["stage"], "gather")
            self.assertEqual(assignment(self.child("gather", 2))["part"], 2)
            self.assertEqual(progress["parts"]["2015/01/1"]["outcome"], "accepted")
            save.assert_called_once()

    def test_rejection_waits_for_new_daily_authorization(self):
        self.advance()
        self.complete(self.child("gather"), "gathered")
        self.advance()
        self.complete(self.child("solve"), "published", receipt={"year": 2015, "day": 1, "part": 1, "answer": "42"})
        self.advance()
        self.complete(self.child("submit"), "rejected", receipt={"year": 2015, "day": 1, "part": 1, "answer": "42"})
        self.advance()
        before = len(self.api.rows)
        self.assertEqual(self.advance()["reason"], "rejected")
        self.assertEqual(len(self.api.rows), before)
        self.advance(repair=True)
        self.assertEqual(assignment(self.child("gather", attempt=1))["attempt"], 1)
        self.assertEqual(self.api.docs[self.control["id"], "rejections"], {"1": ["42"]})

    def test_blocked_specialist_retries_same_stage_without_redoing_earlier_ones(self):
        self.advance()
        self.complete(self.child("gather"), "gathered")
        self.advance()
        # entry.py's catch-all handler records a transient infra failure
        # (lock contention, a flaky API call) generically as "blocked" --
        # this is not a semantic puzzle rejection.
        self.complete(self.child("solve"), "blocked", reason="Another company mutation is active; retry later")
        result = self.advance()
        self.assertEqual(result["reason"], "blocked")
        gather_attempts_before = {assignment(r)["attempt"] for r in self.api.rows.values()
            if (a := assignment(r)) and a["stage"] == "gather"}
        # A later continuation (no repair) must self-heal: it retries only
        # the stage that failed, not the whole day from "gather", and it
        # does not need allow_repair=True / the next daily cycle.
        result = self.advance()
        self.assertEqual(result["stage"], "solve")
        gather_attempts_after = {assignment(r)["attempt"] for r in self.api.rows.values()
            if (a := assignment(r)) and a["stage"] == "gather"}
        self.assertEqual(gather_attempts_before, gather_attempts_after)
        self.assertEqual(assignment(self.child("solve", attempt=1))["attempt"], 1)

    def test_blocked_specialist_eventually_waits_for_repair(self):
        self.advance()
        self.complete(self.child("gather"), "gathered")
        self.advance()  # dispatches solve, attempt 0
        self.complete(self.child("solve", attempt=0), "blocked", reason="transient")
        result = self.advance()  # detects it, records state.outcome=blocked
        self.assertEqual(result["reason"], "blocked")
        for attempt in range(1, BLOCKED_RETRY_LIMIT + 1):
            result = self.advance()  # consumes one retry, dispatches a fresh attempt
            self.assertEqual(result["stage"], "solve")
            self.complete(self.child("solve", attempt=attempt), "blocked", reason="transient")
            result = self.advance()  # detects it again
            self.assertEqual(result["reason"], "blocked")
        # Once the bounded self-healing budget is exhausted, it parks the
        # day for a real daily/manual repair instead of retrying forever.
        before = len(self.api.rows)
        result = self.advance()
        self.assertEqual(result["outcome"], "wait")
        self.assertEqual(result["reason"], "blocked")
        self.assertEqual(len(self.api.rows), before)

    def test_uncertain_submission_never_auto_repairs(self):
        self.api.put_document(self.control["id"], "state", {"part": 1, "attempt": 0, "outcome": "uncertain"})
        with self.assertRaises(Blocked):
            self.advance(repair=True)

    def test_result_bound_to_exact_attempt(self):
        self.advance()
        row = self.child("gather")
        self.api.put_document(row["id"], "result", {"assignment": {**assignment(row), "attempt": 9}, "outcome": "gathered"})
        with self.assertRaises(Blocked):
            self.advance()

    def test_stage_cannot_report_other_stage_success(self):
        self.advance()
        self.complete(self.child("gather"), "accepted")
        result = self.advance()
        self.assertEqual(result["outcome"], "wait")

    def test_repeated_specialist_completion_keeps_single_result(self):
        self.advance()
        child = self.child("gather")
        env = {"PAPERCLIP_AGENT_ID": "Problem Gatherer", "PAPERCLIP_COMPANY_ID": "company"}
        with patch.dict(os.environ, env):
            for _ in range(2):
                complete_stage(self.api, child["id"], assignment(child), {"outcome": "gathered"})
        self.assertEqual(self.api.rows[child["id"]]["status"], "done")
        self.assertEqual(len(self.api.docs), 1)
        self.assertIn("@CTO", self.api.comments[0]["body"])

    def test_controller_notification_happens_after_mutation_lock_release(self):
        self.advance()
        child = self.child("gather")
        original = self.api.request
        with tempfile.TemporaryDirectory() as root:
            def request(method, path, body=None):
                if path.endswith("/comments"):
                    with lock(root):
                        pass
                return original(method, path, body)
            env = {"PAPERCLIP_AGENT_ID": "Problem Gatherer", "PAPERCLIP_COMPANY_ID": "company"}
            with patch.dict(os.environ, env), patch.object(self.api, "request", side_effect=request):
                with stage_notifier(self.api, child["id"], assignment(child)), lock(root):
                    complete_stage(self.api, child["id"], assignment(child), {"outcome": "gathered"}, notify=False)
                    self.assertEqual(self.api.comments, [])
            self.assertEqual(len(self.api.comments), 1)

    def test_continuation_with_no_authorization_cannot_select(self):
        self.api.rows[self.control["id"]]["status"] = "done"
        with patch.object(self.controller, "select", side_effect=AssertionError("must not select")):
            result = self.controller.run(self.control["id"], select=False)
        self.assertEqual(result["outcome"], "complete")

    def test_reconcile_stops_before_authorizing_unsolved_work(self):
        before = len(self.api.rows)
        with patch("aoc_repair.calendar", return_value=[(2015, 1, 1)]), patch("aoc_repair.load_progress", return_value={"parts": {}}):
            result = self.controller.select("reconcile", authorize=False)
        self.assertEqual(result["nextPart"], {"year": 2015, "day": 1, "part": 1})
        self.assertEqual(len(self.api.rows), before)

    def test_existing_candidate_is_verified_and_dispatched_straight_to_submit(self):
        receipt = {"schema": 1, "year": 2015, "day": 1, "part": 1, "answer": "42",
            "commit": "deadbeef", "files": {}, "owner": "owner", "verification": {},
            "formatting": "passed", "tests": "passed", "runner": "passed", "verifiedAt": "now"}
        with patch("aoc_repair.calendar", return_value=[(2015, 1, 1)]), \
                patch("aoc_repair.load_progress", return_value={"parts": {}}), \
                patch("aoc_repair.candidate_present", return_value=True), \
                patch("workflow.verify", return_value=receipt):
            result = self.controller.select("daily", authorize=True)
        self.assertEqual(result["stage"], "submit")
        submit_child = self.child("submit")
        control_id = submit_child["parentId"]
        self.assertEqual(self.api.docs[control_id, "publication"], receipt)
        self.assertEqual(self.api.docs[control_id, "state"]["start"], "submit")
        self.assertFalse(any((a := assignment(r)) and a["stage"] in ("gather", "solve")
            for r in self.api.rows.values() if r["parentId"] == control_id))

    def test_candidate_failing_verify_falls_through_to_full_pipeline(self):
        with patch("aoc_repair.calendar", return_value=[(2015, 1, 1)]), \
                patch("aoc_repair.load_progress", return_value={"parts": {}}), \
                patch("aoc_repair.candidate_present", return_value=True), \
                patch("workflow.verify", side_effect=Blocked("does not compile")):
            result = self.controller.select("daily", authorize=True)
        self.assertEqual(result["stage"], "gather")
        gather_child = self.child("gather")
        control_id = gather_child["parentId"]
        self.assertIsNone(self.api.docs.get((control_id, "publication")))
        self.assertNotIn("start", self.api.docs[control_id, "state"])

    def test_no_candidate_uses_full_pipeline_unchanged(self):
        with patch("aoc_repair.calendar", return_value=[(2015, 1, 1)]), \
                patch("aoc_repair.load_progress", return_value={"parts": {}}), \
                patch("aoc_repair.candidate_present", return_value=False):
            result = self.controller.select("daily", authorize=True)
        self.assertEqual(result["stage"], "gather")

    def test_straight_to_submit_rejection_is_tracked_like_any_other(self):
        receipt = {"schema": 1, "year": 2015, "day": 1, "part": 1, "answer": "42",
            "commit": "deadbeef", "files": {}, "owner": "owner", "verification": {},
            "formatting": "passed", "tests": "passed", "runner": "passed", "verifiedAt": "now"}
        with patch("aoc_repair.calendar", return_value=[(2015, 1, 1)]), \
                patch("aoc_repair.load_progress", return_value={"parts": {}}), \
                patch("aoc_repair.candidate_present", return_value=True), \
                patch("workflow.verify", return_value=receipt):
            self.controller.select("daily", authorize=True)
        submit_child = self.child("submit")
        control_id = submit_child["parentId"]
        self.complete(submit_child, "rejected", receipt=receipt)
        control = self.api.rows[control_id]
        spec = {"schema": "aoc-task-v1", "year": 2015, "day": 1, "part": 1,
            "stage": "control", "attempt": 0, "generation": "generation", "authorization": "daily"}
        self.assertEqual(self.controller.advance(control, spec, [], False)["reason"], "rejected")
        self.controller.advance(control, spec, [], True)  # repair: bounded retry
        self.assertEqual(assignment(self.child("gather", attempt=1))["attempt"], 1)
        self.assertEqual(self.api.docs[control_id, "rejections"], {"1": ["42"]})

    def test_site_accepted_without_repo_code_requires_operator(self):
        site = type("Site", (), {"account": "account",
            "page": lambda *a: {"complete": 1, "answers": ["42"]}})()
        controller = Controller(self.api, self.repo, site, "company", "generation", "CTO")
        with patch("aoc_repair.calendar", return_value=[(2015, 1, 1)]), \
                patch("aoc_repair.load_progress", return_value={"parts": {}}), \
                patch("aoc_repair.verify", side_effect=Blocked("no code to reproduce the answer")):
            with self.assertRaises(Blocked):
                controller.select("daily", authorize=True)

    def test_site_accepted_with_wrong_candidate_answer_raises_blocked(self):
        site = type("Site", (), {"account": "account",
            "page": lambda *a: {"complete": 1, "answers": ["42"]}})()
        controller = Controller(self.api, self.repo, site, "company", "generation", "CTO")
        wrong_receipt = {"schema": 1, "year": 2015, "day": 1, "part": 1, "answer": "99",
            "commit": "deadbeef", "files": {}, "owner": "owner", "verification": {},
            "formatting": "passed", "tests": "passed", "runner": "passed", "verifiedAt": "now"}
        with patch("aoc_repair.calendar", return_value=[(2015, 1, 1)]), \
                patch("aoc_repair.load_progress", return_value={"parts": {}}), \
                patch("aoc_repair.verify", return_value=wrong_receipt):
            with self.assertRaises(Blocked):
                controller.select("daily", authorize=True)


if __name__ == "__main__":
    unittest.main()
