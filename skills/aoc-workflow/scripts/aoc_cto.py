#!/usr/bin/env python3
"""OpenCode command wrapper: gate a CTO run before starting model inference."""

import contextlib
import io
import json
import os
import subprocess
import sys
import urllib.request

from aoc_cycle_gate import main as check_cycle
from aoc_existing_solution import find_existing_commit, git
from aoc_site_status import is_part_complete

MAX_RECONCILE_ITERATIONS = 524  # one per season part; a defensive cap, not an expectation


def _api(request_timeout=10):
    base = os.environ["PAPERCLIP_API_URL"].rstrip("/")
    # The ephemeral run-scoped PAPERCLIP_API_KEY cannot authenticate company
    # reads/writes for this ssh/legacy-runner execution shape (upstream
    # Paperclip gap; see paperclipai/paperclip#21591). Use a standing
    # agent-scoped key bound under a non-reserved name instead.
    headers = {"Authorization": "Bearer " + os.environ["AOC_PAPERCLIP_API_KEY"],
               "X-Paperclip-Run-Id": os.environ["PAPERCLIP_RUN_ID"],
               "Content-Type": "application/json"}
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            return None
    opener = urllib.request.build_opener(NoRedirect)
    def request(method, path, data=None):
        req = urllib.request.Request(base + path, headers=headers, method=method,
                                     data=None if data is None else json.dumps(data).encode())
        with opener.open(req, timeout=request_timeout) as response:
            return json.load(response)
    return request


def finish_occurrence(result, note="No puzzle work selected; this check is complete."):
    """Persist the CTO's decision before the launcher exits successfully."""
    task = os.environ.get("PAPERCLIP_TASK_ID")
    if not task:
        raise ValueError("no task identity for CTO disposition")
    request = _api(request_timeout=5)
    issue = request("GET", "/api/issues/" + task)
    if (issue.get("companyId") != os.environ["PAPERCLIP_COMPANY_ID"]
            or issue.get("assigneeAgentId") != os.environ["PAPERCLIP_AGENT_ID"]
            or issue.get("status") == "cancelled"):
        raise ValueError("CTO occurrence identity or ownership mismatch")
    if issue.get("status") == "done":
        return
    comment = "CTO preflight: " + json.dumps(result) + ". " + note
    updated = request("PATCH", "/api/issues/" + task, {"status": "done", "comment": comment})
    if updated.get("status") != "done":
        raise ValueError("CTO occurrence disposition was not persisted")


def write_last_part(repo_dir, part):
    """Record the fact of the last completed part in scala3-aoc's LAST.md and
    push it. Deliberately a fact, not a decision: aoc_cycle_gate.py's
    next_part() is the one place that computes what comes after it."""
    year, day, number = part
    path = str(repo_dir) + "/LAST.md"
    with open(path, "w") as handle:
        handle.write("```aoc-last\n" + json.dumps({"year": year, "day": day, "part": number}) + "\n```\n")
    git(repo_dir, "add", "LAST.md")
    git(repo_dir, "commit", "-m", f"Reconcile AoC {year} Day{day:02d} part{number}")
    git(repo_dir, "push")


def sync_repo(repo_dir):
    """Fast-forward-only pull so the gate's LAST.md read reflects the
    latest accepted part, not a stale staged checkout. Never discards
    another agent's work: a diverged or dirty tree fails closed."""
    git(repo_dir, "fetch", "origin", "main")
    git(repo_dir, "merge", "--ff-only", "origin/main")


def site_complete(next_part):
    year, day, part = next_part
    return is_part_complete(year, day, part, os.environ["AOC_SESSION"])


