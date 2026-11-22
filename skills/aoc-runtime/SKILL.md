---
name: aoc-runtime
description: Execute the company's deterministic stages, publication, submission, and restart checkpoints
---

This is the complete executable company release. The tools-image launcher
verifies `release.json` before invoking `scripts/entry.py`. Use the emitted
`AOC_RUNTIME_DIR`, `AOC_REPO_DIR`, and `AOC_ASSIGNMENT` values; never infer a
solution checkout from Paperclip's dispatch directory.

Solver publication: `python3 "$AOC_RUNTIME_DIR/scripts/entry.py" publish
--answer ANSWER --files YEAR/path ...`. Only the CTO assigns downstream work.
Failures remain on the assigned stage with an explicit unblock action.

Do not change these imported files in a run. Operators publish another release.
