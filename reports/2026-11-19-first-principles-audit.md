# First-principles audit: 2015 Day01 part1

Audited on November 19, 2026 at the board's request.

## Result

The recorded solver run contains no web search, solution-page retrieval,
third-party implementation access or access to another solution repository.
Its observable work is consistent with independently deriving the implementation
from the official rules and validating it with samples and a separate count.
The original instructions required algorithm design and tests but did not
explicitly prohibit solution lookup. That prohibition is now explicit in the
company package and deployed agent/skill instructions.

## Evidence and coverage

- [Solver assignment AOC-4][solver-issue], run
  `c6c89a2a-6879-4ee4-a7df-3e67bce4f84c`, succeeded from 05:47:04 to
  05:50:22 UTC on November 19, 2026.
- Retrieved the complete uncompressed run log: 263,242 bytes, matching the
  run's recorded `logBytes`; parsed all 120 provider records.
- Reviewed all 36 tool actions: 3 skill loads, 11 reads, 1 glob, 17 shell
  commands, 3 writes and 1 edit. There were no search or web-fetch tool calls.
- The first reads of `Day01.scala` and `Day01Test.scala` returned file-not-found.
  Solver then created both files; it did not open an existing Day01 solution.
- Allowed reads were the official cached statement and personal input, repository
  guidance, the Day00 template, build configuration and company publication
  helper. Repository history contained this cycle's template/bootstrap/material.
- Shell commands inspected those files, counted input characters, ran sbt,
  discovered/invoked the publication helper and updated the Paperclip task.
  The helper performs Paperclip API calls and Git operations on the canonical
  repository; these are coordination/publication, not solution research.
  Build dependency downloads are also allowed generic tooling traffic.

## Algorithm and independent verification

The official rules map an opening parenthesis to one floor up and a closing
parenthesis to one floor down, starting at zero. Accumulating those increments
therefore yields the final floor: linear time and constant auxiliary space.

Before writing the Scala implementation, the solver independently counted
3,569 opening and 3,431 closing parentheses in the personal input, obtaining
`3569 - 3431 = 138`. It then wrote the Scala fold and tested the official
examples, empty input, single-character boundaries and the real input.
The full year project passed 38 tests. An additional operator count also
returned 138. Advent of Code accepted the answer; [AOC-6][review-issue] completed
review with `accepted: true` and `repairRequired: false`.

The [solution commit][solution] is
`7da3db8a6f9bcc6f3603da53c412026592d466ef` in `rolandtritsch/scala3-aoc`.

## Limits

This audits recorded tool actions and artifacts. It cannot establish what was
in the model's training data or prove the absence of internal prior knowledge.
The new policy prohibits relying on remembered puzzle-specific solutions as a
substitute for deriving and independently validating the algorithm. It also
requires source disclosure and a reviewer provenance check for future parts.
The policy is not a network sandbox: generic documentation, dependencies,
coordination and publication still require network access.

[solver-issue]: https://paperclip.tritsch.org/AOC/issues/AOC-4
[review-issue]: https://paperclip.tritsch.org/AOC/issues/AOC-6
[solution]: https://github.com/rolandtritsch/scala3-aoc/commit/7da3db8a6f9bcc6f3603da53c412026592d466ef
