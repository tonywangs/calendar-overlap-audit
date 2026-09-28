# Supported semantics (schema 1)

This is a bounded audit of local files, not a provider sync client or a full RFC
validator. No novelty is claimed. The design uses [RFC 5545](https://www.rfc-editor.org/rfc/rfc5545)
sections 3.3.5, 3.3.10, 3.6.1 and 3.8.5; [icalendar](https://icalendar.readthedocs.io/)
provides content decoding. [recurring-ical-events](https://recurring-ical-events.readthedocs.io/)
already offers general recurrence queries and override handling. Its query implementation
and error handling were reviewed. Here an intentionally smaller recurrence engine makes
candidate budgets and exclusions explicit; it is not a replacement for that library.

## Contract before implementation

* Required analysis bounds are ISO dates, start inclusive and end exclusive, 1–90
  civil days in the required display timezone. All calculations use UTC instants.
* VEVENT with UID and DTSTART; DTEND is exclusive. Missing DTEND means one civil
  day for DATE, zero duration for DATE-TIME. DURATION is unsupported in this version.
* DAILY or WEEKLY RRULE, optional positive INTERVAL, COUNT **or** UNTIL, EXDATE,
  and weekly BYDAY (unqualified weekdays) and WKST. Other rule parts, RDATE,
  EXRULE and RECURRENCE-ID are incomplete, not silently approximated.
  Unbounded rules are evaluated only to the window end with a candidate budget.
* DTSTART must match weekly BYDAY. Generated nonexistent local starts are skipped
  without consuming COUNT. Ambiguous starts use the first occurrence. Explicit
  nonexistent DTSTART/DTEND uses the pre-gap offset (RFC 5545 3.3.5).
  Timed DTEND defines a fixed elapsed duration for every occurrence; all-day spans
  retain their number of civil dates. UNTIL is inclusive and must match DTSTART's
  type, with UTC UNTIL for zoned/UTC starts and local UNTIL for floating starts.
* Floating times use the display timezone, visibly recorded. IANA zones come from
  pinned tzdata, not the host. Unknown TZIDs are incomplete. Embedded VTIMEZONE
  definitions are unsupported and mark the file incomplete; recognized IANA TZIDs
  may still yield provisional results. There is no timezone alias guessing.
* Cancelled and transparent events do not occupy time. All-day events are listed
  separately and never included in timed occupancy or overlap pairs. Zero-length
  timed events remain traceable but do not occupy time.
* UID is a global identity across files. Identical unfolded VEVENT definitions with the
  same UID are deduplicated and retain all source references. Differing definitions
  of the same UID, including overrides, cause the entire UID group to be excluded
  as ambiguous. Sequence numbers are not a license to guess the latest version.
* Clipped timed occurrences contribute to a union of occupied intervals, never a
  sum of event durations. Pair intersections use positive duration only. Daily
  summaries split at display-zone midnight (23/25-hour days are possible).
* Unsupported or malformed input produces an incomplete report with traceable
  diagnostics. A report with no detected pairs is never called conflict-free.
  Missing/unreadable files and exhausted resource limits fail with no report.
* JSON is deterministic for identical input bytes, input order, filenames, window,
  timezone, tool/dependency versions and limits. No current time or machine path is
  embedded. Source references use an ordinal, basename, SHA-256 and event ordinal.
  Only UID, summary and scheduling fields are retained; attendees, descriptions,
  locations, alarms and URLs are omitted.

The CLI will enforce aggregate input bytes, file count, physical/unfolded line size,
event count, generated candidates, retained occurrences, pairs, per-report size and
wall time. Limit failures do not publish partial reports. Output goes into a new
private directory as a bundle; an existing path is never overwritten. SIGINT and
SIGTERM clean up staging files. Hard kill/power loss may leave hidden staging files.

Compatibility with real Google, Apple, Outlook or other personal exports is
unverified. Tests and examples use synthetic data only. Provider-specific extensions
can affect semantics; this tool cannot establish completeness beyond its subset.

## Additional boundaries

The parser accepts UTF-8 (with an optional BOM), CRLF or LF, RFC content-line
folding, and escaped text. Blank physical lines are tolerated. Calendar VERSION
must be 2.0; CALSCALE must be absent or GREGORIAN. METHOD must be absent or PUBLISH.
Unknown descriptive properties and extension properties are not interpreted.
VEVENT alarms are ignored. Other calendar components are excluded with an
incomplete diagnostic. DTSTAMP and PRODID are not required for this audit, which
is deliberately not a full conformance validator. Leap-second timestamps are
unsupported and make the event incomplete. UID comparison is case-sensitive.

Recurring COUNT counts valid starts before EXDATE; excluding DTSTART does not
restart the count. Weekly intervals use WKST (Monday by default). DTSTART that
does not satisfy a supplied weekly BYDAY is rejected instead of defining an
unsynchronized series. Repeated EXDATE properties and comma-separated lists are
supported; their floating/absolute and DATE/DATE-TIME types must match DTSTART
(absolute exclusions may use UTC or another recognized IANA zone).

Input order is significant for local report IDs. Deduplication compares the whole
unfolded VEVENT text, including metadata/property order; reordering or updating
metadata can therefore make the UID ambiguous. This conservative policy can omit
otherwise equivalent events, and always reports that omission as incomplete.
Calendar exports must be snapshots: detached cancellation/scheduling messages are
not merged into historical versions. STATUS:CANCELLED suppresses a whole series,
subject to identity/override checks. Missing DTSTART is allowed only for this
whole-series cancellation case. Tentative events occupy time; individual attendee
acceptance/decline is not interpreted.

All resource flags may lower, but never exceed, the documented hard ceilings.
Library callers get cooperative time checks; the CLI additionally uses a POSIX
wall-clock signal that interrupts blocking work. Floating-time interpretation is a
user-selected convention, recorded per event, rather than an inferred home zone.
Pinned tzdata 2025.2 makes results reproducible but may not reflect later timezone
rule changes. Change the dependency deliberately and rerun fixtures before auditing
jurisdictions affected by newer rules.
