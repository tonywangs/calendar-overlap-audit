# Validation and measured workloads

For current schema-2 override results, see [version 0.2 validation](overrides.md).
The measurements below are the preserved version 0.1 baseline; `tests.log` now
contains the latest full-suite output.

All inputs are synthetic. These results describe local runs, not provider compatibility or a performance guarantee.
## Correctness and integration
The verification suite passed **71 tests** on Linux with Python 3.12.3, pytest 8.4.2, Playwright 1.55.0 and Chromium 140.0.7339.16. The current plain pytest output is saved in [tests.log](tests.log).
* An independent exhaustive unit-cell oracle checks union duration and every pair intersection in **400 seeded interval cases** (seeds 0–399). It does not reuse the sweep/merge algorithms.
* **220 additional seeded end-to-end ICS cases** (seeds 10000–10219) check parsing, clipping, citations, daily occupancy and pair results against a discrete cell oracle.
* Hand-authored fixtures check spring DST gaps, fall folds, exact elapsed recurrence duration, weekly week starts and exclusions, COUNT/UNTIL boundaries, floating times, all-day spans, nested events, simultaneous starts, zero-length reminders, transparency and cancellation.
* CLI checks cover malformed input fingerprints, resource exhaustion, file/directory/symlink collisions, a concurrent output reservation, disk-full/rename failure injection, SIGINT/SIGTERM cleanup and a wall-time signal interrupting blocking work.
* Real Chromium runs offline with HTTP(S) requests intercepted and aborted. Tests exercise search/type/source filters, incomplete warnings, Enter navigation through pair/occurrence/event/backreference citations, Tab navigation, Escape reset, imported hostile markup, and JavaScript-disabled viewing. No network requests or imported script execution were observed. Desktop and 390-pixel mobile rendering were also inspected; the mobile page had no document-level horizontal overflow.
* A wheel is built locally, installed from predownloaded dependencies with `--no-index` into a fresh isolated virtual environment, then run outside the checkout with Python socket operations blocked. It reproduces **23,400 occupied seconds, 3 pairs and 11 occurrences**, leaving the input hash unchanged.
## Bounded workload measurements
Raw values, input SHA-256 hashes, output sizes/hashes, runtime versions and implementation hashes are in [benchmark.json](benchmark.json). Recreate them with:
```sh
.venv/bin/python scripts/benchmark.py --output /tmp/calendar-benchmark.json --repeats 3
```
Each row below summarizes three fresh CLI processes, without a warmup. Elapsed time includes startup, parsing, analysis, serialization and disk writes. Peak RSS is Linux `wait4` process maximum resident memory, not incremental allocation or a system-wide memory measurement. Input generation is outside the timed process. All windows are 2026-01-01 through 2026-04-01 (exclusive), UTC, using default limits. The random workload uses seed 20260928; all other generators are deterministic.
| Workload | Result | Elapsed range (s) | Max RSS (KiB) | JSON bytes | HTML bytes |
| --- | --- | ---: | ---: | ---: | ---: |
| `sparse_3000` | 3,000 occurrences; 0 pairs | 1.733–3.333 | 49,916 | 1922730 | 2185909 |
| `seeded_500` | 500 occurrences; 32 pairs | 0.509–0.525 | 37,404 | 336544 | 379871 |
| `dense_180` | 180 occurrences; 16,110 pairs | 0.978–1.276 | 63,720 | 2965628 | 4950172 |
| `daily_100_by_90` | 9,000 occurrences; 0 pairs | 1.358–1.527 | 57,696 | 3147248 | 4108587 |
| `dense_pair_limit_250` | Pair limit; no bundle | 0.369–0.403 | 47,580 | — | — |
| `ancient_candidate_limit` | Candidate limit; no bundle | 2.877–3.366 | 47,580 | — | — |

The 3,000 sparse events occupy 90,000 seconds; the 180 simultaneous events occupy only 3,600 seconds despite 16,110 pairs. The 100 daily series expanded to 9,000 occurrences occupy 270,000 seconds. The benchmark checks these known answers, input preservation and complete-report status. Successful output hashes are identical across the three repetitions of each workload.

The two limit-rejection workloads are expected negative results: 250 simultaneous events would exceed the 20,000-pair ceiling, and a daily series beginning in year 1 exhausts the 200,000-candidate ceiling before reaching the window. Neither produces a report directory or leftover staging directory. These failures demonstrate the bounded behavior; they are not reported as successful full analyses.

## Limits of this evidence

The workloads are modest and synthetic. There is no real-provider export validation, cross-platform measurement, formal accessibility audit, memory-exhaustion sandbox, or browser-scale performance guarantee at every limit combination. The memory figures are observed peaks, not enforced caps. The worst supported combination can hit a report-size or time limit before the occurrence limit. Pinned tzdata 2025.2 may differ from newer civil-time rules. See [supported semantics](../docs/semantics.md) for excluded features.

## Occurrence-only availability

See [the paired workload experiment](occurrence-availability.md) for the current
implementation. Existing measurement files and examples above are preserved as
historical evidence and verified against the frozen original source. The initial
new benchmark exposed inherited RSS accounting; its raw run and corrected
measurement method are documented rather than presented as a memory improvement.
