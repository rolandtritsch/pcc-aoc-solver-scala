#!/usr/bin/env python3
"""Detect whether scala3-aoc already has a committed solution for a day/part.

A committed source/test pair is trusted without re-running sbt: the Solver's
publish helper (aoc-solve-scala/scripts/aoc_solver_publish.py publish) never
lets a commit/push happen unless its tests already passed, so a committed
real-input test case is itself the evidence. Re-verifying with sbt at
reconciliation time would be redundant JVM/compile cost for a fact already
established at commit time.
"""
import argparse
from pathlib import Path
import re
import subprocess
import sys


def git(repo, *args):
    result = subprocess.run(["git", *args], cwd=repo, capture_output=True,
                            text=True, timeout=60)
    if result.returncode:
        raise RuntimeError(f"git {args[0]} exited {result.returncode}: {result.stderr}")
    return result.stdout.rstrip("\n")


def source_file(repo, year, day):
    return repo / str(year) / "src" / "main" / "scala" / f"aoc{year}" / f"Day{day:02d}.scala"


def test_file(repo, year, day):
    return repo / str(year) / "src" / "test" / "scala" / f"aoc{year}" / f"Day{day:02d}Test.scala"


def has_real_input_case(test_text, day, part):
    """Require a test naming convention tying the assertion to the real puzzle input,
    not just the official examples, before treating a part as genuinely solved."""
    pattern = re.compile(rf"Day0*{day}\s*-\s*part{part}\s*-\s*real input", re.I)
    return bool(pattern.search(test_text))


def find_existing_commit(repo, year, day, part):
    """Return the full commit sha that last touched this day's files if a
    committed, real-input-test-named solution already exists for the given
    part; else None."""
    repo = Path(repo)
    src = source_file(repo, year, day)
    test = test_file(repo, year, day)
    if not src.is_file() or not test.is_file():
        return None
    if not has_real_input_case(test.read_text(), day, part):
        return None
    commit = git(repo, "log", "-1", "--format=%H", "--",
                str(src.relative_to(repo)), str(test.relative_to(repo)))
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        return None
    return commit


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-dir", required=True, type=Path)
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument("--day", type=int, required=True)
    parser.add_argument("--part", type=int, required=True, choices=(1, 2))
    args = parser.parse_args(argv)
    commit = find_existing_commit(args.repo_dir, args.year, args.day, args.part)
    print(commit or "unsolved")
    return 0 if commit else 1


if __name__ == "__main__":
    sys.exit(main())
