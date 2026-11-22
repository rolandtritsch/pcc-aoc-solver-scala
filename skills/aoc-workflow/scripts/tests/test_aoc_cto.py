import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).parents[1]))
spec = importlib.util.spec_from_file_location("wrapper", Path(__file__).parents[1] / "aoc_cto.py")
wrapper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wrapper)


def result(mode, code, **extra):
    def check():
        print(json.dumps({"mode": mode, **extra}))
        return code
    return check


def sequence(*steps):
    """steps: (mode, code, extra-dict) tuples consumed one per check() call."""
    it = iter(steps)
    def check():
        mode, code, extra = next(it)
        print(json.dumps({"mode": mode, **extra}))
        return code
    return check


class WrapperTest(unittest.TestCase):
    def setUp(self):
        self.finisher = patch.object(wrapper, "finish_occurrence").start()
        self.addCleanup(patch.stopall)

    def test_wait_persists_disposition_before_success(self):
        self.assertEqual(wrapper.run(["run"], result("wait", 1), Mock()), 0)
        self.finisher.assert_called_once_with({"mode": "wait"})

    def test_failed_disposition_is_not_success(self):
        self.finisher.side_effect = OSError("unavailable")
        self.assertEqual(wrapper.run(["run"], result("wait", 1), Mock()), 2)

    def test_complete_persists_disposition(self):
        self.assertEqual(wrapper.run(["run"], result("complete", 1), Mock()), 0)
        self.finisher.assert_called_once_with({"mode": "complete"})

    def test_configuration_hello_probe_checks_provider_without_cycle_credentials(self):
        probe = Mock(return_value=Mock(returncode=0))
        check = Mock()
        with patch.dict(os.environ, {"OPENCODE_DISABLE_PROJECT_CONFIG": "true"}, clear=True), \
                patch.object(sys, "stdin", io.StringIO("Respond with hello.")):
            self.assertEqual(wrapper.run(["run"], check=check, probe=probe), 0)
        check.assert_not_called()
        probe.assert_called_once()

    def test_unauthenticated_arbitrary_prompt_cannot_bypass_gate(self):
        probe = Mock()
        with patch.dict(os.environ, {"OPENCODE_DISABLE_PROJECT_CONFIG": "true"}, clear=True), \
                patch.object(sys, "stdin", io.StringIO("Start another puzzle")):
            self.assertEqual(wrapper.run(["run"], probe=probe), 2)
        probe.assert_not_called()

    def test_authenticated_run_never_uses_probe_exception(self):
        probe = Mock()
        launch = Mock()
        with patch.dict(os.environ, {"OPENCODE_DISABLE_PROJECT_CONFIG": "true",
                                    "PAPERCLIP_RUN_ID": "real-run"}, clear=True):
            self.assertEqual(wrapper.run(["run"], result("wait", 1), launch, probe), 0)
        probe.assert_not_called()
        launch.assert_not_called()

    def test_busy_cycle_does_not_launch_provider(self):
        launch = Mock()
        self.assertEqual(wrapper.run(["run", "--model", "flash"], result("wait", 1), launch), 0)
        launch.assert_not_called()

    def test_completed_season_does_not_launch_provider(self):
        launch = Mock()
        self.assertEqual(wrapper.run(["run", "--model", "flash"], result("complete", 1), launch), 0)
        launch.assert_not_called()

    def test_unknown_evidence_fails_without_provider(self):
        launch = Mock()
        self.assertEqual(wrapper.run(["run"], result("unknown", 2), launch), 2)
        launch.assert_not_called()

    def test_ready_cycle_passes_exact_arguments_to_opencode(self):
        launch = Mock()
        args = ["run", "--format", "json", "--model", "flash"]
        self.assertEqual(wrapper.run(args, result("ready", 0), launch), 0)
        launch.assert_called_once_with("/usr/local/bin/opencode", ["/usr/local/bin/opencode", *args])

    def test_ready_without_repo_dir_skips_reconciliation(self):
        launch = Mock()
        site_check = Mock()
        reconcile_existing = Mock()
        with patch.dict(os.environ, {}, clear=True):
            code = wrapper.run(["run"], result("ready", 0, nextPart=[2015, 4, 1]), launch,
                               reconcile_existing=reconcile_existing, site_complete_check=site_check)
        self.assertEqual(code, 0)
        site_check.assert_not_called()
        reconcile_existing.assert_not_called()
        launch.assert_called_once()

    def test_repo_sync_failure_fails_closed_before_the_gate_runs(self):
        launch = Mock()
        check = Mock()
        sync = Mock(side_effect=RuntimeError("diverged"))
        with patch.dict(os.environ, {"AOC_REPO_DIR": "/repo"}, clear=True):
            code = wrapper.run(["run"], check, launch, sync=sync)
        self.assertEqual(code, 2)
        check.assert_not_called()
        launch.assert_not_called()

    def test_not_yet_complete_on_site_launches_normal_pipeline(self):
        launch = Mock()
        site_check = Mock(return_value=False)
        reconcile_existing = Mock()
        with patch.dict(os.environ, {"AOC_REPO_DIR": "/repo"}, clear=True):
            code = wrapper.run(["run"], result("ready", 0, nextPart=[2015, 5, 1]), launch,
                               reconcile_existing=reconcile_existing, site_complete_check=site_check,
                               sync=Mock())
        self.assertEqual(code, 0)
        site_check.assert_called_once_with([2015, 5, 1])
        reconcile_existing.assert_not_called()
        launch.assert_called_once()

    def test_catches_up_several_already_solved_parts_in_one_pass(self):
        launch = Mock()
        check = sequence(
            ("ready", 0, {"nextPart": [2015, 5, 1]}),
            ("ready", 0, {"nextPart": [2015, 5, 2]}),
            ("ready", 0, {"nextPart": [2015, 6, 1]}),
        )
        site_check = Mock(side_effect=[True, True, False])
        reconcile_existing = Mock(return_value="review-issue")
        with patch.dict(os.environ, {"AOC_REPO_DIR": "/repo"}, clear=True):
            code = wrapper.run(["run"], check, launch,
                               reconcile_existing=reconcile_existing, site_complete_check=site_check,
                               sync=Mock())
        self.assertEqual(code, 0)
        self.assertEqual([c.args[0] for c in site_check.call_args_list],
                         [[2015, 5, 1], [2015, 5, 2], [2015, 6, 1]])
        self.assertEqual([c.args for c in reconcile_existing.call_args_list],
                         [([2015, 5, 1], "/repo"), ([2015, 5, 2], "/repo")])
        launch.assert_called_once()
        self.finisher.assert_not_called()

    def test_catch_up_that_reaches_season_completion_finishes_instead_of_launching(self):
        launch = Mock()
        check = sequence(
            ("ready", 0, {"nextPart": [2025, 12, 2]}),
            ("complete", 1, {}),
        )
        site_check = Mock(return_value=True)
        reconcile_existing = Mock(return_value="review-issue")
        with patch.dict(os.environ, {"AOC_REPO_DIR": "/repo"}, clear=True):
            code = wrapper.run(["run"], check, launch,
                               reconcile_existing=reconcile_existing, site_complete_check=site_check,
                               sync=Mock())
        self.assertEqual(code, 0)
        launch.assert_not_called()
        self.finisher.assert_called_once_with({"mode": "complete"})

    def test_site_status_check_failure_fails_closed(self):
        launch = Mock()
        site_check = Mock(side_effect=RuntimeError("network down"))
        with patch.dict(os.environ, {"AOC_REPO_DIR": "/repo"}, clear=True):
            code = wrapper.run(["run"], result("ready", 0, nextPart=[2015, 5, 1]), launch,
                               site_complete_check=site_check, sync=Mock())
        self.assertEqual(code, 2)
        launch.assert_not_called()

    def test_reconciliation_failure_fails_closed(self):
        launch = Mock()
        site_check = Mock(return_value=True)
        reconcile_existing = Mock(side_effect=ValueError("no local commit"))
        with patch.dict(os.environ, {"AOC_REPO_DIR": "/repo"}, clear=True):
            code = wrapper.run(["run"], result("ready", 0, nextPart=[2015, 5, 1]), launch,
                               reconcile_existing=reconcile_existing, site_complete_check=site_check,
                               sync=Mock())
        self.assertEqual(code, 2)
        launch.assert_not_called()

    def test_reconciliation_loop_is_capped(self):
        launch = Mock()
        site_check = Mock(return_value=True)
        reconcile_existing = Mock(return_value="review-issue")
        with patch.dict(os.environ, {"AOC_REPO_DIR": "/repo"}, clear=True):
            code = wrapper.run(["run"], result("ready", 0, nextPart=[2015, 5, 1]), launch,
                               reconcile_existing=reconcile_existing, site_complete_check=site_check,
                               sync=Mock())
        self.assertEqual(code, 0)
        self.assertEqual(reconcile_existing.call_count, wrapper.MAX_RECONCILE_ITERATIONS)
        launch.assert_called_once()

    def test_completed_rejection_can_launch_same_part_repair(self):
        launch = Mock()
        wrapper.run(["run"], result("repair", 1), launch)
        launch.assert_called_once()

    def test_cli_probe_does_not_need_company_credentials(self):
        launch = Mock();check = Mock()
        wrapper.run(["--version"], check, launch)
        check.assert_not_called();launch.assert_called_once()

