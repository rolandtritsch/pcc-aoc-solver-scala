#!/usr/bin/env python3
"""Bind the company's paused agents to its prepared SSH execution environment."""
import argparse
import json
import os
from pathlib import Path
import urllib.request


class Client:
    def __init__(self):
        home = Path.home() / ".paperclip"
        context = json.loads((home / "context.json").read_text())
        profile = context["profiles"][context["currentProfile"]]
        self.base = os.environ.get("PAPERCLIP_API_URL", profile["apiBase"]).rstrip("/")
        auth = json.loads((home / "auth.json").read_text())
        self.token = os.environ.get("PAPERCLIP_API_KEY") or auth["credentials"][self.base]["token"]

    def request(self, path, method="GET", body=None):
        request = urllib.request.Request(
            self.base + "/api" + path, method=method,
            data=None if body is None else json.dumps(body).encode(),
            headers={"Authorization": "Bearer " + self.token, "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=120) as response:
            return json.load(response)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--company-id", required=True)
    parser.add_argument("--host", required=True)
    parser.add_argument("--private-key-file", type=Path, required=True)
    parser.add_argument("--known-hosts-file", type=Path, required=True)
    args = parser.parse_args()
    client = Client()
    prefix = "/companies/" + args.company_id
    agents = client.request(prefix + "/agents")
    if not agents or any(agent["status"] != "paused" for agent in agents):
        raise SystemExit("Pause all company agents before migrating their environment")
    expected_names = {"CTO", "Problem Gatherer", "Problem Solver", "Problem Submitter",
                      "Solution Reviewer"}
    if {agent["name"] for agent in agents} != expected_names:
        raise SystemExit("Unexpected company agent roster")
    settings = client.request("/instance/settings/experimental")
    if not settings.get("enableEnvironments"):
        client.request("/instance/settings/experimental", "PATCH", {"enableEnvironments": True})
    matches = [env for env in client.request(prefix + "/environments") if env["name"] == "AoC Scala runtime"]
    config = {
        "host": args.host, "port": 22, "username": "paperclip",
        "remoteWorkspacePath": "/workspaces/agents", "strictHostKeyChecking": True,
        "knownHosts": args.known_hosts_file.read_text().strip(), "useHostAuth": True,
    }
    if matches:
        environment = client.request("/environments/" + matches[0]["id"])
        config["privateKeySecretRef"] = environment["config"]["privateKeySecretRef"]
        environment = client.request("/environments/" + environment["id"] + "?companyId=" + args.company_id,
                                     "PATCH", {"config": config})
    else:
        config["privateKey"] = args.private_key_file.read_text()
        environment = client.request(prefix + "/environments", "POST", {
            "name": "AoC Scala runtime", "driver": "ssh", "config": config,
            "description": "Dedicated Fargate runtime with a pinned Java/sbt/OpenCode image and separate storage.",
        })
    environment_id = environment["id"]
    probe = client.request("/environments/" + environment_id + "/probe?companyId=" + args.company_id, "POST", {})
    if not probe.get("ok"):
        raise SystemExit("SSH environment probe failed; agents were not changed")
    for agent in agents:
        path = "/agents/" + agent["id"]
        current = client.request(path + "/configuration")
        adapter = current["adapterConfig"]
        adapter["cwd"] = "/paperclip/workspaces/scala3-aoc"  # Controller-side source staging.
        adapter["command"] = {"CTO": "/usr/local/bin/aoc-cto"}.get(
            agent["name"], "/usr/local/bin/aoc-opencode")
        env = adapter.setdefault("env", {})
        values = {
            "HOME": "/home/paperclip", "PATH": "/opt/java/bin:/opt/sbt/bin:/usr/local/bin:/usr/bin:/bin",
            "JAVA_HOME": "/opt/java", "AOC_REPO_DIR": ".",
            "AOC_COMPANY_PACKAGE_DIR": "/opt/aoc-company", "AOC_PAPERCLIP_API_URL": client.base,
        }
        env.update({key: {"type": "plain", "value": value} for key, value in values.items()})
        client.request(path, "PATCH", {
            "expectedConfigurationRevision": current["configurationRevision"],
            "defaultEnvironmentId": environment_id, "runner": "legacy", "adapterConfig": adapter,
        })
        saved = client.request(path + "/configuration")
        if saved.get("defaultEnvironmentId") != environment_id or saved["adapterConfig"]["command"] != adapter["command"]:
            raise SystemExit("Agent environment readback failed")
        print("Configured " + agent["name"])
    print("Environment " + environment_id + " verified; all agents remain paused")


if __name__ == "__main__":
    main()
