"""Tests for aoc_repair.py's next_unsolved(), using a temp directory shaped
like scala3-aoc instead of the real repo, and fakes for site/repo matching
tests/test_workflow.py's conventions (hand-rolled, not mocks)."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

from unittest.mock import patch  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "skills/aoc-runtime/scripts"))

from common import Blocked  # noqa: E402
from aoc_repair import next_unsolved  # noqa: E402


def make_day(root, year, day, parts=(1, 2)):
    day_dir = Path(root) / str(year) / "src/main/scala" / f"aoc{year}" / f"day{day:02}"
    day_dir.mkdir(parents=True, exist_ok=True)
    for part in parts:
        (day_dir / f"Part{part}.scala").write_text("// stub\n")


class FakeRepo:
    def __init__(self, path, invalid_receipts=()):
        self.path = Path(path)
        self.synced = False
        self.invalid_receipts = set(invalid_receipts)

    def sync(self):
        self.synced = True

    def validate_receipt(self, receipt):
        if receipt.get("answer") in self.invalid_receipts:
            raise Blocked("Publication inputs/build/source changed")


class FakeSite:
    def __init__(self, account="acct"):
        self.account = account

    def page(self, year, day):
        return {"complete": 0, "answers": []}  # not yet solved on the real site


class NextUnsolvedTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        self.site = FakeSite()
        self.repo = FakeRepo(self.root)

    def tearDown(self):
        self.tmp.cleanup()

    def write_progress(self, parts):
        aoc_dir = Path(self.root) / ".aoc"
        aoc_dir.mkdir(parents=True, exist_ok=True)
        (aoc_dir / "progress.json").write_text(json.dumps(
            {"schema": 1, "account": self.site.account, "parts": parts}))

    def test_empty_repo_first_part_is_discovered(self):
        self.write_progress({})
        year, day, part, state = next_unsolved(self.repo, self.site)
        self.assertEqual((year, day, part), (2015, 1, 1))
        self.assertEqual(state, "DISCOVERED")

    def test_candidate_present_without_receipt(self):
        make_day(self.root, 2015, 1)
        self.write_progress({})
        year, day, part, state = next_unsolved(self.repo, self.site)
        self.assertEqual((year, day, part), (2015, 1, 1))
        self.assertEqual(state, "CANDIDATE_PRESENT")

    def test_accepted_parts_are_skipped_regardless_of_stale_cursor(self):
        # Mirrors the real scala3-aoc drift: progress.json says days 1-9 part1
        # accepted (days 1-8 both parts); a stale external cursor (not even
        # read by this function) would disagree -- it must not matter.
        parts = {}
        for day in range(1, 9):
            make_day(self.root, 2015, day)
            parts[f"2015/{day:02}/1"] = {"outcome": "accepted", "site": {"account": "acct"}, "receipt": {"answer": "x"}}
            parts[f"2015/{day:02}/2"] = {"outcome": "accepted", "site": {"account": "acct"}, "receipt": {"answer": "x"}}
        make_day(self.root, 2015, 9, parts=(1,))
        parts["2015/09/1"] = {"outcome": "accepted", "site": {"account": "acct"}, "receipt": {"answer": "x"}}
        self.write_progress(parts)

        year, day, part, state = next_unsolved(self.repo, self.site)
        self.assertEqual((year, day, part), (2015, 9, 2))
        self.assertEqual(state, "DISCOVERED")

    def test_idempotent_across_two_calls(self):
        make_day(self.root, 2015, 1)
        self.write_progress({})
        first = next_unsolved(self.repo, self.site)
        second = next_unsolved(self.repo, self.site)
        self.assertEqual(first, second)

    def test_stale_historical_receipt_trusts_recorded_site_acceptance(self):
        # Mirrors two real incidents (2026-11-25 day17, 2026-11-26 day19):
        # day17/part1 was accepted and receipted, then day17/part2 was later
        # committed -- invalidating part1's stored receipt purely because
        # hashing is scoped per day, not per part, even though part1 itself
        # is untouched and the site still shows it accepted. This is
        # expected and happens on every two-part day, not corruption, so it
        # must never trigger a local re-verify (which predictably fails for
        # reasons unrelated to this part, and cascades into a crash one
        # level up in workflow.py's own CANDIDATE_PRESENT check). The site
        # already confirmed acceptance; next_unsolved() must trust that
        # recorded evidence and continue past it without calling verify().
        parts = {}
        for day in range(1, 17):
            make_day(self.root, 2015, day)
            parts[f"2015/{day:02}/1"] = {"outcome": "accepted", "site": {"account": "acct"}, "receipt": {"answer": "x"}}
            parts[f"2015/{day:02}/2"] = {"outcome": "accepted", "site": {"account": "acct"}, "receipt": {"answer": "x"}}
        make_day(self.root, 2015, 17, parts=(1, 2))
        parts["2015/17/1"] = {"outcome": "accepted", "site": {"account": "acct"}, "receipt": {"answer": "stale-answer"}}
        parts["2015/17/2"] = {"outcome": "accepted", "site": {"account": "acct"}, "receipt": {"answer": "x"}}
        self.repo = FakeRepo(self.root, invalid_receipts={"stale-answer"})
        self.write_progress(parts)
        with patch("aoc_repair.verify", side_effect=Blocked("sbt failed")) as verify_mock:
            year, day, part, state = next_unsolved(self.repo, self.site)
        verify_mock.assert_not_called()
        self.assertEqual((year, day, part), (2015, 18, 1))
        self.assertEqual(state, "DISCOVERED")


if __name__ == "__main__":
    unittest.main()