class DispositionTest(unittest.TestCase):
    def test_wait_updates_only_owned_issue_with_run_audit_header(self):
        env = {"PAPERCLIP_TASK_ID":"task", "PAPERCLIP_API_URL":"https://example.invalid",
               "AOC_PAPERCLIP_API_KEY":"test-key", "PAPERCLIP_RUN_ID":"run",
               "PAPERCLIP_COMPANY_ID":"company", "PAPERCLIP_AGENT_ID":"cto"}
        seen=[]
        def open_request(req, timeout):
            seen.append(req)
            response=Mock()
            value=({"companyId":"company","assigneeAgentId":"cto","status":"in_progress"}
                   if req.method=='GET' else {"status":"done"})
            response.__enter__=Mock(return_value=io.StringIO(json.dumps(value)))
            response.__exit__=Mock(return_value=False)
            return response
        opener=Mock();opener.open.side_effect=open_request
        with patch.dict(os.environ,env,clear=True),patch.object(wrapper.urllib.request,'build_opener',return_value=opener):
            wrapper.finish_occurrence({"mode":"wait"})
        self.assertEqual([r.method for r in seen],['GET','PATCH'])
        self.assertEqual(seen[-1].get_header('X-paperclip-run-id'),'run')
        self.assertEqual(json.loads(seen[-1].data)['status'],'done')

    def test_foreign_owner_is_preserved(self):
        env={"PAPERCLIP_TASK_ID":"task","PAPERCLIP_API_URL":"https://example.invalid",
             "AOC_PAPERCLIP_API_KEY":"test-key","PAPERCLIP_RUN_ID":"run",
             "PAPERCLIP_COMPANY_ID":"company","PAPERCLIP_AGENT_ID":"cto"}
        response=Mock();response.__enter__=Mock(return_value=io.StringIO(json.dumps({"companyId":"other"})))
        response.__exit__=Mock(return_value=False)
        opener=Mock();opener.open.return_value=response
        with patch.dict(os.environ,env,clear=True),patch.object(wrapper.urllib.request,'build_opener',return_value=opener):
            with self.assertRaises(ValueError):wrapper.finish_occurrence({"mode":"wait"})
        self.assertEqual(opener.open.call_count,1)


