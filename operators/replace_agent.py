"""Replace a stuck agent (e.g. one permanently stuck in lifecycleState
"pausing" -- see AGENTS.md and skills/deploy-aoc-company's troubleshooting
section) without losing its generation/environment/account binding or
orphaning the tasks it still owns.

Orchestrates the exact manual sequence worked out live on 2026-11-25/26 by
shelling out to the already-proven `operators/aoc.py` commands, rather than
reimplementing deploy/bind/credentials from scratch:

1. Resolve generation/environment/account from the CURRENT agent's own
   configuration *before* touching anything. This matters because
   `operators/aoc.py deploy`'s auto-detect reads the live agent list, which
   excludes terminated agents -- once the old agent is gone, there is
   nothing left to auto-detect from, and a careless redeploy silently
   falls back to all-plain env (no generation/release/account bound on any
   of the four roles) and a fresh random generation (breaking
   `repo.assert_owner()` for every future run).
2. Record every open task still assigned to the old agent -- a later
   `finish()` call from the replacement enforces exact assignee identity
   and raises "Task ownership mismatch" forever otherwise.
3. Terminate the old agent (status flips to "terminated" immediately; its
   background lifecycle cleanup may spin forever in "terminating" -- that
   does not block anything downstream).
4. Redeploy (`aoc.py deploy`), which creates the fresh replacement by name.
5. Rebind explicitly with the PRESERVED generation/environment/account
   (never the auto-detected one -- see point 1).
6. Mint the replacement's standing Paperclip API key (`aoc.py credentials`).
7. Reassign every task recorded in step 2 to the replacement's agent id.
8. Verify.

Usage:
    python3 operators/replace_agent.py --company <id> --role cto
    python3 operators/replace_agent.py --company <id> --role problem-solver \\
        --generation <id> --environment <id> --account <fingerprint>  # override auto-resolve

Always prints a final reminder: resume all four agents and re-enable the
routine/trigger yourself -- this script does not do either, since whether
they *should* be re-enabled is an operator decision, not an automatic one.
"""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "skills/aoc-runtime/scripts"))
from api import Api
from common import Blocked
from company import NAMES

ROOT = Path(__file__).resolve().parent.parent
AOC_PY = str(ROOT / "operators/aoc.py")


def active_agent(api, company, role):
    agents = api.request("GET", f"/companies/{company}/agents")
    name = NAMES[role]
    agent = next((a for a in agents if a["name"] == name and a["status"] != "terminated"), None)
    if not agent:
        raise Blocked(f"No active agent named {name!r} in {company}")
    return agent


def resolve_binding(api, company, role, generation=None, environment=None, account=None):
    agent = active_agent(api, company, role)
    config = api.request("GET", f"/agents/{agent['id']}/configuration")
    # bind() writes the real generation/account into metadata.aoc, not env:
    # every plain env value (regardless of content) comes back from a GET as
    # the literal string "***REDACTED***", so reading AOC_GENERATION/
    # AOC_ACCOUNT out of adapterConfig.env silently resolves to that literal
    # placeholder instead of the real value -- Paperclip's own redaction
    # guard then 422s the later bind PATCH ("A redacted value was changed or
    # moved") rather than let a bogus value through, but only after
    # replace() has already terminated the old agent.
    aoc_metadata = (config.get("metadata") or {}).get("aoc", {})
    resolved = {
        "generation": generation or aoc_metadata.get("generation"),
        "environment": environment or config.get("defaultEnvironmentId"),
        "account": account or aoc_metadata.get("account"),
    }
    if not all(resolved.values()):
        raise Blocked("Could not resolve generation/environment/account from the "
            "agent being replaced; pass --generation/--environment/--account explicitly")
    return agent, resolved


def stale_assignments(api, company, agent_id):
    rows = api.request("GET", f"/companies/{company}/issues"
        "?status=backlog,todo,in_progress,blocked,in_review&limit=1000")
    return [r["id"] for r in rows if r.get("assigneeAgentId") == agent_id]


def reassign(api, tasks, new_agent_id):
    for task in tasks:
        saved = api.request("PATCH", "/issues/" + task, {"assigneeAgentId": new_agent_id})
        if saved.get("assigneeAgentId") != new_agent_id:
            raise Blocked("Reassignment readback failed for " + task)


def run_cli(*args):
    result = subprocess.run([sys.executable, AOC_PY, *args], capture_output=True, text=True)
    if result.returncode != 0:
        raise Blocked(f"{' '.join(args)} failed: {result.stdout}{result.stderr}")
    return json.loads(result.stdout)


def replace(api, company, role, generation=None, environment=None, account=None):
    old, binding = resolve_binding(api, company, role, generation, environment, account)
    tasks = stale_assignments(api, company, old["id"])
    api.request("POST", f"/agents/{old['id']}/terminate", {})
    with tempfile.TemporaryDirectory() as tmp:
        record = str(Path(tmp) / "deploy-record.json")
        package_file = str(Path(tmp) / "release-package.json")
        run_cli("deploy", "plan", "--company", company, "--record", record)
        run_cli("deploy", "apply", "--company", company, "--record", record)
        run_cli("package", "--package", package_file)
        run_cli("bind", "apply", "--company", company,
            "--environment", binding["environment"], "--generation", binding["generation"],
            "--account", binding["account"], "--package", package_file)
        run_cli("credentials", "apply", "--company", company)
        new = active_agent(api, company, role)
        reassign(api, tasks, new["id"])
        verification = run_cli("bind", "verify", "--company", company,
            "--environment", binding["environment"], "--generation", binding["generation"],
            "--account", binding["account"], "--package", package_file)
    return {"oldAgentId": old["id"], "newAgentId": new["id"], "role": role,
        "reassignedTasks": tasks, "binding": binding, "verification": verification}


def main(argv):
    parser = argparse.ArgumentParser(description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--company", required=True)
    parser.add_argument("--role", required=True, choices=tuple(NAMES))
    parser.add_argument("--generation")
    parser.add_argument("--environment")
    parser.add_argument("--account")
    args = parser.parse_args(argv)
    api = Api.local()
    result = replace(api, args.company, args.role, args.generation, args.environment, args.account)
    print(json.dumps(result, indent=2))
    print("\nNext: resume all four agents and re-enable the routine/trigger "
        "yourself -- deploy's own quiesce() paused everything again.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
