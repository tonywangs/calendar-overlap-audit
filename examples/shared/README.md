# Complete synthetic shared-window example

All names, schedules and commitments are synthetic. `report.html` opens directly
from disk without a server or network. The JSON and HTML are deterministic.

Alex works 09:00–17:00 in New York on Monday and Tuesday. Sam works the same hours
in London. For a 30-minute meeting, shared candidate ranges are:

| UTC date | UTC window | Duration |
| --- | --- | --- |
| March 9, 2026 | 13:00–14:00 | 60 minutes |
| March 9, 2026 | 15:00–15:30 | 30 minutes |
| March 9, 2026 | 16:00–17:00 | 60 minutes |
| March 10, 2026 | 13:00–15:00 | 120 minutes |

Sam's source ends March 10 at 15:00 UTC. The remaining nine hours of the horizon
are unknown for Sam, not free. The export coverage timezone is independent of
the participant's working timezone: Sam's synthetic export uses Tokyo date
bounds to demonstrate partial coverage. The manifest explicitly asserts that
each source includes complete occupancy within its own bounds.

After installing the project, from this directory:

```sh
calendar-shared --manifest manifest.json --output /tmp/shared-example-report
```

To reproduce from the synthetic VEVENT calendars using fresh output directories:

```sh
calendar-freebusy alex-calendar.ics --start 2026-03-09 --end 2026-03-11 \
  --timezone UTC --all-day ignore \
  --uid 5e603c28-3e93-4cf5-9e25-0e0e48aab378 --created-at 2026-10-10T01:00:00Z \
  --output /tmp/alex-synthetic-export
calendar-freebusy sam-calendar.ics --start 2026-03-09 --end 2026-03-11 \
  --timezone Asia/Tokyo --all-day ignore \
  --uid 5e603c28-3e93-4cf5-9e25-0e0e48aab378 --created-at 2026-10-10T01:00:00Z \
  --output /tmp/sam-synthetic-export
cmp /tmp/alex-synthetic-export/busy.ics alex-busy.ics
cmp /tmp/sam-synthetic-export/busy.ics sam-busy.ics
calendar-shared --manifest manifest.json --output /tmp/shared-example-report
```

Reproduce every fixture and both report files into a **new** directory from the
repository root:

```sh
.venv/bin/python scripts/shared_examples.py --output /tmp/shared-reproduced
```

The shared command accepts only this documented VFREEBUSY subset, not arbitrary
VEVENT calendars. Read [the contract](../../docs/shared-windows.md) before
asserting completeness on any real input. Neither local reports nor exports
establish provider interoperability or real-world availability.
