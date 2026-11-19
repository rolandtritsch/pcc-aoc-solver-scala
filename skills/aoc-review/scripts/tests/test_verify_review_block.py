import importlib.util
import json
import subprocess
import sys
import tempfile
from pathlib import Path
import unittest

SCRIPT = Path(__file__).parents[1] / "verify_review_block.py"
spec = importlib.util.spec_from_file_location("verify_block", SCRIPT)
validator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(validator)
COMMIT = "28c21aba3d5f3bd9e79af256fa77111480d9c184"
ISSUE = {"id": "review-id", "title": "AoC 2015 Day01 part2: review (submission attempt)",
         "description": '```aoc-solver-publication\n' + json.dumps({"year":2015,"day":1,"part":2,"commit":COMMIT}) + '\n```'}


def good(**overrides):
    result = {"reviewIssueId": ISSUE["id"], "year":2015,"day":1,"part":2,
              "solutionCommit": COMMIT, "accepted":True,"repairRequired":False,
              "provenance":{"status":"clear","sources":["official statement"],
                            "solverRuns":[{"runId":"solver-run","logBytes":100,"toolCalls":2,"complete":True}]}}
    result.update(overrides)
    return '```aoc-review-result\n' + json.dumps(result) + '\n```'


class VerifyTest(unittest.TestCase):
    def test_valid_acceptance_and_repair(self):
        self.assertTrue(validator.verify(ISSUE,good())[0])
        self.assertTrue(validator.verify(ISSUE,good(accepted=False,repairRequired=True,provenance={"status":"unknown"}))[0])

    def test_shape_identity_commit_and_provenance_defects(self):
        for changes in [{"reviewIssueId":"other"},{"year":2025},{"day":2},{"part":True},
                        {"solutionCommit":"f"*40},{"accepted":"yes"},{"repairRequired":0},
                        {"provenance":None},{"provenance":{"status":"unknown"}},
                        {"provenance":{"status":"clear","sources":["rules"],"solverRuns":[]}}]:
            with self.subTest(changes=changes): self.assertFalse(validator.verify(ISSUE,good(**changes))[0])

    def test_partial_log_cannot_clear(self):
        for field,value in [("complete",False),("logBytes",0),("toolCalls",0)]:
            result=json.loads(good().split('\n')[1]); result['provenance']['solverRuns'][0][field]=value
            self.assertFalse(validator.verify(ISSUE,'```aoc-review-result\n'+json.dumps(result)+'\n```')[0])

    def test_no_title_can_replace_handoff(self):
        issue = dict(ISSUE,description="",title=ISSUE['title']+' (attempt commit '+COMMIT+')')
        self.assertFalse(validator.verify(issue,good())[0])

    def test_bad_missing_or_duplicate_block(self):
        for body in ['no block','```aoc-review-result\n{bad\n```',good()+good()]:
            self.assertFalse(validator.verify(ISSUE,body)[0])

    def test_finale_requires_reason_and_correct_calendar(self):
        issue=dict(ISSUE,title='AoC 2025 Day12 part2: review',description='```aoc-review-context\n'+json.dumps({'kind':'finale','solutionCommit':COMMIT})+'\n```')
        body=good(year=2025,day=12,provenance={'status':'not_applicable','reason':'Authenticated completion interaction; no solver'})
        self.assertTrue(validator.verify(issue,body)[0])
        self.assertFalse(validator.verify(ISSUE,good(provenance={'status':'not_applicable','reason':'skip'}))[0])

    def test_invalid_calendar_and_receipt_identity(self):
        for title in ['AoC 2025 Day13 part2: review','AoC 2026 Day01 part2: review']:
            self.assertFalse(validator.verify(dict(ISSUE,title=title),good())[0])
        description=ISSUE['description'].replace('"year": 2015','"year": 2025')
        self.assertFalse(validator.verify(dict(ISSUE,description=description),good())[0])

    def test_cli_requires_full_issue(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'issue.json';path.write_text(json.dumps(ISSUE))
            for body,code in [(good(),0),('no block',1)]:
                proc=subprocess.run([sys.executable,str(SCRIPT),'--issue-file',str(path)],input=body,capture_output=True,text=True)
                self.assertEqual(proc.returncode,code,proc.stdout+proc.stderr)


if __name__=='__main__': unittest.main()
