"""Adapter contract / chaos tests for aoc_repair.next_unsolved() against a
REAL git repository (not FakeRepo) -- the one piece of the doc's "adapter
contract tests" / "chaos injection" layer that predates aoc_repair.py and
so wasn't exercised against it yet. Reuses the real-git fixture harness
pattern from tests/test_runtime.py's GitTests (bare remote + real clone via
Repository.prepare()). No real Paperclip, no real AoC network traffic --
`verify()` is patched since exercising a real sbt build is already covered
by the lease/claim spike in docs/2026-11-25_refactor-analysis.md, and is
not what this layer is meant to re-prove.
"""
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "skills/aoc-runtime/scripts"))

from aoc_repair import next_unsolved  # noqa: E402
from common import Blocked, write_json  # noqa: E402
from repository import Repository  # noqa: E402


class FakeSite:
    def __init__(self, account="account", responses=None):
        self.account = account
        self._responses = responses or {}

    def page(self, year, day):
        return self._responses.get((year, day), {"complete": 0, "answers": []})


class RealGitChaosTests(unittest.TestCase):
    """Mirrors tests/test_runtime.py's GitTests fixture setup exactly, so
    this suite exercises the same real-git contract, applied to
    next_unsolved() instead of Repository's own methods directly."""

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
        day01 = self.source / "2015/src/main/scala/aoc2015/day01"
        day01.mkdir(parents=True)
        (day01 / "Part1.scala").write_text("object Part1")
        self.git(self.source, "add", ".")
        self.git(self.source, "commit", "-m", "initial")
        self.git(self.source, "push", "origin", "main")

    def tearDown(self):
        self.temp.cleanup()

    def git(self, root, *args):
        return subprocess.run(["git", *args], cwd=root, check=True, text=True,
                               capture_output=True).stdout.strip()

    def prepare(self):
        return Repository.prepare(self.root, "attempt", self.owner, str(self.remote))

    def test_candidate_present_against_a_real_repo_is_idempotent(self):
        repo = self.prepare()
        site = FakeSite()
        first = next_unsolved(repo, site)
        second = next_unsolved(repo, site)
        self.assertEqual(first, second)
        self.assertEqual((first[0], first[1], first[2], first[3]),
                          (2015, 1, 1, "CANDIDATE_PRESENT"))

    def test_self_heals_when_receipt_commit_is_no_longer_an_ancestor(self):
        # Simulates a receipt that no longer matches the real repo state
        # (stale file hashes / unknown commit) -- repo.validate_receipt()
        # fails for real against the actual git history, forcing repair.
        repo = self.prepare()
        stale_receipt = {"schema": 1, "owner": self.owner, "year": 2015, "day": 1,
                          "commit": "0" * 40, "files": {}, "formatting": "passed",
                          "tests": "passed", "runner": "passed", "answer": "138"}
        write_json(self.source / ".aoc/progress.json", {
            "schema": 1, "account": "account",
            "parts": {"2015/01/1": {"outcome": "accepted",
                "receipt": stale_receipt, "site": {"account": "account"}}}})
        self.git(self.source, "add", ".")
        self.git(self.source, "commit", "-m", "stale receipt")
        self.git(self.source, "push", "origin", "main")
        repo.sync()

        site = FakeSite(responses={(2015, 1): {"complete": 1, "answers": ["138"],
            "account": "account", "observedAt": "now"}})
        fresh_receipt = {**stale_receipt, "commit": self.git(repo.path, "rev-parse", "HEAD")}
        with patch("aoc_repair.verify", return_value=fresh_receipt):
            result = next_unsolved(repo, site)
        # Part 1 repaired and accepted for real; part 2 (no candidate) is next.
        self.assertEqual(result[:3], (2015, 1, 2))
        self.assertEqual(result[3], "DISCOVERED")

    def test_diverged_checkout_fails_closed_before_reconciling(self):
        # The "reimport mid-flight" / concurrent-writer chaos scenario:
        # local HEAD and origin/main have diverged for real. Reconciliation
        # must never run against an unsynced checkout.
        repo = self.prepare()
        (repo.path / "local-only.txt").write_text("uncommitted local work")
        self.git(repo.path, "add", ".")
        self.git(repo.path, "commit", "-m", "local-only, never pushed")
        (self.source / "other.txt").write_text("remote advanced independently")
        self.git(self.source, "add", ".")
        self.git(self.source, "commit", "-m", "remote advance")
        self.git(self.source, "push", "origin", "main")
        with self.assertRaises(Blocked):
            repo.sync()
        # Even though sync() correctly refused, confirm next_unsolved() itself
        # doesn't silently paper over a stale HEAD if called anyway: the
        # committed candidate is still visible on disk, so it still reports
        # CANDIDATE_PRESENT rather than crashing -- the safety is that the
        # caller (select()) never gets here without a prior successful sync.
        site = FakeSite()
        result = next_unsolved(repo, site)
        self.assertEqual(result[:3], (2015, 1, 1))


if __name__ == "__main__":
    unittest.main()
