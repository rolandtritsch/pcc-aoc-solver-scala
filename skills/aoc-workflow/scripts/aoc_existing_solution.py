#!/usr/bin/env python3
"""Detect whether scala3-aoc already has a verified, passing solution for a day/part."""
import argparse
from pathlib import Path
import re
import subprocess
import sys
import tempfile


class CheckError(RuntimeError):
    pass


def command(repo, args, timeout=600):
    # No shell/pipeline: a failed sbt process cannot be hidden by tail.
    with tempfile.NamedTemporaryFile(mode="w+", prefix="aoc-existing-",
                                     suffix=".log", delete=False) as log:
        try:
            result = subprocess.run(args, cwd=repo, stdout=log,
                                    stderr=subprocess.STDOUT, timeout=timeout)
        except subprocess.TimeoutExpired:
            raise CheckError(f"{args[0]} timed out; private diagnostics: {log.name}") from None
        log.seek(0)
        output = log.read()
    if result.returncode:
        raise CheckError(f"{args[0]} exited {result.returncode}; private diagnostics: {log.name}")
    Path(log.name).unlink()
    return re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", output)


def git(repo, *args):
    return command(repo, ["git", *args], 60).rstrip("\n")


def source_file(repo, year, day):
    return repo / str(year) / "src" / "main" / "scala" / f"aoc{year}" / f"Day{day:02d}.scala"


def test_file(repo, year, day):
    return repo / str(year) / "src" / "test" / "scala" / f"aoc{year}" / f"Day{day:02d}Test.scala"


def has_real_input_case(test_text, day, part):
    """Require a test naming convention tying the assertion to the real puzzle input,
    not just the official examples, before treating a part as genuinely solved."""
    pattern = re.compile(rf"Day0*{day}\s*-\s*part{part}\s*-\s*real input", re.I)
    return bool(pattern.search(test_text))


def tests_passed(output):
    match = re.search(r"Total\s+(\d+),\s*Failed\s+(\d+),\s*Errors\s+(\d+)", output)
    if not match:
        return False
    total, failed, errors = (int(value) for value in match.groups())
    return total > 0 and failed == 0 and errors == 0


def find_existing_commit(repo, year, day, part, run=command):
    """Return the full commit sha that last touched this day's files if a passing,
    real-input-verified solution already exists for the given part; else None."""
    repo = Path(repo)
    src = source_file(repo, year, day)
    test = test_file(repo, year, day)
    if not src.is_file() or not test.is_file():
        return None
    if not has_real_input_case(test.read_text(), day, part):
        return None
    try:
        output = run(repo / str(year), ["sbt", "--batch", f"testOnly *Day{day:02d}Test*"])
    except CheckError:
        return None
    if not tests_passed(output):
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
