import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location(
    "existing", Path(__file__).parents[1] / "aoc_existing_solution.py")
existing = importlib.util.module_from_spec(spec)
spec.loader.exec_module(existing)

PASSING_OUTPUT = "aoc2015.Day03Test:\n[info] Passed: Total 11, Failed 0, Errors 0, Passed 11\n"
FAILING_OUTPUT = "aoc2015.Day03Test:\n[info] Passed: Total 11, Failed 1, Errors 0, Passed 10\n"


class ExistingSolutionTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = Path(self.tmp.name)
        self.year = 2015
        self.day = 3
        self.write_day(part1=True, part2=True)
        self.run_git("init", "-b", "main")
        self.run_git("config", "user.name", "Test")
        self.run_git("config", "user.email", "test@example.invalid")
        self.run_git("add", ".")
        self.run_git("commit", "-m", "Day03")
        self.commit = existing.git(self.repo, "rev-parse", "HEAD")

    def run_git(self, *args):
        subprocess.run(["git", *args], cwd=self.repo, check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def write_day(self, part1, part2):
        src = existing.source_file(self.repo, self.year, self.day)
        test = existing.test_file(self.repo, self.year, self.day)
        src.parent.mkdir(parents=True, exist_ok=True)
        test.parent.mkdir(parents=True, exist_ok=True)
        src.write_text("object Day03:\n  def part1(s: String) = 0\n  def part2(s: String) = 0\n")
        cases = []
        if part1:
            cases.append('  test("Day03 - part1 - real input"):\n    assertEquals(1, 1)')
        if part2:
            cases.append('  test("Day03 - part2 - real input"):\n    assertEquals(1, 1)')
        test.write_text("class Day03Test:\n" + "\n".join(cases) + "\n")

    def fake_run(self, output):
        def run(repo, args, timeout=600):
            return output
        return run

    def test_passing_real_input_test_is_solved(self):
        commit = existing.find_existing_commit(
            self.repo, self.year, self.day, 1, run=self.fake_run(PASSING_OUTPUT))
        self.assertEqual(commit, self.commit)

    def test_failing_tests_are_not_solved(self):
        commit = existing.find_existing_commit(
            self.repo, self.year, self.day, 1, run=self.fake_run(FAILING_OUTPUT))
        self.assertIsNone(commit)

    def test_missing_source_file_is_not_solved(self):
        existing.source_file(self.repo, self.year, self.day).unlink()
        commit = existing.find_existing_commit(
            self.repo, self.year, self.day, 1, run=self.fake_run(PASSING_OUTPUT))
        self.assertIsNone(commit)

    def test_part_without_real_input_case_is_not_solved(self):
        self.write_day(part1=True, part2=False)
        commit = existing.find_existing_commit(
            self.repo, self.year, self.day, 2, run=self.fake_run(PASSING_OUTPUT))
        self.assertIsNone(commit)

    def test_sbt_failure_is_not_solved(self):
        def raising(repo, args, timeout=600):
            raise existing.CheckError("sbt crashed")
        commit = existing.find_existing_commit(self.repo, self.year, self.day, 1, run=raising)
        self.assertIsNone(commit)

    def test_tests_passed_requires_executed_tests(self):
        self.assertFalse(existing.tests_passed("no summary line here"))
        self.assertFalse(existing.tests_passed("Total 0, Failed 0, Errors 0"))
        self.assertTrue(existing.tests_passed("Total 11, Failed 0, Errors 0"))

    def test_command_rejects_nonzero_exit(self):
        with self.assertRaises(existing.CheckError):
            existing.command(self.repo, ["sh", "-c", "exit 1"])


if __name__ == "__main__":
    unittest.main()
