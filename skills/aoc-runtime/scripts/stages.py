"""Mechanical gathering and submission with durable uncertain outcomes."""
import time
from urllib.parse import urlencode

from common import Blocked, finale, identity, now, read_json, write_json
from publication import verify
from aoc_site import verdict


def _scrub(article):
    # AoC's fetched article HTML can leave trailing whitespace on interior
    # lines too (e.g. day 25's ASCII chimney-weight table), not just a
    # trailing blank line at the end -- git diff --cached --check flags
    # either, aborting the gather commit before it starts.
    lines = [line.rstrip() for line in article.splitlines()]
    while lines and not lines[-1]:
        lines.pop()
    return "\n".join(lines)


def gather(repo, site, assignment):
    year, day, part = (assignment[k] for k in ("year", "day", "part"))
    identity(year, day, part)
    repo.bootstrap(year)
    page = site.page(year, day)
    if len(page["articles"]) < part:
        raise Blocked("Assigned part statement is locked")
    statement = f"{year}/problems/Day{day:02}Problem.txt"
    target = repo.path / statement
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("\n\n".join(_scrub(a) for a in page["articles"][:part]) + "\n")
    input_name = f"{year}/src/main/resources/inputs/Day{day:02}.txt"
    path = repo.path / input_name
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists() and not finale(year, day, part):
        content = site.fetch(year, day, "/input")
        if not content or not content.endswith("\n") or "<html" in content.lower() or "log in" in content.lower():
            raise Blocked("Unrecognized personal input")
        path.write_text(content)
    files = [statement] + ([input_name] if path.exists() else [])
    commit = repo.commit(files, f"{year} Day{day:02}: gather part {part}")
    return {"outcome": "gathered", "commit": commit, "files": files}


def submit(repo, site, assignment, receipt, checkpoint, persist=lambda value: None, sleep=time.sleep,
           rejected_answers=()):
    year, day, part = (assignment[k] for k in ("year", "day", "part"))
    identity(year, day, part)
    repo.assert_owner()
    page = site.page(year, day)
    final = finale(year, day, part)
    if not final:
        if not receipt or any(receipt.get(k) != assignment[k] for k in ("year", "day", "part")):
            raise Blocked("Missing/mismatched publication receipt")
        repo.validate_receipt(receipt)
        if page["complete"] >= part:
            if len(page["answers"]) < part or page["answers"][part - 1] != receipt["answer"]:
                raise Blocked("Accepted site answer and publication disagree")
            return {"outcome": "accepted", "receipt": receipt, "site": evidence(page)}
    elif page["complete"] >= 2:
        return {"outcome": "accepted", "kind": "finale", "site": evidence(page)}

    state = read_json(checkpoint, {})
    if state.get("outcome") in ("intent", "uncertain", "rejected"):
        raise Blocked("Previous submission unresolved/rejected; operator or next authorization required")
    if final:
        # Only the known noncomputational level=2 form is supported. No numeric answer.
        html = site.fetch(year, day)
        if page["complete"] != 1 or not ('name="level" value="2"' in html and 'name="answer"' not in html):
            raise Blocked("Finale prerequisites/interaction need operator inspection")
        data = urlencode({"level": 2}).encode()
    else:
        if receipt["answer"] in rejected_answers:
            raise Blocked("Previously rejected answer cannot be posted unchanged")
        receipt = verify(repo, year, day, part, receipt["answer"])
        data = urlencode({"level": part, "answer": receipt["answer"]}).encode()
    for retry in range(3):
        repo.assert_owner()
        state = {"outcome": "intent", "attempt": retry, "at": now()}
        write_json(checkpoint, state)
        persist(state)  # Must reach Paperclip before a non-idempotent POST.
        try:
            outcome, text, delay = verdict(site.fetch(year, day, "/answer", data))
        except Exception:
            outcome, text, delay = "uncertain", "Submission transport uncertain", None
        state = {"outcome": outcome, "verdict": text, "at": now(), "attempt": retry}
        write_json(checkpoint, state)
        persist(state)
        if outcome == "rate_limited" and retry < 2:
            sleep(delay)
            continue
        if outcome == "accepted":
            confirmed = site.page(year, day)
            if confirmed["complete"] < part:
                raise Blocked("Submission verdict not confirmed on puzzle page")
            return {**state, "receipt": receipt, "site": evidence(confirmed),
                    "kind": "finale" if final else "computational"}
        return {**state, "receipt": receipt}


def evidence(page):
    return {k: page[k] for k in ("account", "complete", "answers", "observedAt")}
