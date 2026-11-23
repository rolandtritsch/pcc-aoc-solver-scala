import copy
import importlib.util
import json
import tempfile
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "operators"), str(ROOT / "skills/aoc-runtime/scripts")]
from common import Blocked, read_json, write_json, digest
from company import NAMES, bind, quiesce, verify
from lifecycle import activate, assert_previous_owner, resume_ready
from infrastructure import Infrastructure
from package import build, validate
import aoc


class CompanyApi:
    base = "https://paperclip.example"

    def __init__(self):
        self.calls = []
        self.agents = [{"id": key, "name": name, "status": "paused"} for key, name in NAMES.items()]
        self.routine = {"id": "daily", "status": "paused", "triggers": [
            {"id": "trigger", "enabled": False, "cronExpression": "0 6 * * *", "timezone": "UTC"}]}
        self.configs = {key: {"configurationRevision": "revision", "defaultEnvironmentId": "old",
            "runtimeConfig": {"heartbeat": {"enabled": False}}, "adapterConfig": {
                "instructionsFilePath": f"/paperclip/instructions/{key}/AGENTS.md", "env": {
                    "GH_TOKEN": {"type": "secret_ref", "secretId": "github"},
                    "AOC_SESSION": {"type": "secret_ref", "secretId": "aoc"},
                    "AOC_PAPERCLIP_API_KEY": {"type": "secret_ref", "secretId": key},
                    "OPENROUTER_API_KEY": {"type": "secret_ref", "secretId": "model"},
                    "PRESERVE": {"type": "plain", "value": "***REDACTED***"}}}} for key in NAMES}

    def request(self, method, path, body=None):
        self.calls.append((method, path, copy.deepcopy(body)))
        if path == "/companies/company":
            return {"id": "company"}
        if path == "/companies/company/agents":
            return self.agents
        if path == "/companies/company/live-runs":
            return []
        if path == "/companies/company/routines":
            return [self.routine]
        if path == "/routines/daily":
            if method == "PATCH":
                self.routine.update(body)
            return copy.deepcopy(self.routine)
        if path == "/routine-triggers/trigger":
            self.routine["triggers"][0].update(body)
            return self.routine["triggers"][0]
        if path.startswith("/agents/"):
            key = path.split("/")[2]
            if method == "GET" and path == "/agents/" + key:
                return copy.deepcopy(next(a for a in self.agents if a["id"] == key))
            if path.endswith("/instructions-bundle"):
                return {"resolvedEntryPath": self.configs[key]["adapterConfig"]["instructionsFilePath"]}
            if path.endswith("/pause"):
                next(a for a in self.agents if a["id"] == key)["status"] = "paused"
                return {}
            if path.endswith("/resume"):
                next(a for a in self.agents if a["id"] == key)["status"] = "idle"
                return {}
            if method == "PATCH":
                self.configs[key].update(body)
            return copy.deepcopy(self.configs[key])
        raise AssertionError((method, path))


