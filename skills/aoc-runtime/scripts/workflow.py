"""Single assignment owner; deterministic continuation of one authorized day."""
import json
import os
from contextlib import contextmanager

from aoc_repair import next_unsolved
from aoc_state import CANDIDATE_PRESENT
from common import Blocked, digest, finale, identity, now
from publication import verify
from repository import load_progress, save_progress
from stages import evidence

ROLES = {"gather": "Problem Gatherer", "solve": "Problem Solver", "submit": "Problem Submitter"}
STAGES = ("gather", "solve", "submit")
# A generic infra hiccup (lock contention, a flaky API call) is recorded as
# "blocked" by entry.py's catch-all exception handler; it is not a semantic
# puzzle outcome like "rejected"/"rate_limited"/"uncertain" and should not
# need a full daily/manual allow_repair cycle to clear.
BLOCKED_RETRY_LIMIT = 5


def assignment(task):
    try:
        value = json.loads(task.get("description") or "null")
    except ValueError:
        return None
    if not isinstance(value, dict) or value.get("schema") != "aoc-task-v1":
        return None
    return value


class Controller:
    def __init__(self, api, repo, site, company, generation, agent):
        self.api, self.repo, self.site = api, repo, site
        self.company, self.generation, self.agent = company, generation, agent

    def tasks(self):
        # Full descriptions/documents are fetched by ID before decisions.
        rows = self.api.request("GET", f"/companies/{self.company}/issues?status=backlog,todo,in_progress,blocked,in_review&limit=1000")
        return [self.api.request("GET", "/issues/" + r["id"]) for r in rows
                if r["title"].startswith("AoC ")]

    def create(self, spec, agent, parent=None, status="todo"):
        key = digest(spec)
        return self.api.request("POST", f"/companies/{self.company}/issues", {
            "title": f"AoC {spec['year']} Day{spec['day']:02} part{spec['part']}: {spec['stage']}",
            "description": json.dumps(spec, sort_keys=True), "assigneeAgentId": agent,
            "status": status, "parentId": parent, "idempotencyKey": key, "allowDuplicate": True})

    def run(self, task, select=False):
        self.repo.assert_owner()
        rows = self.tasks()
        controls = [(r, assignment(r)) for r in rows]
        controls = [(r, a) for r, a in controls if a and a.get("stage") == "control"
                    and a.get("generation") == self.generation and r["status"] not in ("done", "cancelled")]
        if len(controls) > 1:
            raise Blocked("Multiple active day authorizations; operator reconciliation required")
        if controls:
            control, spec = controls[0]
            result = self.advance(control, spec, rows, allow_repair=select)
        elif select:
            result = self.select(task)
        else:
            result = {"outcome": "complete", "reason": "No active authorization; continuation cannot select"}
        self.api.put_document(task, "decision", result)
        # A persistent control task remains blocked while its children execute.
        if not any(r["id"] == task for r, _ in controls):
            self.api.finish(task, self.agent, self.company)
        return result

    def select(self, source, authorize=True):
        result = next_unsolved(self.repo, self.site)
        if result is None:
            return {"outcome": "complete", "parts": 524}
        year, day, part, candidate_state = result
        if not authorize:
            return {"outcome": "ready", "nextPart": {"year": year, "day": day, "part": part}}
        spec = {"schema": "aoc-task-v1", "generation": self.generation,
            "authorization": source, "year": year, "day": day, "part": part,
            "stage": "control", "attempt": 0}
        control = self.create(spec, self.agent, status="backlog")
        state = {"part": part, "attempt": 0}
        if candidate_state == CANDIDATE_PRESENT:
            try:
                receipt = verify(self.repo, year, day, part)
            except Blocked:
                pass  # no usable candidate; fall through to the gather-first pipeline
            else:
                self.api.put_document(control["id"], "publication", receipt)
                state["start"] = "submit"
        self.api.put_document(control["id"], "state", state)
        # Paperclip rejects a bare status="blocked" PATCH unless the issue
        # already has an unresolved blocker, a pending interaction/approval,
        # or an explicit unblockDescriptor (HTTP 422 otherwise) -- the
        # control task has none of the first two at creation time, since its
        # first specialist child doesn't exist yet. "board" is correct here
        # (not an agent/user): this control task unblocks itself once its
        # own stage pipeline finishes, not because any one person/agent acts.
        self.api.request("PATCH", "/issues/" + control["id"], {"status": "blocked",
            "unblockDescriptor": {"owner": "board", "action": "Specialist stage children complete"}})
        return self.advance(control, spec, [], False)

    def advance(self, control, spec, rows, allow_repair):
        state, _ = self.api.document(control["id"], "state")
        state = state or {"part": spec["part"], "attempt": 0}
        if state.get("outcome") == "blocked":
            retries = state.get("blockedRetries", 0)
            if retries >= BLOCKED_RETRY_LIMIT and not allow_repair:
                return {"outcome": "wait", "reason": "blocked"}
            # Retry just the stage that hit the transient failure (not the
            # whole day from "gather") and do not require allow_repair: a
            # lock/API hiccup is not a semantic puzzle rejection, so it
            # should self-heal on the next continuation ping within a few
            # minutes, not wait for the next daily/manual check.
            state = {"part": state["part"], "attempt": state["attempt"] + 1,
                "start": state.get("failedStage", "gather"),
                "blockedRetries": 0 if allow_repair else retries + 1}
            self.api.put_document(control["id"], "state", state)
        elif state.get("outcome") in ("rejected", "rate_limited", "uncertain"):
            if not allow_repair:
                return {"outcome": "wait", "reason": state["outcome"]}
            if state["outcome"] == "uncertain":
                page = self.site.page(spec["year"], spec["day"])
                if page["complete"] < state["part"]:
                    raise Blocked("Uncertain submission remains unconfirmed; no repeat POST permitted")
                receipt, _ = self.api.document(control["id"], "publication")
                if not finale(spec["year"], spec["day"], state["part"]):
                    if not receipt or page["answers"][state["part"] - 1] != receipt["answer"]:
                        raise Blocked("Uncertain submission does not match the accepted answer")
                    self.repo.validate_receipt(receipt)
                return self.finish_part(control, spec, state, {"outcome": "accepted",
                    "kind": "reconciled", "receipt": receipt, "site": evidence(page)})
            start = "submit" if state["outcome"] == "rate_limited" else "gather"
            state = {"part": state["part"], "attempt": state["attempt"] + 1, "start": start}
            self.api.put_document(control["id"], "state", state)
        agents = self.api.request("GET", f"/companies/{self.company}/agents")
        by_name = {a["name"]: a["id"] for a in agents if a["status"] != "terminated"}
        start_index = STAGES.index(state["start"]) if state.get("start") in STAGES else 0
        for index, stage in enumerate(STAGES):
            if index < start_index:
                continue
            if stage == "solve" and finale(spec["year"], spec["day"], state["part"]):
                continue
            child_spec = {**spec, "stage": stage, "part": state["part"], "attempt": state["attempt"]}
            child = self.create(child_spec, by_name[ROLES[stage]], control["id"])
            result, _ = self.api.document(child["id"], "result")
            if not result:
                return {"outcome": "wait", "task": child["id"], "stage": stage}
            if result.get("assignment") != child_spec:
                raise Blocked("Stage result identity mismatch")
            if result["outcome"] != {"gather": "gathered", "solve": "published", "submit": "accepted"}[stage]:
                if result["outcome"] == "rejected" and result.get("receipt"):
                    rejections, _ = self.api.document(control["id"], "rejections")
                    rejections = rejections or {}
                    answers = rejections.setdefault(str(state["part"]), [])
                    if result["receipt"]["answer"] not in answers:
                        answers.append(result["receipt"]["answer"])
                    self.api.put_document(control["id"], "rejections", rejections)
                state["outcome"] = result["outcome"]
                if result["outcome"] == "blocked":
                    state["failedStage"] = stage
                self.api.put_document(control["id"], "state", state)
                return {"outcome": "wait", "reason": result["outcome"]}
            if child["status"] != "done":
                return {"outcome": "wait", "reason": "Result persisted; specialist must finish disposition"}
            if stage == "solve":
                if any(result["receipt"].get(k) != child_spec[k] for k in ("year", "day", "part")):
                    raise Blocked("Publication receipt belongs to another puzzle part")
                self.repo.validate_receipt(result["receipt"])
                self.api.put_document(control["id"], "publication", result["receipt"])
            if stage == "submit":
                if (result.get("site", {}).get("account") != self.site.account
                        or result["site"].get("complete", 0) < state["part"]):
                    raise Blocked("Submission result lacks same-account acceptance evidence")
        return self.finish_part(control, spec, state, result)

    def finish_part(self, control, spec, state, result):
        self.repo.sync()
        progress = load_progress(self.repo, self.site.account)
        key = identity(spec["year"], spec["day"], state["part"])
        progress["parts"][key] = {k: v for k, v in result.items() if k != "assignment"}
        save_progress(self.repo, progress)
        if state["part"] == 1:
            self.api.put_document(control["id"], "state", {"part": 2, "attempt": 0})
            return self.advance(control, spec, [], False)
        self.api.finish(control["id"], self.agent, self.company)
        return {"outcome": "accepted", "year": spec["year"], "day": spec["day"]}


def complete_stage(api, task, spec, result, notify=True):
    if result.get("assignment") not in (None, spec):
        raise Blocked("Result belongs to another assignment")
    api.put_document(task, "result", {**result, "assignment": spec})
    api.finish(task, os.environ["PAPERCLIP_AGENT_ID"], os.environ["PAPERCLIP_COMPANY_ID"])
    if notify:
        notify_parent(api, task)


def notify_parent(api, task):
    row = api.request("GET", "/issues/" + task)
    parent = row.get("parentId")
    if not parent:
        raise Blocked("Stage has no CTO authorization")
    # Comment/mention is the supported same-company notification path; an agent
    # may not invoke another agent's heartbeat endpoint directly.
    api.request("POST", f"/issues/{parent}/comments", {
        "body": f"@CTO Stage result ready: [{row['identifier']}](/" +
                row["identifier"].split("-")[0] + f"/issues/{row['identifier']}). Continue this authorization only.",
        "reopen": False})


@contextmanager
def stage_notifier(api, task, spec):
    try:
        yield
    finally:
        if spec and spec["stage"] != "control":
            result, _ = api.document(task, "result")
            if result:
                notify_parent(api, task)
