# Occurrence-only availability experiment

The new default computes gaps without enumerating overlap pairs. The original
`calendar-audit` output and the availability `--include-overlaps` compatibility
path retain pair enumeration and the original examples. The working specification
remains version 1; default availability reports are schema 2, with a distinct
occurrence-only audit instead of an empty overlap list.

## Design and reproducibility

The immutable workload description is [availability-suite.json](../scripts/availability-suite.json),
SHA-256 `4f17184db6ba7a6ba6a6c439d483c78af34e36a1d66999012c25340630c2bcec`.
It was written and hashed before measurements: 13 cases, from empty/sparse to dense,
plus unsupported input and occurrence/output/runtime exhaustion. The seed is
20261001 (these particular workload generators are deterministic without randomness).
Each case uses six paired repetitions, ordered AB, BA, AB, BA, AB, BA. A is the
frozen original source, authenticated against historical measurements; B is the
candidate. Identical input bytes, spec, dependencies and resource ceilings apply.
Each repetition starts a fresh Python CLI worker. No warmups or removed outliers.

[Raw corrected measurements](benchmark-occurrences.json) preserve all 156 runs,
actual elapsed seconds, Linux process-address-space peak RSS (`VmHWM`, KiB),
separate `getrusage` accounting, output byte lengths/hashes, semantic hashes,
exit codes and incomplete outcomes. Source/script/suite/input hashes, settings,
Python version, dependencies and host details are included. Times cover startup,
analysis, serialization, publication and measurement capture. Reproduce with:

```sh
.venv/bin/python scripts/benchmark_occurrences.py --output /tmp/occurrence-measurements.json
```

The verifier replays one pair per workload and checks exact outcomes/hashes, not
speed thresholds. It also checks all six saved balanced pairs and stable outputs.
The semantic hash excludes only schema/type markers and the explicitly removed
pair data, count and limit; all remaining report fields must agree when both
implementations emit a report. Old measurement files are never rewritten to
suggest they measured this implementation.

## Measurement correction retained as a negative result

The [initial six-pair run](benchmark-occurrences-initial.json) used child
`getrusage(RUSAGE_SELF).ru_maxrss`. Its repeated 59,688 KiB values revealed that
pre-exec parent RSS could dominate the supposed fresh-worker measurement. Its
[source](../tests/baseline/benchmark-occurrences-initial.json) is retained with its
original hash. **Do not use that run's RSS fields as fresh-process measurements.**
Its timings also overlapped verification activity; they are preserved but not used
in the comparison table below.

The bounded [reproduction](../scripts/rss_probe.py) allocates 100,000,000 bytes only
in the parent, then execs a small Python child. On this host, the saved
[probe result](peak-rss-probe.json) is 110,976 KiB from `getrusage`, versus
10,544 KiB from the child's `/proc/self/status` `VmHWM` and `VmRSS`. Re-run with
`.venv/bin/python scripts/rss_probe.py --output /tmp/rss-probe.json`.
This is an accounting artifact, not a claim that the child used the parent's
100 MB. The corrected run uses `VmHWM` for the worker's current address space and
retains `getrusage` separately for transparency. The workload suite and application
source are identical in both runs. No tests or other experiments were deliberately
run alongside the corrected measurements; unrelated shared-host load is uncontrolled.

## Semantic and operational validation

* 256 seeded cases compare every non-pair semantic field with the frozen original;
  the compatibility mode also matches the complete original JSON exactly. These
  cases independently check gap intervals with a second-by-second occupancy oracle,
  including DST transitions, fractional offsets, all-day policies, transparency,
  cancellations and overrides.
* 12 dense seeded cases exceed 20,000 overlap pairs. An independent elementary-
  interval occupancy oracle checks gaps, busy blocks, complete contributor lists
  and boundary witnesses. It includes adjacency, nesting, tied boundaries,
  zero-duration events, moved/cancelled/transparent overrides and two input files.
  The baseline hits its pair cap; a sentinel forbids any pair-enumeration call in
  the candidate, even with `pairs=1`.
* Existing regression tests are retained. Additional checks cover source snapshot
  conflicts, unsupported/orphan series, every expansion limit, expiration after
  expansion, dense CLI behavior and interruption during expansion/complement.
  Existing output collision, serialization, disk, rename and cancellation cleanup
  tests run against the new default. Resolution exhaustion retains an incomplete
  diagnostic bundle; other applicable exhaustion returns no bundle.
