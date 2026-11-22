import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location("gate", Path(__file__).parents[1] / "aoc_cycle_gate.py")
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)
import json
COMMIT = "abc12345678" + "0" * 29
PROVENANCE = {"status": "clear", "sources": ["official statement"], "solverRuns": [{"runId": "solver-run", "logBytes": 100, "toolCalls": 1, "complete": True}]}
SINCE = "2026-10-10T18:00:00Z"
AGENTS = [{"id": name, "name": name} for name in list(gate.STAGES) + ["Other Agent", "CTO"]]
START_OF_SEASON_LAST = (2015, 1, 1)
DAY4_PART2 = (2015, 4, 2)


def issue(stage="review", status="done", created="2026-10-10T19:00:00Z", day=1):
    name = next(name for name, value in gate.STAGES.items() if value == stage)
    return {"id": "issue-" + stage, "identifier": "AOC-" + stage,
            "title": f"AoC 2025 Day{day:02} part1: {stage}", "createdAt": created,
            "status": status, "assigneeAgentId": name,
            "description": "```aoc-solver-publication\n" + json.dumps({"year":2025,"day":day,"part":1,"commit":COMMIT}) + "\n```"}


def accepted(id):
    match = __import__('re').search(r"review-(20\d{2})-(\d+)-([12])$", id)
    year, day, number = map(int, match.groups()) if match else (2025, 1, 1)
    result = {"reviewIssueId": id, "year": year, "day": day, "part": number,
              "solutionCommit": COMMIT, "accepted": True, "repairRequired": False, "provenance": PROVENANCE}
    return [{"body": "```aoc-review-result\n" + json.dumps(result) + "\n```"}]


class GateTest(unittest.TestCase):
    def check(self, rows, comments=accepted, runs=(), last_part=START_OF_SEASON_LAST):
        return gate.evaluate(rows, AGENTS, SINCE, comments, runs, last_part)["mode"]

    def test_empty_cycle_is_ready(self):
        self.assertEqual(self.check([]), "ready")

    def test_next_part_comes_from_last_part_not_issue_replay(self):
        result = gate.evaluate([], AGENTS, SINCE, accepted, (), DAY4_PART2)
        self.assertEqual(result["mode"], "ready")
        self.assertEqual(result["nextPart"], [2015, 5, 1])

    def test_final_season_part_as_last_is_complete(self):
        self.assertEqual(self.check([], last_part=gate.SEASON_FINAL), "complete")

    def test_live_specialist_blocks_regardless_of_last_part(self):
        self.assertEqual(self.check([], runs=[{"id": "run", "agentId": "Problem Solver"}],
                                    last_part=gate.SEASON_FINAL), "wait")

    def test_unresolved_current_cycle_review_blocks_even_at_final_part(self):
        self.assertEqual(self.check([issue(status="in_progress")], last_part=gate.SEASON_FINAL), "wait")

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

    def test_old_cycle_tasks_do_not_block(self):
        self.assertEqual(self.check([issue(status="blocked", created="2026-10-09T19:00:00Z")]), "ready")

    def test_non_pipeline_agent_does_not_block(self):
        row = issue(status="in_progress"); row["assigneeAgentId"] = "Other Agent"
        self.assertEqual(self.check([row]), "ready")

    def test_cancelled_premature_work_does_not_block(self):
        self.assertEqual(self.check([issue("gather", "cancelled")]), "ready")

    def test_live_specialist_still_blocks(self):
        self.assertEqual(self.check([issue()], runs=[{"id": "run", "agentId": "Problem Solver"}]), "wait")

    def test_completed_rejection_permits_only_repair(self):
        body = '```aoc-review-result\n{"reviewIssueId":"issue-review","year":2025,"day":1,"part":1,"solutionCommit":"abc1234567800000000000000000000000000000","accepted":false,"repairRequired":true,"provenance":{"status":"unknown"}}\n```'
        self.assertEqual(self.check([issue()], lambda id: [{"body": body}]), "repair")

    def test_structured_result_identity_must_match(self):
        body = '```aoc-review-result\n{"reviewIssueId":"another","year":2025,"day":1,"part":1,"solutionCommit":"abc1234567800000000000000000000000000000","accepted":true,"repairRequired":false,"provenance":{"status":"clear","sources":["official statement"],"solverRuns":[{"runId":"run","logBytes":100,"toolCalls":1,"complete":true}]}}\n```'
        with self.assertRaises(ValueError): self.check([issue()], lambda id: [{"body": body}])

    def test_unknown_pipeline_title_fails_closed(self):
        row = issue();row["title"] = "Investigate something"
        with self.assertRaises(ValueError): self.check([row])

    def test_success_record_for_another_commit_cannot_release_gate(self):
        row = issue(); row["title"] += " (attempt commit abc1234)"
        body = '```aoc-review-result\n{"reviewIssueId":"issue-review","year":2025,"day":1,"part":1,"solutionCommit":"def5678","accepted":true,"repairRequired":false,"provenance":{"status":"clear","sources":["official statement"],"solverRuns":[{"runId":"run","logBytes":100,"toolCalls":1,"complete":true}]}}\n```'
        with self.assertRaises(ValueError): self.check([row], lambda id: [{"body": body}])

    def test_matching_structured_success_releases_gate(self):
        row = issue(); row["title"] += " (attempt commit abc1234)"
        body = '```aoc-review-result\n{"reviewIssueId":"issue-review","year":2025,"day":1,"part":1,"solutionCommit":"abc1234567800000000000000000000000000000","accepted":true,"repairRequired":false,"provenance":{"status":"clear","sources":["official statement"],"solverRuns":[{"runId":"run","logBytes":100,"toolCalls":1,"complete":true}]}}\n```'
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


