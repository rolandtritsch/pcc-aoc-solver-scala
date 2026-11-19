#!/usr/bin/env python3
"""Validate a review result against the full issue JSON and provenance coverage.

Usage: verify_review_block.py --issue-file ISSUE.json [--body-file COMMENT.md]
The issue JSON must contain id, title and the submitter's description/receipt.
Comment body defaults to stdin. This validates evidence declarations, not the
truth of an audit: the reviewer must inspect the complete tool logs first.
"""

import argparse
from pathlib import Path
import json
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "aoc-workflow" / "scripts"))
from aoc_review_contract import block, validate


def verify(issue, body):
    try:
        result = validate(issue, block(body, "aoc-review-result"))
        return True, "valid block recording " + ("repair" if result["repairRequired"] else "acceptance" if result["accepted"] else "inconclusive verdict")
    except (ValueError, TypeError, KeyError) as error:
        return False, str(error)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--issue-file", required=True)
    parser.add_argument("--body-file")
    args = parser.parse_args(argv)
    issue = json.loads(Path(args.issue_file).read_text())
    body = Path(args.body_file).read_text() if args.body_file else sys.stdin.read()
    ok, detail = verify(issue, body)
    print(("OK: " if ok else "DEFECT: ") + detail)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
