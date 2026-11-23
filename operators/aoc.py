#!/usr/bin/env python3
"""Operator entry point: inspect/plan/apply/verify, with private resumable journals."""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import sys
import uuid

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "skills/aoc-runtime/scripts"))
from api import Api
from common import Blocked, command, digest, git, now, read_json, write_json
from company import assert_quiet, bind, inventory, quiesce, verify, sync_instructions, sync_routine
from infrastructure import Infrastructure
from lifecycle import activate, archive, credentials, environment, assert_previous_owner, resume_ready
from cutover import retire_legacy
from package import build, payload, validate
from repository import ORIGIN, Repository


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("action", choices=("diagnose", "package", "deploy", "replace", "bind", "tools", "recover", "bootstrap", "own", "install", "credentials", "environment", "activate", "archive", "retire", "probe", "reconcile"))
    p.add_argument("phase", nargs="?", choices=("plan", "apply", "verify"), default="plan")
    p.add_argument("--company")
    p.add_argument("--name")
    p.add_argument("--record", type=Path)
    p.add_argument("--package", type=Path)
    p.add_argument("--secrets-file", type=Path)
    p.add_argument("--environment")
    p.add_argument("--host")
    p.add_argument("--private-key-file", type=Path)
    p.add_argument("--known-hosts-file", type=Path)
    p.add_argument("--qualification", type=Path)
    p.add_argument("--account", help="SHA-256 fingerprint of the authenticated AoC user label")
    p.add_argument("--generation", default=None)
    p.add_argument("--image")
    p.add_argument("--repository", type=Path, help="Operator's clean solution checkout for ownership transfer")
    p.add_argument("--infra", type=Path, default=ROOT.parent / "pulumi-paperclip")
    p.add_argument("--stack", default="rolandtritsch/paperclip/paperclip")
    p.add_argument("--scope", choices=("workspace", "progress", "runtime-efs", "controller-efs", "database", "instance"))
    p.add_argument("--path", type=Path)
    p.add_argument("--approval", help="Concrete destructive operation plan hash approved by the user")
    p.add_argument("--backup", help="Approved paired DB/key backup reference, never key contents")
    return p


def load_or_create(args, plan):
    if args.phase == "plan":
        if not args.record:
            raise Blocked("Specify --record to persist this reviewable operation")
        if args.record.exists():
            raise Blocked("Operation record already exists; use apply/verify or a new record")
        record = {"schema": 1, "action": args.action, "plan": plan, "planHash": digest(plan),
                  "createdAt": now(), "steps": {}}
        write_json(args.record, record)
        return record
    if not args.record:
        raise Blocked("Apply/verify requires the reviewed --record")
    record = read_json(args.record)
    if not record or record["action"] != args.action or digest(record["plan"]) != record["planHash"]:
        raise Blocked("Invalid/changed operation record")
    return record


def step(args, record, name, function):
    if name not in record["steps"]:
        value = function()
        record["steps"][name] = value if value is not None else True
        write_json(args.record, record)
    return record["steps"][name]


