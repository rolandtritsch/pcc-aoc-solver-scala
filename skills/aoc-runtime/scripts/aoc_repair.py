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

from aoc_state import reconcile
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
                    # Expected, not corruption: repository.hashes() scopes by
                    # DAY, not by PART, so part1's stored receipt goes stale
                    # the instant part2's files are committed to the same
                    # day -- which happens on every single day with two
                    # parts. Re-running a local verify here predictably
                    # fails for reasons unrelated to this part's own
                    # correctness, and doing so from next_unsolved() plus
                    # again from workflow.py's own CANDIDATE_PRESENT check
                    # cascades into a second verify() against now-dirty
                    # state and an uncaught crash (hit live 2026-11-25 on
                    # day19, the first day authorized after day18 added a
                    # part2). The site already confirms acceptance
                    # (entry["site"], asserted above) -- that is this
                    # project's actual acceptance oracle. Trust it; never
                    # re-solve or discard an already-accepted part because
                    # a LATER, unrelated part changed.
                    pass
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
