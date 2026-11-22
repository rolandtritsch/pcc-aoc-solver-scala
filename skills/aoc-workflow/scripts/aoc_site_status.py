#!/usr/bin/env python3
"""Read-only, authoritative check of a day's completion on adventofcode.com.

One request covers both parts of a day: the puzzle page itself states
"The first half of this puzzle is complete!" once part1 is accepted, and
"Both parts of this puzzle are complete!" once part2 is accepted too. This
is the live source of truth for whether a part is already solved -- faster
and more authoritative than re-deriving it from local evidence.
"""
import argparse
import sys
import urllib.request

BOTH_COMPLETE = "Both parts of this puzzle are complete!"
FIRST_COMPLETE = "The first half of this puzzle is complete!"


def fetch_page(year, day, session, timeout=10):
    request = urllib.request.Request(
        f"https://adventofcode.com/{year}/day/{day}",
        headers={"Cookie": f"session={session}"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read(1024 * 1024).decode("utf-8", errors="replace")


def parts_complete(html):
    """Return (part1_complete, part2_complete) from the puzzle page text."""
    if BOTH_COMPLETE in html:
        return True, True
    if FIRST_COMPLETE in html:
        return True, False
    return False, False


def is_part_complete(year, day, part, session, fetch=fetch_page):
    part1, part2 = parts_complete(fetch(year, day, session))
    return part2 if part == 2 else part1


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument("--day", type=int, required=True)
    parser.add_argument("--part", type=int, required=True, choices=(1, 2))
    args = parser.parse_args(argv)
    import os
    session = os.environ["AOC_SESSION"]
    complete = is_part_complete(args.year, args.day, args.part, session)
    print("complete" if complete else "incomplete")
    return 0 if complete else 1


if __name__ == "__main__":
    sys.exit(main())