def imports(args, api):
    package = read_json(args.package) if args.package else build(ROOT)
    validate(package)
    generation = args.generation
    binding = None
    if not generation and args.company and args.action == "deploy":
        agents = api.request("GET", f"/companies/{args.company}/agents")
        cto = next((a for a in agents if a["name"] == "CTO"), {})
        generation = (cto.get("metadata") or {}).get("aoc", {}).get("generation")
        account = (cto.get("metadata") or {}).get("aoc", {}).get("account")
        if account and cto.get("defaultEnvironmentId"):
            binding = {"environment": cto["defaultEnvironmentId"], "account": account}
    plan = {"company": args.company, "name": args.name, "package": package,
            "generation": generation or str(uuid.uuid4()), "binding": binding,
            "oldCompany": args.company if args.action == "replace" else None}
    record = load_or_create(args, plan)
    plan = record["plan"]
    body = payload(plan["package"], None if args.action == "replace" else plan["company"], plan["name"])
    if args.phase == "plan":
        preview = api.request("POST", "/companies/import/preview", body)
        record["preview"] = preview
        write_json(args.record, record)
        if preview.get("errors"):
            raise Blocked("Import preview contains errors; inspect the saved record")
        agents = preview["manifest"]["agents"]
        routine = preview["manifest"]["issues"][0].get("routine") or {}
        if len(agents) != 4 or any(a["adapterType"] != "opencode_local" for a in agents):
            raise Blocked("Preview lost the intended agent adapter configuration")
        triggers = routine.get("triggers", [])
        if len(triggers) != 1 or triggers[0].get("cronExpression") != "0 6 * * *":
            raise Blocked("Preview lost the daily trigger; check YAML indentation")
        return {"planHash": record["planHash"], "agents": [a["slug"] for a in agents],
                "helpers": len(plan["package"]["files"]), "triggers": triggers, "errors": []}
    if args.phase == "verify":
        company = record["steps"].get("import", {}).get("company", {}).get("id")
        if not company:
            raise Blocked("Import has not completed")
        result = verify(api, company)
        # Verify the full stored helper inventory, not just SKILL.md presence.
        skills = api.request("GET", f"/companies/{company}/skills")
        skill = next(s for s in skills if s["slug"] == "aoc-runtime")
        detail = api.request("GET", f"/companies/{company}/skills/{skill['id']}")
        actual = {f["path"] for f in detail["fileInventory"]}
        expected = {k[len("skills/aoc-runtime/"):] for k in plan["package"]["files"] if k.startswith("skills/aoc-runtime/")}
        if actual != expected:
            raise Blocked("Imported helper inventory differs from release")
        return result
    if plan["company"]:
        step(args, record, "quiesce", lambda: quiesce(api, plan["company"]))
    if "import" not in record["steps"]:
        # An uncertain import cannot be blindly repeated, especially for new_company.
        if record.get("importIntent") and body["target"]["mode"] == "new_company":
            raise Blocked("Import response lost; diagnose live company before reconciling journal")
        record["importIntent"] = True
        write_json(args.record, record)
        body["pauseAutomations"] = True
        if body["target"]["mode"] == "existing_company":
            body["include"]["issues"] = False  # Routines are reconciled explicitly, never imported twice.
            # Imports replace env maps. Preserve company-local credentials while
            # applying the new declarative configuration, never cross-company refs.
            current = api.request("GET", f"/companies/{plan['company']}/agents")
            by_name = {a["name"]: a for a in current}
            overrides = {}
            for desired in record["preview"]["manifest"]["agents"]:
                previous = by_name.get(desired["name"])
                adapter = dict(desired["adapterConfig"])
                if previous:
                    config = api.request("GET", f"/agents/{previous['id']}/configuration")
                    old_env = {key: value for key, value in config["adapterConfig"].get("env", {}).items()
                        if value.get("type") == "secret_ref"}
                    adapter["env"] = {**old_env, **adapter.get("env", {})}
                overrides[desired["slug"]] = {"adapterType": desired["adapterType"],
                    "runner": "legacy", "adapterConfig": adapter}
            body["adapterOverrides"] = overrides
        if args.secrets_file:
            if args.secrets_file.stat().st_mode & 0o077:
                raise Blocked("Secrets file must be mode 0600")
            body["secretValues"] = read_json(args.secrets_file)
        step(args, record, "import", lambda: api.request("POST", "/companies/import", body))
    company = record["steps"]["import"]["company"]["id"]
    step(args, record, "instructions", lambda: sync_instructions(api, company, plan["package"]["files"]))
    step(args, record, "routine", lambda: sync_routine(api, company, plan["package"]["files"]))
    if plan.get("binding"):
        step(args, record, "binding", lambda: bind(api, company, plan["binding"]["environment"],
            plan["generation"], plan["package"]["packageHash"], plan["binding"]["account"]))
    return {"company": company, "generation": plan["generation"], "packageHash": plan["package"]["packageHash"],
            "next": "bind credentials/environment, verify runtime, transfer owner, then enable; company remains paused"}


