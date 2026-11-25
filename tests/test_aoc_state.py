"""Tests for the Option A reconciliation primitives (aoc_state.py).

Converts the three validated local spikes (2026-11-25: historical-drift
reconcile, real-build lease/fencing, real-process racing) into a fast,
no-network, no-sbt regression suite, per docs/2026-11-25_refactor-analysis.md's
"must-have, any option" testing tier.
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "skills/aoc-runtime/scripts"))

from aoc_state import (ACCEPTED, CANDIDATE_PRESENT, DISCOVERED,  # noqa: E402
                        NEEDS_OPERATOR, UNCERTAIN, FileLeaseStore, LeaseError,
                        LeaseStore, reconcile)


class ReconcileTests(unittest.TestCase):
    def test_receipt_accepted_wins_regardless_of_site(self):
        receipt = {"outcome": "accepted"}
        for site_status in (None, "unsolved", "uncertain", "accepted"):
            self.assertEqual(reconcile(True, receipt, site_status), ACCEPTED)
            self.assertEqual(reconcile(False, receipt, site_status), ACCEPTED)

    def test_site_accepted_with_candidate_is_accepted(self):
        self.assertEqual(reconcile(True, None, "accepted"), ACCEPTED)

    def test_site_accepted_without_candidate_never_fabricates(self):
        self.assertEqual(reconcile(False, None, "accepted"), NEEDS_OPERATOR)

    def test_uncertain_parks_and_never_blind_retries(self):
        self.assertEqual(reconcile(True, None, "uncertain"), UNCERTAIN)
        self.assertEqual(reconcile(False, None, "uncertain"), UNCERTAIN)

    def test_no_evidence_reflects_candidate_presence(self):
        self.assertEqual(reconcile(True, None, None), CANDIDATE_PRESENT)
        self.assertEqual(reconcile(False, None, None), DISCOVERED)

    def test_idempotent(self):
        args = (True, {"outcome": "accepted"}, None)
        self.assertEqual(reconcile(*args), reconcile(*args))


class LeaseStoreTests(unittest.TestCase):
    def test_acquire_then_renew_extends_expiry(self):
        store = LeaseStore()
        lease = store.acquire("owner-a", ttl=10, at=0)
        self.assertFalse(store.is_expired(at=5))
        store.renew(lease.fence_token, ttl=10, at=5)
        self.assertFalse(store.is_expired(at=14))

    def test_cannot_acquire_while_unexpired(self):
        store = LeaseStore()
        store.acquire("owner-a", ttl=10, at=0)
        with self.assertRaises(LeaseError):
            store.acquire("owner-b", ttl=10, at=5)

    def test_expired_lease_can_be_reacquired_and_bumps_fence(self):
        store = LeaseStore()
        first = store.acquire("owner-a", ttl=10, at=0)
        second = store.acquire("owner-b", ttl=10, at=11)
        self.assertEqual(second.fence_token, first.fence_token + 1)

    def test_stale_fence_cannot_renew(self):
        store = LeaseStore()
        lease = store.acquire("owner-a", ttl=5, at=0)
        store.acquire("owner-b", ttl=5, at=6)  # expired; reacquire bumps fence
        with self.assertRaises(LeaseError):
            store.renew(lease.fence_token, ttl=5, at=7)

    def test_stale_effect_rejected_after_fence_bump(self):
        store = LeaseStore()
        lease = store.acquire("owner-a", ttl=5, at=0)
        store.acquire("owner-b", ttl=5, at=6)
        with self.assertRaises(LeaseError):
            store.submit_effect(lease.fence_token, "late result", at=7)

    def test_valid_effect_accepted(self):
        store = LeaseStore()
        lease = store.acquire("owner-a", ttl=10, at=0)
        self.assertEqual(store.submit_effect(lease.fence_token, "result", at=1), "result")


class FileLeaseStoreRaceTests(unittest.TestCase):
    """Real OS-process race, trimmed down from the racing-instances spike
    (no sbt; just the lock primitive) so it stays fast and deterministic
    enough for a CI-style run."""

    def test_only_one_of_many_forked_children_acquires(self):
        with tempfile.TemporaryDirectory() as lease_dir:
            n_children = 8
            read_fds, write_fds = zip(*(os.pipe() for _ in range(n_children)))
            pids = []
            for i in range(n_children):
                pid = os.fork()
                if pid == 0:
                    for fd in read_fds:
                        os.close(fd)
                    import time
                    store = FileLeaseStore(lease_dir, "2015/01/1")
                    try:
                        store.acquire(f"child-{i}", ttl=2)
                        os.write(write_fds[i], b"ACCEPTED")
                        # Hold the lock briefly so siblings forking within
                        # this window genuinely contend for it, matching
                        # the real racing-instances spike's shape.
                        time.sleep(0.2)
                    except LeaseError:
                        os.write(write_fds[i], b"DENIED")
                    finally:
                        store.release()
                        os.close(write_fds[i])
                    os._exit(0)
                pids.append(pid)
            for fd in write_fds:
                os.close(fd)
            results = []
            for fd in read_fds:
                results.append(os.read(fd, 16))
                os.close(fd)
            for pid in pids:
                os.waitpid(pid, 0)

            accepted = [r for r in results if r == b"ACCEPTED"]
            denied = [r for r in results if r == b"DENIED"]
            self.assertEqual(len(accepted), 1)
            self.assertEqual(len(denied), n_children - 1)


if __name__ == "__main__":
    unittest.main()
