# Schedule v2 validation

Measurements collected 2026-10-05 on Linux x86-64, kernel 6.8.0-124-generic,
glibc 2.39, Python 3.12.3; icalendar 6.3.2, tzdata 2025.2,
python-dateutil 2.9.0.post0 and six 1.17.0. All calendars are explicitly synthetic.
No personal data, paid inference or provider account was used.

## Observable behavior

The [example](../examples/schedule-report/report.html) has 57,600 working seconds,
28,800 occupied seconds and three qualifying gaps totaling 28,800 seconds. It
shows Friday fully booked, Saturday closed by its weekly schedule, Sunday opened
by a replacement, Monday closed by an empty replacement, and Tuesday split around
lunch. Inputs and output JSON/HTML reproduce byte for byte, including a fresh
wheel installed offline outside the repository.

Schedule v2 reuses the adopted occurrence index and interval complement. It adds
strict bounded validation and per-date explanations; it does not claim a novel
scheduling algorithm or RFC 7953 compatibility. Version 1's historical examples,
frozen implementations, benchmark observations and test log are retained.

## Reproducible workload observations

[`benchmark-schedule.json`](benchmark-schedule.json) retains both fresh-process
observations per workload, seed 20261005, exact specifications, input/output hashes,
artifact sizes, implementation hashes, applicable limits and environment details.
Runtime is CLI elapsed time including interpreter startup and writes. Peak RSS is
Linux `/proc/self/status` VmHWM inside each new process, not inherited pre-exec
`getrusage` RSS. Every worker blocks socket access. Input hashes are checked after
each run. The table reports median elapsed time and maximum peak RSS across two
runs; these are observations on a shared host, not timing guarantees.

| Synthetic workload | Effective windows | Median CLI seconds | Peak RSS KiB | JSON bytes | HTML bytes |
| --- | ---: | ---: | ---: | ---: | ---: |
| Maximum windows, empty calendar, 90 days | 1,440 | 1.067 | 38,208 | 1,168,431 | 1,308,582 |
| Split days, 100 daily series × 90 | 180 | 1.595 | 82,292 | 5,568,454 | 5,216,268 |
| 90 dated replacements, same series | 120 | 1.465 | 77,304 | 4,437,597 | 4,616,804 |
| 100 events spanning 90 days | 180 | 0.486 | 34,560 | 1,309,046 | 656,701 |
| Spring DST, split windows | 6 | 0.312 | 26,112 | 10,058 | 17,174 |
| Fall DST, split windows | 6 | 0.311 | 26,132 | 10,058 | 17,174 |
| Unsupported recurrence, incomplete | 180 | 0.326 | 27,448 | 141,845 | 143,289 |

The split-recurring workload has **zero qualifying gaps** at the 30-minute minimum;
this is a valid negative availability result, not missing output. The spanning
workload is fully booked. Unsupported recurrence returns exit 2 with provisional
busy data, null availability totals and no candidates. All six supported workloads
return exit 0, and each workload's two JSON and HTML hashes agree. Memory still
grows with occurrences, window intersections, provenance and output size. No
performance improvement over the prior version is claimed by this experiment.

## Verification coverage

The current single command is:

```sh
.venv/bin/python scripts/verify_schedule.py
```

The production test run passed **1,130 tests in 66.71 seconds**, including the
browser checks. Prepare the pinned dependencies, local wheelhouse and Chromium as
described in [README](../README.md). The verifier includes:

- 256 seeded v2 schedules with random split hours, adjacent declarations, closures,
  replacement openings, spanning events, known recurrence moves/cancellations,
  transparency, point events and both all-day policies. An independent endpoint
  partition oracle derives windows and free gaps from raw inputs, with explicit
  expected US DST offsets; production conversion/merge/index code is not used to
  derive expected results. A separate endpoint oracle verifies event witnesses.
- Explicit boundary, minimum-gap, fully-booked/closed/below-minimum/incomplete,
  24:00, spring/fall ambiguous/nonexistent endpoint and replacement-precedence cases.
- Maximum window and exception counts, malformed input, duplicate dates/JSON keys,
  schedule bytes, horizon and processing/report limits. Existing CLI collision,
  serialization, disk failure, interruption and cleanup checks also run on v2.
- Network-blocked Chromium with exception navigation, explanation backreferences,
  date and event filters, keyboard controls, hostile text and JavaScript disabled.
- 32 v1 workloads comparing complete JSON and HTML bytes in both pipeline modes
  to the frozen indexed implementation, plus all earlier seeded v1 regressions,
  historical examples, frozen candidate tests and workload replays.
- An isolated installed CLI with blocked sockets, exact v2 example output,
  repeated reports and unchanged input hashes; all earlier installed examples.
- Authentication and replay of these workload hashes, without asserting equality
  of runtime/RSS across machines or comparing new timings to old performance gates.

The historical index verifier now authenticates the unchanged index function's AST
rather than requiring the entire availability module to remain frozen; v2 extends
validation and report assembly in that module. Frozen source and benchmark files
remain unchanged. The historical candidate regression run excludes only tests
introduced for the public v2 schedule format, which that frozen candidate cannot
parse; production runs the full suite.

Real provider export compatibility remains unverified. Tests cover a conservative
subset, not arbitrary calendars or every IANA timezone transition. These are local
export audits, not live booking guarantees. The processing ceiling is enforced;
there is no OS memory quota or constant-memory guarantee. Hard kills can leave
staging files as documented in the existing CLI failure contract.