class NextPartTest(unittest.TestCase):
    def test_part1_advances_to_part2_same_day(self):
        self.assertEqual(gate.next_part((2015, 4, 1)), (2015, 4, 2))

    def test_part2_advances_to_next_day_part1(self):
        self.assertEqual(gate.next_part((2015, 4, 2)), (2015, 5, 1))

    def test_last_25day_year_rolls_to_next_year(self):
        self.assertEqual(gate.next_part((2015, 25, 2)), (2016, 1, 1))

    def test_last_12day_year_2025_rolls_within_calendar(self):
        self.assertEqual(gate.next_part((2025, 11, 2)), (2025, 12, 1))

    def test_final_season_part_has_no_successor(self):
        with self.assertRaises(ValueError):
            gate.next_part(gate.SEASON_FINAL)

    def test_rejects_out_of_calendar_input(self):
        with self.assertRaises(ValueError):
            gate.next_part((2026, 1, 1))


class ReadLastPartTest(unittest.TestCase):
    def write(self, tmp_path, text):
        (tmp_path / "LAST.md").write_text(text)

    def test_reads_fenced_block(self):
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            self.write(path, '```aoc-last\n{"year": 2015, "day": 4, "part": 2}\n```\n')
            self.assertEqual(gate.read_last_part(path), (2015, 4, 2))

    def test_missing_block_fails_closed(self):
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            self.write(path, 'no block here')
            with self.assertRaises(ValueError):
                gate.read_last_part(path)

    def test_out_of_calendar_value_fails_closed(self):
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            self.write(path, '```aoc-last\n{"year": 2026, "day": 1, "part": 1}\n```\n')
            with self.assertRaises(ValueError):
                gate.read_last_part(path)


class ReviewContractRegressionTest(unittest.TestCase):
    check = GateTest.check
    def test_actual_generic_title_cannot_accept_unrelated_commit(self):
        row = issue()
        row["title"] = "AoC 2025 Day01 part1: review (submission attempt)"
        wrong = accepted(row["id"])[0]["body"].replace(COMMIT, "f" * 40)
        with self.assertRaisesRegex(ValueError, "handoff"):
            self.check([row], lambda _: [{"body": wrong}])

    def test_missing_handoff_receipt_blocks(self):
        row = issue(); row["description"] = "Solution commit: " + COMMIT
        with self.assertRaises(ValueError): self.check([row])

    def test_provenance_cannot_clear_from_handoff_and_reflog_alone(self):
        body = accepted("issue-review")[0]["body"]
        result = json.loads(body.split("\n")[1]); result["provenance"] = {"status": "unknown"}
        with self.assertRaisesRegex(ValueError, "provenance"):
            self.check([issue()], lambda _: [{"body": "```aoc-review-result\n" + json.dumps(result) + "\n```"}])


class DetailFetchTest(unittest.TestCase):
    def test_truncated_list_description_is_replaced_before_validation(self):
        full=issue(); compact=dict(full,description="truncated list preview")
        calls=[]
        def detail(row):
            calls.append(row['id']); return full
        result=gate.evaluate([compact],AGENTS,SINCE,accepted,[],START_OF_SEASON_LAST,detail)
        self.assertEqual(result['mode'],'ready')
        self.assertEqual(calls,[full['id']])


if __name__ == "__main__":
    unittest.main()
