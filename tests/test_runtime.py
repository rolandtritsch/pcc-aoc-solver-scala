import copy
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import shutil
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "skills/aoc-runtime/scripts"))
sys.path.insert(0, str(ROOT / "operators"))
from common import Blocked, calendar, digest, identity, lock, read_json, write_json
from publication import check_output
from repository import Repository, load_progress
from aoc_site import Page, status, verdict
from stages import gather, submit
from workflow import Controller, assignment, complete_stage
from package import build, payload, validate
from entry import run_model

spec = importlib.util.spec_from_file_location("launch", ROOT / "runtime/launch.py")
launch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(launch)


def html(complete=0, answer="42", user="Tester", stars="1*", day=1):
    banner = '<div class="user">' + user + '<a>[AoC++]</a><span class="star-count">' + stars + '</span></div>'
    article = f'<article><h2>--- Day {day}: Puzzle ---</h2><p>Rules</p></article>'
    marker = ("Both parts of this puzzle are complete!" if complete == 2 else
              "The first half of this puzzle is complete!" if complete else "")
    answers = f'<p>Your puzzle answer was <code>{answer}</code>.</p>' if complete else ""
    return banner + article + answers + marker + '<form><input name="level" value="1"></form>'


class SiteTests(unittest.TestCase):
    def test_login_and_unrecognized_200_fail_closed(self):
        for page in ("<html>Please log in</html>", '<div class="user">Tester</div>'):
            with self.assertRaises(Blocked):
                status(page, digest("Tester"), 1)

    def test_wrong_account_blocks(self):
        with self.assertRaises(Blocked):
            status(html(user="Other"), digest("Tester"), 1)

    def test_star_count_does_not_change_account(self):
        for stars in ("1*", "524*"):
            self.assertEqual(status(html(stars=stars), digest("Tester"), 1)["complete"], 0)

    def test_recognized_unsolved(self):
        self.assertEqual(status(html(), digest("Tester"), 1)["answers"], [])

    def test_wrong_day_blocks(self):
        with self.assertRaises(Blocked):
            status(html(), digest("Tester"), 2)

    def test_completion_needs_answer_evidence(self):
        with self.assertRaises(Blocked):
            status(html(1).replace('Your puzzle answer was', 'Missing answer'), digest("Tester"), 1)

    def test_accepted_text_answer_is_preserved(self):
        page = status(html(1, "A&amp;B"), digest("Tester"), 1)
        self.assertEqual(page["answers"], ["A&B"])

    def test_articles_exclude_known_answers(self):
        page = status(html(1), digest("Tester"), 1)
        self.assertNotIn("42", "".join(page["articles"]))

    def test_rate_limit_delay(self):
        outcome, _, delay = verdict('<article>You gave an answer too recently. You have 1m 2s left to wait.</article>')
        self.assertEqual((outcome, delay), ("rate_limited", 67))

    def test_unknown_wrong_level_is_not_acceptance(self):
        self.assertEqual(verdict('<article>You don’t seem to be solving the right level.</article>')[0], "uncertain")