def main(args):
    if args.action == "package":
        result = build(ROOT)
        if args.package:
            write_json(args.package, result)
        return {k: v for k, v in result.items() if k != "files"}
    if args.action == "install":
        target = Path.home() / ".codex/skills"
        target.mkdir(parents=True, exist_ok=True)
        for source in (ROOT / "operators/skills").iterdir():
            destination = target / source.name
            if destination.is_symlink() and destination.resolve() == source.resolve():
                continue
            if destination.exists() or destination.is_symlink():
                raise Blocked("Existing skill preserved: " + str(destination))
            destination.symlink_to(source)
        return {"installed": str(target)}
    if args.action == "bootstrap":
        return infrastructure(args, None)
    api = Api.local()
    if args.action == "diagnose":
        companies = api.request("GET", "/companies")
        if not args.company:
            return [{k: c.get(k) for k in ("id", "name", "status")} for c in companies]
        state = inventory(api, args.company)
        return {"company": state["company"]["id"], "agents": [{k: a.get(k) for k in ("id", "name", "status")} for a in state["agents"]],
            "routines": state["routines"], "liveRuns": len(state["liveRuns"])}
    if args.action in ("deploy", "replace"):
        return imports(args, api)
    if args.action in ("credentials", "environment", "activate", "archive", "retire", "probe", "reconcile"):
        if not args.company:
            raise Blocked("Explicit company identity required")
        if args.phase != "apply":
            return inventory(api, args.company) if args.phase == "verify" else {"action": args.action, "company": args.company}
        if args.action == "credentials":
            return credentials(api, args.company)
        if args.action == "retire":
            return retire_legacy(api, args.company)
        if args.action in ("probe", "reconcile"):
            state = assert_quiet(api, args.company)
            cto = next(a for a in state["agents"] if a["name"] == "CTO")
            # Lifecycle commands return before readiness. Queuing against a
            # still-paused agent immediately blocks the new task.
            resume_ready(api, cto["id"])
            task = api.request("POST", f"/companies/{args.company}/issues", {
                "title": "AoC runtime " + args.action, "description": json.dumps({"schema":
                    "aoc-probe-v1" if args.action == "probe" else "aoc-reconcile-v1", "templateTests": True}),
                "assigneeAgentId": cto["id"], "status": "todo", "idempotencyKey": "aoc-" + args.action + "-" + (args.generation or str(uuid.uuid4()))})
            return {"task": task["id"], "agent": cto["id"], "next": "Wait for qualification document, then pause CTO again"}
        if args.action == "archive":
            return archive(api, args.company)
        if args.action == "activate":
            return activate(api, args.company, read_json(args.qualification, {}) if args.qualification else {})
        if not all((args.host, args.private_key_file, args.known_hosts_file)):
            raise Blocked("Environment requires host, private-key-file and authenticated known-hosts-file")
        if args.private_key_file.stat().st_mode & 0o077:
            raise Blocked("SSH private key must be mode 0600")
        return environment(api, args.company, args.host, args.private_key_file.read_text(), args.known_hosts_file.read_text())
    if args.action == "bind":
        if not all((args.company, args.environment, args.generation, args.account, args.package)):
            raise Blocked("Bind requires company, environment, generation, account and saved package")
        release = read_json(args.package)
        validate(release)
        if args.phase != "apply":
            return verify(api, args.company) if args.phase == "verify" else {"bind": args.company, "release": release["packageHash"]}
        bind(api, args.company, args.environment, args.generation, release["packageHash"], args.account)
        return {"bound": args.company}
    if args.action == "own":
        if not all((args.repository, args.company, args.generation)):
            raise Blocked("Ownership requires repository, company and generation")
        if args.phase != "apply":
            return {"owner": {"company": args.company, "generation": args.generation}}
        assert_quiet(api, args.company)
        repo = args.repository.resolve()
        if git(repo, "status", "--porcelain"):
            raise Blocked("Operator solution checkout must be clean")
        if Path(git(repo, "rev-parse", "--show-toplevel")) != repo or git(repo, "remote", "get-url", "origin") != ORIGIN:
            raise Blocked("Ownership transfer requires the expected solution repository root/origin")
        if git(repo, "symbolic-ref", "--short", "HEAD") != "main":
            raise Blocked("Ownership transfer requires main")
        files = [".aoc/owner.json"]
        if git(repo, "ls-remote", "origin", "refs/heads/main"):
            git(repo, "pull", "--ff-only", "origin", "main")
            previous = read_json(repo / ".aoc/owner.json")
            if previous and previous["company"] != args.company:
                assert_previous_owner(api, previous, args.record)
        else:
            template = ROOT / "skills/aoc-runtime/assets/template"
            shutil.copytree(template, repo / "0000")
            (repo / ".gitignore").write_text("**/target/\n**/.bsp/\n**/.metals/\n**/.bloop/\n")
            workflow = repo / ".github/workflows/ci.yml"
            workflow.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(template.parent / "ci.yml", workflow)
            files += ["0000", ".gitignore", ".github/workflows/ci.yml"]
        write_json(repo / ".aoc/owner.json", {"company": args.company, "generation": args.generation})
        git(repo, "add", "--force", "--", *files)
        git(repo, "diff", "--cached", "--check")
        if git(repo, "diff", "--cached", "--name-only"):
            git(repo, "commit", "-m", "Transfer AoC company ownership")
        git(repo, "push", "origin", "HEAD:main")
        return {"ownerCommit": git(repo, "rev-parse", "HEAD")}
    return infrastructure(args, api)


