# Shared meeting windows, contract v1

This is an offline intersection of asserted occupancy and explicit working hours,
not a booking service or an inference of people's willingness to meet. No novelty
is claimed for interval intersection. The input contract and validation matrix
below were specified before implementation.

## Sources and design review

Reviewed [RFC 5545](https://www.rfc-editor.org/rfc/rfc5545.html), sections 3.1,
3.2.9, 3.3.6, 3.3.9, 3.6.4 and 3.8.2.6, and the installed, pinned independent
reader [icalendar 6.3.2](https://pypi.org/project/icalendar/6.3.2/), specifically
`prop.vPeriod`, `cal.FreeBusy` and `Calendar.from_ical`. The reader accepts more
syntax than this tool (including zero-length periods); it is a decoding reference,
not a validator of our coverage assertion. Existing `availability.complement`,
`schedule.effective_schedule`, pinned timezone lookup, strict DST boundary
resolution, and exclusive bundle writer were reviewed. The older commands and
schemas are unchanged. The new interval engine and import reader are separate;
the existing timezone resolver and bundle writer are reused.

## Frozen input contract

A version-1 JSON manifest has exactly `version`, `start`, `end`,
`duration_seconds`, `participants`. Horizon bounds are whole-second UTC strings
`YYYY-MM-DDTHH:MM:SSZ`, positive and at most 90 elapsed days. Duration is an integer
1–7,776,000 seconds. There are 1–16 participants, each with exactly `alias`,
`timezone`, `weekly`, `sources`. Aliases are distinct printable strings of 1–64
characters. Timezones come from pinned tzdata 2025.2.

`weekly` maps weekday codes MO–SU to arrays of `[HH:MM, HH:MM]` pairs; a missing
weekday is closed. Maximum 16 windows per weekday. Only an end permits `24:00`.
An end earlier than the start means the following day; equal clocks are rejected
(use 00:00–24:00 for a full day). Windows belong to their starting weekday;
previous-day overnight spill is included at the horizon's start. Overlaps and
adjacent working windows are unioned. No holiday or exception inference.
Ambiguous or nonexistent local boundaries reject the analysis, even where part
of a declared shift lies outside the horizon. A shift crossing a DST transition
with unambiguous endpoints is valid; meeting duration uses elapsed UTC seconds.

Each participant has a nonempty `sources` array. Each source has exactly `path`
and `complete_occupancy`, which must be JSON `true`. Paths are local regular
files, resolved relative to the manifest. This is the operator's assertion that
this file describes **all occupancy for this participant between its DTSTART
and DTEND**, after any export policies, and that the alias is its sole owner.
No software can establish the truth of that assertion. Do not assert it for
truncated, filtered, request-only, or uncertain exports. No network paths/URLs
are fetched. The same file/inode cannot be assigned to different participants.

Each UTF-8 ICS file contains exactly one VCALENDAR and one VFREEBUSY, no other
components. CRLF and LF and normal space/tab folding are accepted. Bare CR,
control bytes, blank lines, malformed nesting, unknown properties/parameters,
multiple components and multiple calendars are rejected. Required singleton
properties: calendar VERSION:2.0 and PRODID; component UID, DTSTAMP, DTSTART,
DTEND. Optional calendar CALSCALE:GREGORIAN and METHOD:PUBLISH only. Optional
component ORGANIZER, CONTACT, URL (singletons) and COMMENT (repeatable) are
ignored metadata. ATTENDEE and other scheduling-message semantics are rejected.
No parameters on metadata; no descriptive metadata or source paths/names enter
reports. The manifest assigns ownership; ORGANIZER is neither authenticated nor
used to infer identity. Imported UID/DTSTAMP do not select a latest revision.

DTSTART, DTEND and DTSTAMP must use basic UTC `YYYYMMDDTHHMMSSZ`, optionally
`VALUE=DATE-TIME`. Positive coverage bounds are mandatory, at most 90 elapsed
days per file; periods must be wholly inside them. Coverage may be outside or
partly inside the horizon. An empty occupancy list is valid only under the same
explicit completeness assertion. All intervals in the application use [start,
end): the ending instant is excluded. This deliberately uses the enclosing RFC
VFREEBUSY bounds as a half-open coverage assertion, without adding a second at
DTEND. Uncovered time is unknown and is never a candidate.

FREEBUSY supports comma-separated UTC start/end or start/positive-duration
periods. Duration grammar: optional `+`, weeks OR days with optional time OR time;
integer H/M/S units in RFC order, no fractions, months, years or leap seconds.
`FBTYPE` defaults to BUSY; BUSY, BUSY-TENTATIVE and BUSY-UNAVAILABLE all block.
FREE is validated and counted but never subtracts busy or extends coverage.
Unknown FBTYPE rejects the file (a stricter subset than RFC's busy fallback).
Only FBTYPE and optional VALUE=PERIOD parameters are accepted; duplicates reject.
Unsorted, duplicate, adjacent and overlapping periods are accepted and unioned.
Across overlapping complete sources, busy wins even if another source omits it
or calls it FREE. There is no replacement or precedence by timestamp. This can
understate available time for conflicting snapshots, never clear known busy time.

## Computation and output

For each participant: union coverage; union blocking periods; union working
shifts; intersect working time with coverage; subtract blocking periods.
Intersect those sets across all participants, merge adjacent results, and retain
maximal windows at least the requested duration. Windows are **candidate ranges**,
not discrete slots and not booked meetings. A meeting may start anywhere from a
window's start through `latest_start` inclusive. Short gaps are omitted only after
all intersections, not before. Report coverage gaps separately across the whole
horizon, including outside working hours.

Output is a new directory with deterministic `report.json` and self-contained
`report.html`. JSON has `report_type: shared-windows`, `schema_version: 1`;
participant IDs and window IDs follow manifest and chronological order. UTC
intervals include exact elapsed seconds; each shared window includes participant
local times and UTC latest start. Reports retain input byte counts and SHA-256
hashes, normalized schedules, merged coverage/busy/working/free intervals and
coverage gaps, so the set calculation is auditable. No imported descriptions,
identities, source names or paths are copied. Aliases are user-supplied labels,
not anonymization. Precise availability, working hours and hashes remain sensitive.

HTML works without JavaScript; optional UTC-date and minimum-length filters
select intersecting windows (a date can match a window starting the day before).
Native disclosure controls inspect local times, and participant links expose
coverage and occupancy evidence. Keyboard Escape clears filters. No external
resources or requests; Content Security Policy limits the page to inline static
style/script. Provider interoperability, human usability and real participant
availability remain unvalidated.

## Validation matrix frozen before implementation

- At least 250 seeded cases against an independent discrete-time oracle, with
  multiple participants, arbitrary coverage, busy/FREE conflict, adjacency,
  duplicates and duration boundaries; independently decode accepted periods.
- Empty occupancy; disjoint or partial coverage; all busy; exact minimum and
  one-second-short windows; adjacent schedules; overnight spill; spring and fall
  DST crossing, ambiguous and nonexistent boundaries.
- Missing bounds/assertion; multiple owners/components; unsupported types,
  recurrence, timezones and methods; malformed/zero/reversed/overflow periods;
  duplicate JSON keys/properties/parameters and invalid UTF-8.
- Export/import round trips; repeated bytes; unchanged inputs; installed offline
  synthetic workflow; cancellation, byte/period/work/runtime/report limits,
  collisions, serialization failure and rollback/cleanup.
- Network-blocked Chromium: filter, inspection, keyboard, narrow viewport,
  hostile labels and ignored ICS text, and JavaScript disabled.
- Bounded workload replays retain actual runtime, peak process RSS, input/output
  hashes, artifact sizes and dependency versions. Existing verification remains.

## CLI, limits and reproducibility

After the README's installation, run:

```sh
.venv/bin/calendar-shared --manifest examples/shared/manifest.json --output /tmp/shared-report
```

Or run `.venv/bin/python -m calendar_audit.shared_cli` with the same flags. The
manifest is an exact-key versioned format, not an arbitrary JSON configuration;
[the complete example](../examples/shared/manifest.json) supplies every field.
An empty `weekly` object means closed every day. Source paths may be absolute
local paths or relative to the manifest directory. No account integration exists.

| Resource | Default hard ceiling | Lower with |
| --- | ---: | --- |
| Participants | 16 | Use fewer participants |
| UTC horizon / each source coverage | 90 elapsed days | Shorten explicit bounds |
| Manifest bytes | 256 KiB | `--max-manifest-bytes` |
| Total bytes, including manifest and repeated source reads | 8 MiB | `--max-input-bytes` |
| Source files, including repeated references | 32 | `--max-files` |
| Physical and unfolded content line | 64 KiB | `--max-line-bytes` |
| Raw periods, including FREE and duplicates | 20,000 | `--max-periods` |
| Charged computation operations | 2,000,000 | `--max-operations` |
| Materialized report intervals, including evidence | 100,000 | `--max-intervals` |
| Shared windows | 20,000 | `--max-windows` |
| Each serialized report artifact | 8 MiB | `--max-report-bytes` |
| CLI wall time, including reading and serialization | 30 seconds | `--max-seconds` |

Positive integer caps cannot exceed the defaults; seconds may be fractional.
Operations count content lines, parsed period validation, interval scans, local
schedule boundaries and local-time formatting; sorting reserves `n * bit_length(n)`
operations. This is a deterministic work budget, not a CPU instruction counter or
an operating-system memory cap. Byte/period/interval caps bound retained data;
RSS observations are not memory guarantees. The POSIX timer also interrupts reads
and serialization; library calls have cooperative checks. Linux and macOS signals
are required by the CLI; only Linux/Python 3.12 has been exercised here.

Working-time expansion considers the previous local date through the end's local
date, resolving all declared boundaries on those dates before clipping. Therefore
an ambiguous/nonexistent boundary on those edge dates may conservatively reject
a run even if that individual shift is outside the UTC horizon. Dates whose local
expansion would underflow/overflow Python's representable years also reject.

Exit 0 means analysis completed within this subset, **not** that all requested
time has coverage; inspect `coverage_complete` separately. No windows is a valid
result. Invalid/unsupported input or serialization/filesystem failure exits 1;
resource exhaustion exits 2; handled cancellation exits 130. Argparse errors
also exit 2. No report is emitted on a failure; existing destinations survive.
Outputs are mode 0600 in a new mode-0700 directory. As in the older commands,
SIGKILL, power loss and concurrent readers are outside the rollback guarantee;
wait for exit 0 before consuming a bundle. Input hashes describe bytes read during
the run; concurrent external edits to inputs are outside the consistency guarantee.

Prepare the existing offline verification wheelhouse and Chromium as described
in the README, then run the single gate:

```sh
.venv/bin/python scripts/verify_shared.py
```

It includes the production suite, historical regressions and workload replays,
example reproduction, isolated installed export-to-import workflow, and shared
workload replay. No network is needed after preparation. Historical free/busy and
schedule benchmarks now run against authenticated source snapshots so adding the
new modules/entry point does not rewrite measurements or misattribute them to the
new package. Current production tests still exercise every old command.

New synthetic measurements can be written to a fresh path with
`python scripts/benchmark_shared.py --output /tmp/shared-measurements.json`.
Use the environment's Python executable (normally `.venv/bin/python`). Replay
checks deterministic input/output hashes and outcomes, not historical timings.
Actual observations and unvalidated aspects are in
[the shared-window results](../results/shared-windows.md).

The accepted date-time markers `T`/`Z` and duration letters are uppercase and
numeric fields use ASCII digits. Property names, parameter names and enumerated
FBTYPE values are case-insensitive. The independent pinned reader's rejection
of lowercase UTC markers is retained as an explicit negative validation case.