class Contracts(unittest.TestCase):
    def test_solver_budget_terminates_execution(self):
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaises(Blocked):
                run_model([sys.executable, "-c", "import time; time.sleep(30)"], root, "", os.environ, timeout=0.1)

    def test_calendar_boundaries(self):
        parts = calendar()
        self.assertEqual(len(parts), 524)
        self.assertEqual(parts[-1], (2025, 12, 2))
        for triple in ((2026, 1, 1), (2025, 13, 1), (2015, 0, 1), (2015, 1, True)):
            with self.assertRaises(Blocked):
                identity(*triple)

    def test_zero_tests_and_ambiguous_runner_block(self):
        output = "+ Day01\n  + sample\n2 tests passed. 0 tests failed. 0 tests ignored.\n[success]\nDay01 - part1: -42"
        self.assertEqual(check_output(output, 2015, 1, 1, "-42"), "-42")
        for bad in (output.replace("2 tests passed", "0 tests passed"), output + "\nDay01 - part1: -42", output.replace("+ Day01", "+ Day02")):
            with self.assertRaises(Blocked):
                check_output(bad, 2015, 1, 1, "-42")

    def test_atomic_private_checkpoint_and_corruption(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "state.json"
            write_json(path, {"outcome": "intent"})
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(read_json(path)["outcome"], "intent")
            path.write_text("broken")
            with self.assertRaises(Blocked):
                read_json(path)

    def test_runtime_lock_refuses_concurrent_mutation(self):
        with tempfile.TemporaryDirectory() as root:
            with lock(root):
                with patch("common.time.sleep"):
                    with self.assertRaises(Blocked):
                        with lock(root):
                            pass

    def test_runtime_lock_retries_through_brief_contention(self):
        # Two of this company's own agents can briefly overlap on the shared
        # workspace lock; a short-lived collision should self-clear instead
        # of failing on the very first attempt.
        import fcntl as fcntl_module
        attempts = []
        real_flock = fcntl_module.flock

        def flaky(handle, operation):
            if operation & fcntl_module.LOCK_NB:
                attempts.append(1)
                if len(attempts) < 3:
                    raise BlockingIOError()
            return real_flock(handle, operation)

        with tempfile.TemporaryDirectory() as root:
            with patch("common.fcntl.flock", side_effect=flaky), patch("common.time.sleep"):
                with lock(root):
                    pass
        self.assertEqual(len(attempts), 3)


class Packages(unittest.TestCase):
    def test_allowlisted_complete_python_inventory(self):
        package = build(ROOT)
        validate(package)
        self.assertIn("skills/aoc-runtime/scripts/stages.py", package["files"])
        self.assertFalse(any("operators/" in k or "solution-reviewer" in k for k in package["files"]))
        body = payload(package, "company")
        self.assertEqual(body["collisionStrategy"], "replace")
        self.assertEqual(body["source"]["files"], package["files"])

    def test_modified_package_rejected(self):
        package = build(ROOT)
        package["files"]["skills/aoc-runtime/scripts/entry.py"] += "# tamper\n"
        with self.assertRaises(Blocked):
            validate(package)

    def test_simulated_ssh_delivery_checks_real_bytes(self):
        package = build(ROOT)
        with tempfile.TemporaryDirectory() as root:
            target = Path(root) / ".paperclip-runtime/opencode/skills/aoc-runtime--key"
            prefix = "skills/aoc-runtime/"
            for name, content in package["files"].items():
                if name.startswith(prefix):
                    file = target / name[len(prefix):]
                    file.parent.mkdir(parents=True, exist_ok=True)
                    file.write_text(content)
            self.assertEqual(launch.resolve_release(root, package["packageHash"]), target)
            (target / "scripts/entry.py").write_text("tampered")
            with self.assertRaises(RuntimeError):
                launch.resolve_release(root, package["packageHash"])

    def test_missing_release_and_symlink_fail(self):
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaises(RuntimeError):
                launch.resolve_release(root, "missing")


class GitTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.remote = self.root / "remote.git"
        self.source = self.root / "source"
        self.owner = {"company": "company", "generation": "g1"}
        self.git(self.root, "init", "--bare", "--initial-branch=main", str(self.remote))
        self.git(self.root, "clone", str(self.remote), str(self.source))
        self.git(self.source, "config", "user.name", "Test")
        self.git(self.source, "config", "user.email", "test@example.com")
        write_json(self.source / ".aoc/owner.json", self.owner)
        file = self.source / "2015/src/main/scala/aoc2015/Day01.scala"
        file.parent.mkdir(parents=True)
        file.write_text("solution")
        self.git(self.source, "add", ".")
        self.git(self.source, "commit", "-m", "initial")
        self.git(self.source, "push", "origin", "main")

    def tearDown(self):
        self.temp.cleanup()

    def git(self, root, *args):
        return subprocess.run(["git", *args], cwd=root, check=True, text=True, capture_output=True).stdout.strip()

    def prepare(self):
        return Repository.prepare(self.root, "attempt", self.owner, str(self.remote))

    def test_fresh_and_behind_checkouts_recover(self):
        repo = self.prepare()
        (self.source / "other.txt").write_text("change")
        self.git(self.source, "add", ".")
        self.git(self.source, "commit", "-m", "advance")
        self.git(self.source, "push", "origin", "main")
        repo.sync()
        self.assertEqual(repo.parity(), self.git(self.source, "rev-parse", "HEAD"))

    def test_dirty_and_ahead_work_preserved(self):
        repo = self.prepare()
        (repo.path / "precious.txt").write_text("keep")
        with self.assertRaises(Blocked):
            repo.sync()
        self.assertTrue((repo.path / "precious.txt").exists())
        self.git(repo.path, "add", ".")
        self.git(repo.path, "commit", "-m", "local-only")
        with self.assertRaises(Blocked):
            repo.sync()

    def test_old_owner_cannot_publish_after_transfer(self):
        repo = self.prepare()
        write_json(self.source / ".aoc/owner.json", {"company": "new", "generation": "g2"})
        self.git(self.source, "add", ".")
        self.git(self.source, "commit", "-m", "transfer")
        self.git(self.source, "push", "origin", "main")
        with self.assertRaises(Blocked):
            repo.assert_owner()

    def test_metadata_commits_do_not_invalidate_receipt(self):
        repo = self.prepare()
        receipt = {"schema": 1, "year": 2015, "day": 1, "owner": self.owner,
            "commit": repo.parity(), "files": repo.hashes(2015, 1),
            "formatting": "passed", "tests": "passed", "runner": "passed"}
        write_json(repo.path / ".aoc/progress.json", {"progress": "metadata"})
        repo.commit([".aoc/progress.json"], "progress")
        repo.validate_receipt(receipt)
        (repo.path / "2015/src/main/scala/aoc2015/Day01.scala").write_text("changed")
        with self.assertRaises(Blocked):
            repo.validate_receipt(receipt)

    def test_missing_and_corrupt_progress(self):
        repo = self.prepare()
        self.assertEqual(load_progress(repo, "account")["parts"], {})
        write_json(repo.path / ".aoc/progress.json", {"schema": 1, "account": "other", "parts": {}})
        with self.assertRaises(Blocked):
            load_progress(repo, "account")

    def test_receipt_hashes_include_assigned_package_and_shared_code_only(self):
        repo = self.prepare()
        paths = ["src/main/scala/aoc2015/day01/Part1.scala",
                 "src/main/scala/aoc2015/day02/Part1.scala",
                 "src/main/scala/aoc2015/util/AocError.scala",
                 "src/test/scala/aoc2015/day01/Day01Test.scala",
                 "src/test/resources/inputs/Day01Invalid.txt",
                 ".scalafix/FunctionEndMarkers.scala"]
        for name in paths:
            path = repo.path / "2015" / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("fixture")
        repo.commit(["2015/" + name for name in paths], "layout fixtures")
        hashes = repo.hashes(2015, 1)
        for name in paths:
            self.assertEqual("2015/" + name in hashes, "/day02/" not in name)

    def test_same_attempt_can_resume_only_its_intended_dirty_files(self):
        repo = self.prepare()
        name = "2015/src/main/scala/aoc2015/Day01.scala"
        (repo.path / name).write_text("unfinished")
        repo.sync(allowed_dirty={name})
        self.assertEqual((repo.path / name).read_text(), "unfinished")
        (repo.path / "foreign.txt").write_text("keep")
        with self.assertRaises(Blocked):
            repo.sync(allowed_dirty={name})

    def test_year_bootstrap_preserves_template_and_updates_ci(self):
        repo = self.prepare()
        shutil.copytree(ROOT / "skills/aoc-runtime/assets/template", repo.path / "0000")
        files = [str(p.relative_to(repo.path)) for p in (repo.path / "0000").rglob("*") if p.is_file()]
        repo.commit(files, "template", force=True)
        before = (repo.path / "0000/build.sbt").read_bytes()
        import repository
        original = repository.command
        def run(cwd, args, timeout=900):
            if args[0] == "sbt":
                return "+ Day00\n34 tests passed. 0 tests failed. 0 tests ignored.\nDay00 - part1: 55"
            return original(cwd, args, timeout)
        with patch("repository.command", side_effect=run):
            repo.bootstrap(2016)
        self.assertEqual((repo.path / "0000/build.sbt").read_bytes(), before)
        self.assertIn('scala3-aoc-2016', (repo.path / "2016/build.sbt").read_text())
        self.assertIn("2016", (repo.path / ".github/workflows/ci.yml").read_text())
        self.assertTrue((repo.path / "2016/src/main/scala/aoc2016/day00/Part1.scala").is_file())

    def test_gather_strips_trailing_blank_lines_before_whitespace_check(self):
        repo = self.prepare()
        shutil.copytree(ROOT / "skills/aoc-runtime/assets/template", repo.path / "0000")
        files = [str(p.relative_to(repo.path)) for p in (repo.path / "0000").rglob("*") if p.is_file()]
        repo.commit(files, "template", force=True)

        class FakeGatherSite:
            def page(self, year, day):
                # A trailing blank line in the fetched article text (as real
                # AoC HTML extraction produces) must not break the commit's
                # git diff --check whitespace gate.
                return {"articles": ["Day 5: doesn't matter.\n\nHow many strings?\n\n"]}

            def fetch(self, year, day, suffix="", data=None):
                return "1,2,3\n"

        import repository
        original = repository.command
        def run(cwd, args, timeout=900):
            if args[0] == "sbt":
                return "+ Day00\n34 tests passed. 0 tests failed. 0 tests ignored.\nDay00 - part1: 55"
            return original(cwd, args, timeout)
        with patch("repository.command", side_effect=run):
            result = gather(repo, FakeGatherSite(), {"year": 2016, "day": 5, "part": 1})
        self.assertEqual(result["outcome"], "gathered")
        text = (repo.path / "2016/problems/Day05Problem.txt").read_text()
        self.assertTrue(text.endswith("strings?\n"))
        self.assertFalse(text.endswith("\n\n"))


class FakeRepository:
    def assert_owner(self):
        pass

    def validate_receipt(self, receipt):
        pass


class FakeSite:
    def __init__(self, responses, complete=0):
        self.responses, self.complete, self.posts = list(responses), complete, 0

    def page(self, year, day):
        return {"account": "account", "complete": self.complete, "answers": ["42"] if self.complete else [], "observedAt": "now"}

    def fetch(self, year, day, suffix="", data=None):
        self.posts += 1
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        if "right answer!" in response:
            self.complete = 1
        return response


class SubmissionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "checkpoint.json"
        self.spec = {"year": 2015, "day": 1, "part": 1}
        self.receipt = {**self.spec, "answer": "42"}
        self.verifier = patch("stages.verify", return_value=self.receipt)
        self.verifier.start()

    def tearDown(self):
        self.verifier.stop()
        self.temp.cleanup()

    def test_lost_response_never_posts_again(self):
        site = FakeSite([TimeoutError()])
        result = submit(FakeRepository(), site, self.spec, self.receipt, self.path)
        self.assertEqual(result["outcome"], "uncertain")
        with self.assertRaises(Blocked):
            submit(FakeRepository(), site, self.spec, self.receipt, self.path)
        self.assertEqual(site.posts, 1)

    def test_lost_response_reconciles_if_site_accepted(self):
        write_json(self.path, {"outcome": "intent"})
        site = FakeSite([], complete=1)
        result = submit(FakeRepository(), site, self.spec, self.receipt, self.path)
        self.assertEqual(result["outcome"], "accepted")
        self.assertEqual(site.posts, 0)

    def test_checkpoint_must_persist_before_post(self):
        site = FakeSite([])
        def fail(value):
            raise Blocked("API unavailable")
        with self.assertRaises(Blocked):
            submit(FakeRepository(), site, self.spec, self.receipt, self.path, persist=fail)
        self.assertEqual(site.posts, 0)

    def test_bounded_rate_limit_retry(self):
        site = FakeSite(['<article>You gave an answer too recently. Wait 2s.</article>'] * 3)
        waits = []
        result = submit(FakeRepository(), site, self.spec, self.receipt, self.path, sleep=waits.append)
        self.assertEqual((result["outcome"], site.posts, waits), ("rate_limited", 3, [7, 7]))

    def test_wrong_answer_cannot_be_resubmitted_on_retry(self):
        site = FakeSite(["<article>That's not the right answer.</article>"])
        result = submit(FakeRepository(), site, self.spec, self.receipt, self.path)
        self.assertEqual(result["outcome"], "rejected")
        with self.assertRaises(Blocked):
            submit(FakeRepository(), site, self.spec, self.receipt, self.path)
        self.assertEqual(site.posts, 1)

    def test_mismatched_receipt_prevents_post(self):
        with self.assertRaises(Blocked):
            submit(FakeRepository(), FakeSite([]), self.spec, {**self.receipt, "part": 2}, self.path)


if __name__ == "__main__":
    unittest.main()
