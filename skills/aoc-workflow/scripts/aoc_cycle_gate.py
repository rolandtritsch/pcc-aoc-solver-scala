#!/usr/bin/env python3
"""Read-only, fail-closed guard before CTO puzzle selection. No model or Git calls."""

import datetime as dt
import json
import os
import re
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from aoc_review_contract import block, validate

STAGES = {
    "Problem Gatherer": "gather", "Problem Solver": "solve",
    "Problem Submitter": "submit", "Solution Reviewer": "review",
}
SEASON_PARTS = {(year, day, part) for year in range(2015, 2026)
                for day in range(1, (12 if year == 2025 else 25) + 1)
                for part in (1, 2)}
SEASON_FINAL = max(SEASON_PARTS)
OPEN = {"backlog", "todo", "in_progress", "in_review", "blocked"}


def days_in_season(year):
    return 12 if year == 2025 else 25


def next_part(last):
    """Pure, deterministic successor of a (year, day, part) triple. The
    caller is expected to check SEASON_FINAL separately; this raises rather
    than inventing 2026 work if it is called on it anyway."""
    year, day, part = last
    if last not in SEASON_PARTS:
        raise ValueError("last completed part is outside the supported calendar")
    if part == 1:
        return (year, day, 2)
    if day < days_in_season(year):
        return (year, day + 1, 1)
    if year < 2025:
        return (year + 1, 1, 1)
    raise ValueError("no part follows the final season part")


def read_last_part(repo_dir):
    """Read scala3-aoc's LAST.md: the fact of the last completed part,
    recorded by the Solution Reviewer. Missing/malformed evidence fails
    closed rather than guessing a starting point."""
    path = Path(repo_dir) / "LAST.md"
    text = path.read_text()
    match = re.search(r"```aoc-last\s*(\{.*?\})\s*```", text, re.S)
    if not match:
        raise ValueError("LAST.md is missing its aoc-last block")
    value = json.loads(match.group(1))
    last = (value.get("year"), value.get("day"), value.get("part"))
    if last not in SEASON_PARTS:
        raise ValueError("LAST.md records a part outside the supported calendar")
    return last


def timestamp(value):
    parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("cycle timestamp must include a timezone")
    return parsed


def part(issue):
    match = re.search(r"\bAoC\s+(20\d{2})\s+Day\s*0*(\d+)\s*part\s*([12])\b", issue["title"], re.I)
    if not match:
        raise ValueError("unrecognized current pipeline task: " + issue["identifier"])
    selected = tuple(map(int, match.groups()))
    if selected not in SEASON_PARTS:
        raise ValueError("year/day/part outside supported calendar")
    return selected


def review_result(issue, comments):
    """Require an explicit year-qualified review result; prose never clears the gate."""
    bodies = [c.get("body", "") for c in comments]
    for body in bodies:
        match = re.search(r"```aoc-review-result\s*(\{.*?\})\s*```", body, re.S)
        if match:
            result = validate(issue, block(body, "aoc-review-result"))
            if result.get("accepted") is True and result.get("repairRequired") is False:
                return "accepted"
            if result.get("repairRequired") is True:
                return "repair"
            return "unknown"
    return "unknown"


def evaluate(issues, agents, since, comments, live_runs, last_part, issue_detail=lambda row: row):
    start = timestamp(since)
    names = {a["id"]: a["name"] for a in agents}
    groups = {}
    for issue in issues:
        if timestamp(issue["createdAt"]) < start:
            continue
        stage = STAGES.get(names.get(issue.get("assigneeAgentId")))
        if not stage:
            continue
        groups.setdefault(part(issue), []).append((stage, issue))
    running = [r["id"] for r in live_runs
               if names.get(r.get("agentId")) in STAGES]
    if running:
        return {"mode": "wait", "runs": running, "reason": "specialist run is still active"}
    unfinished = [i["identifier"] for entries in groups.values()
                  for _, i in entries if i["status"] in OPEN]
    if unfinished:
        return {"mode": "wait", "issues": unfinished,
                "reason": "current cycle has unfinished stage tasks"}
    for selected in sorted(groups):
        entries = groups[selected]
        if all(i["status"] == "cancelled" for _, i in entries):
            continue
        open_issues = [i["identifier"] for _, i in entries if i["status"] in OPEN]
        if open_issues:
            return {"mode": "wait", "part": selected, "issues": open_issues,
                    "reason": "current cycle has unfinished stage tasks"}
        reviews = [i for stage, i in entries if stage == "review" and i["status"] == "done"]
        if not reviews:
            return {"mode": "wait", "part": selected, "reason": "completed review is missing"}
        latest = max(reviews, key=lambda i: timestamp(i["createdAt"]))
        latest = issue_detail(latest)
        result = review_result(latest, comments(latest["id"]))
        if result != "accepted":
            return {"mode": "repair" if result == "repair" else "wait", "part": selected,
                    "issues": [latest["identifier"]], "reason": "review has not cleared advancement"}
    if last_part == SEASON_FINAL:
        return {"mode": "complete", "reason": "LAST.md records the final season part accepted; archive finished"}
    return {"mode": "ready", "nextPart": list(next_part(last_part)),
            "reason": "LAST.md records the last accepted part with no unresolved current-cycle work"}


def main():
    try:
        base = os.environ["PAPERCLIP_API_URL"].rstrip("/")
        company = os.environ["PAPERCLIP_COMPANY_ID"]
        # The ephemeral run-scoped PAPERCLIP_API_KEY cannot authenticate company
        # reads for this ssh/legacy-runner execution shape (upstream Paperclip
        # gap; see paperclipai/paperclip#21591). Use a standing agent-scoped key
        # bound under a non-reserved name instead.
        token = os.environ["AOC_PAPERCLIP_API_KEY"]
        since = os.environ["AOC_CYCLE_STARTED_AT"]
        timestamp(since)
        last_part = read_last_part(os.environ["AOC_REPO_DIR"])
        deadline = time.monotonic() + 20

        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *args, **kwargs):
                return None

        opener = urllib.request.build_opener(NoRedirect)

        def get(path, require_list=True):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("gate telemetry deadline exceeded")
            request = urllib.request.Request(base + path, headers={"Authorization": "Bearer " + token})
            with opener.open(request, timeout=min(5, remaining)) as response:
                data = response.read(1024 * 1024 + 1)
                if len(data) > 1024 * 1024:
                    raise ValueError("gate response too large")
                result = json.loads(data)
                if require_list and not isinstance(result, list):
                    raise ValueError("gate response is not a list")
                return result

        prefix = "/api/companies/" + company
        agents = get(prefix + "/agents")
        issues = []
        for page in range(100):
            rows = get(prefix + "/issues?limit=100&offset=" + str(page * 100))
            issues.extend(rows)
            if len(rows) < 100:
                break
        else:
            raise ValueError("issue pagination exceeded bound")
        result = evaluate(issues, agents, since,
                          lambda id: get("/api/issues/" + id + "/comments"),
                          get(prefix + "/live-runs?minCount=0"),
                          last_part,
                          lambda row: get("/api/issues/" + row["id"], require_list=False))
        print(json.dumps(result))
        return 0 if result["mode"] == "ready" else 1
    except Exception as error:
        # Never echo request headers, credentials, or a provider response body.
        print(json.dumps({"mode": "unknown", "reason": type(error).__name__ + ": gate evidence unavailable"}))
        return 2


if __name__ == "__main__":
    sys.exit(main())
