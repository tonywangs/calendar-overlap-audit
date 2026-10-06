# Offline occupied-time export

## Contract frozen before implementation (2026-10-06)

`calendar-freebusy` accepts local calendars, required ISO civil-date `--start`
and exclusive `--end` (1–90 days), `--timezone`, explicit `--all-day block|ignore`,
and a new `--output` directory. It writes only `busy.ics`. No schedule is read:
closed working hours are not event occupancy, and unoccupied time is not a claim
of working-hour availability or a booking guarantee.

The existing occurrence-only pipeline supplies recurrence, exceptions, moved
occurrences, cancellation, transparency, tentative-event, floating-time, timezone,
deduplication and conservative snapshot semantics. See [semantics](semantics.md)
and [overrides](overrides.md). Any incomplete analysis withholds the whole export,
even when the problematic event is outside the horizon or all-day events are
ignored. This is completeness within the supported subset, not full RFC validation.

Timed intervals are clipped to `[start, end)` UTC instants. `block` maps DATE
occupancy to full civil days in the selected timezone; `ignore` omits it.
Zero-duration occupancy is omitted. Overlapping and adjacent intervals merge.
Horizon and blocked all-day midnight boundaries must be unambiguous and existent
(using the existing schedule boundary policy); unsupported boundaries fail closed.
The event pipeline's established gap/fold policies remain unchanged.

Output is a minimal VCALENDAR containing VERSION 2.0, constant PRODID and one
VFREEBUSY, with UID, DTSTAMP, DTSTART, DTEND and zero or more sorted
FREEBUSY;FBTYPE=BUSY start/end periods. All date-times use whole-second UTC `Z`.
No METHOD, ORGANIZER, recurrence properties, source metadata or diagnostic sidecar
is emitted. This is an RFC 5545 data object, not an iTIP publish transaction.
RFC 5545 calls the VFREEBUSY bounds an inclusive enclosing window; the occupancy
calculation uses half-open intervals, including periods that end at the envelope
end. A nonzero horizon with no occupancy is valid and has no FREEBUSY properties;
a zero-length horizon is rejected.

A fresh random UUID4 in `urn:uuid:` form identifies each export independently of
source identities. DTSTAMP defaults to creation time (current UTC, truncated to
seconds). For byte-identical reproduction, supply `--uid` as a canonical UUID4
and `--created-at YYYY-MM-DDTHH:MM:SSZ`. The resulting UID is still prefixed
`urn:uuid:`. Caller-supplied values must be independently chosen: never reuse a
source UID. Explicit timestamps describe the intended artifact creation instant,
not source modification time. No separate CREATED property is used. Serialization
uses CRLF and folds content lines at 75 octets with a space continuation.

Only structural constants, chosen export identity/time, horizon bounds and merged
occupied times reach the serializer. Event UIDs, titles, descriptions, locations,
attendees, organizers, URLs, paths and hashes cannot be copied by this projection.
**Precise occupied times remain disclosed. This is not anonymization.** A reused
export UUID can link artifacts, and a caller can deliberately encode information
in a supplied UUID or timestamp. Share only with intended recipients.

## Prior work and standards reviewed