class ReconcileTest(unittest.TestCase):
    def env(self):
        return {"PAPERCLIP_API_URL": "https://example.invalid", "AOC_PAPERCLIP_API_KEY": "test-key",
               "PAPERCLIP_RUN_ID": "run", "PAPERCLIP_COMPANY_ID": "company"}

    def opener_for(self, responses):
        seen = []
        def open_request(req, timeout):
            seen.append(req)
            response = Mock()
            response.__enter__ = Mock(return_value=io.StringIO(json.dumps(responses.pop(0))))
            response.__exit__ = Mock(return_value=False)
            return response
        opener = Mock()
        opener.open.side_effect = open_request
        return opener, seen

    def test_no_local_commit_fails_closed(self):
        find_commit = Mock(return_value=None)
        write_last = Mock()
        with self.assertRaises(ValueError):
            wrapper.reconcile([2015, 4, 1], "/repo", find_commit=find_commit, write_last=write_last)
        find_commit.assert_called_once_with("/repo", 2015, 4, 1)
        write_last.assert_not_called()

    def test_existing_solution_creates_already_done_review_and_writes_last(self):
        responses = [
            [{"id": "reviewer-id", "name": "Solution Reviewer"}, {"id": "cto-id", "name": "CTO"}],
            {"id": "issue-1", "status": "done"},
            {"status": "done"},
        ]
        opener, seen = self.opener_for(responses)
        find_commit = Mock(return_value="a" * 40)
        write_last = Mock()
        with patch.dict(os.environ, self.env(), clear=True), \
                patch.object(wrapper.urllib.request, "build_opener", return_value=opener):
            issue_id = wrapper.reconcile([2015, 4, 1], "/repo", find_commit=find_commit, write_last=write_last)
        self.assertEqual(issue_id, "issue-1")
        self.assertEqual([r.method for r in seen], ["GET", "POST", "PATCH"])
        created = json.loads(seen[1].data)
        self.assertEqual(created["assigneeAgentId"], "reviewer-id")
        self.assertEqual(created["status"], "done")
        self.assertEqual(created["title"], "AoC 2015 Day04 part1: review")
        patched = json.loads(seen[2].data)
        self.assertNotIn("status", patched)
        self.assertIn("aoc-review-result", patched["comment"])
        self.assertIn("a" * 40, patched["comment"])
        result = json.loads(patched["comment"].split("```aoc-review-result\n")[1].split("\n```")[0])
        self.assertEqual(result["provenance"],
                         {"status": "reconciled", "verifiedBy": "aoc_site_status", "siteConfirmed": True})
        write_last.assert_called_once_with("/repo", (2015, 4, 1))

    def test_missing_reviewer_agent_fails_closed(self):
        responses = [[{"id": "cto-id", "name": "CTO"}]]
        opener, seen = self.opener_for(responses)
        find_commit = Mock(return_value="a" * 40)
        write_last = Mock()
        with patch.dict(os.environ, self.env(), clear=True), \
                patch.object(wrapper.urllib.request, "build_opener", return_value=opener):
            with self.assertRaises(ValueError):
                wrapper.reconcile([2015, 4, 1], "/repo", find_commit=find_commit, write_last=write_last)
        write_last.assert_not_called()


