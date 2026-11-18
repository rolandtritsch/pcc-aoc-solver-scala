import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location("gate", Path(__file__).parents[1] / "aoc_cycle_gate.py")
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)
SINCE = "2026-10-10T18:00:00Z"
AGENTS = [{"id": name, "name": name} for name in list(gate.STAGES) + ["WatchDog", "Model Tester", "CTO"]]


def issue(stage="review", status="done", created="2026-10-10T19:00:00Z", day=1):
    name = next(name for name, value in gate.STAGES.items() if value == stage)
    return {"id": "issue-" + stage, "identifier": "AOC-" + stage,
            "title": f"AoC 2025 Day{day:02} part1: {stage}", "createdAt": created,
            "status": status, "assigneeAgentId": name}


def accepted(id):
    import json
    match = __import__('re').search(r"review-(20\d{2})-(\d+)-([12])$", id)
    year, day, number = map(int, match.groups()) if match else (2025, 1, 1)
    result = {"reviewIssueId": id, "year": year, "day": day, "part": number,
              "solutionCommit": "abc12345678", "accepted": True, "repairRequired": False}
    return [{"body": "```aoc-review-result\n" + json.dumps(result) + "\n```"}]


class GateTest(unittest.TestCase):
    def check(self, rows, comments=accepted, runs=()):
        return gate.evaluate(rows, AGENTS, SINCE, comments, runs)["mode"]

    def test_empty_company_ready(self):
        self.assertEqual(self.check([]), "ready")

    def season(self):
        rows = []
        for year, day, part_number in sorted(gate.SEASON_PARTS):
            row = issue(day=day)
            row["id"] = f"review-{year}-{day}-{part_number}"
            row["identifier"] = f"AOC-{year}-{day}-{part_number}"
            row["title"] = f"AoC {year} Day{day:02} part{part_number}: review"
            rows.append(row)
        return rows

    def test_all_524_parts_complete_without_extra_day(self):
        rows = self.season()
        def reviewed(id):
            _, year, day, part_number = id.split("-")
            import json
            result = {"reviewIssueId": id, "year": int(year), "day": int(day), "part": int(part_number),
                      "solutionCommit": "abc12345678", "accepted": True, "repairRequired": False}
            return [{"body": "```aoc-review-result\n" + json.dumps(result) + "\n```"}]
        self.assertEqual(self.check(rows, reviewed), "complete")

    def test_missing_finale_review_is_not_complete(self):
        self.assertEqual(len(gate.SEASON_PARTS), 524)
        self.assertEqual(self.check(self.season()[:-1]), "ready")

    def test_finale_review_alone_cannot_complete_season(self):
        self.assertEqual(self.check(self.season()[-1:]), "ready")

    def test_cancelled_finale_is_not_complete(self):
        rows = self.season(); rows[-1]["status"] = "cancelled"
        self.assertEqual(self.check(rows), "ready")

    def test_unfinished_finale_waits(self):
        rows = self.season(); rows[-1]["status"] = "in_progress"
        self.assertEqual(self.check(rows), "wait")

    def test_finale_repair_is_not_complete(self):
        rows = self.season()
        def comments(id):
            if id != rows[-1]["id"]: return accepted(id)
            return [{"body": '```aoc-review-result\n{"reviewIssueId":"review-2025-12-2","year":2025,"day":12,"part":2,"solutionCommit":"abc123","accepted":false,"repairRequired":true}\n```'}]
        self.assertEqual(self.check(rows, comments), "repair")

    def test_live_specialist_after_last_review_still_waits(self):
        self.assertEqual(self.check(self.season(), runs=[{"id":"run", "agentId":"Problem Solver"}]), "wait")

    def test_old_cycle_completion_does_not_stop_new_cycle(self):
        rows=self.season()
        for row in rows: row["createdAt"]="2026-10-09T19:00:00Z"
        self.assertEqual(self.check(rows), "ready")

    def test_active_solver_blocks_selection(self):
        self.assertEqual(self.check([issue("solve", "in_progress")]), "wait")

    def test_solved_and_submitted_without_review_waits(self):
        self.assertEqual(self.check([issue("solve"), issue("submit")]), "wait")

    def test_review_in_progress_blocks_next_part(self):
        self.assertEqual(self.check([issue(status="in_progress")]), "wait")

    def test_successful_review_releases_gate(self):
        self.assertEqual(self.check([issue()]), "ready")

    def test_done_without_review_evidence_waits(self):
        self.assertEqual(self.check([issue()], lambda id: []), "wait")

    def test_old_tasks_do_not_block(self):
        self.assertEqual(self.check([issue(status="blocked", created="2026-10-09T19:00:00Z")]), "ready")

    def test_watchdog_and_model_tester_do_not_block(self):
        rows = []
        for name in ("WatchDog", "Model Tester"):
            row = issue(status="in_progress"); row["assigneeAgentId"] = name
            rows.append(row)
        self.assertEqual(self.check(rows), "ready")

    def test_cancelled_premature_work_does_not_block(self):
        self.assertEqual(self.check([issue("gather", "cancelled")]), "ready")

    def test_live_specialist_still_blocks(self):
        self.assertEqual(self.check([issue()], runs=[{"id": "run", "agentId": "Problem Solver"}]), "wait")

    def test_completed_rejection_permits_only_repair(self):
        body = '```aoc-review-result\n{"reviewIssueId":"issue-review","year":2025,"day":1,"part":1,"solutionCommit":"abc123","accepted":false,"repairRequired":true}\n```'
        self.assertEqual(self.check([issue()], lambda id: [{"body": body}]), "repair")

    def test_structured_result_identity_must_match(self):
        body = '```aoc-review-result\n{"reviewIssueId":"another","year":2025,"day":1,"part":1,"solutionCommit":"abc123","accepted":true,"repairRequired":false}\n```'
        with self.assertRaises(ValueError): self.check([issue()], lambda id: [{"body": body}])

    def test_unknown_pipeline_title_fails_closed(self):
        row = issue();row["title"] = "Investigate something"
        with self.assertRaises(ValueError): self.check([row])

    def test_success_record_for_another_commit_cannot_release_gate(self):
        row = issue(); row["title"] += " (attempt commit abc1234)"
        body = '```aoc-review-result\n{"reviewIssueId":"issue-review","year":2025,"day":1,"part":1,"solutionCommit":"def5678","accepted":true,"repairRequired":false}\n```'
        with self.assertRaises(ValueError): self.check([row], lambda id: [{"body": body}])

    def test_matching_structured_success_releases_gate(self):
        row = issue(); row["title"] += " (attempt commit abc1234)"
        body = '```aoc-review-result\n{"reviewIssueId":"issue-review","year":2025,"day":1,"part":1,"solutionCommit":"abc12345678","accepted":true,"repairRequired":false}\n```'
        self.assertEqual(self.check([row], lambda id: [{"body": body}]), "ready")

    def test_same_day_in_different_years_does_not_collide(self):
        first = issue(); first["title"] = "AoC 2015 Day01 part1: review"
        first["id"] = "review-2015-1-1"
        second = issue("solve", "in_progress")
        self.assertEqual(self.check([first, second]), "wait")

    def test_wrong_review_year_cannot_clear_gate(self):
        row = issue()
        with self.assertRaises(ValueError):
            self.check([row], lambda id: [{"body": accepted(id)[0]["body"].replace('2025', '2015')}])

    def test_calendar_limits(self):
        for title in ("AoC 2025 Day13 part1", "AoC 2014 Day01 part1", "AoC 2026 Day01 part1"):
            row = issue(); row["title"] = title
            with self.assertRaises(ValueError): self.check([row])
        row = issue(); row["title"] = "AoC 2015 Day25 part2"
        self.assertEqual(gate.part(row), (2015, 25, 2))

    def test_legacy_prose_cannot_clear_year_qualified_gate(self):
        self.assertEqual(self.check([issue()], lambda id: [{"body": "**Verdict:** Accepted. No puzzle repair is outstanding."}]), "wait")

    def test_repair_waits_for_later_open_stage(self):
        rejected = issue()
        pending = issue("gather", "todo", day=2)
        body = accepted(rejected["id"])[0]["body"].replace('"repairRequired": false', '"repairRequired": true')
        self.assertEqual(self.check([rejected, pending], lambda id: [{"body": body}]), "wait")

    def test_repair_waits_for_live_specialist(self):
        body = accepted("issue-review")[0]["body"].replace('"repairRequired": false', '"repairRequired": true')
        self.assertEqual(self.check([issue()], lambda id: [{"body": body}],
                                   [{"id": "run", "agentId": "Problem Solver"}]), "wait")


if __name__ == "__main__":
    unittest.main()
