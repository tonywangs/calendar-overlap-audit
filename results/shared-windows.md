# Shared-window validation and bounded observations

This feature implements a conservative VFREEBUSY import contract, explicit
participant working hours and an auditable intersection of known free time.
It does not introduce a new scheduling algorithm or establish real-world
availability. The original commands, examples and historical measurements remain.

## Reproduction

After preparing the dependencies, wheelhouse and Chromium described in the
repository README, run `.venv/bin/python scripts/verify_shared.py` offline.
The gate authenticates measured source and input hashes, executes the full
production suite and frozen regressions, reproduces synthetic examples, installs
a wheel in an isolated environment, and replays bounded workloads. Timings are
observations; only outcomes and deterministic hashes are replay assertions.

## Semantic and operational evidence

The shared-window suite includes 512 fixed seeds (55,451,000–55,451,511) with
1–5 participants, 1–3 coverage sources per person, mixed busy types and FREE,
start/end and start/duration forms, duplicate/unsorted periods, overlapping
working windows and nine minimum durations. An independent oracle enumerates
600 one-second cells per case and run-length encodes them. It checks each
participant's coverage, unknown gaps, busy, working and free sets as well as the
final shared windows. It does not call production interval operations.
`icalendar==6.3.2` independently decodes every accepted seeded calendar.

Hand-specified cases cover exact-second duration boundaries, empty occupancy,
adjacent periods and shifts, disjoint/partial/outside coverage, busy-over-FREE
conflicts across complete sources, all 16 participants over 90 days, previous-day
overnight spill, and New York spring/fall transitions. The overnight transition
cases last three and five elapsed hours respectively. Ambiguous/nonexistent
boundaries, missing completeness assertions, multiple component/owner ambiguity,
unsupported semantics, malformed and overflowing periods, duplicate fields,
invalid UTF-8 and byte/period limits are rejected.

CLI checks cover repeated identical artifacts, unchanged input hashes,
export/import round trips, restrictive output permissions, all exposed resource
caps, FIFO rejection, existing output collisions (including symlinks), a
reservation race, failed JSON/HTML serialization, disk and rename failures,
SIGINT/SIGTERM during parsing/serialization/writes, actual timer interruption,
and cleanup of owned partial output.

Network-blocked Chromium checks exercise 375px and 1280px widths: UTC-date
intersection filtering across midnight, elapsed-duration filters, native window
inspection, participant evidence links, skip navigation, keyboard activation,
Escape/reset, hidden-window hash navigation and no horizontal overflow. Hostile
aliases render as text and hostile imported comments do not enter the report.
JavaScript-disabled disclosure/inspection also works. These automated checks
are not a human usability or formal accessibility study.

The isolated installed workflow exports two synthetic VEVENT calendars to
VFREEBUSY, imports them through the manifest, and discovers the four independently
specified candidate ranges totaling 16,200 seconds. Sam's last nine horizon hours
remain explicitly unknown. Two executions exactly match the committed JSON and
HTML. Sockets are denied and input hashes remain unchanged.

## Negative findings and evidence preservation

An early independent comparison rejected lowercase UTC markers in the pinned
reader. The production subset now explicitly requires uppercase T/Z and duration
letters, with ASCII numeric fields; a rejection test preserves that finding.
No compatibility claim is made for syntax outside the documented subset.

The original free/busy gate initially completed its tests but failed historical
source authentication once new modules were added: the old benchmark hashed all
Python files. Historical schedule/free-busy replays now reconstruct their exact
measured source from `tests/baseline/freebusy-v1.json`, authenticate every file
against the saved measurements, and verify that old production source remains
unchanged. Only packaging's added command differs. The frozen index regression
suite excludes the new shared tests because that historical package lacks the
feature; the current production suite includes them. Historical result files
and examples are unchanged.

## Measurement protocol