class OperatorTests(unittest.TestCase):
    def test_resume_waits_for_real_readiness_before_returning(self):
        api = Mock()
        api.request.side_effect = [{"status": "paused"},
            {"status": "paused", "lifecycleState": "resuming"},
            {"status": "idle", "lifecycleState": "ready"}]
        with patch("lifecycle.time.sleep") as sleep:
            resume_ready(api, "cto")
        sleep.assert_called_once_with(2)
        self.assertEqual(api.request.call_args.args, ("GET", "/agents/cto"))

    def test_recovery_verification_cannot_pass_before_apply(self):
        infra = Infrastructure(ROOT, "test")
        with self.assertRaises(Blocked):
            infra.verify_recovery({"scope": "runtime-efs"}, {})

    def test_storage_replacement_requires_changed_physical_identity(self):
        infra = Infrastructure(ROOT, "test")
        plan = {"scope": "runtime-efs", "outputs": {"aocRuntimeFilesystem": "old"}}
        with patch.object(infra, "outputs", return_value={"aocRuntimeFilesystem": "old"}):
            with self.assertRaises(Blocked):
                infra.verify_recovery(plan, {"deploy": True})
        with patch.object(infra, "outputs", return_value={"aocRuntimeFilesystem": "new"}), patch.object(infra, "wait", return_value={"rollout": "COMPLETED"}):
            result = infra.verify_recovery(plan, {"deploy": True})
            self.assertFalse(result["companyReady"])

    def test_stopped_controller_does_not_pass_database_recovery(self):
        infra = Infrastructure(ROOT, "test")
        plan = {"scope": "database", "outputs": {"rdsEndpoint": "old"}}
        with patch.object(infra, "outputs", return_value={"rdsEndpoint": "new"}), patch.object(infra, "aws", return_value={"services": [{"desiredCount": 0}]}):
            with self.assertRaises(Blocked):
                infra.verify_recovery(plan, {"deploy": True})

    def test_missing_previous_owner_needs_same_instance_reset_evidence(self):
        api = CompanyApi()
        with patch("lifecycle.assert_quiet", side_effect=Blocked("Paperclip GET /companies/old: HTTP 404")):
            with self.assertRaises(Blocked):
                assert_previous_owner(api, {"company": "old"})
            with tempfile.TemporaryDirectory() as root:
                path = Path(root) / "reset.json"
                plan = {"scope": "database", "affectedCompanies": [{"id": "old"}], "outputs": {"dnsRecord": "paperclip.example"}}
                write_json(path, {"action": "recover", "plan": plan, "planHash": digest(plan), "steps": {"deploy": True}})
                assert_previous_owner(api, {"company": "old"}, path)
                api.base = "https://another.example"
                with self.assertRaises(Blocked):
                    assert_previous_owner(api, {"company": "old"}, path)

    def test_bind_preserves_secret_refs_and_redacted_env(self):
        api = CompanyApi()
        bind(api, "company", "environment", "generation", "release", "account")
        for key, config in api.configs.items():
            env = config["adapterConfig"]["env"]
            self.assertEqual(env["GH_TOKEN"]["secretId"], "github")
            self.assertEqual(env["PRESERVE"]["value"], "***REDACTED***")
            self.assertEqual(config["defaultEnvironmentId"], "environment")
            self.assertEqual(env["AOC_RELEASE"]["value"], "release")
            self.assertEqual(config["adapterConfig"]["cwd"], f"/paperclip/instructions/{key}")
        self.assertNotIn("AOC_SESSION", api.configs["problem-solver"]["adapterConfig"]["env"])

    def test_quiesce_disables_schedules_before_pausing(self):
        api = CompanyApi()
        api.routine["status"] = "active"
        api.routine["triggers"][0]["enabled"] = True
        api.agents[0]["status"] = "idle"
        quiesce(api, "company")
        writes = [path for method, path, body in api.calls if method != "GET"]
        self.assertEqual(writes[0], "/routine-triggers/trigger")
        self.assertEqual(api.agents[0]["status"], "paused")

    def test_missing_bindings_block_activation(self):
        api = CompanyApi()
        with self.assertRaises(Blocked):
            activate(api, "company", {"releaseDelivery": True})
        self.assertFalse(any(path.endswith("/resume") for _, path, _ in api.calls))

    def test_activation_requires_complete_qualification(self):
        api = CompanyApi()
        bind(api, "company", "environment", "generation", "release", "account")
        with self.assertRaises(Blocked):
            activate(api, "company", {})
        result = activate(api, "company", {key: "evidence" for key in (
            "releaseDelivery", "templateTests", "gitAuthorization", "imageDigest", "sshHostKey", "account")})
        self.assertEqual(result["schedule"], "active")

    def test_reviewer_or_missing_trigger_blocks_readiness(self):
        api = CompanyApi()
        bind(api, "company", "environment", "generation", "release", "account")
        api.agents.append({"id": "reviewer", "name": "Solution Reviewer", "status": "paused"})
        with self.assertRaises(Blocked):
            verify(api, "company")
        api.agents.pop()
        api.routine["triggers"] = []
        with self.assertRaises(Blocked):
            verify(api, "company")

    def test_operation_record_rejects_plan_tampering(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "operation.json"
            args = aoc.parser().parse_args(["recover", "plan", "--record", str(path)])
            record = aoc.load_or_create(args, {"scope": "runtime-efs"})
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            record["plan"]["scope"] = "database"
            path.write_text(json.dumps(record))
            args.phase = "apply"
            with self.assertRaises(Blocked):
                aoc.load_or_create(args, {})


if __name__ == "__main__":
    unittest.main()
