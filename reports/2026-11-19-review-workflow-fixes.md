# Review workflow fixes

Implemented after inspecting [AOC-6][] and [AOC-11][] on November 19, 2026.
Both Day01 answers remain accepted; no puzzle-code repair was identified.

## Changes

- CTO preflight now persists a `wait`/`complete` decision and completes its owned
  coordination occurrence before exiting successfully. Failed disposition writes
  fail the run. Unknown evidence remains fail-closed. Recovered [AOC-9][], whose
  correct 06:00 wait decision had triggered recovery because the task stayed open.
- Gate and reviewer self-check share one review contract. The full commit must
  match the submitter's publication receipt in the full review description,
  including for generic submission-attempt titles. The gate fetches full issue
  details because issue-list descriptions can be truncated.
- Accepted advancement requires explicit provenance clearance, allowed sources,
  solver run IDs and complete log byte/tool-call coverage. Missing, partial or
  contaminated provenance cannot clear acceptance. Authenticated noncomputational
  finales have a separate, explicitly justified contract.
- Pipeline agents receive `AOC_COMPANY_PACKAGE_DIR`. Runtime skill-loader
  directories omitted supporting scripts during both solver runs; instructions
  now point directly to deployed company helpers instead of asking agents to
  rediscover or recreate them.
- Reviewer mechanical checks reuse the publication verifier, preserving
  formatting, executed assigned-day tests, exact runner output and clean
  HEAD/tracking/live-remote equality before and after checks. The two helpers in
  scala3-aoc now delegate to this package. The evidence checker has no skip-tests
  option, and its solution commit is mandatory.

## Audit migration

Inspected the complete available redacted solver logs, every recorded tool input
and the gatherer material. No prohibited solution lookup was observed. These
observations concern recorded behavior, not the model's training history.

| Part | Solver run | Log bytes | Tool actions |
| --- | --- | ---: | ---: |
| 1 | c6c89a2a-6879-4ee4-a7df-3e67bce4f84c | 263242 | 36 |
| 2 | e969cabf-dc28-4417-a300-b3f7983b8dd9 | 253657 | 31 |

Also inspected gatherer runs `77e93d22-ca6e-4345-b886-6847488bc419`
(151860 bytes, 24 tool actions) and `93e00801-c9a7-4e25-8e81-2c6c6515837b`
(249550 bytes, 41 tool actions). Two canceled part1 solver dispatches never
started and have no stored logs. Audit supplements preserve the original
solution commits and authoritative submission verdicts. An audit comment
reactivated AOC-6 during migration; its completed disposition was restored.

The contract validates evidence declarations. The reviewer must still perform
the actual audit and independently assess algorithm correctness/site acceptance.

## Verification and deployment

- All 128 offline tests pass locally and in the deployed package: workflow 47,
  review 8, publication 17 and WatchDog 56.
- Regression coverage includes generic-title wrong commits, missing/truncated
  handoff evidence, incomplete provenance, authenticated finale exemptions,
  owned-task completion, run audit headers and failed disposition writes.
- Deployed company files, CTO/reviewer instructions, managed skills and pipeline
  environment settings were updated. Existing bindings were preserved using
  configuration revisions; no credentials were copied into this repository.
- scala3-aoc helper consolidation is published as
  `d7523f0528342361679e15d454de7f68485099d9`, with clean HEAD/tracking/live-remote
  equality. Live verification passed formatting, assigned-day/full tests and
  runner answer `1771` using the consolidated helper.
- No new puzzle day or submission was started during verification. The daily
  routine retains its existing 06:00 Europe/Dublin schedule.

[AOC-6]: https://paperclip.tritsch.org/AOC/issues/AOC-6
[AOC-9]: https://paperclip.tritsch.org/AOC/issues/AOC-9
[AOC-11]: https://paperclip.tritsch.org/AOC/issues/AOC-11