[RFC 5545](https://www.rfc-editor.org/rfc/rfc5545.html) §§3.1, 3.3.9, 3.6.4,
3.7.3–4, 3.8.2.6 and 3.8.7.2 define folding, positive periods, component fields,
calendar fields, UTC busy values, ordering and creation time. The local pinned
`icalendar==6.3.2` FreeBusy class declares required UID/DTSTAMP and optional
repeated FREEBUSY; its reader will independently parse the custom serializer's
output. Its [API documentation](https://icalendar.readthedocs.io/en/stable/reference/api/icalendar.cal.free_busy.html)
and [iCal4j's existing FreeBusy service](https://www.ical4j.org/freebusy/) were
reviewed. Busy-time exchange is established functionality; no novelty is claimed.
The reader shares input decoding dependencies with the occurrence pipeline but
is independent of the export serializer and mathematical interval oracle.

## Bounded validation protocol

Freeze 256 calendar seeds starting at 554500, both all-day policies, and an
independent endpoint-cell union oracle derived from generator expectations,
never from production occurrences. Cover empty occupancy, spanning and touching
intervals, overlaps across calendars, duplicate snapshots, DAILY/WEEKLY recurrence,
EXDATE, moved/cancelled overrides, transparent/tentative events, floating times,
DATE spans and both New York DST transitions. Parse every generated export with
pinned icalendar; assert exact union, required/allowed properties, UTC, ordering,
positive durations, containment, CRLF/folding and planted-secret absence. Hash
inputs before/after and verify deterministic identity/time reproduction.

Retain the full schedule verification chain and historical evidence. Add malformed
and unsupported input, limits, cancellation, collision, serialization and cleanup
checks. Install a wheel into an isolated environment offline; exercise ordinary,
recurring and both DST examples with socket access denied. Record fresh-process
elapsed time, Linux peak RSS, artifact sizes, dependency versions and hashes for
bounded empty, sparse, dense, recurring, DST and rejected workloads. Timing and
memory are observations on a shared host, not performance thresholds. Synthetic
parser validation does not establish provider interoperability.

## Setup and use

Follow [README installation](../README.md#install-and-run). The new command uses
the existing pinned runtime dependencies; it requires no account or network.
Reinstall the package after updating a checkout to register the new entry point.

```sh
.venv/bin/python -m pip install --no-build-isolation -e .
.venv/bin/calendar-freebusy examples/freebusy/ordinary.ics \
  --start 2026-03-03 --end 2026-03-04 --timezone UTC --all-day ignore \
  --uid 5e603c28-3e93-4cf5-9e25-0e0e48aab378 --created-at 2026-10-06T01:00:00Z \
  --output /tmp/ordinary-busy
```

This merges three commitments into one 09:00–11:00 BUSY period. The example UUID
and timestamp are for reproducible samples; omit them to generate a fresh export.
Only `/tmp/ordinary-busy/busy.ics` is written. The output directory and file use
permissions 0700 and 0600. Choose a new destination each time. An output collision
(including a symlink or an input file) fails without overwriting it. Signals and
handled filesystem/serialization failures clean up owned output and staging.
SIGKILL, machine failure and concurrent readers are outside that cleanup guarantee.

[Complete examples](../examples/freebusy/README.md) cover recurrence overrides,
both DST transitions and all-day policy. To inspect why an export was withheld,
run `calendar-audit` separately with the same inputs and horizon into a new private
directory; its report contains source identities and must not accompany the
shareable busy artifact. No diagnostic report is generated implicitly.

Exit status: 0 exported; 2 incomplete analysis or exhausted resources (no export);
1 invalid settings, missing inputs, serialization or filesystem failure; 130
cancellation. Argparse also returns 2 for missing/unknown command arguments.

## Resource bounds and compatibility

Every limit below is a positive hard ceiling; command flags may only lower it.
Bounds apply across all supplied calendars, with `--max-report-bytes` applied to
the complete serialized artifact. `--max-intervals` counts the final merged union;
raw occupancy remains bounded by `--max-occurrences`. There is no pair computation
and no `--max-pairs` option on this command.

| Flag | Default and maximum |
| --- | ---: |
| `--max-files` | 32 |
| `--max-input-bytes` | 8,388,608 aggregate |
| `--max-line-bytes` | 65,536 physical/unfolded |
| `--max-events` | 5,000 |
| `--max-candidates` | 200,000 |
| `--max-resolutions` | 200,000 |
| `--max-occurrences` | 20,000 |
| `--max-intervals` | 20,000 merged periods |
| `--max-seconds` | 30 POSIX wall-clock seconds |
| `--max-report-bytes` | 8,388,608 |

The horizon is at most 90 civil days. Input and occurrence records, interval
sorting and the output buffer are materialized; memory is not constant. The union
stage is O(N log N) time and O(N) memory, while upstream daily summaries retain
existing O(D N) work. A runtime cap can stop a workload below other ceilings.
Library calls have cooperative checks; the CLI adds a POSIX signal deadline.
Linux is measured, macOS execution is unverified. Provider import/subscription
behavior, iTIP/CalDAV workflows and actual Google/Apple/Outlook interoperability
have not been tested. Embedded VTIMEZONE, RDATE, DURATION and recurrence outside
the documented subset withhold output. Pinned tzdata may lag later rule changes.

## Verify and reproduce evidence

Prepare the offline wheelhouse and Chromium as described in the README verification
section (the preserved historical browser tests still need Chromium). Then run:

```sh
.venv/bin/python scripts/verify_freebusy.py
```

This checks production tests, frozen regressions, historical result hashes,
independent seeded and fixed oracles, installed CLI workflows and all measured
workload outputs. It never compares new timing observations to historical timing
thresholds. It does not modify saved results. To collect new observations:

```sh
.venv/bin/python scripts/benchmark_freebusy.py --output /tmp/new-freebusy-measurements.json
```

Choose a new output file. See [measurements and limitations](../results/freebusy.md).