def reconcile(next_part, repo_dir, find_commit=find_existing_commit, write_last=write_last_part):
    """The site already confirms this part is accepted: record its review
    directly instead of re-running gather/solve/submit for work that is
    already done. Returns the created review issue id, or raises if the
    local checkout has no matching commit to cite as evidence."""
    year, day, part = next_part
    commit = find_commit(repo_dir, year, day, part)
    if not commit:
        raise ValueError("site confirms this part is accepted but no local commit was found")
    request = _api()
    company = os.environ["PAPERCLIP_COMPANY_ID"]
    agents = request("GET", "/api/companies/" + company + "/agents")
    reviewer = next((a["id"] for a in agents if a["name"] == "Solution Reviewer"), None)
    if not reviewer:
        raise ValueError("Solution Reviewer agent not found; cannot reconcile")
    title = f"AoC {year} Day{day:02d} part{part}: review"
    description = ("```aoc-solver-publication\n" +
                   json.dumps({"year": year, "day": day, "part": part, "commit": commit}) +
                   "\n```")
    # Created already `done`: Paperclip never wakes an assignee for a task
    # created pre-closed, unlike create-as-todo-then-patch-to-done, which
    # would wake the Solution Reviewer for real before the patch landed.
    issue = request("POST", "/api/issues", {
        "companyId": company, "title": title, "description": description,
        "assigneeAgentId": reviewer, "status": "done", "priority": "medium",
    })
    result = {"reviewIssueId": issue["id"], "year": year, "day": day, "part": part,
              "solutionCommit": commit, "accepted": True, "repairRequired": False,
              "provenance": {"status": "reconciled", "verifiedBy": "aoc_site_status",
                              "siteConfirmed": True}}
    comment = ("Reconciled: an authenticated adventofcode.com check confirms this part "
              "is already accepted (commit " + commit + "); no new gather/solve/submit "
              "run was started.\n\n```aoc-review-result\n" + json.dumps(result) + "\n```")
    updated = request("PATCH", "/api/issues/" + issue["id"], {"comment": comment})
    if updated.get("status") != "done":
        raise ValueError("reconciliation review disposition was not persisted")
    write_last(repo_dir, (year, day, part))
    return issue["id"]


def run(args, check=check_cycle, launch=os.execv, probe=subprocess.run,
       finish=None, reconcile_existing=reconcile, site_complete_check=site_complete,
       sync=sync_repo):
    binary = os.environ.get("AOC_OPENCODE_BINARY", "/usr/local/bin/opencode")
    # Paperclip's configuration probe has no run-scoped API credentials.
    # Permit only its fixed, tool-free hello prompt; real runs still use the gate.
    if (args and args[0] == "run"
            and os.environ.get("OPENCODE_DISABLE_PROJECT_CONFIG") == "true"
            and not os.environ.get("PAPERCLIP_RUN_ID")
            and not os.environ.get("PAPERCLIP_API_KEY")):
        prompt = sys.stdin.read(64)
        if prompt != "Respond with hello.":
            print("CTO preflight: refusing an unauthenticated non-probe invocation")
            return 2
        return probe([binary, *args], input=prompt, text=True, check=False).returncode
    if args and args[0] == "run":
        repo_dir = os.environ.get("AOC_REPO_DIR")
        if repo_dir:
            # The gate reads LAST.md from this checkout; it must be current
            # with origin before the gate runs, not only afterward. A
            # fast-forward-only pull never discards another agent's work.
            try:
                sync(repo_dir)
            except Exception as error:
                print("CTO repo sync failed: " + type(error).__name__)
                return 2

        def recheck():
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                exit_code = check()
            try:
                return json.loads(output.getvalue()), exit_code
            except (ValueError, TypeError):
                return {"mode": "unknown", "reason": "invalid gate result"}, 2

        result, code = recheck()
        mode = result.get("mode")
        iterations = 0
        while (mode == "ready" and code == 0 and result.get("nextPart")
               and repo_dir and iterations < MAX_RECONCILE_ITERATIONS):
            iterations += 1
            try:
                complete = site_complete_check(result["nextPart"])
            except Exception as error:
                print("CTO site-status check failed: " + type(error).__name__)
                return 2
            if not complete:
                break
            try:
                reconcile_existing(result["nextPart"], repo_dir)
            except Exception as error:
                print("CTO reconciliation failed: " + type(error).__name__)
                return 2
            result, code = recheck()
            mode = result.get("mode")
        if mode not in ("ready", "repair") or code not in (0, 1):
            print(json.dumps({"type": "text", "part": {"type": "text",
                             "text": "CTO preflight: " + json.dumps(result)}}))
            if mode in ("wait", "complete") and code == 1:
                try:
                    (finish or finish_occurrence)(result)
                except Exception as error:
                    print("CTO disposition failed: " + type(error).__name__)
                    return 2
                return 0
            return 2
    launch(binary, [binary, *args])
    return 0


if __name__ == "__main__":
    sys.exit(run(sys.argv[1:]))
