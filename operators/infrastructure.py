"""Explicit Pulumi/AWS operations; no automatic reset escalation."""
import json
import os
from pathlib import Path
import subprocess
import shlex
import time
import urllib.request

from common import Blocked, command


class Infrastructure:
    def __init__(self, root, stack):
        self.root, self.stack = Path(root), stack
        self.env = {**os.environ, "AWS_PROFILE": "roland"}

    def pulumi(self, *args):
        result = subprocess.run(["pulumi", *args, "--stack", self.stack], cwd=self.root,
                                env=self.env, text=True, capture_output=True)
        if result.returncode:
            raise Blocked("Pulumi failed; inspect local diagnostics before retrying")
        return result.stdout

    def aws(self, *args):
        raw = command(self.root, ["aws", "--profile", "roland", "--region", "eu-west-1", *args])
        return json.loads(raw) if raw else None

    def outputs(self):
        return json.loads(self.pulumi("stack", "output", "--json"))

    def quarantine(self, path, generation):
        tasks = self.aws("ecs", "list-tasks", "--cluster", "paperclip", "--service-name", "paperclip-aoc-runtime")["taskArns"]
        if len(tasks) != 1:
            raise Blocked("Workspace recovery requires exactly one runtime task")
        code = '''import fcntl,json,pathlib
root=pathlib.Path('/workspaces/aoc')
path=pathlib.Path(PATH).resolve()
allowed=root/'checkouts'
if path==allowed or not path.is_relative_to(allowed): raise RuntimeError('Invalid quarantine path')
with open(root/'.mutation.lock','a') as lock:
 fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
 target=path.with_name(path.name+'.quarantine-'+GENERATION)
 if path.exists():
  if target.exists(): raise RuntimeError('Quarantine destination exists')
  path.rename(target)
 elif not target.exists(): raise RuntimeError('Workspace not found')
 print('AOC_RECOVERY '+json.dumps({'quarantined':str(target)}))
'''.replace("PATH", repr(path)).replace("GENERATION", repr(generation))
        raw = command(self.root, ["aws", "--profile", "roland", "--region", "eu-west-1", "ecs", "execute-command",
            "--cluster", "paperclip", "--task", tasks[0], "--container", "aoc-runtime", "--interactive",
            "--command", "python3 -c " + shlex.quote(code)], 120)
        for line in raw.splitlines():
            if line.startswith("AOC_RECOVERY "):
                return json.loads(line[len("AOC_RECOVERY "):])
        raise Blocked("Recovery response lost; inspect source/quarantine before retrying")

    def wait(self, service, expected=None, timeout=900):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            result = self.aws("ecs", "describe-services", "--cluster", "paperclip", "--services", service)
            if result.get("failures") or len(result.get("services", [])) != 1:
                raise Blocked("ECS service not found")
            row = result["services"][0]
            primary = next(d for d in row["deployments"] if d["status"] == "PRIMARY")
            if primary.get("rolloutState") == "FAILED":
                raise Blocked("ECS rollout failed")
            if (primary.get("rolloutState") == "COMPLETED" and row["runningCount"] == row["desiredCount"]
                    and row["pendingCount"] == 0 and len(row["deployments"]) == 1):
                tasks = self.aws("ecs", "list-tasks", "--cluster", "paperclip", "--service-name", service)["taskArns"]
                details = self.aws("ecs", "describe-tasks", "--cluster", "paperclip", "--tasks", *tasks)
                if expected and any(c.get("imageDigest") != expected.split("@")[-1]
                                    for t in details["tasks"] for c in t["containers"]):
                    raise Blocked("Running task is not the requested image digest")
                return {"service": service, "rollout": "COMPLETED", "tasks": tasks}
            time.sleep(10)
        raise Blocked("ECS rollout timeout; operation remains resumable")

    def health(self):
        outputs = self.outputs()
        controller = self.wait(outputs["serviceName"])
        targets = self.aws("elbv2", "describe-target-health", "--target-group-arn", outputs["targetGroupArn"])
        rows = targets["TargetHealthDescriptions"]
        if not rows or any(t["TargetHealth"]["State"] != "healthy" for t in rows):
            raise Blocked("Controller load-balancer targets unhealthy")
        with urllib.request.urlopen("https://" + outputs["dnsRecord"].rstrip(".") + "/api/health", timeout=20) as response:
            if response.status != 200:
                raise Blocked("Public controller health failed")
        return {**controller, "targets": "healthy", "publicHealth": "passed"}

    def verify_recovery(self, plan, steps):
        if not steps:
            raise Blocked("Recovery has not been applied")
        if plan["scope"] == "workspace":
            return self.quarantine(plan["path"], plan["generation"])
        if plan["scope"] == "progress":
            if not steps.get("progressCommit"):
                raise Blocked("Progress reconstruction has not been committed")
            from common import git
            git(plan["repository"], "fetch", "origin", "main")
            git(plan["repository"], "merge-base", "--is-ancestor", steps["progressCommit"], "origin/main")
            return {"progressCommit": steps["progressCommit"], "verified": True}
        if not steps.get("deploy"):
            raise Blocked("Storage replacement has not completed")
        outputs = self.outputs()
        keys = {"runtime-efs": ["aocRuntimeFilesystem"], "controller-efs": ["efsId"],
            "database": ["rdsEndpoint"], "instance": ["aocRuntimeFilesystem", "efsId", "rdsEndpoint"]}[plan["scope"]]
        if any(not outputs.get(key) or outputs[key] == plan["outputs"].get(key) for key in keys):
            raise Blocked("Live stack does not show the planned storage replacement")
        if plan["scope"] != "runtime-efs":
            services = self.aws("ecs", "describe-services", "--cluster", "paperclip", "--services", "paperclip-service")
            if not services["services"] or services["services"][0]["desiredCount"] == 0:
                raise Blocked("Controller is intentionally stopped; restore the paired vault key or bootstrap fresh state before verification")
            self.health()
        runtime = self.wait("paperclip-aoc-runtime")
        return {"storageReplaced": True, "runtime": runtime, "companyReady": False,
                "required": "authenticated SSH repinning and company qualification before activation"}
