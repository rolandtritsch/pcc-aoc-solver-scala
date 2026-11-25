"""Board-only maintenance and declarative runtime bindings."""
import json
from pathlib import Path

from common import Blocked
from package import AGENTS

NAMES = dict(zip(AGENTS, ("CTO", "Problem Gatherer", "Problem Solver", "Problem Submitter")))


def inventory(api, company):
    return {"company": api.request("GET", "/companies/" + company),
        "agents": api.request("GET", f"/companies/{company}/agents"),
        "routines": api.request("GET", f"/companies/{company}/routines"),
        "liveRuns": api.request("GET", f"/companies/{company}/live-runs")}


def quiesce(api, company):
    state = inventory(api, company)
    for routine in state["routines"]:
        for trigger in routine.get("triggers", []):
            api.request("PATCH", "/routine-triggers/" + trigger["id"], {"enabled": False})
        if routine["status"] != "archived":
            api.request("PATCH", "/routines/" + routine["id"], {"status": "paused"})
    for agent in state["agents"]:
        if agent["status"] not in ("paused", "terminated"):
            api.request("POST", f"/agents/{agent['id']}/pause", {})
    assert_quiet(api, company)


def assert_quiet(api, company):
    state = inventory(api, company)
    if state["liveRuns"]:
        raise Blocked("Live runs remain; wait for drain before retrying")
    if any(a["status"] not in ("paused", "terminated") for a in state["agents"]):
        raise Blocked("All agents must be paused")
    if any(r["status"] == "active" or any(t["enabled"] for t in r.get("triggers", []))
           for r in state["routines"]):
        raise Blocked("Disable schedules as well as pausing agents")
    return state


def bind(api, company, environment, generation, release, account):
    state = assert_quiet(api, company)
    active = [a for a in state["agents"] if a["status"] != "terminated"]
    if {a["name"] for a in active} != set(NAMES.values()) or len(active) != 4:
        raise Blocked("Expected exactly four intended roles; retire obsolete agents first")
    env_row = api.request("GET", "/environments/" + environment)
    # adapterConfig.cwd is the agent's execution working directory. For a
    # remote (ssh) environment that directory must exist ON THE REMOTE HOST,
    # never the Paperclip server's own local instructions-bundle path
    # (/paperclip/instances/...) -- the paperclip user has no permission to
    # create that path remotely, and the agent's lifecycle "host" verification
    # step fails with an unlogged, uncategorized mkdir error (surfaces only as
    # a generic "unclassified" failure; confirmed via the raw
    # POST /companies/:id/adapters/:type/test-environment API, which is the
    # only way to see the real stack trace -- the lifecycle worker never logs
    # provider error text by design). Root-caused 2026-11-25.
    remote_cwd = (env_row.get("config") or {}).get("remoteWorkspacePath") if env_row.get("driver") == "ssh" else None
    shared = {}
    for agent in active:
        config = api.request("GET", "/agents/" + agent["id"] + "/configuration")
        for key, value in config["adapterConfig"].get("env", {}).items():
            if key in ("GH_TOKEN", "AOC_SESSION", "OPENROUTER_API_KEY") and value.get("type") == "secret_ref":
                shared.setdefault(key, value)
    for agent in active:
        role = next(key for key, value in NAMES.items() if value == agent["name"])
        path = "/agents/" + agent["id"]
        config = api.request("GET", path + "/configuration")
        adapter = config["adapterConfig"]
        bundle = api.request("GET", path + "/instructions-bundle")
        instructions = bundle.get("resolvedEntryPath") or adapter.get("instructionsFilePath")
        if not instructions or not instructions.startswith("/"):
            raise Blocked("Import must materialize a managed instruction bundle first")
        adapter["cwd"] = remote_cwd or str(Path(instructions).parent)
        adapter["instructionsFilePath"] = instructions
        adapter["command"] = "/usr/local/bin/aoc-cto" if role == "cto" else "/usr/local/bin/aoc-opencode"
        env = adapter.setdefault("env", {})
        for key in ("GH_TOKEN", "AOC_SESSION"):
            if not env.get(key) and key in shared:
                env[key] = shared[key]
        if role == "problem-solver":
            env.pop("AOC_SESSION", None)
        # PATCH replaces env; preserve all existing bindings and redacted values.
        values = {"AOC_ROLE": role, "AOC_GENERATION": generation, "AOC_RELEASE": release,
            "AOC_ACCOUNT": account, "AOC_PAPERCLIP_API_URL": api.base,
            "AOC_WORKSPACE_ROOT": "/workspaces/aoc", "JAVA_HOME": "/opt/java"}
        for key in ("AOC_REPO_DIR", "AOC_COMPANY_PACKAGE_DIR", "AOC_CYCLE_STARTED_AT"):
            env.pop(key, None)
        env.update({k: {"type": "plain", "value": v} for k, v in values.items()})
        api.request("PATCH", path, {"expectedConfigurationRevision": config["configurationRevision"],
            "defaultEnvironmentId": environment, "runner": "legacy", "adapterConfig": adapter,
            "metadata": {**(config.get("metadata") or {}), "aoc": {
                "generation": generation, "release": release, "account": account}}})
        saved = api.request("GET", path + "/configuration")
        if saved.get("defaultEnvironmentId") != environment or saved["adapterConfig"]["cwd"] != adapter["cwd"]:
            raise Blocked("Agent binding readback failed")


