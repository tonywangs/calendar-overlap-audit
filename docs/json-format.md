# JSON schema 1

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
| `occurrences` | IDs (`o1`…), event reference, all-day flag, original and clipped half-open bounds, timed display-zone bounds with offsets |
| `overlaps` | IDs (`p1`…), two occurrence references, UTC intersection bounds and exact positive seconds |
| `daily` | Local date, elapsed day length, union occupied seconds, timed occurrence count (including zero-length reminders), separate all-day count |
| `occupied_seconds` | Union of all clipped positive-duration timed intervals |

All-day bounds are ISO dates. Timed calculation bounds are UTC ISO timestamps
ending in `Z`; `local_start` and `local_end` use the selected display timezone with
explicit offsets. Original bounds allow readers to distinguish source duration from
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

Issue categories are `invalid_calendar`, `unsupported_component`,
`invalid_identity`, `ambiguous_identity`, and `unsupported_event`. Errors in a
file's component structure exclude the whole file, preserving its fingerprint.
Errors in one event's scheduling values exclude that event. Resource exhaustion
is a fatal CLI error, not a truncated schema-1 report. Even a syntactically valid
report with `complete: false` cannot support conclusions of no conflicts or free
time.

The supported subset is defined in [semantics.md](semantics.md); `complete` is not a
claim that arbitrary provider extensions were understood or that a user's supplied
files represent all commitments. It also does not imply attendance acceptance:
`ATTENDEE`/`PARTSTAT` are not interpreted.
