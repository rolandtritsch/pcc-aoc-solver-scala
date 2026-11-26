import copy
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "operators"), str(ROOT / "skills/aoc-runtime/scripts")]
from common import Blocked
import replace_agent as ra


class FakeApi:
    def __init__(self, agents, configs, issues=None):
        self.agents = agents
        self.configs = configs
        self.issues = issues or []
        self.calls = []

    def request(self, method, path, body=None):
        self.calls.append((method, path, copy.deepcopy(body)))
        if path.endswith("/agents") and method == "GET":
            return copy.deepcopy(self.agents)
        if path.startswith("/agents/") and path.endswith("/configuration"):
            key = path.split("/")[2]
            return copy.deepcopy(self.configs[key])
        if "/issues?status=" in path:
            return copy.deepcopy(self.issues)
        if path.startswith("/issues/") and method == "PATCH":
            for row in self.issues:
                if row["id"] == path.split("/")[2]:
                    row.update(body)
                    return copy.deepcopy(row)
        if path.endswith("/terminate"):
            for agent in self.agents:
                if path == f"/agents/{agent['id']}/terminate":
                    agent["status"] = "terminated"
            return {}
        raise AssertionError((method, path, body))


def agent(id_, name, status="paused"):
    return {"id": id_, "name": name, "status": status}


def bound_config(environment_id, generation="gen-1", account="acct-1"):
    # bind() writes the real generation/account into metadata.aoc. The
    # adapterConfig.env entries are what a real Paperclip GET actually
    # returns: every plain value comes back as the literal string
    # "***REDACTED***", regardless of content -- included here so a
    # resolver that (incorrectly) reads env instead of metadata would pick
    # up that placeholder instead of failing loudly.
    return {"defaultEnvironmentId": environment_id, "metadata": {"aoc": {
                "generation": generation, "account": account}},
            "adapterConfig": {"env": {
                "AOC_GENERATION": {"type": "plain", "value": "***REDACTED***"},
                "AOC_ACCOUNT": {"type": "plain", "value": "***REDACTED***"}}}}


class ResolveBindingTests(unittest.TestCase):
    def test_resolves_from_the_current_agents_own_metadata(self):
        api = FakeApi(
            agents=[agent("old-cto", "CTO")],
            configs={"old-cto": bound_config("env-1")},
        )
        old, binding = ra.resolve_binding(api, "company", "cto")
        self.assertEqual(old["id"], "old-cto")
        self.assertEqual(binding, {"generation": "gen-1", "environment": "env-1", "account": "acct-1"})

    def test_redacted_env_placeholder_is_never_mistaken_for_the_real_value(self):
        # Regression: resolve_binding() used to read AOC_GENERATION/
        # AOC_ACCOUNT from adapterConfig.env, which a real Paperclip GET
        # always redacts -- resolving to the literal string
        # "***REDACTED***" instead of the real value, which then 422s the
        # later bind PATCH ("A redacted value was changed or moved").
        api = FakeApi(
            agents=[agent("old-cto", "CTO")],
            configs={"old-cto": bound_config("env-1")},
        )
        _, binding = ra.resolve_binding(api, "company", "cto")
        self.assertNotIn("***REDACTED***", binding.values())

    def test_explicit_overrides_win_over_resolved_values(self):
        api = FakeApi(
            agents=[agent("old-cto", "CTO")],
            configs={"old-cto": bound_config("env-1")},
        )
        _, binding = ra.resolve_binding(api, "company", "cto", generation="gen-override")
        self.assertEqual(binding["generation"], "gen-override")
        self.assertEqual(binding["account"], "acct-1")

    def test_missing_binding_data_raises_rather_than_silently_redeploying_wrong(self):
        api = FakeApi(
            agents=[agent("old-cto", "CTO")],
            configs={"old-cto": {"defaultEnvironmentId": None, "metadata": None, "adapterConfig": {"env": {}}}},
        )
        with self.assertRaises(Blocked):
            ra.resolve_binding(api, "company", "cto")

    def test_terminated_agent_is_not_the_active_one(self):
        api = FakeApi(
            agents=[agent("old-cto", "CTO", status="terminated"), agent("new-cto", "CTO", status="paused")],
            configs={"new-cto": bound_config("env-1")},
        )
        old, _ = ra.resolve_binding(api, "company", "cto")
        self.assertEqual(old["id"], "new-cto")


class StaleAssignmentAndReassignTests(unittest.TestCase):
    def test_finds_only_tasks_assigned_to_the_given_agent(self):
        api = FakeApi(agents=[], configs={}, issues=[
            {"id": "t1", "assigneeAgentId": "old-cto"},
            {"id": "t2", "assigneeAgentId": "someone-else"},
            {"id": "t3", "assigneeAgentId": "old-cto"},
        ])
        self.assertEqual(sorted(ra.stale_assignments(api, "company", "old-cto")), ["t1", "t3"])

    def test_reassign_moves_every_stale_task_to_the_new_agent(self):
        api = FakeApi(agents=[], configs={}, issues=[
            {"id": "t1", "assigneeAgentId": "old-cto"},
            {"id": "t3", "assigneeAgentId": "old-cto"},
        ])
        ra.reassign(api, ["t1", "t3"], "new-cto")
        self.assertTrue(all(row["assigneeAgentId"] == "new-cto" for row in api.issues))

    def test_reassign_raises_on_a_failed_readback(self):
        class StubbornApi(FakeApi):
            def request(self, method, path, body=None):
                if method == "PATCH":
                    return {"assigneeAgentId": "still-old"}
                return super().request(method, path, body)
        api = StubbornApi(agents=[], configs={}, issues=[{"id": "t1", "assigneeAgentId": "old-cto"}])
        with self.assertRaises(Blocked):
            ra.reassign(api, ["t1"], "new-cto")


class ReplaceOrchestrationTests(unittest.TestCase):
    def test_replace_terminates_old_redeploys_and_reassigns_in_order(self):
        # active_agent() is called twice: once (as the old agent) before
        # termination, once (as the replacement) after the CLI-driven
        # redeploy -- simulate that by swapping the fake's roster between
        # the two run_cli-mocked calls.
        api = FakeApi(
            agents=[agent("old-cto", "CTO")],
            configs={"old-cto": bound_config("env-1")},
            issues=[{"id": "control-1", "assigneeAgentId": "old-cto"}],
        )

        def fake_run_cli(*args):
            if args[:2] == ("deploy", "apply"):
                api.agents.append(agent("new-cto", "CTO"))
            if args[0] == "bind" and args[1] == "verify":
                return {"roles": 4, "paused": True}
            return {}

        with patch("replace_agent.run_cli", side_effect=fake_run_cli):
            result = ra.replace(api, "company", "cto")

        self.assertEqual(result["oldAgentId"], "old-cto")
        self.assertEqual(result["newAgentId"], "new-cto")
        self.assertEqual(result["reassignedTasks"], ["control-1"])
        self.assertEqual(next(a for a in api.agents if a["id"] == "old-cto")["status"], "terminated")
        self.assertEqual(next(r for r in api.issues if r["id"] == "control-1")["assigneeAgentId"], "new-cto")
        self.assertEqual(result["binding"], {"generation": "gen-1", "environment": "env-1", "account": "acct-1"})


if __name__ == "__main__":
    unittest.main()
