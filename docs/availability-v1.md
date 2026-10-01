# Availability specification v1

The working-window specification remains current. The original output/pipeline
described below is available with `--include-overlaps`; the new default uses
[occurrence-only analysis and availability JSON schema 2](occurrence-pipeline.md).

Frozen before implementation. This is an offline complement of supported exported
commitments, not a booking guarantee, provider integration, or novelty claim.

## Inputs and command

`calendar-availability INPUT.ics [INPUT.ics ...] --spec working.json --output NEW_DIR`

The UTF-8 JSON object must contain exactly these keys (no duplicate keys):

```json
{
  "version": 1,
  "start": "2026-03-06",
  "end": "2026-03-11",
  "timezone": "America/New_York",
  "weekdays": ["MO", "TU", "WE", "TH", "FR"],
  "work_start": "09:00",
  "work_end": "17:00",
  "minimum_seconds": 1800,
  "all_day": "block"
}
```

Dates are start-inclusive/end-exclusive; 1–90 civil days, lowerable with
`--max-days`. Weekdays are a nonempty unique subset of MO through SU, normalized
into weekday order. Hours are strict HH:MM; start is 00:00–23:59, end may also be
24:00 (next midnight). End must be later than start: one independent, nonovernight
window per selected date. An overnight schedule needs separate runs. Each daily
window is an independent search domain, including adjacent full-day windows.
Minimum duration is a positive integer elapsed second count, at most 7,776,000.
All-day policy is mandatory: `block` subtracts opaque DATE events on their civil
dates in the working timezone; `ignore` explicitly excludes those events from
busy time. Both retain the original occurrence records. Transparency and cancelled
instances never occupy time. There is no implicit holiday or attendance policy.
The spec file is a regular file, at most 16 KiB, and is fingerprinted.

## Time and interval semantics

Use pinned tzdata IANA zones, also for floating event times. Both folds are
round-tripped through UTC for every working boundary. Zero matching instants is
nonexistent; two distinct instants is ambiguous. Reject either with date, time,
zone and an instruction to change hours/date/zone. Query start/end midnights must
also be unambiguous because the underlying audit clips to these bounds. This is
stricter than the retained imported-event RFC semantics. Interior transitions are
allowed: a 00:00–04:00 window can contain three or five elapsed hours. UTC endpoints,
local endpoints with numeric offsets, and exact elapsed seconds are reported.

Clip positive-length busy occurrences to each daily window; sort, merge overlapping
or touching intervals, then take the complement. Zero-duration events do not block.
Only maximal gaps within that window with duration >= minimum_seconds survive.
Boundary citations name all occurrences ending/starting at the neighboring merged
block's endpoint; busy blocks also list every contributing occurrence. Empty boundary
citation lists mean the working-window edge. Commitments crossing midnight and
multi-day DATE events are clipped independently for each window.

## Trust, limits and outputs

Use the existing schema-2 audit unchanged: recurrence replacement, original identity,
EXDATE, cancellations, transparency, duplicate fingerprints, and source snapshot
boundaries follow [overrides.md](overrides.md). All unsupported input and unresolved
families make the entire availability result incomplete. In that case `candidates`
is empty and `candidate_seconds` is null, not zero availability; provisional busy
blocks and the nested audit remain inspectable. Complete means only supplied exports
and selected policies. Even an ignored all-day event is still parsed and validated.

All existing `--max-*` limits apply; pair calculation remains bounded even though
availability itself only needs a union. Exhausted operational limits return exit 2,
print INCOMPLETE, and produce no bundle. Invalid specs, filesystem/serialization
errors and collisions return 1; cancellation returns 130. Unsupported inputs produce
an incomplete diagnostic bundle and exit 2. Success returns 0. No overwrite or input
modification. Hard kill cleanup has the same limitations as the original CLI.

JSON `schema_version: 1`, `report_type: availability` includes normalized settings,
spec filename/bytes/SHA-256, daily working windows and merged busy blocks, candidate
intervals, total candidate seconds (after minimum filtering), and a nested schema-2
`audit` with hashes and provenance. IDs are deterministic for fixed ordered inputs
and bytes; no timestamp or absolute path is added. HTML embeds escaped text only,
contains the full audit, has a date filter for windows/gaps and occurrence citations,
and works without a server or network. Escape clears the date filter; Tab/Enter use
native controls and anchors. Report size limits apply to the combined output.

## Related work and compatibility

[RFC 5545 §3.6.1](https://www.rfc-editor.org/rfc/rfc5545.html#section-3.6.1)
defines exclusive event ends; [§3.8.2.7](https://www.rfc-editor.org/rfc/rfc5545.html#section-3.8.2.7)
defines opaque versus transparent busy time. This command retains the prior bounded
recurrence implementation and its documented differences rather than claiming full
RFC support. VFREEBUSY and VAVAILABILITY imports remain unsupported.

Reviewed the independent [icalendar Availability implementation](https://icalendar.readthedocs.io/en/latest/_modules/icalendar/cal/availability.html)
and [FreeBusy API](https://icalendar.readthedocs.io/en/stable/reference/api/icalendar.cal.free_busy.html):
they model standard calendar availability/free-busy components. This tool instead
accepts a strict bounded local working-hours specification and emits auditable
interval complements. The existing pinned recurring-ical-events comparison remains
part of verification. Seeded complement validation uses an independent discrete
occupancy oracle; synthetic fixtures do not establish real-provider compatibility.