def verify(api, company):
    state = assert_quiet(api, company)
    agents = [a for a in state["agents"] if a["status"] != "terminated"]
    if len(agents) != 4 or {a["name"] for a in agents} != set(NAMES.values()):
        raise Blocked("Imported roster mismatch")
    routines = [r for r in state["routines"] if r["status"] != "archived"]
    if len(routines) != 1:
        raise Blocked("Expected exactly one routine")
    routine = api.request("GET", "/routines/" + routines[0]["id"])
    triggers = routine.get("triggers", [])
    if len(triggers) != 1 or triggers[0].get("cronExpression") != "0 6 * * *" or triggers[0].get("timezone") != "UTC":
        raise Blocked("Daily trigger is missing or malformed")
    for agent in agents:
        config = api.request("GET", "/agents/" + agent["id"] + "/configuration")
        if not config.get("defaultEnvironmentId"):
            raise Blocked("Agent environment not bound")
        if config.get("runtimeConfig", {}).get("heartbeat", {}).get("enabled"):
            raise Blocked("Interval heartbeat must be disabled")
        env = config["adapterConfig"].get("env", {})
        for key in ("AOC_PAPERCLIP_API_KEY", "GH_TOKEN", "AOC_RELEASE", "AOC_ACCOUNT"):
            if not env.get(key):
                raise Blocked("Missing required agent binding: " + key)
        if agent["name"] != "Problem Solver" and not env.get("AOC_SESSION"):
            raise Blocked("Missing site account credential")
        if agent["name"] == "Problem Solver" and not env.get("OPENROUTER_API_KEY"):
            raise Blocked("Solver model credential is not bound")
    return {"company": company, "roles": 4, "schedule": "0 6 * * * UTC", "paused": True,
            "runtimeQualification": "required: probe, release hashes, authenticated Git, template tests"}


def sync_instructions(api, company, files):
    agents = api.request("GET", f"/companies/{company}/agents")
    by_name = {a["name"]: a for a in agents}
    for slug, name in NAMES.items():
        path = f"/agents/{by_name[name]['id']}/instructions-bundle/file"
        desired = files[f"agents/{slug}/AGENTS.md"].split("\n---\n", 1)[1].lstrip()
        current = api.request("GET", path + "?path=AGENTS.md")
        if current["content"] != desired:
            api.request("PUT", path, {"path": "AGENTS.md", "content": desired,
                "baseRevisionId": (current.get("revision") or {}).get("id"),
                "clearLegacyPromptTemplate": True})
        saved = api.request("GET", path + "?path=AGENTS.md")
        if saved["content"] != desired:
            raise Blocked("Canonical agent instruction readback failed")
    return {"instructions": "canonical revisions verified for four roles"}


def sync_routine(api, company, files):
    rows = api.request("GET", f"/companies/{company}/routines")
    candidates = sorted([r for r in rows if r["title"] == "Daily next-day selection" and r["status"] != "archived"],
                        key=lambda r: r.get("createdAt", r["id"]))
    agents = api.request("GET", f"/companies/{company}/agents")
    cto = next(a for a in agents if a["name"] == "CTO")
    desired = {"title": "Daily next-day selection", "status": "paused", "assigneeAgentId": cto["id"],
        "description": files["tasks/daily-selection/TASK.md"].split("\n---\n", 1)[1].lstrip(),
        "concurrencyPolicy": "coalesce_if_active", "catchUpPolicy": "skip_missed"}
    if candidates:
        routine = api.request("PATCH", "/routines/" + candidates[0]["id"], desired)
        for duplicate in candidates[1:]:
            for trigger in duplicate.get("triggers", []):
                api.request("PATCH", "/routine-triggers/" + trigger["id"], {"enabled": False})
            api.request("PATCH", "/routines/" + duplicate["id"], {"status": "archived"})
    else:
        routine = api.request("POST", f"/companies/{company}/routines", desired)
    routine = api.request("GET", "/routines/" + routine["id"])
    triggers = routine.get("triggers", [])
    desired_trigger = {"enabled": False, "cronExpression": "0 6 * * *", "timezone": "UTC"}
    if len(triggers) > 1:
        raise Blocked("Multiple triggers on canonical routine; disable/reconcile explicitly")
    if triggers:
        api.request("PATCH", "/routine-triggers/" + triggers[0]["id"], desired_trigger)
    else:
        api.request("POST", "/routines/" + routine["id"] + "/triggers", {"kind": "schedule", **desired_trigger})
    return {"routine": routine["id"], "duplicatesArchived": len(candidates[1:])}
