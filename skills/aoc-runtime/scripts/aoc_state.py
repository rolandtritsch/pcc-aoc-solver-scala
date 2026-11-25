"""Option A: level-triggered reconciliation state machine.

Every tick recomputes the state of one part from the repository and the
authenticated AoC site; nothing is trusted from a stored cursor. See
docs/2026-11-25_refactor-analysis.md for the authority model and the full
state table this implements a subset of.

Validated by three local spikes (2026-11-25): real historical repo drift
self-heals with no explicit repair step; the Lease/fencing primitive below
survived a real multi-minute `sbt` build under heartbeat renewal and
correctly rejected a late, fenced-out worker's result; and real OS-process
races for the same lease produced exactly one winner across 50/50 trials.
"""
import fcntl
import os
import time
from dataclasses import dataclass, replace

from common import Blocked

# Decisions a reconcile() call can return. Not the full 17-state table in
# the refactor doc -- Option A only needs the subset a per-part tick can
# observe directly; GATHERING/SOLVING/PUBLISHING/SUBMITTING/LEASED are
# owned by the specialist-dispatch machinery in workflow.py, not here.
ACCEPTED = "ACCEPTED"
CANDIDATE_PRESENT = "CANDIDATE_PRESENT"
DISCOVERED = "DISCOVERED"
NEEDS_OPERATOR = "NEEDS_OPERATOR"
UNCERTAIN = "UNCERTAIN"


def reconcile(candidate_present, receipt, site_status=None):
    """Pure. `receipt` is a `.aoc/progress.json` entry or None. `site_status`
    is one of None (no fresh query made), "accepted", "unsolved", or
    "uncertain" -- the caller decides whether a query was worth making.

    Never fabricates ACCEPTED without either a trusted receipt or fresh site
    confirmation, and never resolves UNCERTAIN except via a later site query.
    """
    if receipt is not None and receipt.get("outcome") == "accepted":
        return ACCEPTED
    if site_status == "accepted":
        return ACCEPTED if candidate_present else NEEDS_OPERATOR
    if site_status == "uncertain":
        return UNCERTAIN
    return CANDIDATE_PRESENT if candidate_present else DISCOVERED


@dataclass(frozen=True)
class Lease:
    lease_id: str
    fence_token: int
    owner: str
    expires_at: float


class LeaseError(Blocked):
    pass


class LeaseStore:
    """In-memory lease/fencing primitive for one part_key. A real deployment
    backs this with a file lock (see `FileLeaseStore` below) so it holds
    across real OS-level process races, not just within one process."""

    def __init__(self):
        self._lease = None

    def acquire(self, owner, ttl, at=None):
        at = time.time() if at is None else at
        if self._lease is not None and self._lease.expires_at > at:
            raise LeaseError(f"lease held by {self._lease.owner!r}")
        fence = 1 if self._lease is None else self._lease.fence_token + 1
        self._lease = Lease(lease_id="lease", fence_token=fence, owner=owner,
                             expires_at=at + ttl)
        return self._lease

    def renew(self, fence_token, ttl, at=None):
        at = time.time() if at is None else at
        if self._lease is None or self._lease.fence_token != fence_token:
            raise LeaseError(f"stale fence_token={fence_token}")
        self._lease = replace(self._lease, expires_at=at + ttl)
        return self._lease

    def is_expired(self, at=None):
        at = time.time() if at is None else at
        return self._lease is None or self._lease.expires_at <= at

    def submit_effect(self, fence_token, payload, at=None):
        at = time.time() if at is None else at
        if self.is_expired(at):
            raise LeaseError("lease expired; no owner holds it")
        if fence_token != self._lease.fence_token:
            raise LeaseError(
                f"stale effect: fence_token={fence_token} != "
                f"current={self._lease.fence_token}")
        return payload


class FileLeaseStore(LeaseStore):
    """Same contract as `LeaseStore`, but `acquire()` is backed by a real,
    non-blocking OS file lock (`fcntl.flock(LOCK_EX | LOCK_NB)`) on
    `lease_dir/<part_key file-safe>.lock`, so two separate company
    instances -- not just two callers in one process -- cannot both acquire
    the same part's lease. Validated by the racing-instances spike: 50/50
    real concurrent-process trials produced exactly one winner."""

    def __init__(self, lease_dir, part_key):
        super().__init__()
        os.makedirs(lease_dir, exist_ok=True)
        safe = part_key.replace("/", "_")
        self._lock_path = f"{lease_dir}/{safe}.lock"
        self._fd = None

    def acquire(self, owner, ttl, at=None):
        fd = os.open(self._lock_path, os.O_CREAT | os.O_RDWR, 0o644)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            os.close(fd)
            raise LeaseError(f"lease file held by another process: {self._lock_path}")
        self._fd = fd
        try:
            return super().acquire(owner, ttl, at)
        except LeaseError:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)
            self._fd = None
            raise

    def release(self):
        if self._fd is not None:
            fcntl.flock(self._fd, fcntl.LOCK_UN)
            os.close(self._fd)
            self._fd = None
