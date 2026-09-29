# Single-instance override contract (schema 2)

Frozen before implementation for version 0.2.0. This is a deliberately bounded
snapshot policy, not a claim of provider compatibility or novel recurrence work.

## References and existing implementations

[RFC 5545 §3.8.4.4](https://www.rfc-editor.org/rfc/rfc5545#section-3.8.4.4)
identifies a recurrence by its original start, even after a move. Value types must
match the master; floating identity remains floating. §3.8.5.1 makes EXDATE remove
starts from the recurrence set, while preserving the original DTSTART for identity.
§3.8.1.11 defines CANCELLED status; scheduling transactions are outside this audit.
§3.3.10 skips generated nonexistent local times without consuming COUNT.

Reviewed the source distributed in **recurring-ical-events 3.8.0**, especially
`series/rrule.py` (`Series.__init__`, `between`) and **python-dateutil
2.9.0.post0** (`rrule.py`). The former maps original identities to modifications,
selects highest sequence revisions, and separately queries moved modifications.
This audit instead rejects competing revisions and verifies recurrence membership.
These libraries provide useful independent comparisons, not an authoritative oracle.
Package releases: [recurring-ical-events 3.8.0](https://pypi.org/project/recurring-ical-events/3.8.0/),
[dateutil source](https://github.com/dateutil/dateutil/blob/2.9.0.post0/src/dateutil/rrule.py).

## Supported decisions

* A UID has one master and zero or more single-instance RECURRENCE-ID components.
  A master with exceptions must have a supported DAILY or WEEKLY RRULE. RANGE of
  any value is unsupported. Exceptions cannot contain RRULE, EXDATE, RDATE, EXRULE
  or DURATION. Nonrecurring masters with exceptions are incomplete.
* RECURRENCE-ID must use exactly the master's time form: DATE, floating, UTC, or
  the same recognized TZID. Equivalent identities expressed in another timezone
  are deliberately unsupported. Identity uses original local civil fields, not
  moved start or normalized gap instants. Ambiguous times use the first fold.
* Active exceptions require DTSTART. DTSTART keeps DATE versus DATE-TIME and
  floating versus absolute type; absolute effective timing may use another known
  zone. Explicit DTEND determines elapsed duration (civil days for DATE). Without
  DTEND, inherit the master's duration, not its absolute end. SUMMARY, TRANSP and
  STATUS inherit when absent; an explicit empty summary remains empty. No other
  descriptive properties affect analysis. Effective properties are recorded.
* STATUS:CANCELLED exceptions may omit DTSTART/DTEND. Any supplied timing is still
  validated. They suppress exactly their original identity, produce a cancellation
  diagnostic, and consume no occupancy. A cancelled master with any exceptions
  is ambiguous. Existing whole-series cancellations without exceptions remain valid.
* Every exception identity must belong to the valid master recurrence before
  EXDATE. An EXDATE targeting the same identity as any exception is incomplete,
  including cancellation exceptions: do not guess deletion versus restoration.
  Unrelated EXDATE values retain their existing behavior, including excluded seed.
* Compare complete unfolded component bytes (including property order/metadata).
  Exact duplicates merge source references. Distinct masters or distinct exceptions
  for one identity exclude the entire UID, irrespective of SEQUENCE/DTSTAMP.
  Component reordering does not change semantic results; local report IDs do change.
* Each input file is a snapshot boundary. For a UID appearing in multiple files,
  the set of complete component fingerprints must be identical in every file.
  Repeated identical components within a file are harmless. Never attach a detached
  exception from one file to a master in another. Different snapshot sets are
  incomplete and exclude that UID; unrelated UIDs are still analyzed.
* Expand original candidates through both the window end and the latest exception
  identity, even when the effective start is outside the window. Clip only after
  replacement. This finds instances moved into/out of the window, including an
  original identity after the window. Never count both original and replacement.
* Override families have a separate aggregate **200,000 resolution-candidate**
  ceiling (lowerable with `--max-resolutions`). Exhaustion excludes the unresolved
  family and marks the report incomplete. No partial family is retained. The
  existing candidate ceiling applies to ordinary families and remains fatal.
  Input, time, occurrence, pair and output ceilings remain fatal for all families.
* JSON schema 2 adds original recurrence identity, master/override references,
  effective timing and cancellation diagnostics. HTML offers both directions of
  those references. Transparent replacements remain traceable in event records
  but contribute no occurrences, preserving the previous transparency convention.

## Completion checks

Exercise moved starts/ends, inherited properties, cancellations, DATE/floating/
UTC/zoned types, DST gaps/folds, EXDATE, duplicates, source boundaries, orphans,
unsupported inputs and resolution exhaustion. Validate at least 200 seeded series
against independently materialized occurrences, all overlap pairs and occupancy.
Compare pinned independent implementations; retain discrepancies and explanations.
Retain baseline tests, offline installed CLI, network-blocked browser checks and
bounded process measurements. Only synthetic fixtures are used.
