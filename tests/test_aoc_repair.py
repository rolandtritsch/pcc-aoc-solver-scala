"""Tests for aoc_repair.py's next_unsolved()/repair(), using a temp directory
shaped like scala3-aoc instead of the real repo, and fakes for site/repo
matching tests/test_workflow.py's conventions (hand-rolled, not mocks)."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "skills/aoc-runtime/scripts"))

from aoc_repair import next_unsolved, repair  # noqa: E402
from aoc_state import LeaseError  # noqa: E402


def make_day(root, year, day, parts=(1, 2)):
    day_dir = Path(root) / str(year) / "src/main/scala" / f"aoc{year}" / f"day{day:02}"
    day_dir.mkdir(parents=True, exist_ok=True)
    for part in parts:
        (day_dir / f"Part{part}.scala").write_text("// stub\n")


class FakeRepo:
    def __init__(self, path):
        self.path = Path(path)
        self.synced = False

    def sync(self):
        self.synced = True

    def validate_receipt(self, receipt):
        pass  # accepted entries in these tests are already trustworthy


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


class RepairTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        self.lease_dir = str(Path(self.tmp.name) / "leases")
        self.site = FakeSite()
        self.repo = FakeRepo(self.root)

    def tearDown(self):
        self.tmp.cleanup()

    def write_progress(self, parts):
        aoc_dir = Path(self.root) / ".aoc"
        aoc_dir.mkdir(parents=True, exist_ok=True)
        (aoc_dir / "progress.json").write_text(json.dumps(
            {"schema": 1, "account": self.site.account, "parts": parts}))

    def test_repair_syncs_repo_and_returns_next_candidate(self):
        make_day(self.root, 2015, 1)
        self.write_progress({})
        result = repair(self.repo, self.site, self.lease_dir, owner="test-owner")
        self.assertTrue(self.repo.synced)
        self.assertEqual(result["outcome"], "candidate")
        self.assertEqual((result["year"], result["day"], result["part"]), (2015, 1, 1))
        self.assertIn("fence_token", result)

    def test_repair_releases_lease_so_a_second_call_can_acquire(self):
        self.write_progress({})
        repair(self.repo, self.site, self.lease_dir, owner="owner-a")
        # Must not raise: the first call released its lease on return.
        repair(self.repo, self.site, self.lease_dir, owner="owner-b")

    def test_concurrent_repair_is_denied_while_one_is_held(self):
        from aoc_state import FileLeaseStore
        held = FileLeaseStore(self.lease_dir, "repair")
        held.acquire("blocker", ttl=60)
        try:
            with self.assertRaises(LeaseError):
                repair(self.repo, self.site, self.lease_dir, owner="other")
        finally:
            held.release()


if __name__ == "__main__":
    unittest.main()
