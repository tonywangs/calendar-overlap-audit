# Working schedules v2

`calendar-availability --spec examples/working-v2.json` accepts a custom, offline
JSON schedule. Version 1 remains supported with byte-identical report semantics
and examples. Version 2 produces availability report schema 3 (also when
`--include-overlaps` is requested); the nested audit retains its own schema.

## Format

All eight keys are required: `version` (integer 2), `start`, `end`, `timezone`,
`weekly`, `exceptions`, `minimum_seconds`, `all_day`. No extra keys are accepted. Dates are strict `YYYY-MM-DD`, start inclusive
and end exclusive. Timezone is an explicit IANA name from pinned tzdata.

`weekly` is an object mapping any of `MO TU WE TH FR SA SU` to arrays of
`["HH:MM", "HH:MM"]` windows. Omitted weekdays and empty arrays mean closed.
`exceptions` is an array of objects containing exactly `date` and `windows`.
A date may occur only once and must lie inside the horizon. Its windows **replace**
the weekly windows for that date; `[]` closes it, including a normally open day.
A nonempty replacement can open a weekend. No holidays or locale rules are inferred.

Windows may be supplied in any order; the report sorts them by start time. A
start must be `00:00`–`23:59`; only an end may be `24:00` (next local midnight).
Zero-length and overnight windows are rejected. Overlapping or duplicate windows
are rejected within each declaration. Touching windows are permitted and merged
into one effective window, so a minimum-length gap can cross their shared edge.
Windows on different dates remain separate, even across midnight.

Every effective declared endpoint is resolved **before** adjacent windows merge.
Ambiguous (fall DST) and nonexistent (spring DST) boundaries are rejected, including
an internal shared edge. Replaced weekly endpoints are not resolved on that date.
Query start/end midnights must also be unambiguous and existent. A window crossing
a DST transition with valid endpoints is allowed and measured in elapsed seconds.

Intervals are half-open `[start, end)`: an event touching a window endpoint does
not block it. Busy intervals are clipped and unioned within each effective window.
The existing event recurrence/override, cancellation, transparency and all-day
policies apply unchanged. `all_day` must explicitly be `block` or `ignore`.
`minimum_seconds` is an integer 1–7,776,000 applied to each contiguous free gap;
shorter gaps still contribute to free time, but are not candidates. Lunch breaks
and closed dates never contribute to free or occupied working time.

## Audit fields and HTML

Schema 3 adds `days`, one entry for every date, and working-time totals. Each day
records the weekly declaration, applied replacement (or null), selected declaration,
effective window IDs, and a stable explanation anchor. The schedule's fingerprint
identifies the exact original bytes. Window IDs link to their day's explanation;
exceptions link to the date where they apply. Busy blocks and gap endpoint witnesses
retain occurrence → event → source provenance.

`working_seconds` counts effective windows; `observed_occupied_seconds` counts the
union of supported busy intervals within them. `occupied_seconds`, `free_seconds`
and `candidate_seconds` are null if analysis is incomplete; observed occupancy
is then provisional. These fields occur on each day and at report level.
`status` is `closed` for a date with no windows, `incomplete` for an open date with
incomplete analysis, `fully_booked` when busy time fills all working windows,
`below_minimum` when free time exists but no gap qualifies, or `available`.
`analysis_complete` is recorded on every day, including closed dates, so closure
never conceals incomplete calendar input. All candidates are withheld globally on
incomplete analysis.

The self-contained HTML shows these explanations, totals, closures and applied
exceptions. Date filtering affects explanations, effective windows and gaps.
Following a hidden explanation link clears the date filter. Tab/Enter follow links;
Escape clears filters; all content is available without JavaScript.

## Bounds and failures

The JSON file is at most **16,384 bytes** (including whitespace), with at most
**16 windows per declaration**, **256 total declared windows** (weekly plus
exceptions), and **90 exceptions**. The horizon is 1–90 civil days, reducible with
`--max-days`; at most 1,440 effective windows can result. API validation applies
the same counts and a 16,384-byte compact JSON encoding bound; file loading also
checks original bytes. Duplicate JSON object keys and duplicate exception dates
are errors. Dates outside the horizon are errors, avoiding silently unused rules.

Existing ceilings apply: 30 seconds CLI wall time, 8 MiB per output report,
20,000 occurrences, and the other documented input/expansion limits. Lower them
using CLI flags. Schedule count exhaustion returns exit 2 with no bundle;
oversized files and malformed schedules return 1 (preserving v1 file-load behavior). Serialization, interruption and output collisions
use the existing staged-write cleanup. API callers must serialize/check their own
JSON output size; the CLI enforces both JSON and HTML sizes.

## Related work and compatibility

This is not a new availability algorithm. [RFC 7953](https://www.rfc-editor.org/rfc/rfc7953.html)
defines VAVAILABILITY/AVAILABLE, recurring availability and prioritized combination
for iCalendar and CalDAV. This tool does not implement those components, priority
rules, CalDAV or free-busy exchange. Its dated JSON replacements are deliberately
smaller in scope. [FullCalendar businessHours](https://fullcalendar.io/docs/businessHours)
already supports multiple business-hour declarations; its display configuration
is not this file format or an import contract. Sources inspected 2026-10-05.

Existing indexed selection supports multiple sorted windows internally; v2 makes
that capability public with bounded validation and auditable date replacements.
The independent interval oracle, v1 frozen implementations and synthetic exports
are validation aids, not proof of compatibility with real provider exports. Such
compatibility remains unverified. No private account or live scheduling is used.
