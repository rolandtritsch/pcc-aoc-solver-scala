"""Shared review contract: bind verdicts to handoff evidence and log coverage."""

import json
import re

SHA = re.compile(r"^[0-9a-f]{40}$")


def block(body, name):
    matches = re.findall(r"```" + re.escape(name) + r"\s*(\{.*?\})\s*```", body or "", re.S)
    if len(matches) != 1:
        raise ValueError(f"expected exactly one {name} block")
    value = json.loads(matches[0])
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be an object")
    return value


def identity(title):
    match = re.search(r"\bAoC\s+(20\d{2})\s+Day\s*0*(\d+)\s*part\s*([12])\b", title or "", re.I)
    if not match:
        raise ValueError("cannot parse year/day/part from issue title")
    year, day, part = map(int, match.groups())
    if not (2015 <= year <= 2025 and 1 <= day <= (12 if year == 2025 else 25)):
        raise ValueError("year/day outside supported calendar")
    return year, day, part


def expected_commit(issue):
    """Read the submitter's receipt, never the reviewer's result or title alone."""
    description = issue.get("description") or ""
    selected = identity(issue["title"])
    if "```aoc-solver-publication" in description:
        receipt = block(description, "aoc-solver-publication")
        if tuple(receipt.get(k) for k in ("year", "day", "part")) != selected:
            raise ValueError("handoff receipt year/day/part mismatch")
        commit = receipt.get("commit")
    else:
        context = block(description, "aoc-review-context")
        year, day, part = selected
        if context.get("kind") != "finale" or part != 2 or day != (12 if year == 2025 else 25):
            raise ValueError("computational review requires submitter publication receipt")
        commit = context.get("solutionCommit")
    if not isinstance(commit, str) or not SHA.fullmatch(commit):
        raise ValueError("handoff solution commit must be a full hex sha")
    return commit


def validate(issue, result):
    selected = identity(issue["title"])
    if result.get("reviewIssueId") != issue["id"]:
        raise ValueError("reviewIssueId does not match this review issue")
    for key, expected in zip(("year", "day", "part"), selected):
        if type(result.get(key)) is not int or result[key] != expected:
            raise ValueError(f"block {key} does not match issue {key}")
    if result.get("solutionCommit") != expected_commit(issue):
        raise ValueError("solutionCommit does not match handoff solution commit")
    attempt = (re.search(r"/\s*([0-9a-f]{7,40})\s*\)?\s*$", issue["title"])
               or re.search(r"attempt\s+commit\s+([0-9a-f]{7,40})", issue["title"], re.I))
    if attempt and not result["solutionCommit"].startswith(attempt.group(1)):
        raise ValueError("solutionCommit does not match attempt commit")
    for key in ("accepted", "repairRequired"):
        if type(result.get(key)) is not bool:
            raise ValueError(f"{key} must be true/false")
    provenance = result.get("provenance")
    if not isinstance(provenance, dict) or provenance.get("status") not in ("clear", "unknown", "contaminated", "not_applicable"):
        raise ValueError("explicit provenance status is required")
    if provenance["status"] == "not_applicable":
        year, day, part = selected
        if (part != 2 or day != (12 if year == 2025 else 25)
                or not provenance.get("reason") or "```aoc-solver-publication" in (issue.get("description") or "")):
            raise ValueError("provenance exemption requires a noncomputational finale and reason")
    if provenance["status"] == "clear":
        logs = provenance.get("solverRuns")
        if (not isinstance(logs, list) or not logs
                or not isinstance(provenance.get("sources"), list) or not provenance["sources"]
                or any(not isinstance(source, str) or not source.strip() for source in provenance["sources"])):
            raise ValueError("provenance clearance requires solver logs and sources")
        for log in logs:
            if (not isinstance(log, dict) or not log.get("runId") or log.get("complete") is not True
                    or type(log.get("logBytes")) is not int or log["logBytes"] <= 0
                    or type(log.get("toolCalls")) is not int or log["toolCalls"] <= 0):
                raise ValueError("provenance clearance requires complete solver log coverage")
    if result["accepted"] and not result["repairRequired"] and provenance["status"] not in ("clear", "not_applicable"):
        raise ValueError("provenance has not cleared advancement")
    return result
