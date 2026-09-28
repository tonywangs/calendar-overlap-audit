# Calendar overlap audit

Turn local `.ics` exports into a traceable, offline report of overlapping
commitments and occupied time. Every finding links to an event record and source
fingerprint. No accounts, server, API keys, or personal calendar access are needed.

**Working example:** the synthetic calendar has **3 overlapping pairs and 6.5
occupied hours** over March 6–10, 2026 in `America/New_York`. Nested meetings do not
inflate occupancy. All-day entries are shown separately.

A [checked-in synthetic HTML report](examples/synthetic-report/report.html) and its
[JSON data](examples/synthetic-report/report.json) are included for local inspection.

## Install and run

Python 3.11+ on Linux or macOS with POSIX signals is required. Linux/Python 3.12 is
the tested platform. Install dependencies once; analysis itself is offline.

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m pip install --no-build-isolation -e .
.venv/bin/calendar-audit tests/fixtures/synthetic.ics \
  --start 2026-03-06 --end 2026-03-11 --timezone America/New_York \
  --output /tmp/calendar-synthetic-report
```

Open `/tmp/calendar-synthetic-report/report.html` directly in a browser.
`report.json` contains deterministic, versioned data with exact integer seconds.
The end date is **exclusive**. Choose a fresh output directory for each audit;
existing files, directories, and symlinks are never overwritten. Multiple inputs
are accepted before the options. Runtime dependencies are pinned in `pyproject.toml`;
verification dependencies are pinned in `requirements-dev.txt`.

If your Linux distribution omits `venv`/`ensurepip`, install its Python venv package
through your normal environment setup before following these instructions.

## What the report means

* Occupied time is the **union** of positive-duration timed intervals, clipped to
  the requested 1–90 civil-day window. Touching ends are not overlaps.
* Daily totals split at local midnight; DST days may have 23 or 25 hours.
* Daily and weekly recurrence supports `COUNT`, inclusive `UNTIL`, `INTERVAL`,
  `EXDATE`, and weekly `BYDAY`/`WKST`. The analysis window and candidate limit bound
  rules without `COUNT` or `UNTIL`.
* Floating times use the explicitly chosen display timezone. All-day events,
  cancelled events and transparent events do not consume timed occupancy.
* Identical unfolded event definitions with the same UID are counted once across
  files, retaining source citations. Different definitions or overrides sharing a
  UID are excluded as ambiguous.
* An **INCOMPLETE** banner means some data could not be interpreted. Reported
  occupancy and overlaps are provisional. Zero detected overlaps never proves
  availability.

See [supported semantics and exclusions](docs/semantics.md),
[JSON schema conventions](docs/json-format.md), and
[measured validation results](results/README.md).

The HTML provides search, type and source filters, event backreferences, and native
keyboard navigation. Tab moves through controls; Enter follows links; Escape clears
filters. Following a hidden occurrence citation reveals it. Summary totals always
refer to the full analysis, not the filtered view. The page also works without
JavaScript, with all findings visible.

## Resource limits and failure behavior

| Resource | Hard ceiling (default) |
| --- | ---: |
| Total input bytes | 8 MiB |
| Input files | 32 |
| Physical/unfolded line bytes | 64 KiB |
| VEVENT definitions | 5,000 |
| Recurrence candidates, including before window | 200,000 |
| Retained occurrences, including all-day/zero-length | 20,000 |
| Overlapping pairs | 20,000 |
| Each output report | 8 MiB |
| CLI wall time | 30 seconds |

Use `--max-input-bytes`, `--max-files`, `--max-line-bytes`, `--max-events`,
`--max-candidates`, `--max-occurrences`, `--max-pairs`, `--max-report-bytes`, and
`--max-seconds` to **lower** limits. They cannot be raised above the ceilings.
Limits fail the audit instead of publishing truncated findings. Very old rules can
exhaust the candidate budget before reaching the window. `--help` lists options.

Exit codes: **0** complete within the supported subset, **2** incomplete report
written, **1** invalid arguments/operational or limit failure (argparse syntax
errors also use 2, without a report), **130** interrupted. Handle both the exit code
and existence of the requested bundle in automation.

Input files are read-only. Output directories are mode `0700`, report files `0600`.
Writes are staged, then placed into an exclusively reserved new directory. Ordinary
write failures and handled cancellation remove this run's partial files. The two
files are not an atomic transaction for concurrent readers; consume the bundle
after successful process completion. A hard kill/power loss can leave hidden
staging directories or an incomplete destination; remove those manually after
confirming no audit is running. Cancellation after publication can leave a complete
bundle. Existing destinations are never deleted.

Reports retain summaries, UIDs and source basenames, so they can contain private
information. Attendees, descriptions, locations, URLs and alarm fields are omitted.
Imported text is escaped; the report has no external assets or network requests.
This is not an anonymizer or a general-purpose hostile-file sandbox.

## Reproduce validation

Prepare the offline verification dependencies once (requires network):

```sh
PLAYWRIGHT_BROWSERS_PATH="$PWD/.cache/ms-playwright" .venv/bin/python -m playwright install chromium
mkdir -p .cache/wheels
.venv/bin/python -m pip download --only-binary=:all: --dest .cache/wheels \
  'icalendar==6.3.2' 'tzdata==2025.2' 'python-dateutil==2.9.0.post0' 'six==1.17.0'
```

Chromium also needs its standard Linux system libraries. Missing browser binaries
or libraries fail the suite; browser checks are never silently skipped.

Then run the complete verification suite with one command:

```sh
.venv/bin/python scripts/verify.py
```

This runs unit and seeded exhaustive-oracle tests, actual Chromium interaction with
network access blocked, output-failure/cancellation tests, and a freshly built wheel
installed into an isolated virtual environment entirely from local wheels. The
installed CLI runs outside this checkout with socket creation blocked.

Recreate the bounded workload measurements separately:

```sh
.venv/bin/python scripts/benchmark.py --output /tmp/calendar-benchmark.json --repeats 3
```

Every input is synthetic and reproducible. Compatibility with real provider exports
is **unverified**. Unsupported features include monthly/yearly rules, custom
`VTIMEZONE`, `DURATION`, `RDATE`, recurrence overrides and scheduling messages. This
is an intentionally limited audit tool, not a full iCalendar validator or a new
recurrence algorithm.