def infrastructure(args, api):
    infra = Infrastructure(args.infra, args.stack)
    outputs = infra.outputs() if args.action != "bootstrap" and args.phase == "plan" else {}
    plan = {"scope": args.scope, "path": str(args.path) if args.path else None, "company": args.company,
        "image": args.image, "stack": args.stack, "infraRoot": str(args.infra.resolve()), "outputs": outputs,
        "generation": args.generation or str(uuid.uuid4()), "backup": args.backup,
        "repository": str(args.repository.resolve()) if args.repository else None, "account": args.account,
        "affectedCompanies": [{k: c.get(k) for k in ("id", "name", "status")} for c in
            (api.request("GET", "/companies") if api and args.phase == "plan" else [])]}
    record = load_or_create(args, plan)
    plan = record["plan"]
    infra = Infrastructure(Path(plan.get("infraRoot", str(args.infra))), plan["stack"])
    if args.phase == "plan":
        return {"planHash": record["planHash"], "plan": plan}
    if args.phase == "verify":
        return infra.health() if args.action != "recover" else infra.verify_recovery(plan, record["steps"])
    if args.action == "tools":
        if not plan["image"] or not re.fullmatch(r"[^\s]+@sha256:[a-f0-9]{64}", plan["image"]):
            raise Blocked("Tools deployment requires an immutable image digest from runtime/publish.py")
        step(args, record, "config", lambda: infra.pulumi("config", "set", "aoc_runtime_image", plan["image"]))
        step(args, record, "preview", lambda: infra.pulumi("preview", "--non-interactive"))
        step(args, record, "deploy", lambda: infra.pulumi("up", "--yes", "--non-interactive"))
        return step(args, record, "rollout", lambda: infra.wait("paperclip-aoc-runtime", plan["image"]))
    if args.action == "bootstrap":
        step(args, record, "preview", lambda: infra.pulumi("preview", "--non-interactive"))
        return step(args, record, "deploy", lambda: infra.pulumi("up", "--yes", "--non-interactive"))
    if args.action != "recover" or not plan["scope"]:
        raise Blocked("Recovery needs an explicit scope")
    if args.approval != record["planHash"]:
        raise Blocked("Destructive recovery requires the user-approved concrete plan hash")
    if not record["steps"]:
        live = infra.outputs()
        for key in ("aocRuntimeFilesystem", "efsId", "rdsEndpoint"):
            if key in plan["outputs"] and live.get(key) != plan["outputs"][key]:
                raise Blocked("Physical resource identity changed since the approved reset plan")
    for company in plan["affectedCompanies"]:
        if company["status"] == "active" and (plan["scope"] in ("instance", "database", "controller-efs")
                                              or company["id"] == plan["company"]):
            step(args, record, "quiesce-" + company["id"], lambda c=company: quiesce(api, c["id"]))
    if plan["scope"] == "workspace":
        if not plan["path"] or not plan["company"]:
            raise Blocked("Workspace quarantine requires explicit company and remote path")
        return step(args, record, "quarantine", lambda: infra.quarantine(plan["path"], plan["generation"]))
    if plan["scope"] == "progress":
        if not all((plan["repository"], plan["account"], plan["company"])):
            raise Blocked("Progress reconstruction requires repository, account and company")
        path = Path(plan["repository"])
        owner = read_json(path / ".aoc/owner.json")
        if not owner or owner["company"] != plan["company"]:
            raise Blocked("Progress reconstruction company does not own repository")
        repo = Repository(path, owner)
        repo.sync()
        index = path / ".aoc/progress.json"
        if index.exists():
            backup = args.record.with_suffix(".progress-backup")
            if not backup.exists():
                backup.touch(mode=0o600)
                backup.write_bytes(index.read_bytes())
        write_json(index, {"schema": 1, "account": plan["account"], "parts": {}})
        commit = repo.commit([".aoc/progress.json"], "Reconstruct AoC progress from Git and site evidence")
        record["steps"]["progressCommit"] = commit
        write_json(args.record, record)
        return {"commit": commit, "next": "Run an explicit CTO check to verify and reconcile historical parts"}
    if plan["scope"] in ("instance", "database", "controller-efs") and not plan["backup"]:
        raise Blocked("Paired database/master-key backup reference required before instance reset")
    keys = {"runtime-efs": ["aoc_runtime_data_generation"], "controller-efs": ["controller_data_generation"],
            "database": ["database_generation"], "instance": ["controller_data_generation", "database_generation", "aoc_runtime_data_generation"]}[plan["scope"]]
    # Remove state protection and stop affected services BEFORE changing any
    # resource generation. A single preview cannot replace protected resources.
    step(args, record, "allow-replacement", lambda: infra.pulumi("config", "set", "allow_data_replacement", "true"))
    if plan["scope"] in ("instance", "database", "controller-efs"):
        step(args, record, "stop-controller", lambda: infra.pulumi("config", "set", "desired_count", "0"))
    step(args, record, "stop-runtime", lambda: infra.pulumi("config", "set", "aoc_runtime_desired_count", "0"))
    step(args, record, "unprotect-and-stop", lambda: infra.pulumi("up", "--yes", "--non-interactive"))
    infra.aws("ecs", "wait", "services-stable", "--cluster", "paperclip", "--services", "paperclip-aoc-runtime", "paperclip-service")
    for key in keys:
        step(args, record, key, lambda k=key: infra.pulumi("config", "set", k, plan["generation"]))
    step(args, record, "preview", lambda: infra.pulumi("preview", "--non-interactive"))
    step(args, record, "deploy", lambda: infra.pulumi("up", "--yes", "--non-interactive"))
    infra.pulumi("config", "set", "allow_data_replacement", "false")
    infra.pulumi("config", "set", "aoc_runtime_desired_count", "1")
    if plan["scope"] in ("instance", "database", "controller-efs"):
        # Do not start a database with its corresponding vault key missing.
        # Restoration/fresh initialization is an explicit follow-up operation.
        record["restoreRequired"] = True
        write_json(args.record, record)
    infra.pulumi("up", "--yes", "--non-interactive")
    return {"reset": plan["scope"], "required": "restore paired DB/key or bootstrap fresh credentials; repin SSH before activation"}


if __name__ == "__main__":
    try:
        print(json.dumps(main(parser().parse_args()), indent=2, default=str))
    except (Blocked, KeyError, ValueError) as error:
        print(str(error), file=sys.stderr)
        sys.exit(2)
