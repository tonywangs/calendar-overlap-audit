# Indexed selection results

**Decision: adopted.** Exact correctness and every frozen performance gate passed.
The production availability module is byte-identical to the measured candidate.
JSON schemas, recurrence/override handling, all-day policies, incomplete outcomes,
resource ceilings and example bytes are unchanged.

[Protocol and algorithm](../docs/indexed-selection.md),
[frozen hashes](../experiments/index-freeze.json),
[raw observations](benchmark-index.json), and
[machine-readable decision](index-decision.json) preserve the experiment.
The source baseline is the catalog tree
`b803165876f77ce5fef0c49c6d56cf6848dcd1d7`, saved as
`tests/baseline/occurrence-pipeline.json` and authenticated against the earlier
occurrence-only measurements. No historical examples or measurements were replaced.

## Six balanced pairs per workload

Measured 2026-10-02 on the recorded Linux/Python environment. Values separated by
`/` are baseline / candidate. End-to-end and availability-stage times are medians
in seconds. Peak RSS is the maximum of six fresh-process Linux VmHWM observations
in KiB. Improvement is positive for faster candidate execution.

| Workload | End-to-end (s) | Improvement | Availability stage (s) | Peak RSS (KiB) |
| --- | ---: | ---: | ---: | ---: |
| short_empty | 0.2942 / 0.2914 | +1.0% | 0.0003 / 0.0003 | 27,012 / 27,064 |
| short_sparse | 0.3352 / 0.3415 | -1.9% | 0.0030 / 0.0030 | 27,520 / 27,540 |
| short_dense | 0.3131 / 0.3146 | -0.5% | 0.0005 / 0.0007 | 27,180 / 27,024 |
| short_spanning | 0.3467 / 0.3436 | +0.9% | 0.0022 / 0.0023 | 27,268 / 27,256 |
| long_sparse | 2.7733 / 1.8341 | +33.9% | 1.1722 / 0.2795 | 92,404 / 92,560 |
| long_dense | 2.0771 / 1.0934 | +47.4% | 1.0259 / 0.0457 | 59,096 / 58,124 |
| long_spanning | 0.6597 / 0.6122 | +7.2% | 0.0852 / 0.0771 | 38,056 / 38,140 |
| long_all_day | 0.7422 / 0.7651 | -3.1% | 0.1046 / 0.1029 | 37,784 / 39,856 |

Both predefined long-horizon targets improved by more than 20% end-to-end.
The largest control regression was `long_all_day`: **22.9 ms / 3.1%** end-to-end.
It exceeds 20 ms but not 10%, so the conjunctive gate passes. Its RSS increase,
**2,072 KiB / 5.5%**, also passes. `short_sparse` regressed **6.3 ms / 1.9%** and
`short_dense` **1.4 ms / 0.5%**. Stage-level overhead also appears in tiny/dense
short cases; this is not a universal speedup. All JSON and HTML hashes are exact
across both implementations and all repetitions, with unchanged source/spec hashes.

## Correctness and verification

256 new seeded cases compare complete baseline and candidate report dictionaries
and deterministic JSON in both compatibility modes, with a nonbinding 30-second
per-report deadline. The independent elementary-segment oracle verifies every
busy union, contributor, endpoint witness, complement and gap citation. Cases
include three-day horizons, spring/fall DST, two sources, moved/cancelled/transparent
recurrence instances, unsupported rules, long and nested intervals, tied boundaries,
zero lengths and both all-day policies. Another 32 cases directly exercise split
windows, repeated dates and exact touching boundaries. Timed and all-day fanout
tests check deadline enforcement within bucket assignment. Additional CLI tests
interrupt lazy index consumption with deadlines, SIGINT and SIGTERM, checking
input preservation and cleanup.

The frozen candidate passed all 457 pre-existing tests, including original seeded
oracles, resource exhaustion, malformed inputs, output collisions, serialization
failures, SIGINT/SIGTERM cleanup and network-blocked Chromium. Final package
verification passed **750 tests** and additionally ran installed CLIs in an
isolated environment from a locally built wheel, preserving input hashes and
reproducing checked-in examples.
`results/tests.log` contains the latest production test output. Historical workload
replays use authenticated historical source; the new replay uses both frozen
implementations. It verifies outcomes and bytes, never historical runtime values.

## Reproduce

After the dependency, Chromium and local wheelhouse preparation in the README,
run this single command to verify all evidence and collect a fresh six-pair run:

```sh
.venv/bin/python scripts/verify_index.py --measure /tmp/calendar-index-new.json
```

Choose a new output filename. For verification plus one pair per workload without
collecting a new six-pair run, omit `--measure`. New runs do not overwrite the
historical evidence or automatically change the production decision. The script
prints and records fresh observations; a different host may produce a different
performance gate outcome. No external data or services are required after setup.

## Limitations

All data is synthetic; real-provider compatibility and performance remain
unverified. Shared-host process timings include scheduler/I/O variability and are
observations, not guarantees or a statistical significance claim. Repetition order
is balanced, with no warmup or post-hoc workload tuning. RSS is an observed peak,
not a hard memory cap. The index retains O(N+A+W+K) auxiliary state; long spans can
make K proportional to occurrences times windows. Output/provenance memory and
sorting costs remain, and maximum combinations may hit time/report limits.
Split windows are tested internally but are not added to public spec v1. The
pinned timezone database and existing supported iCalendar subset are unchanged.
