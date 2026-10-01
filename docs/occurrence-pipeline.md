# Occurrence-only availability

## Inspection before refactoring (2026-10-01)

The pipeline in `core.analyze` reads/fingerprints sources, scans components,
groups UID snapshots, resolves whole recurrence families, assigns occurrence IDs,
enumerates timed overlap pairs, and finally summarizes daily occupied time.
Availability v1 then takes those occurrences and computes working-window complements.

Diagnostics and limits observed before changes:

| Stage | Diagnostics / resource outcomes |
| --- | --- |
| Read and scan | `invalid_calendar`, `unsupported_component`, `invalid_identity`; file, byte, line and event limits |
| Family preparation and expansion | `unsupported_event` plus `SeriesError` codes: conflicting snapshots/masters/overrides, orphan overrides, cancelled master with overrides, nonrecurring master, unsupported range/override, incompatible identity/timing, EXDATE collision, missing override start and `resolution_limit`; candidate and occurrence limits |
| Pair enumeration | No input diagnostics. Only `pairs limit exceeded` and elapsed-time failure. It cannot make a previously unsupported family valid. |
| Summary and complement | Elapsed-time checks; availability working-boundary/spec validation; unsupported input suppresses all candidates |
| Serialization/publication | JSON/HTML byte caps, deadline, cancellation and filesystem failure; no partial bundle on handled failure |

All stages share the runtime budget. Override-resolution exhaustion produces `resolution_limit`, excludes the whole
family, and suppresses candidates in an incomplete bundle. Other operational exhaustion raises `AuditError`
and the CLI returns an incomplete outcome without a bundle; it is not an empty
calendar. Input diagnostics produce an inspectable incomplete bundle.

## Sources inspected

[RFC 5545](https://www.rfc-editor.org/rfc/rfc5545.html), especially §§3.6.1,
3.8.2.7, 3.8.4.4 and 3.8.5.3: exclusive ends, transparency, original recurrence
identity and recurrence sets remain upstream concerns. Pair enumeration is not a
prerequisite for busy-time union. No claim of full RFC coverage or novelty is made.

[dateutil's rrule implementation](https://dateutil.readthedocs.io/en/stable/_modules/dateutil/rrule.html)
provides bounded recurrence iteration and recurrence-set inclusion/exclusion;
it does not supply this tool's conservative snapshot policy or gap provenance.
[recurring-ical-events CalendarQuery](https://github.com/niccokunzmann/python-recurring-ical-events/blob/main/recurring_ical_events/query.py)
expands series into occurrences for a requested range. That separation supports
keeping expansion independent of a pairwise conflict report. The existing pinned
independent recurrence comparisons (including recorded disagreements) are retained.

## Revised pipeline and formats

`analyze` retains its schema-2 overlap report and bounded pair sweep.
`analyze_occurrences` uses the same reader, scanner, family resolver, IDs and daily
union summary, skipping the pair sweep entirely. Availability defaults to this
path and feeds its occurrences to the unchanged complement/provenance algorithm.
The tests replace the pair function with a failing sentinel to enforce this boundary.

The default availability JSON is now `schema_version: 2`, `report_type:
availability`. Its working specification remains **version 1**. Its `audit` is
`report_type: occurrences`, `schema_version: 1`, with all prior source, event,
occurrence, cancellation, diagnostic, daily summary and dependency fields. The
`overlaps` field and inapplicable `pairs` limit/count are absent, not zero or an
empty claim of no conflicts. Candidate IDs, windows and provenance semantics are
unchanged. Dispatch on both report type and schema version.

For the original availability JSON schema 1 and nested overlap audit, pass
`--include-overlaps` (Python: `availability(..., include_overlaps=True)`). This
also retains the pair limit and reproduces the original example bytes. Existing
`calendar-audit` invocations and formats are unchanged. The old examples and
measurements remain historical artifacts; new default example files live under
`examples/occurrence-availability-report/`.

All file, input-byte, physical/unfolded-line, event, recurrence-candidate,
override-resolution, occurrence, date, runtime and output limits remain in force.
`--max-pairs` is accepted and validated for command compatibility but applies only
with `--include-overlaps`. It is omitted from default report limits. Limits cannot
be raised past their existing ceilings. The shared budget covers expansion,
summaries, complement, rendering and publication; the CLI also enforces its POSIX
deadline. Serialization failure, collision and cancellation behavior is unchanged.

No change is made to cancellation/transparency, all-day policy, floating time,
DST folds/gaps, override membership resolution or source snapshot boundaries.
Even all-day events ignored by the selected policy must be interpretable.
Unsupported components/families and resolution exhaustion withhold every candidate.
Other applicable exhaustion returns exit 2 with no bundle. Invalid input/settings,
serialization and filesystem failures return 1; cancellation returns 130.

Removing pair materialization removes the quadratic *pair-output* cost. It does
not establish constant memory: sources, events, occurrences, sorted interval lists,
provenance lists and JSON/HTML buffers are materialized. With D working days and N
occurrences, the existing complement sorts up to N intervals per day, so its time
bound remains O(D N log N), in addition to parsing and recurrence resolution.
Provenance/report storage can grow with D N; D is capped at 90. The report-byte and
runtime caps can still stop dense or long calendars before the occurrence ceiling.

## Reproduction

After the dependency preparation in README, run `.venv/bin/python scripts/verify.py`.
It includes baseline equivalence, independent dense and second-lattice oracles,
legacy examples, browser navigation with networking blocked, failure/cancellation
cleanup, installed default/legacy/dense CLI checks, historical workload replay and
the new frozen suite's deterministic outcomes. It verifies measurements against
source hashes; runtime and RSS are observations, not pass/fail thresholds.

`tests/baseline/availability-v1.json` stores the original project source/scripts
as text for offline baseline execution. `scripts/baseline.py` authenticates these
against unchanged historical evidence. This avoids silently running historical
measurements against changed code. The frozen suite is
`scripts/availability-suite.json`; six balanced paired repetitions alternate
baseline-first and candidate-first. Re-measure with:

```sh
.venv/bin/python scripts/benchmark_occurrences.py --output /tmp/occurrence-measurements.json
```

See [actual results and limitations](../results/occurrence-availability.md).

The benchmark records each worker's Linux `/proc/self/status` `VmHWM` after the
CLI finishes, which tracks its current address space's peak resident set. It also
retains `getrusage_maxrss_kib` as a separate accounting observation; do not treat
that as the fresh-process peak. An initial run exposed inherited pre-exec parent
RSS in `getrusage`; both that run and a bounded reproduction are retained in results.
The parent uses monotonic elapsed time around each fresh CLI process. Timing
includes startup, input processing, serialization, publication and metric capture.