`benchmark-shared.json` contains two fresh socket-blocked Python processes for
each workload, with input/implementation SHA-256, exact artifact hashes/sizes,
limits, Python/platform and pinned dependency versions. CLI seconds cover the
command after importing it; parent elapsed includes interpreter startup. Peak
RSS is Linux `/proc/self/status` VmHWM for the child, not inherited process-family
RSS. Runs took place on a shared host; no speed or memory improvement is claimed.

Five negative workloads deliberately exceed the period, retained-window, report,
computation or wall-time budget. Each exits 2, emits no report and leaves no staging
directory. A workload may hit a report or runtime bound before other numeric
ceilings: the limits are rejection guards, not a guarantee that every combination
of maximum inputs will yield a report.

## Remaining limits

Provider interoperability, human usability and real participant availability are
unvalidated. Completeness and ownership are operator assertions; input hashes do
not prove either. Only the documented subset is accepted; no scheduling-message
or attendee interpretation, freshness inference, holiday exceptions or booking
operation exists. Pinned tzdata 2025.2 can differ from newer civil-time rules.
Precise times/schedules and hashes remain sensitive despite excluding imported
metadata. Linux/Python 3.12 was exercised; other platforms and catastrophic
termination are outside these measurements. RSS is observed, not an enforced OS
memory cap. The synthetic tests are not a proof for all calendar data.

## Recorded bounded workload observations

Measured 2026-10-10T01:19:27.543290+00:00; Python 3.12.3. Two observations per row.

| Workload | Exit | Parent elapsed range (s) | Peak RSS range (KiB) | JSON bytes | HTML bytes |
| --- | ---: | ---: | ---: | ---: | ---: |
| `empty_16_people_32_files_90_days` | 0 | 0.717–0.773 | 25,680–25,696 | 45239 | 34350 |
| `sparse_2000_four_people` | 0 | 2.120–2.207 | 39,524–39,528 | 2528778 | 2073616 |
| `dense_20000_sixteen_people` | 0 | 2.007–2.033 | 26,308–26,332 | 44669 | 32645 |
| `spring_overnight` | 0 | 0.605–0.611 | 25,396–25,440 | 3449 | 6636 |
| `fall_overnight` | 0 | 0.525–0.572 | 25,372–25,396 | 3449 | 6636 |
| `disjoint_coverage` | 0 | 0.492–0.570 | 25,384–25,484 | 5749 | 7781 |
| `period_limit` | 2 | 1.721–1.866 | 32,624–32,880 | — | — |
| `window_limit` | 2 | 2.733–4.520 | 68,980–69,108 | — | — |
| `report_limit` | 2 | 0.466–0.469 | 31,840–31,844 | — | — |
| `operations_limit` | 2 | 0.242–0.260 | 25,352–25,432 | — | — |
| `runtime_limit` | 2 | 0.282–0.283 | 25,268–25,300 | — | — |

Dependency versions: `icalendar==6.3.2`, `playwright==1.55.0`, `pytest==8.4.2`, `python-dateutil==2.9.0.post0`, `six==1.17.0`, `tzdata==2025.2`.

Both repeats have identical output hashes and outcomes for each workload. Full input, implementation and output SHA-256 values and unrounded timings are in [the raw evidence](benchmark-shared.json).

## Final verification

On October 10, 2026, `.venv/bin/python scripts/verify_shared.py` exited 0:

- 2,456 production tests passed in 113.50 seconds, including 732 shared-feature
  checks (512 seeded oracle cases) and all 1,724 pre-existing tests.
- 457 frozen index-era regressions passed in 34.27 seconds against their
  authenticated historical import path.
- Historical occurrence, index, schedule and free/busy workload replays passed;
  the reconstructed schedule worker includes its authenticated transitive helper.
- Isolated installed CLIs, byte-identical examples, network-blocked Chromium,
  unchanged input hashes and all eleven shared workload replays passed.
- Publication bounds and `git diff --check` passed.

These are actual verification outcomes. Expected exit-2 workload rejections are
counted as validated failure behavior, not as completed availability analyses.
