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


def finish_occurrence(result):
    """Persist the no-work decision before the launcher exits successfully."""
    task = os.environ.get("PAPERCLIP_TASK_ID")
    if not task:
        raise ValueError("no task identity for CTO no-work disposition")
    base = os.environ["PAPERCLIP_API_URL"].rstrip("/")
    headers = {"Authorization": "Bearer " + os.environ["PAPERCLIP_API_KEY"],
               "X-Paperclip-Run-Id": os.environ["PAPERCLIP_RUN_ID"],
               "Content-Type": "application/json"}
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            return None
    opener = urllib.request.build_opener(NoRedirect)
    def request(method, data=None):
        req = urllib.request.Request(base + "/api/issues/" + task, headers=headers,
                                     data=None if data is None else json.dumps(data).encode(), method=method)
        with opener.open(req, timeout=5) as response:
            return json.load(response)
    issue = request("GET")
    if (issue.get("companyId") != os.environ["PAPERCLIP_COMPANY_ID"]
            or issue.get("assigneeAgentId") != os.environ["PAPERCLIP_AGENT_ID"]
            or issue.get("status") == "cancelled"):
        raise ValueError("CTO occurrence identity or ownership mismatch")
    if issue.get("status") == "done":
        return
    comment = "CTO preflight: " + json.dumps(result) + ". No puzzle work selected; this check is complete."
    updated = request("PATCH", {"status": "done", "comment": comment})
    if updated.get("status") != "done":
        raise ValueError("CTO occurrence disposition was not persisted")


def run(args, check=check_cycle, launch=os.execv, probe=subprocess.run, finish=None):
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
