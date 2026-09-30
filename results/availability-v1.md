# Availability v1 validation and measured results

These results use clearly labeled synthetic inputs. They establish the tested
bounded behavior, not real-provider compatibility or a booking guarantee. Historical
overlap and override examples, measurements and recurrence comparisons are retained.

## Reproduce

After the README dependency/browser preparation:

```sh
.venv/bin/python scripts/verify.py
```

The verifier runs all regressions and the new availability checks, builds a wheel
in a fresh isolated environment from the local wheelhouse, denies sockets in the
installed CLI, and reproduces saved report and workload output hashes. It does not
require network access. To collect new performance observations without overwriting
historical evidence:

```sh
.venv/bin/python scripts/benchmark_availability.py --output /tmp/availability-measurements.json
```

## Checks

The full verifier passed: **420 tests in 24.85 seconds**, installed offline CLI,
legacy and availability example reproduction, pinned recurrence comparison, and
11 availability workload replays. Timing refers to this run, not a promise.

* 256 seeded second-lattice oracle cases (seeds 20260930 through 20261185):
  independently enumerate occupied seconds and locate free runs, without production
  sorting, union or complement code. Include zero/overlapping intervals, cancellations,
  transparency, moved recurring instances, all-day policies, New York spring/fall
  transitions and Kathmandu offsets. The oracle supplies explicit expected UTC
  working bounds instead of calling the implementation timezone resolver.
* Targeted cases cover adjacency and tied endpoint citations, exact minimum
  duration, empty/full windows, midnight-crossing events, exclusive all-day ends,
  weekdays, ambiguous/nonexistent boundaries and a skipped civil date.
* Incomplete analysis withholds all gaps: unsupported input, orphan and conflicting
  snapshots, unresolved recurrence limits. CLI checks cover date/occurrence/input/
  candidate/event/report/time limits, malformed specs, collisions, injected JSON/
  HTML/write/rename failures, signals, cleanup and unchanged input hashes.
* Network-blocked Chromium exercises date filtering, keyboard navigation, hidden
  citation reveal, event/source provenance, hostile calendar text, incomplete
  warnings and JavaScript-disabled viewing. Native date inputs have multiple
  focusable segments, so Tab navigation follows the browser control.
* The installed synthetic example and repeated reports are byte-identical:
  two 25,200-second candidates, 50,400 seconds total. Legacy examples remain
  byte-identical; the independent pinned recurrence comparison still records
  seven agreements and three documented differences.

## Measurements

Measured at 2026-09-30T20:10:00.975498+00:00, Python 3.12.3,
`Linux-6.8.0-124-generic-x86_64-with-glibc2.39`.
Two fresh CLI processes per workload, no warmup. Elapsed time is `perf_counter`
wall time, including startup, parsing, computation, serialization and writing.
Peak RSS is Linux `wait4` child `ru_maxrss` in KiB for the child lifecycle, including
fork/exec startup; inherited memory from the benchmark parent can impose a floor.
These shared-host observations are not hard memory or latency guarantees. Runtime
dependencies and implementation hashes are recorded in
[benchmark-availability-v1.json](benchmark-availability-v1.json).

| Synthetic workload | Exit | Elapsed range (s) | Peak RSS (KiB) | JSON / HTML bytes |
| --- | ---: | ---: | ---: | ---: |
| empty_90_days | 0 | 0.398–0.424 | 25,460 | 71,108 / 83,676 |
| seeded_500 | 0 | 0.858–1.053 | 33,496 | 850,424 / 771,855 |
| sparse_3000 | 0 | 2.889–3.175 | 73,284 | 4,868,007 / 4,348,280 |
| dense_100 | 0 | 0.622–0.656 | 57,048 | 1,102,458 / 1,620,149 |
| daily_40_by_90 | 2 | 0.523–0.545 | 57,048 | no bundle |
| pair_limit_250 | 2 | 0.391–0.428 | 57,048 | no bundle |
| all_day_block | 0 | 0.315–0.325 | 57,048 | 81,363 / 61,575 |
| all_day_ignore | 0 | 0.340–0.387 | 57,048 | 71,815 / 84,335 |
| dst_spring | 0 | 0.280–0.302 | 57,048 | 2,890 / 9,872 |
| dst_fall | 0 | 0.296–0.296 | 57,048 | 2,888 / 9,868 |
| unsupported | 2 | 0.296–0.341 | 57,048 | 42,851 / 46,820 |

## Negative outcomes and remaining limits

Both `daily_40_by_90` (40 simultaneous recurring events) and `pair_limit_250`
exhaust the existing pair ceiling. Availability currently retains the full
underlying overlap audit; it therefore stops on that limit even when an interval
union alone would be cheap. Exit 2 and no bundle are the expected conservative
outcomes. A future dedicated occurrence-only audit could remove this bottleneck
while retaining provenance, but has not been implemented or measured here.

An unsupported monthly recurrence produces an incomplete diagnostic bundle with
no candidates and null total duration. It does not silently become free time.
All-day blocking on every date produces a complete zero-candidate result, distinct
from incomplete analysis. Spring and fall windows measure three and five hours.

Only one nonovernight working window per selected date is supported. Adjacent
daily windows remain separate domains. Ambiguous query midnights are rejected
even if working hours would be unambiguous. Imported recurrence semantics retain
the previous supported subset and documented differences; VFREEBUSY, VAVAILABILITY,
split shifts, holidays, buffers and real-provider compatibility are not validated.
Candidate gaps only cover supplied exports and explicit all-day policy.
