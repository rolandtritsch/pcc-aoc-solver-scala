"""Guards against the drift the original design suffered from: progress.json
being written outside the sanctioned path (docs/2026-11-25_refactor-analysis.md
"Bad" finding -- nothing stopped a future script from writing it directly).

Only two sites may write `.aoc/progress.json`:
  - repository.save_progress() -- the sanctioned projector.
  - operators/aoc.py's audited, human-approved destructive-recovery reset
    (requires an explicit approval hash, takes a backup, resets to an empty
    schema-valid baseline and defers population to reconciliation).
"""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ALLOWED_WRITERS = {
    "skills/aoc-runtime/scripts/repository.py",
    "operators/aoc.py",
}
WRITE_CALL = re.compile(r"write_json\(|\.write_text\(|\.write_bytes\(")


class ProgressIntegrityTests(unittest.TestCase):
    def test_only_sanctioned_code_writes_progress_json(self):
        offenders = []
        for path in ROOT.rglob("*.py"):
            rel = str(path.relative_to(ROOT))
            if rel.startswith("tests/") or rel in ALLOWED_WRITERS:
                continue
            text = path.read_text()
            if "progress.json" in text and WRITE_CALL.search(text):
                offenders.append(rel)
        self.assertEqual(offenders, [],
            f"Unsanctioned progress.json write site(s): {offenders}")


if __name__ == "__main__":
    unittest.main()
