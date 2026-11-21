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
from aoc_existing_solution import find_existing_commit


def _api(request_timeout=10):
    base = os.environ["PAPERCLIP_API_URL"].rstrip("/")
    headers = {"Authorization": "Bearer " + os.environ["PAPERCLIP_API_KEY"],
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


def reconcile(next_part, repo_dir, find_commit=find_existing_commit):
    """If the repository already has a verified, passing solution for the next
    unfinished part, record its review directly instead of re-running
    gather/solve/submit for work that is already done. Returns the created
    review issue id, or None if no existing solution was found."""
    year, day, part = next_part
    commit = find_commit(repo_dir, year, day, part)
    if not commit:
        return None
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
    issue = request("POST", "/api/issues", {
        "companyId": company, "title": title, "description": description,
        "assigneeAgentId": reviewer, "status": "todo", "priority": "medium",
    })
    result = {"reviewIssueId": issue["id"], "year": year, "day": day, "part": part,
              "solutionCommit": commit, "accepted": True, "repairRequired": False,
              "provenance": {"status": "unknown"}}
    comment = ("Reconciled: an existing passing solution for this part was already in "
              "the repository (commit " + commit + "); no new gather/solve/submit run "
              "was started.\n\n```aoc-review-result\n" + json.dumps(result) + "\n```")
    updated = request("PATCH", "/api/issues/" + issue["id"], {"status": "done", "comment": comment})
    if updated.get("status") != "done":
        raise ValueError("reconciliation review disposition was not persisted")
    return issue["id"]


def run(args, check=check_cycle, launch=os.execv, probe=subprocess.run,
       finish=None, reconcile_existing=reconcile):
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
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = check()
        try:
            result = json.loads(output.getvalue())
        except (ValueError, TypeError):
            result = {"mode": "unknown", "reason": "invalid gate result"}
            code = 2
        mode = result.get("mode")
        if mode == "ready" and code == 0 and result.get("nextPart"):
            year, day, part = result["nextPart"]
            repo_dir = os.environ.get("AOC_REPO_DIR")
            try:
                reconciled = reconcile_existing(result["nextPart"], repo_dir) if repo_dir else None
            except Exception as error:
                print("CTO reconciliation check failed: " + type(error).__name__)
                return 2
            if reconciled:
                note = (f"Reconciled AoC {year} Day{day:02d} part{part} from an existing "
                        f"repository solution (review {reconciled}); waiting for the next "
                        "daily-selection cycle to find the next unfinished day.")
                print(json.dumps({"type": "text", "part": {"type": "text",
                                 "text": "CTO preflight: " + note}}))
                try:
                    (finish or finish_occurrence)(result, note)
                except Exception as error:
                    print("CTO disposition failed: " + type(error).__name__)
                    return 2
                return 0
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