class WriteLastPartTest(unittest.TestCase):
    def test_writes_commits_and_pushes(self):
        import tempfile
        calls = []
        def fake_git(repo, *args):
            calls.append((repo, args))
            return ""
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(wrapper, "git", fake_git):
            wrapper.write_last_part(directory, (2015, 4, 2))
            content = Path(directory, "LAST.md").read_text()
        self.assertIn('"year": 2015', content)
        self.assertIn('"day": 4', content)
        self.assertIn('"part": 2', content)
        self.assertEqual([args[0] for _, args in calls], ["add", "commit", "push"])


class SyncRepoTest(unittest.TestCase):
    def test_fetches_pushes_then_fast_forwards_main(self):
        calls = []
        def fake_git(repo, *args):
            calls.append((repo, args))
            return ""
        with patch.object(wrapper, "git", fake_git):
            wrapper.sync_repo("/repo")
        self.assertEqual(calls, [
            ("/repo", ("fetch", "origin", "main")),
            ("/repo", ("push", "origin", "HEAD:main")),
            ("/repo", ("fetch", "origin", "main")),
            ("/repo", ("merge", "--ff-only", "origin/main")),
        ])

    def test_push_resolves_locally_committed_but_unpushed_work(self):
        """A staged checkout with unpushed Reviewer commits: push succeeds
        (local is a strict extension of origin), so the merge that follows
        is a trivial no-op fast-forward rather than a failure."""
        calls = []
        def fake_git(repo, *args):
            calls.append(args)
            return ""
        with patch.object(wrapper, "git", fake_git):
            wrapper.sync_repo("/repo")
        self.assertIn(("push", "origin", "HEAD:main"), calls)
        self.assertIn(("merge", "--ff-only", "origin/main"), calls)

    def test_rejected_push_does_not_block_the_fallback_merge_attempt(self):
        """Genuine divergence: push is rejected and swallowed; the merge
        still runs and raises its own informative error."""
        def fake_git(repo, *args):
            if args[0] == "push":
                raise RuntimeError("git push exited 1: rejected")
            if args[0] == "merge":
                raise RuntimeError("git merge exited 128: diverged")
            return ""
        with patch.object(wrapper, "git", fake_git):
            with self.assertRaisesRegex(RuntimeError, "diverged"):
                wrapper.sync_repo("/repo")


class SiteCompleteTest(unittest.TestCase):
    def test_delegates_to_is_part_complete_with_session(self):
        with patch.object(wrapper, "is_part_complete", return_value=True) as is_complete, \
                patch.dict(os.environ, {"AOC_SESSION": "token"}, clear=True):
            self.assertTrue(wrapper.site_complete([2015, 4, 1]))
        is_complete.assert_called_once_with(2015, 4, 1, "token")


if __name__ == "__main__":
    unittest.main()
