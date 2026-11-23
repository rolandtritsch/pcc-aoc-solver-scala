import sys
from pathlib import Path
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "skills/aoc-runtime/scripts"))
from common import Blocked
from publication import allowed_files, check_output, check_tests, run_checks, _checked_projects


ZIO_DAY = "\x1b[32m+\x1b[0m Day06\n  + sample\n20 tests passed. 0 tests failed. 0 tests ignored.\n[success]"


class PublicationTests(unittest.TestCase):
    def setUp(self):
        _checked_projects.clear()

    def test_identical_tree_reuses_year_checks_but_requires_each_days_suite(self):
        with patch("publication.command", side_effect=[ZIO_DAY, "runner", ZIO_DAY.replace("Day06", "Day07")]) as run:
            self.assertEqual(run_checks(Path("2015"), 2015, 6, "tree", "commit"), "runner")
            self.assertEqual(run_checks(Path("2015"), 2015, 6, "tree", "metadata-commit"), "runner")
            self.assertEqual(run_checks(Path("2015"), 2015, 7, "tree", "metadata-commit"), "runner")
        self.assertEqual(run.call_count, 3)
        self.assertEqual(run.call_args.args[1][-1], "testOnly aoc2015.day07.Day07Test")

    def test_changed_tree_and_dirty_publication_never_reuse_checks(self):
        with patch("publication.command", side_effect=[ZIO_DAY, "runner"] * 4) as run:
            for tree in ("tree", "changed-tree", None, None):
                run_checks(Path("2015"), 2015, 6, tree, "commit")
        self.assertEqual(run.call_count, 8)

    def test_cached_year_result_cannot_mask_empty_next_day_suite(self):
        with patch("publication.command", side_effect=[ZIO_DAY, "runner", "[warn] No tests to run"]):
            run_checks(Path("2015"), 2015, 6, "tree", "commit")
            with self.assertRaises(Blocked):
                run_checks(Path("2015"), 2015, 7, "tree", "commit")

    def test_actual_zio_console_shape_and_exact_answer(self):
        self.assertEqual(check_output(ZIO_DAY + "\nDay06 - part2: 15343601", 2015, 6, 2), "15343601")

    def test_wrong_empty_failed_ignored_and_multiple_summaries_block(self):
        for output in (
            ZIO_DAY.replace("Day06", "Day05"),
            ZIO_DAY.replace("20 tests passed", "0 tests passed"),
            ZIO_DAY.replace("0 tests failed", "1 tests failed"),
            ZIO_DAY.replace("0 tests ignored", "1 tests ignored"),
            ZIO_DAY + "\n" + ZIO_DAY,
            "[warn] No tests to run\n[success]",
        ):
            with self.subTest(output=output), self.assertRaises(Blocked):
                check_tests(output, 6)

    def test_empty_assigned_selection_stops_before_full_year_can_mask_it(self):
        with patch("publication.command", return_value="[warn] No tests to run\n[success]") as run:
            with self.assertRaises(Blocked):
                run_checks(Path("2015"), 2015, 6)
        self.assertEqual(run.call_count, 1)
        self.assertIn("testOnly aoc2015.day06.Day06Test", run.call_args.args[1][-1])

    def test_publication_paths_follow_day_and_project_boundaries(self):
        allowed = allowed_files(2015, 7)
        for path in (
            "2015/src/main/scala/aoc2015/day07/Part1.scala",
            "2015/src/main/scala/aoc2015/day07/Wire.scala",
            "2015/src/test/scala/aoc2015/day07/Day07Test.scala",
            "2015/src/main/scala/aoc2015/util/AocError.scala",
            "2015/src/main/scala/aoc2015/Main.scala",
            "2015/src/test/resources/inputs/Day07Invalid.txt",
        ):
            self.assertIn(path, allowed)
        for path in (
            "2015/src/main/scala/aoc2015/day06/Part1.scala",
            "2015/src/main/scala/aoc2015/Day07.scala",
            "2016/src/main/scala/aoc2016/day07/Part1.scala",
            "2015/src/main/scala/aoc2015/day07/../day06/Part1.scala",
            "2015/build.sbt", ".aoc/progress.json",
            "2015/src/main/resources/inputs/Day07.txt",
            "2015/src/main/scala/aoc2015/day07/Evil;run.scala",
        ):
            self.assertNotIn(path, allowed)
