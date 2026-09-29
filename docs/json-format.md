# JSON schema 2

`report.json` is UTF-8, sorted-key, indented JSON with a trailing newline. Schema
version changes when interpretation or structure changes incompatibly. Tool and
runtime dependency versions are embedded. No wall-clock generation timestamp,
absolute source path, or hostname is included. Runtime measurements live separately
in reproducible experiment results, never in deterministic reports.

| Field | Meaning |
| --- | --- |
| `schema_version`, `tool_version`, `dependencies` | Interpretation and implementation versions |
| `window` | Inclusive start date, exclusive end date, IANA timezone and exact UTC bounds |
| `complete` | True only if every supplied file/event was interpretable within the documented subset |
| `issues` | Diagnostics with a `source` or `event` reference, stable category `code`, explanatory `message` |
| `limits`, `counts` | Effective resource limits and deterministic consumed counters (absent counters mean zero) |
| `sources` | Source IDs (`s1`…), basename, byte count and SHA-256 of original bytes |
| `events` | Event IDs (`e1`…), UID, summary, source/VEVENT ordinals, disposition, interpreted time basis and timezone where applicable |
| `occurrences` | IDs (`o1`…), event reference, all-day flag, effective and clipped half-open bounds, timed display-zone bounds with offsets |
| `cancellations` | Resolved single-instance cancellations: master, override, original identity and reason; includes identities outside the window |
| `overlaps` | IDs (`p1`…), two occurrence references, UTC intersection bounds and exact positive seconds |
| `daily` | Local date, elapsed day length, union occupied seconds, timed occurrence count (including zero-length reminders), separate all-day count |
| `occupied_seconds` | Union of all clipped positive-duration timed intervals |

All-day bounds are ISO dates. Timed calculation bounds are UTC ISO timestamps
ending in `Z`; `local_start` and `local_end` use the selected display timezone with
explicit offsets. Effective bounds allow readers to distinguish replacement duration from
clipping. An occurrence ending exactly at the window start is omitted. An
instantaneous event starting within the window is retained with equal bounds.

An event's `disposition` is `included`, `transparent`, `cancelled`, `duplicate`,
`ambiguous`, or `unsupported`. A `duplicate` has `duplicate_of`; the canonical event
retains every source citation. An included event may have no occurrences in the
window. All event ordinals are one-based within their source file. Event records
follow input file and VEVENT order, including duplicates and rejected events.
Occurrences follow canonical event order then recurrence order. Pair order follows
a deterministic interval sweep, not severity. IDs are local to a single report;
use source hash plus event ordinal/UID for input traceability, not cross-run ID
comparison after reordering inputs.

Occurrences contain `master` (canonical master event ID), `override` (canonical
exception ID or null), and `recurrence_id` (original recurrence identity, even when
moved). `event` identifies the effective component: override when replaced, master
otherwise. Identity is an ISO date for DATE, naive local ISO for floating, `Z` for
UTC, or local ISO with offset for zoned. Interpret it with the master's time basis
and timezone; do not compare it to the effective UTC start to identify instances.
Unmodified standalone events also have these fields, using their DTSTART identity.

Canonical event records have `role: master` or `role: override`. An override records
`master`, `recurrence_id`, effective summary/time basis/timezone, `effective_start`,
`effective_end`, `duration_seconds`, and `inherited` (omitted SUMMARY/TRANSP/STATUS
and/or duration). Effective start follows its time basis; timed effective end is UTC.
Cancellation timing is suppressed and informational, not an occupied interval.
Rejected records may have only the fields resolved before validation failed.
Duplicate records reference the canonical record; their own role fields may be
absent. Both canonical master and override provide HTML occurrence backreferences.

Issue categories include `invalid_calendar`, `unsupported_component`,
`invalid_identity`, `unsupported_event`, `conflicting_snapshots`, `conflicting_masters`,
`orphan_override`, `conflicting_overrides`, `cancelled_master_with_overrides`,
`nonrecurring_master`, `unsupported_range`, `incompatible_identity`,
`incompatible_timing`, `exdate_override_collision`, `unsupported_override`,
`missing_override_start`, and `resolution_limit`. Validation reports the first
family failure against each member; it does not promise every possible diagnostic.
A bad family has no retained occurrences or cancellation diagnostics. Its event
records and source hashes remain available. Ordinary resource exhaustion is fatal;
resolution exhaustion produces an incomplete report. Absence of pairs in an
incomplete report never establishes free time.

Schema 1 examples remain in `examples/synthetic-report` as historical artifacts.
Schema 2 changes UID family handling and adds traceability; consumers should check
`schema_version`. IDs are deterministic for identical ordered inputs, but are not
stable under component reordering. Occurrences remain in original recurrence order,
not effective chronological order after moves.

The supported subset is defined in [semantics.md](semantics.md); `complete` is not a
claim that arbitrary provider extensions were understood or that a user's supplied
files represent all commitments. It also does not imply attendance acceptance:
`ATTENDEE`/`PARTSTAT` are not interpreted.
