"""State-repair: reconcile every part from the repo, the live site, and
.aoc/progress.json, self-healing drift along the way.

This is the single, sole implementation of what used to be duplicated as an
inline loop in `Controller.select()` (docs/2026-11-25_refactor-analysis.md's
"full 2015+ rewalk"). `workflow.py`'s `select()` now calls `next_unsolved()`
directly and only owns the Paperclip-specific dispatch step (creating a
control task and choosing where its stage pipeline starts) -- every
reconciliation decision lives here, with its own test suite.
"""
from pathlib import Path

from aoc_state import CANDIDATE_PRESENT, FileLeaseStore, reconcile
from common import Blocked, calendar, finale, identity
from publication import verify
from repository import load_progress, save_progress
from stages import evidence


def candidate_present(repo_path, year, day, part):
    day_dir = Path(repo_path) / str(year) / "src/main/scala" / f"aoc{year}" / f"day{day:02}"
    return (day_dir / f"Part{part}.scala").exists()


def next_unsolved(repo, site):
    """Reconcile the whole calendar against repo + site + progress.json,
    self-healing drift exactly as the original inline loop did (same
    Blocked messages, same repair branches), and return
    `(year, day, part, state)` for the first part with no accepted receipt,
    or `None` if all 524 parts are accepted. `state` is `CANDIDATE_PRESENT`
    or `DISCOVERED` (see aoc_state.py) -- never `ACCEPTED`, since accepted
    parts are reconciled and skipped, not returned.
    """
    progress = load_progress(repo, site.account)
    for year, day, part in calendar():
        key = identity(year, day, part)
        entry = progress["parts"].get(key)
        if entry:
            if entry.get("outcome") != "accepted" or not entry.get("site"):
                raise Blocked("Invalid progress entry")
            if not finale(year, day, part):
                try:
                    repo.validate_receipt(entry["receipt"])
                except Blocked:
                    page = site.page(year, day)
                    receipt = verify(repo, year, day, part)
                    if (page["complete"] < part or len(page["answers"]) < part
                            or page["answers"][part - 1] != receipt["answer"]):
                        raise Blocked("Changed historical solution disagrees with site")
                    entry["receipt"], entry["site"] = receipt, evidence(page)
                    save_progress(repo, progress)
            continue
        page = site.page(year, day)
        if page["complete"] >= part:
            receipt = None if finale(year, day, part) else verify(repo, year, day, part)
            if receipt and (len(page["answers"]) < part or page["answers"][part - 1] != receipt["answer"]):
                raise Blocked("Historical code does not reproduce site's accepted answer")
            progress["parts"][key] = {"outcome": "accepted", "kind": "reconciled",
                "receipt": receipt, "site": evidence(page)}
            save_progress(repo, progress)
            continue
        has_code = candidate_present(repo.path, year, day, part)
        return year, day, part, reconcile(has_code, None, None)
    return None


def repair(repo, site, lease_dir, owner, ttl=120):
    """First-class repair procedure: acquire a fenced lease over the whole
    calendar, resync the repo, and return the next part to work plus its
    reconciled state. Raises Blocked if another owner already holds repair.
    """
    store = FileLeaseStore(lease_dir, "repair")
    lease = store.acquire(owner, ttl)
    try:
        repo.sync()
        result = next_unsolved(repo, site)
        if result is None:
            return {"outcome": "complete", "parts": len(calendar())}
        year, day, part, state = result
        if state == CANDIDATE_PRESENT:
            return {"outcome": "candidate", "year": year, "day": day, "part": part,
                    "fence_token": lease.fence_token}
        return {"outcome": "ready", "year": year, "day": day, "part": part,
                "fence_token": lease.fence_token}
    finally:
        store.release()
