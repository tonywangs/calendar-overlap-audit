# Indexed occurrence selection experiment

The catalog baseline is tree `b803165876f77ce5fef0c49c6d56cf6848dcd1d7`.
Its complete source package is preserved in
`tests/baseline/occurrence-pipeline.json`, authenticated against the previous
occurrence benchmark. Existing examples, implementations and results remain
available. The baseline passed its full verification before experimental edits.

## Prior work and bounded candidate

This is an application of established interval indexing, not a novel algorithm.
Primary sources inspected on 2026-10-02:

- [intervaltree implementation](https://github.com/chaimleib/intervaltree/blob/master/intervaltree/intervaltree.py):
  a mutable interval tree with overlap queries; its set-valued results would need
  ordering for this report's deterministic output.
- [pandas IntervalIndex implementation](https://github.com/pandas-dev/pandas/blob/main/pandas/core/indexes/interval.py):
  includes separate treatment for monotonic nonoverlapping intervals.
- [Python bisect](https://docs.python.org/3/library/bisect.html):
  left/right insertion boundaries implement the strict intersection inequalities.

The fixed candidate is `experiments/indexed_availability.py`. Working windows are
chronological, nonoverlapping and positive-duration. Sort timed `(start,end,id)`
tuples once, then use binary search on window ends and starts to assign each
occurrence to exactly the windows it intersects. Touching endpoints do not
intersect. Bucket insertion retains original tuple ordering. All-day occurrences
use civil-date searches, sort once by ID, and produce sorted `(lo,hi,id)` buckets.
Merge the timed and all-day streams into the original complement algorithm.
The existing standalone complement still sorts unless explicitly told its input
is sorted. No recurrence, diagnostic, report schema or policy changes are planned.

The lower-level index supports split windows with repeated dates; public spec v1
still permits only one window per selected day. Tests exercise split windows
without introducing a new public schema. UTC boundaries continue to come from
the existing DST resolver; all-day eligibility remains civil-date based.

For N timed occurrences, A all-day occurrences, W windows and K total
occurrence/window intersections, selection costs
O(N log N + A log A + (N+A) log W + K + W), with O(N+A+W+K)
auxiliary storage. Complement traversal costs O(K+W); existing provenance sorting
and report construction remain additional costs. The baseline scans N occurrences
and sorts timed/all-day tuples for each window (worst case O(W(N+A) log(N+A))).
Long spans can make K proportional to W(N+A): neither version has constant memory.
Date range, expansion, occurrence, output and time limits still apply. Budget
checks bracket sorting and occur inside assignment fanout and consumption; CLI
signal deadlines also cover Python/C sorting operations.

## Protocol frozen before measurements

`scripts/index-suite.json` freezes eight workloads, seed, resource budgets,
repetitions and gates. `scripts/benchmark_index.py` fixes input generation and
measurement. `experiments/index-freeze.json` records their hashes before the first
candidate benchmark. No workload/candidate tuning after measurements is allowed.

Four short controls and four 90-day workloads cover empty, sparse, dense,
long-spanning and all-day occupancy. Sparse and dense cases have 60 daily event
series; long spans use 300 distinct events. All are synthetic, local and offline.
Each workload gets six fresh-process pairs in AB, BA, AB, BA, AB, BA order.
Inputs, spec, source versions, Python/dependency versions, output hashes and
raw timings/RSS are retained. Correctness runs use the default 30-second deadline
per report, far above these small cases' execution time, never a deliberately
binding deadline. Dedicated failure tests separately exercise exhausted budgets.

End-to-end elapsed time includes interpreter startup through CLI exit and bundle
writes. Availability-stage timing is availability() wall time minus its nested
analyze()/analyze_occurrences() call: validation, windows, selection, union,
provenance and result construction, excluding expansion, serialization and I/O.
Linux `/proc/self/status` VmHWM measures peak RSS in the fresh child's address
space. Parent-inherited getrusage high-water marks are not used.

Adoption requires exact reports and independent oracle checks, at least 20%
median end-to-end improvement on **both** `long_sparse` and `long_dense`, no other
control regression exceeding both 10% and 20 ms, and no peak-RSS increase exceeding
both 15% and 8 MiB on any workload. Timing uses per-implementation medians; RSS uses
the maximum of six observations per implementation. Stage time is explanatory,
not an adoption gate. A failed gate means retaining production behavior and
publishing an honest reproducible negative experiment result.
