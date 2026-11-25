#!/usr/bin/env python3
"""Image-launcher target and the Solver's guarded publication command."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import signal
import sys

from api import Api
from common import Blocked, LockContention, digest, git, lock, read_json, write_json
from publication import publish, verify, allowed_files
from repository import Repository
from aoc_site import Site
from stages import gather, submit
from workflow import Controller, assignment, complete_stage, stage_notifier
from probe import qualify


def run_model(args, cwd, prompt, env, timeout=3600):
    process = subprocess.Popen(args, cwd=cwd, stdin=subprocess.PIPE, text=True,
                               env=env, start_new_session=True)
    def stop(signum, frame):
        if process.poll() is None:
            os.killpg(process.pid, signum)
        raise Blocked("Solver interrupted; current attempt preserved")
    previous = signal.signal(signal.SIGTERM, stop)
    try:
        process.communicate(prompt, timeout=timeout)
        return process.returncode
    except subprocess.TimeoutExpired:
        raise Blocked(f"Solver exceeded {timeout // 60}-minute execution budget; attempt preserved") from None
    finally:
        signal.signal(signal.SIGTERM, previous)
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()


def runtime_context():
    api = Api.runtime()
    task = os.environ["PAPERCLIP_TASK_ID"]
    row = api.request("GET", "/issues/" + task)
    company = os.environ["PAPERCLIP_COMPANY_ID"]
    agent = os.environ["PAPERCLIP_AGENT_ID"]
    if row["companyId"] != company or row.get("assigneeAgentId") != agent:
        raise Blocked("Run/task/assignee identity mismatch")
    generation = os.environ["AOC_GENERATION"]
    spec = assignment(row)
    if spec and spec["generation"] != generation:
        raise Blocked("Assignment belongs to another generation")
    owner = {"company": company, "generation": generation}
    root = Path(os.environ.get("AOC_WORKSPACE_ROOT", "/workspaces/aoc"))
    return api, task, row, spec, owner, root


def run(args):
    api, task, row, spec, owner, root = runtime_context()
    # Control decisions use a separate disposable clone; stage checkouts are
    # deterministic across retries and lie outside Paperclip's restoration tree.
    name = "control-" + owner["generation"] if os.environ["AOC_ROLE"] == "cto" else task
    # Exit order releases the mutation lock before waking the controller.
    with stage_notifier(api, task, spec), lock(root):
        # XDG_CONFIG_HOME is a long Paperclip run path. Keep any sbt IPC path
        # short even when the model invokes sbt directly rather than our helper.
        os.environ["SBT_GLOBAL_SERVER_DIR"] = "/tmp/aoc-sbt"
        try:
            probe = json.loads(row.get("description") or "null")
        except ValueError:
            probe = None
        if isinstance(probe, dict) and probe.get("schema") == "aoc-probe-v1":
            if os.environ["AOC_ROLE"] != "cto":
                raise Blocked("Runtime probes must be assigned to CTO")
            result = qualify(api, task, owner["company"], os.environ["PAPERCLIP_AGENT_ID"],
                             root, template=probe.get("templateTests") is True)
            print(json.dumps({"type": "text", "part": {"type": "text", "text": json.dumps(result)}}))
            return 0
        if spec and spec["stage"] != "control":
            existing, _ = api.document(task, "result")
            if existing:
                complete_stage(api, task, spec, existing, notify=False)
                return 0
        allowed = allowed_files(spec["year"], spec["day"]) if spec and spec["stage"] == "solve" else None
        repo = Repository.prepare(root, name, owner, allowed_dirty=allowed)
        repo.assert_owner()
        site = Site(os.environ.get("AOC_SESSION", ""), os.environ["AOC_ACCOUNT"])
        if os.environ["AOC_ROLE"] == "cto":
            # An authorization task can only continue; routine/manual tasks select.
            controller = Controller(api, repo, site, owner["company"], owner["generation"],
                os.environ["PAPERCLIP_AGENT_ID"])
            result = controller.run(task, select=spec is None)
        else:
            if not spec or spec["stage"] != {"problem-gatherer": "gather",
                    "problem-solver": "solve", "problem-submitter": "submit"}[os.environ["AOC_ROLE"]]:
                raise Blocked("Role/stage mismatch")
            existing, _ = api.document(task, "result")
            if existing:
                complete_stage(api, task, spec, existing, notify=False)
                return 0
            if spec["stage"] == "gather":
                result = gather(repo, site, spec)
            elif spec["stage"] == "submit":
                receipt, _ = api.document(row["parentId"], "publication")
                prior, _ = api.document(task, "submission")
                rejected, _ = api.document(row["parentId"], "rejections")
                checkpoint = root / "submissions" / (task + ".json")
                if prior and not checkpoint.exists():
                    write_json(checkpoint, prior)
                result = submit(repo, site, spec, receipt, checkpoint,
                    persist=lambda value: api.put_document(task, "submission", value),
                    rejected_answers=(rejected or {}).get(str(spec["part"]), []))
            else:
                journal = read_json(root / "publications" / (task + ".json"))
                if journal and not git(repo.path, "status", "--porcelain"):
                    receipt = verify(repo, spec["year"], spec["day"], spec["part"], journal["answer"])
                    complete_stage(api, task, spec, {"outcome": "published", "receipt": receipt}, notify=False)
                    return 0
                env = {**os.environ, "AOC_REPO_DIR": str(repo.path),
                    "AOC_ASSIGNMENT": json.dumps(spec), "AOC_RUNTIME_DIR": str(Path(__file__).resolve().parent.parent)}
                prompt = sys.stdin.read() + "\n\nAssigned stage (authoritative):\n" + json.dumps(spec)
                prompt += '\nPublish with python3 "$AOC_RUNTIME_DIR/scripts/entry.py" publish --answer ANSWER --files PATH ...'
                fresh_args = []
                skip = False
                for argument in args:
                    if skip:
                        skip = False
                        continue
                    if argument in ("--session", "-s"):
                        skip = True
                    elif argument not in ("--continue", "-c") and not argument.startswith("--session="):
                        fresh_args.append(argument)
                result = run_model(["/usr/local/bin/opencode", *fresh_args], repo.path, prompt, env)
                if result:
                    raise Blocked("Solver failed; partial work preserved")
                saved, _ = api.document(task, "result")
                if not saved:
                    raise Blocked("Solver exited without a published result")
                return 0
            complete_stage(api, task, spec, result, notify=False)
    print(json.dumps({"type": "text", "part": {"type": "text", "text": json.dumps(result)}}))
    return 0


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "publish":
        parser = argparse.ArgumentParser()
        parser.add_argument("--answer", required=True)
        parser.add_argument("--files", nargs="+", required=True)
        args = parser.parse_args(sys.argv[2:])
        api, task, row, spec, owner, root = runtime_context()
        if not spec or spec["stage"] != "solve":
            raise Blocked("Only an assigned Solver may publish")
        repo = Repository(Path(os.environ["AOC_REPO_DIR"]), owner)
        # Parent run holds the runtime mutation lock while the solver executes.
        write_json(root / "publications" / (task + ".json"), {"assignment": spec, "answer": args.answer})
        receipt = publish(repo, spec, args.answer, args.files)
        complete_stage(api, task, spec, {"outcome": "published", "receipt": receipt}, notify=False)
        print(json.dumps(receipt))
        return 0
    try:
        return run(sys.argv[1:])
    except Blocked as error:
        try:
            api, task, row, spec, owner, root = runtime_context()
            if spec and os.environ.get("AOC_ROLE") != "cto":
                existing, _ = api.document(task, "result")
                complete_stage(api, task, spec, existing or {"outcome": "blocked", "reason": str(error)})
            elif spec and spec.get("stage") == "control":
                # CTO itself hit a transient failure (e.g. the mutation lock
                # or an API call exhausted its own retries). Leave a
                # breadcrumb on the control issue's state so the next
                # continuation retries the same stage instead of Paperclip's
                # platform-level retry re-dispatching with no record of what
                # already happened. Never downgrade a genuine semantic
                # outcome (rejected/rate_limited/uncertain) that a prior,
                # successful run already recorded.
                if not isinstance(error, LockContention):
                    # Lock contention means another agent (often a long-running
                    # Solver) is still legitimately busy -- nothing is actually
                    # broken, so the control task's state must not be touched.
                    # Recording it as "blocked" here would make the next
                    # continuation restart the whole stage pipeline from
                    # "gather" (failedStage is never known at this generic
                    # catch-all), discarding an already-successful, still-valid
                    # gather/solve result purely because of a busy-lock race.
                    state, _ = api.document(task, "state")
                    state = state or {"part": spec["part"], "attempt": 0}
                    if state.get("outcome") not in ("rejected", "rate_limited", "uncertain"):
                        api.put_document(task, "state", {**state, "outcome": "blocked"})
        except Exception:
            pass  # Keep the original failure visible; task remains recoverable.
        print(json.dumps({"type": "text", "part": {"type": "text", "text": str(error)}}))
        return 2


if __name__ == "__main__":
    sys.exit(main())
