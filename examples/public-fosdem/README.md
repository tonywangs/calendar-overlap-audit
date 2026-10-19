# Real public calendar: FOSDEM 2025

Open [the interactive report](report/report.html) locally. It contains **24 events,
8 overlapping pairs and 27,900 seconds (7 h 45 min) of occupied programming** on
February 1, 2025, displayed in New York time. February 2 has zero occupied time.
These are public conference sessions across two tracks, **not Tony's personal
commitments, attendance, or availability**. Overlap is expected between rooms.

## Launch

From the repository root, after the main README installation:

```sh
.venv/bin/calendar-audit examples/public-fosdem/bsd.ics \
  examples/public-fosdem/legal-and-policy.ics \
  --start 2025-02-01 --end 2025-02-03 \
  --timezone America/New_York --floating-timezone Europe/Brussels \
  --output /tmp/fosdem-audit
```

Choose a new output path if that directory already exists. Open
`/tmp/fosdem-audit/report.html` in a browser (macOS: `open` that path;
Linux desktop: `xdg-open` that path). No web server or account is needed.
Search for `FreeBSD security audits`, follow an overlap's occurrence link, follow
its event record, then return through its occurrence backreference. Escape clears
filters; the Source selector separates tracks. Daily totals remain unfiltered.

## Inputs, attribution and reuse

These files are complete, unchanged public exports of the BSD and Legal and Policy
tracks, retrieved October 19, 2026 from the official FOSDEM archive:

- [BSD source page](https://archive.fosdem.org/2025/schedule/track/bsd/) and
  [original iCalendar export](https://archive.fosdem.org/2025/schedule/track/bsd.ics).
- [Legal and Policy source page](https://archive.fosdem.org/2025/schedule/track/legal-and-policy/)
  and [original iCalendar export](https://archive.fosdem.org/2025/schedule/track/legal-and-policy.ics).

Attribution: **FOSDEM 2025 and the speakers credited in the original exports**.
The footer on both track pages states Creative Commons Attribution 2.0 Belgium;
the same pages' `DC.Rights` metadata instead points to Attribution-ShareAlike 2.0
Belgium. Both notices are recorded in [provenance.json](provenance.json), together
with exact source URLs, retrieval times, sizes and SHA-256 digests. To accommodate
the stricter notice, the preserved data and derived example HTML/JSON are
redistributed under [CC BY-SA 2.0 Belgium](https://creativecommons.org/licenses/by-sa/2.0/be/),
with the [original CC BY notice](https://creativecommons.org/licenses/by/2.0/be/deed.en)
also retained. This does not assign that license to the application code.

No original bytes were rewritten. The report is a derived work: it drops most
metadata, resolves the explicitly selected source timezone, converts display times,
and computes overlaps and unions. Keep this attribution and provenance alongside
copies of the example report.

## The interoperability defect this exposed

The raw exports have floating `DTSTART`/`DTEND`, calendar-level
`X-WR-TIMEZONE:Europe/Brussels`, and standalone event `TZID:Europe-Brussels`.
The latter is not the standard `TZID=Europe/Brussels` parameter on each datetime.
The [official schedule](https://archive.fosdem.org/2025/schedule/) explicitly says
all times are CET (UTC+1). This external evidence justifies the operator assertion
`--floating-timezone Europe/Brussels` for these February dates.

Previously, selecting New York display time interpreted 15:00 as New York 15:00;
the resulting report still claimed completeness. It is now 14:00 UTC / 09:00 New
York, as the published Brussels schedule requires. Without the explicit assertion,
these nonstandard timezone hints now produce a provisional **INCOMPLETE** report
and exit 2. Plain RFC floating calendars without such hints retain the documented
display-zone default.

The option applies to floating datetimes in **all** input files, including recurrence
identities, exclusions and overrides. It does not override UTC or standard TZID
parameters; all-day DATE values remain civil dates in the display window. It is
recorded in JSON and shown in HTML. Different floating source zones require
separate invocations. Source hints are not automatically trusted or normalized.

## Independent reproducible checks

```sh
.venv/bin/python scripts/verify_public.py
```

Use the main README's verification dependency and wheelhouse preparation first.
The script installs a freshly built wheel in an isolated environment and runs its
CLI outside the checkout. It verifies source checksums and compares every event,
overlap and daily total with a deliberately separate parser and a set-of-seconds
oracle. The oracle uses published CET (+01:00), winter New York (-05:00), and Tokyo
(+09:00) offsets, rather than the application's timezone loader or interval code.
Tokyo shifts late sessions across midnight, checking local-day allocation as well
as clock conversion. The frozen files contain no recurrence or DST transition;
this example cannot validate those provider behaviors.

The same script launches offline Chromium and exercises search, source filtering,
keyboard navigation, overlap → occurrence → event → occurrence links, Escape,
clear filters and JavaScript-disabled rendering. It compares the installed output
byte-for-byte with the checked-in HTML/JSON. It also checks that omitting the source
assertion returns an incomplete report. A missing browser or wheelhouse fails the
check; it is never silently skipped.

This validates these two exports, not all FOSDEM tracks, personal providers,
recurring appointments, health inference or real personal availability. The
application's other documented subset limits still apply. No accounts were used.
