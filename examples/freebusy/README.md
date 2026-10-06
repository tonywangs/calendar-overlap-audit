# Synthetic free/busy examples

These examples contain fabricated data. Each `*-busy.ics` is a complete generated
calendar, with fixed export UUID `5e603c28-3e93-4cf5-9e25-0e0e48aab378` and creation
time `2026-10-06T01:00:00Z` for byte-identical reproduction. Do not reuse this sample
identity for personal exports. The export contains precise occupied times.

All commands below require the package installed per the root README, create a
new output directory, and use the explicit `ignore` all-day policy.

```sh
.venv/bin/calendar-freebusy examples/freebusy/ordinary.ics \
  --start 2026-03-03 --end 2026-03-04 --timezone UTC --all-day ignore \
  --uid 5e603c28-3e93-4cf5-9e25-0e0e48aab378 --created-at 2026-10-06T01:00:00Z \
  --output /tmp/freebusy-ordinary

.venv/bin/calendar-freebusy tests/fixtures/overrides.ics \
  --start 2026-03-03 --end 2026-03-06 --timezone UTC --all-day ignore \
  --uid 5e603c28-3e93-4cf5-9e25-0e0e48aab378 --created-at 2026-10-06T01:00:00Z \
  --output /tmp/freebusy-recurring

.venv/bin/calendar-freebusy tests/fixtures/dst-spring.ics \
  --start 2026-03-07 --end 2026-03-11 --timezone America/New_York --all-day ignore \
  --uid 5e603c28-3e93-4cf5-9e25-0e0e48aab378 --created-at 2026-10-06T01:00:00Z \
  --output /tmp/freebusy-spring

.venv/bin/calendar-freebusy tests/fixtures/dst-fall.ics \
  --start 2026-10-31 --end 2026-11-03 --timezone America/New_York --all-day ignore \
  --uid 5e603c28-3e93-4cf5-9e25-0e0e48aab378 --created-at 2026-10-06T01:00:00Z \
  --output /tmp/freebusy-fall
```

| Example | Merged BUSY periods | Occupied elapsed time |
| --- | ---: | ---: |
| Ordinary adjacent/nested commitments | 1 | 2 hours |
| Recurring moved/cancelled/transparent overrides | 1 | 2.5 hours |
| Spring gap and exact elapsed recurrence | 4 | 10.5 hours |
| Fall first fold and explicit longer interval | 3 | 4 hours |

The spring recurrence skips its generated nonexistent 02:30 start. The existing
fixed elapsed duration policy is preserved; adjacent occupied periods merge.
For a DATE-blocking example, repeat the spring command with `--all-day block`
and another output directory: expected periods are `20260307T050000Z/20260310T040000Z`
and `20260310T063000Z/20260310T073000Z`, totaling 72 elapsed hours (71 + 1).

Empty occupancy is valid: use the ordinary input with `--start 2026-04-01 --end
2026-04-02`. It yields one VFREEBUSY envelope with no FREEBUSY properties. A
zero-length horizon fails. Multiple input paths combine commitments before union;
no working schedule is applied.

The verification script installs an isolated wheel offline, runs every command
above twice with sockets disabled, checks unchanged inputs, compares to these
artifacts byte for byte, and parses results against hand-specified UTC intervals.
Provider interoperability is unverified.
