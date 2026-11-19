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


if __name__ == "__main__":
    unittest.main()
