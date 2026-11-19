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


def result(mode, code):
    def check():
        print(json.dumps({"mode": mode}))
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
               "PAPERCLIP_API_KEY":"test-key", "PAPERCLIP_RUN_ID":"run",
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
             "PAPERCLIP_API_KEY":"test-key","PAPERCLIP_RUN_ID":"run",
             "PAPERCLIP_COMPANY_ID":"company","PAPERCLIP_AGENT_ID":"cto"}
        response=Mock();response.__enter__=Mock(return_value=io.StringIO(json.dumps({"companyId":"other"})))
        response.__exit__=Mock(return_value=False)
        opener=Mock();opener.open.return_value=response
        with patch.dict(os.environ,env,clear=True),patch.object(wrapper.urllib.request,'build_opener',return_value=opener):
            with self.assertRaises(ValueError):wrapper.finish_occurrence({"mode":"wait"})
        self.assertEqual(opener.open.call_count,1)


if __name__ == "__main__":
    unittest.main()
