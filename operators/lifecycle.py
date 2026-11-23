"""Explicit key/environment setup and verified activation/cutover helpers."""
from urllib.parse import quote
import time

from common import Blocked, digest, read_json
from api import Api
from company import assert_quiet, inventory, verify


def resume_ready(api, agent, timeout=180):
    api.request("POST", f"/agents/{agent}/resume", {})
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        row = api.request("GET", f"/agents/{agent}")
        if row["status"] == "idle" and row.get("lifecycleState", "ready") == "ready":
            return
        if row.get("lifecycleError"):
            raise Blocked("Agent resume failed; inspect lifecycle state before retrying")
        time.sleep(2)
    raise Blocked("Agent is not ready after resume; no qualification task was queued")


def credentials(api, company):
    state = assert_quiet(api, company)
    existing = api.request("GET", f"/companies/{company}/secrets")
    for agent in state["agents"]:
        if agent["status"] == "terminated":
            continue
        name = "aoc-agent-" + agent["id"]
        matches = [s for s in existing if s["name"] == name]
        if matches:
            secret = matches[0]
        else:
            key = api.request("POST", f"/agents/{agent['id']}/keys", {"name": name})
            try:
                identity = Api(api.base, key["token"]).request("GET", "/agents/me")
                if identity["id"] != agent["id"] or identity["companyId"] != company:
                    raise Blocked("New standing key identity mismatch")
                secret = api.request("POST", f"/companies/{company}/secrets", {
                    "name": name, "provider": "local_encrypted", "value": key["token"]})
            except Exception:
                api.request("DELETE", f"/agents/{agent['id']}/keys/{key['id']}")
                raise
        config = api.request("GET", f"/agents/{agent['id']}/configuration")
        adapter = config["adapterConfig"]
        adapter.setdefault("env", {})["AOC_PAPERCLIP_API_KEY"] = {
            "type": "secret_ref", "secretId": secret["id"], "version": "latest"}
        api.request("PATCH", "/agents/" + agent["id"], {
            "expectedConfigurationRevision": config["configurationRevision"], "adapterConfig": adapter})
    return {"company": company, "standingKeys": "bound separately for each role"}


def environment(api, company, host, private_key, known_hosts):
    assert_quiet(api, company)
    settings = api.request("GET", "/instance/settings/experimental")
    if not settings.get("enableEnvironments"):
        api.request("PATCH", "/instance/settings/experimental", {"enableEnvironments": True})
    name = "AoC Scala " + company
    rows = api.request("GET", f"/companies/{company}/environments")
    matches = [e for e in rows if e["name"] == name]
    config = {"host": host, "port": 22, "username": "paperclip",
        "remoteWorkspacePath": "/workspaces/agents", "strictHostKeyChecking": True,
        "knownHosts": known_hosts, "useHostAuth": True}
    if matches:
        row = api.request("GET", "/environments/" + matches[0]["id"])
        config["privateKeySecretRef"] = row["config"]["privateKeySecretRef"]
        row = api.request("PATCH", f"/environments/{row['id']}?companyId={company}", {"config": config})
    else:
        config["privateKey"] = private_key
        row = api.request("POST", f"/companies/{company}/environments", {
            "name": name, "driver": "ssh", "config": config})
    probe = api.request("POST", f"/environments/{row['id']}/probe?companyId={company}", {})
    if not probe.get("ok"):
        raise Blocked("SSH environment probe failed")
    return {"environment": row["id"], "probe": "passed"}


def archive(api, company):
    state = assert_quiet(api, company)
    for agent in state["agents"]:
        keys = api.request("GET", f"/agents/{agent['id']}/keys")
        for key in keys:
            if not key.get("revokedAt"):
                api.request("DELETE", f"/agents/{agent['id']}/keys/{key['id']}")
    api.request("PATCH", "/companies/" + company, {"status": "archived"})
    saved = api.request("GET", "/companies/" + company)
    if saved["status"] != "archived":
        raise Blocked("Company archive did not persist")
    return {"company": company, "status": "archived"}


def activate(api, company, qualification):
    verify(api, company)
    required = ("releaseDelivery", "templateTests", "gitAuthorization", "imageDigest", "sshHostKey", "account")
    if any(not qualification.get(key) for key in required):
        raise Blocked("Activation requires actual runtime qualification: " + ", ".join(required))
    state = inventory(api, company)
    for agent in state["agents"]:
        if agent["status"] != "terminated":
            resume_ready(api, agent["id"])
    routine = api.request("GET", "/routines/" + next(r["id"] for r in state["routines"] if r["status"] != "archived"))
    api.request("PATCH", "/routines/" + routine["id"], {"status": "active"})
    api.request("PATCH", "/routine-triggers/" + routine["triggers"][0]["id"], {"enabled": True})
    saved = api.request("GET", "/routines/" + routine["id"])
    if saved["status"] != "active" or not saved["triggers"][0]["enabled"]:
        raise Blocked("Schedule activation readback failed")
    return {"company": company, "schedule": "active", "trigger": saved["triggers"][0]["id"]}


def assert_previous_owner(api, previous, record_path=None):
    try:
        assert_quiet(api, previous["company"])
        return
    except Blocked as error:
        if not str(error).endswith("HTTP 404"):
            raise
    record = read_json(record_path) if record_path else None
    if (not record or record.get("action") != "recover"
            or digest(record["plan"]) != record["planHash"]
            or record["plan"].get("scope") not in ("database", "instance")
            or not record.get("steps", {}).get("deploy")
            or previous["company"] not in [c["id"] for c in record["plan"]["affectedCompanies"]]):
        raise Blocked("Previous owner is missing; provide the completed approved database-reset --record")
    from urllib.parse import urlparse
    if urlparse(api.base).hostname != record["plan"]["outputs"].get("dnsRecord", "").rstrip("."):
        raise Blocked("Database-reset evidence belongs to another instance")