* Chromium exercises dense and sparse reports with network routes blocked,
  including gap → occurrence → event → source navigation, filters, keyboard use,
  hostile text and JavaScript-disabled fallback. An isolated wheel installation
  runs ordinary, compatibility and dense CLI workflows with socket access blocked.
  Inputs remain unchanged; repeated reports and legacy examples are byte-identical.

The one-command check is `.venv/bin/python scripts/verify.py`; its actual pytest
output is [tests.log](tests.log). The complete command additionally checks installed
CLI workflows, source authentication, historical recurrence comparison (including
known disagreements), historical availability replay and the new workload replay.

## Corrected measurements

Medians of six runs per implementation; A = baseline, B = occurrence-only.
`Complete` refers to an output report, not process termination. Paired time B/A
is the median of six within-pair ratios; values above 1 mean more elapsed time.

| Workload | A/B exit | A/B complete | A time (s) | B time (s) | A peak RSS (KiB) | B peak RSS (KiB) | B candidate seconds | Paired time B/A |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| empty | 0/0 | True/True | 0.313 | 0.311 | 26,890 | 26,936 | 7776000 | 0.993 |
| sparse_100 | 0/0 | True/True | 0.370 | 0.368 | 28,858 | 28,876 | 7773000 | 1.004 |
| sparse_1000 | 0/0 | True/True | 0.937 | 0.878 | 42,160 | 42,226 | 7746000 | 0.941 |
| sparse_3000 | 0/0 | True/True | 2.436 | 2.188 | 73,396 | 73,420 | 7686000 | 0.903 |
| dense_100 | 0/0 | True/True | 0.577 | 0.380 | 43,042 | 28,026 | 7772400 | 0.637 |
| dense_200 | 0/0 | True/True | 1.126 | 0.415 | 87,922 | 29,108 | 7772400 | 0.355 |
| dense_250 | 2/0 | False/True | 0.382 | 0.454 | 28,526 | 29,846 | 7772400 | 1.262 |
| dense_1000 | 2/0 | False/True | 0.551 | 0.735 | 31,686 | 37,770 | 7772400 | 1.287 |
| daily_40_by_90 | 2/0 | False/True | 0.438 | 1.350 | 31,940 | 47,618 | 7773300 | 3.079 |
| unsupported | 2/2 | False/False | 0.292 | 0.301 | 26,630 | 26,594 | None | 0.980 |
| occurrence_limit | 2/2 | False/False | 0.260 | 0.250 | 25,934 | 25,952 | — | 0.985 |
| output_limit | 2/2 | False/False | 0.371 | 0.396 | 28,624 | 28,418 | — | 1.104 |
| runtime_limit | 2/2 | False/False | 0.233 | 0.236 | 25,822 | 25,846 | — | 0.994 |

Dense 250, dense 1,000 and daily 40×90 now produce complete reports; the
baseline stopped at the pair limit in all six repetitions. Dense 100 and 200
complete on both paths and show the benefit of omitting pair construction and
pair serialization. Sparse cases still pay for parsing, summaries and complement.

The candidate takes longer than the early-failing baseline on dense 250, dense
1,000 and daily 40×90; those are different outcomes, not speed regressions for
equivalent completed work. Higher median elapsed times appear on unsupported input,
the output-limit case and the tiny-runtime case; within-pair ratios reverse the
sign for unsupported/tiny-runtime cases, illustrating noise. Sparse 100 has a
slightly higher paired time ratio despite a lower standalone time median. Empty
and all sparse cases have slightly higher median peak RSS in the candidate. Do not interpret
small differences as significant with six uncontrolled shared-host samples.

Unsupported input yields an incomplete diagnostic report in both implementations.
The occurrence and runtime caps stop both without a bundle. With the 1,024-byte
output cap, the baseline first hits its pair cap; the candidate reaches the output
cap and also publishes nothing. Neither failure is treated as zero availability.

## Limits of the experiment

All calendars are synthetic. This does not establish compatibility with real
provider exports or completeness of a person's commitments. Supported recurrence,
source-boundary and DST policies are unchanged. Working hours remain one
nonovernight window per selected date. Unsupported input withholds all candidates.

Removing pair enumeration removes a quadratic output bottleneck; it does not
make memory constant or remove bounded parsing, recurrence, output and runtime
costs. Event/occurrence lists, provenance, per-day sorting and serialization buffers
still grow. Completing a dense report can consume more time or memory than an old
run that stopped early. Six shared-host observations do not establish a stable
performance distribution, speed guarantee, or significance. Linux `VmHWM` is a
resident-memory high-water measurement, not allocation volume or a cross-platform
memory bound. The experiment changes both computation and the explicitly versioned
pair-report surface, so its timing difference is not solely recurrence processing.
