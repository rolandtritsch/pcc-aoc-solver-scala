"""State-repair: reconcile every part from the repo, under a fenced lease.

Replaces the inline "full 2015+ rewalk" that used to live in
`Controller.select()`. Same self-healing behavior, now expressed as the
reconcile() tick from aoc_state.py and exercised by its own test suite
instead of being embedded in the Paperclip-dispatch control flow.
"""
from pathlib import Path

from aoc_state import ACCEPTED, CANDIDATE_PRESENT, FileLeaseStore, reconcile
from common import calendar, finale, identity
from repository import load_progress, save_progress


def candidate_present(repo_path, year, day, part):
    day_dir = Path(repo_path) / str(year) / "src/main/scala" / f"aoc{year}" / f"day{day:02}"
    return (day_dir / f"Part{part}.scala").exists()


def next_unsolved(repo, site):
    """Reconcile the whole calendar against repo + progress.json receipts,
    self-healing any drift, and return the first (year, day, part) with no
    accepted receipt. Mirrors the old `Controller.select()` rewalk, but
    every decision now goes through the same pure `reconcile()` the test
    suite exercises -- no inline duplicate logic.

    Does not query the live site for undiscovered parts; that remains the
    caller's job (via `self.site.page(...)` in workflow.py) once a specific
    next part is chosen, exactly as before. This function only answers
    "what does the repo already show as accepted or candidate", which is
    read-only and safe to call on every tick.
    """
    progress = load_progress(repo, site.account)
    for year, day, part in calendar():
        key = identity(year, day, part)
        receipt = progress["parts"].get(key)
        has_code = finale(year, day, part) or candidate_present(repo.path, year, day, part)
        state = reconcile(has_code, receipt)
        if state == ACCEPTED:
            continue
        return year, day, part, state
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
