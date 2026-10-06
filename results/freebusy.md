# Offline free/busy validation

The new exporter preserves the existing occurrence pipeline and reports only its
complete merged occupied intervals. This is an interoperability-format milestone,
not a new calendar algorithm or a measured performance improvement.

## Reproducible evidence

Run `.venv/bin/python scripts/verify_freebusy.py` after the README's verification
setup. The suite includes 256 frozen seed values × two explicit all-day policies
(512 calendar/policy cases), endpoint-cell union expectations independent of
production occurrences, pinned `icalendar==6.3.2` parsing and wire-field checks.
Each case also repeats with reversed input order and identical export identity
and creation time. Input hashes are unchanged; planted descriptive secrets,
source paths and source hashes are absent from the artifact. Additional fixed
oracles cover recurrence at the spring gap and autumn fold.

The test suite also covers identity/time validation, octet folding, invalid
serializer intervals, ambiguous/nonexistent midnight boundaries, omission of
pair computation, unsupported calendars, malformed bytes, conflicting snapshots,
limits, filesystem failures, collision races, serialization failure, real SIGINT
and SIGTERM handling, and a signal deadline interrupting blocked serialization.
Invalid and incomplete cases withhold output; cleanup assertions reject leftover
owned output or staging directories. Existing production, frozen candidate,
browser, installed audit/availability CLI and historical workload gates remain.

Four isolated installed CLI workflows (ordinary, recurring overrides, spring,
fall) run twice offline with socket operations denied. Each reconstructed union
matches hand-specified intervals, inputs retain their hashes, and output bytes
match the checked-in [synthetic artifacts](../examples/freebusy/README.md).

## Bounded workload observations

[Machine-readable measurements](benchmark-freebusy.json) retain both fresh-process
runs per workload, source and input SHA-256 hashes, dependency versions, limits,
UTC measurement time, Python/platform details, CLI time, parent elapsed time,
Linux `VmHWM` peak RSS, artifact sizes and deterministic output hashes. The worker
blocks socket access. Timing below includes process startup and metric capture.
The oracle/reader comparison runs in the parent after timing; peak RSS measures
the export process, not the validation parent. No warmup or inferential speedup
claim is made. Replays compare deterministic results and hashes, not timing.

| Workload | Two elapsed observations (s) | Peak RSS range (KiB) | Artifact bytes | Result |
| --- | --- | ---: | ---: | --- |
| Empty 90-day horizon | 0.3023, 0.2518 | 25,420–25,448 | 259 | 0 periods |
| 1,000 disjoint commitments | 0.9423, 0.8247 | 33,228–33,356 | 56,259 | 1,000 periods |
| 2,000 coincident commitments | 1.2793, 1.5562 | 41,224–41,356 | 315 | 1 period |
| 40 daily series × 90 days | 0.5623, 0.5889 | 30,156–30,244 | 5,299 | 90 periods |
| Seeded spring, all-day block | 0.2755, 0.2727 | 25,728–25,756 | 819 | 10 periods |
| Seeded fall, all-day block | 0.2683, 0.2920 | 25,660–25,732 | 931 | 12 periods |
| 10-interval cap | 0.8649, 0.9034 | 33,224 | 0 | Exit 2, withheld |
| 100-occurrence cap | 0.3423, 0.2982 | 25,668–25,804 | 0 | Exit 2, withheld |
| 50-byte output cap | 1.0897, 0.8253 | 33,220–33,224 | 0 | Exit 2, withheld |
| Unsupported monthly recurrence | 0.2568, 0.2638 | 25,456–25,560 | 0 | Exit 2, withheld |

These are observations on one shared Linux/Python 3.12.3 environment. Memory grows
with input records and occurrences even when the merged export is tiny. The dense
workload's small artifact does not imply constant memory. Library and CLI limits
are described in [the supported export contract](../docs/freebusy.md).

## Limits of the evidence

All calendars are synthetic. The independent reader validates parseable output
and the suite explicitly checks required/allowed fields; parser acceptance alone
is not a complete RFC conformance proof. The reader also supplies input decoding
dependencies upstream, while the export serializer and mathematical oracle are
separate implementations. Real-provider import, subscription, scheduling and
CalDAV interoperability have not been performed. No account credentials were used.

The supported recurrence and snapshot subset remains conservative; private
calendars containing unsupported components cannot be exported as apparently
complete busy data. Unoccupied time is not working-hour availability. Precise
occupied times and chosen export identity/time remain disclosed, so this is not
anonymization. Hard kills and power failures may leave staging files.
