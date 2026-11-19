#!/usr/bin/env python3
"""OpenCode command wrapper: gate a CTO run before starting model inference."""

import contextlib
import io
import json
import os
import subprocess
import sys

from aoc_cycle_gate import main as check_cycle


def run(args, check=check_cycle, launch=os.execv, probe=subprocess.run):
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
            return 0 if mode in ("wait", "complete") and code == 1 else 2
    launch(binary, [binary, *args])
    return 0


if __name__ == "__main__":
    sys.exit(run(sys.argv[1:]))
