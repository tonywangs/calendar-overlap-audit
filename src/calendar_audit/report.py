"""Deterministic, escaped, self-contained HTML. No imported executable content."""
from html import escape
import json

from .core import AuditError


def json_bytes(report):
    return (json.dumps(report, ensure_ascii=True, sort_keys=True, indent=2) + '\n').encode('utf-8')


def esc(value):
    return escape(str(value), quote=True)


def hours(seconds):
    return f'{seconds / 3600:.2f} h'


STYLE = '''
:root {color-scheme:light dark; font:17px/1.55 system-ui,sans-serif; --line:#80808070}
body {max-width:1100px; margin:auto; padding:1.5rem; background:Canvas; color:CanvasText}
a {color:LinkText} h1 {line-height:1.15} h2 {margin-top:2.5rem}
nav, .controls {display:flex; gap:1rem; flex-wrap:wrap}
.controls {padding:1rem; border:1px solid var(--line); border-radius:.5rem}
label {display:flex; flex-direction:column} input,select {font:inherit; max-width:100%; padding:.3rem}
button {font:inherit; padding:.3rem .7rem} :focus-visible {outline:3px solid #bc7100; outline-offset:3px}
:target {outline:3px solid #bc7100; outline-offset:3px}
.card {border:1px solid var(--line); border-radius:.5rem; padding:1rem; margin:.8rem 0; overflow-wrap:anywhere}
.warning {border-left:5px solid #bc7100; padding:1rem; background:#bc710015}
.stats {font-size:1.25rem} .muted {opacity:.8} code {overflow-wrap:anywhere}
table {border-collapse:collapse; width:100%} th,td {padding:.5rem; text-align:left; border-bottom:1px solid var(--line)}
.scroll {overflow:auto} [hidden] {display:none !important} .skip {position:absolute; left:-10000px}
.skip:focus {position:static} small {font-size:.85rem} @media print {.controls,nav,.skip {display:none}}
'''

SCRIPT = '''
const search = document.getElementById('search');
const kind = document.getElementById('kind');
const source = document.getElementById('source');
const occurrences = [...document.querySelectorAll('[data-occurrence]')];
const overlaps = [...document.querySelectorAll('[data-pair]')];
function filter() {
  const query = search.value.toLocaleLowerCase();
  const visible = new Set();
  for (const row of occurrences) {
    const match = row.dataset.search.toLocaleLowerCase().includes(query)
      && (!kind.value || row.dataset.kind === kind.value)
      && (!source.value || row.dataset.sources.split(' ').includes(source.value));
    row.hidden = !match;
    if (match) visible.add(row.id);
  }
  let pairs = 0;
  for (const row of overlaps) {
    row.hidden = !row.dataset.refs.split(' ').some(id => visible.has(id));
    if (!row.hidden) pairs++;
  }
  document.getElementById('filter-status').textContent =
    `${visible.size} occurrences and ${pairs} overlap pairs shown. Totals remain unfiltered.`;
}
for (const control of [search, kind, source]) control.addEventListener('input', filter);
function reset() { search.value = ''; kind.value = ''; source.value = ''; filter(); }
document.getElementById('reset').addEventListener('click', reset);
document.addEventListener('keydown', event => {
  if (event.key === 'Escape') { reset(); search.focus(); }
});
// Citation navigation must also work when a filter hid the destination.
document.addEventListener('click', event => {
  const link = event.target.closest('a[href^="#"]');
  if (link) {
    const target = document.getElementById(link.getAttribute('href').slice(1));
    if (target && target.hidden) reset();
  }
});
filter();
'''


def html_bytes(report, budget):
    chunks = []
    size = 0

    def add(value):
        nonlocal size
        budget.check()
        size += len(value.encode('utf-8'))
        if size > budget.limits.report_bytes:
            raise AuditError('report_bytes limit exceeded (HTML)')
        chunks.append(value)

    events = {event['id']: event for event in report['events']}
    occurrences = {o['id']: o for o in report['occurrences']}
    by_master = {e: [] for e in events}
    for event in events.values():
        if event.get('master') in by_master:
            by_master[event['master']].append(event)
    by_event = {e: [] for e in events}
    for o in occurrences.values():
        by_event[o['event']].append(o['id'])
        if o.get('master', o['event']) != o['event']:
            by_event[o['master']].append(o['id'])
    add('<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<meta http-equiv="Content-Security-Policy" content="default-src &#39;none&#39;; '
        'script-src &#39;unsafe-inline&#39;; style-src &#39;unsafe-inline&#39;; '
        'base-uri &#39;none&#39;; form-action &#39;none&#39;">'
        '<title>Calendar overlap audit</title><style>' + STYLE + '</style></head><body>')
    add('<a class="skip" href="#main">Skip to report</a><header><p>OFFLINE CALENDAR AUDIT · SCHEMA 2</p>'
        '<h1>Where commitments overlap</h1><p>Exclusive event ends · union-based occupied time · all-day events kept separate</p></header>'
        '<nav aria-label="Report sections"><a href="#daily">Daily summary</a><a href="#overlaps">Overlaps</a>'
        '<a href="#occurrences">Occurrences</a><a href="#records">Event records</a><a href="#sources">Sources</a></nav>'
        '<main id="main" tabindex="-1">')
    w = report['window']
    add(f'<p><strong>{esc(w["start"])} to {esc(w["end"])} (end exclusive)</strong> · Display timezone: '
        f'<strong>{esc(w["timezone"])}</strong></p>')
    if report['complete']:
        add('<p class="warning"><strong>Complete within the supported subset.</strong> '
            'No unsupported input was detected. This does not validate provider compatibility or establish availability.</p>')
    else:
        add('<p class="warning" role="status"><strong>INCOMPLETE ANALYSIS.</strong> '
            'Some inputs could not be interpreted. Occupancy and overlaps below are provisional; absence of pairs is not evidence of availability.</p>')
    add(f'<p class="stats">{hours(report["occupied_seconds"])} occupied · {len(report["overlaps"])} overlap pairs · '
        f'{sum(o["all_day"] for o in occurrences.values())} all-day occurrences</p>')
    if report['issues']:
        add('<h2 id="issues">Analysis issues</h2><ul>')
        for issue in report['issues']:
            target = issue.get('event', issue.get('source'))
            add(f'<li><a href="#{esc(target)}">{esc(target)}</a>: {esc(issue["message"])}</li>')
        add('</ul>')
    add('<h2 id="daily" tabindex="-1">Daily summary</h2><p>Full-window totals; filters below do not change this table. '
        'Hours are rounded for display; JSON stores exact seconds.</p><div class="scroll"><table><caption>Occupied time by local date</caption>'
        '<thead><tr><th scope="col">Date</th><th scope="col">Day length</th><th scope="col">Occupied</th>'
        '<th scope="col">Timed occurrences</th><th scope="col">All-day occurrences</th></tr></thead><tbody>')
    for row in report['daily']:
        add(f'<tr><th scope="row">{row["date"]}</th><td>{hours(row["day_seconds"])}</td>'
            f'<td>{hours(row["occupied_seconds"])}</td><td>{row["timed_occurrences"]}</td><td>{row["all_day_occurrences"]}</td></tr>')
    add('</tbody></table></div><h2>Explore findings</h2>'
        '<p>Search matches a summary or UID. Pairs appear when either occurrence matches. '
        'Tab navigates controls and links; Enter follows citations; Escape clears filters. Event records always remain visible.</p>'
        '<div class="controls"><label for="search">Summary or UID<input id="search" type="search" autocomplete="off"></label>'
        '<label for="kind">Occurrence type<select id="kind"><option value="">All types</option>'
        '<option value="timed">Timed</option><option value="all-day">All-day</option></select></label>'
        '<label for="source">Source<select id="source"><option value="">All sources</option>')
    for s in report['sources']:
        add(f'<option value="{s["id"]}">{esc(s["id"] + ": " + s["name"])}</option>')
    add('</select></label><button id="reset" type="button">Clear filters</button></div>'
        '<p id="filter-status" aria-live="polite"></p><noscript><p>JavaScript disabled: all findings remain visible.</p></noscript>'
        '<h2 id="overlaps" tabindex="-1">Overlap details</h2>')
    if not report['overlaps']:
        add('<p>No overlapping timed pairs detected in the analyzed subset.</p>')
    for p in report['overlaps']:
        left, right = occurrences[p['left']], occurrences[p['right']]
        add(f'<article class="card" id="{p["id"]}" data-pair data-refs="{p["left"]} {p["right"]}" tabindex="-1">'
            f'<h3>{esc(events[left["event"]]["summary"])} ↔ {esc(events[right["event"]]["summary"])}</h3>'
            f'<p>{esc(p["start"])} – {esc(p["end"])} (UTC) · {p["seconds"]} seconds</p>'
            f'<p>Occurrence citations: <a href="#{p["left"]}">{p["left"]}</a> and '
            f'<a href="#{p["right"]}">{p["right"]}</a></p></article>')
    add('<h2 id="occurrences" tabindex="-1">Occurrences</h2>')
    for o in occurrences.values():
        event = events[o['event']]
        master = events[o.get('master', o['event'])]
        source_ids = ' '.join(sorted({s['source'] for e in (event, master) for s in e['sources']}))
        kind = 'all-day' if o['all_day'] else 'timed'
        add(f'<article class="card" id="{o["id"]}" data-occurrence data-kind="{kind}" '
            f'data-search="{esc(event["summary"] + " " + event["uid"])}" data-sources="{source_ids}" tabindex="-1">'
            f'<h3>{esc(event["summary"])}</h3><p>{kind.title()} · '
            f'{esc(o.get("local_start", o["start"]))} – {esc(o.get("local_end", o["end"]))} (end exclusive)</p>'
            f'<p class="muted">Clipped bounds: {esc(o["clipped_start"])} – {esc(o["clipped_end"])} '
            f'{"(dates)" if o["all_day"] else "(UTC)"}</p>'
            f'<p><a href="#{event["id"]}">Event record {event["id"]}</a> · Occurrence {o["id"]}</p>')
        if 'recurrence_id' in o:
            add(f'<p>Original identity: <code>{esc(o["recurrence_id"])}</code></p>')
        if o.get('override'):
            add(f'<p>Replacement from override <a href="#{o["override"]}">{o["override"]}</a> · '
                f'Master <a href="#{o["master"]}">{o["master"]}</a></p>')
        add('</article>')
    if report.get('cancellations'):
        add('<h2 id="cancellations" tabindex="-1">Cancelled instances</h2><ul>')
        for c in report['cancellations']:
            add(f'<li>Original identity <code>{esc(c["recurrence_id"])}</code>: '
                f'<a href="#{c["override"]}">Cancellation {c["override"]}</a> · '
                f'<a href="#{c["master"]}">Master {c["master"]}</a>. No occupied time.</li>')
        add('</ul>')
    add('<h2 id="records" tabindex="-1">Event records</h2>')
    for e in events.values():
        add(f'<article class="card" id="{e["id"]}" tabindex="-1"><h3>{e["id"]}: {esc(e["summary"])}</h3>'
            f'<p>UID: <code>{esc(e["uid"])}</code> · {esc(e["disposition"])}</p>')
        if 'time_basis' in e:
            add(f'<p>Time basis: {esc(e["time_basis"])} · {esc(e["timezone"])}</p>')
        if e.get('role') == 'override':
            add(f'<p>Override of <a href="#{e["master"]}">Master {e["master"]}</a> · '
                f'Original identity: <code>{esc(e.get("recurrence_id", "unresolved"))}</code></p>')
            if 'effective_start' in e:
                add(f'<p>Effective timing: {esc(e["effective_start"])} – {esc(e["effective_end"])} '
                    f'(end exclusive). Inherited: {esc(", ".join(e["inherited"]) or "none")}</p>')
        related = by_master[e['id']]
        if related:
            add('<p>Override records: ' + ', '.join(f'<a href="#{x["id"]}">{x["id"]}</a>' for x in related) + '</p>')
        if 'duplicate_of' in e:
            add(f'<p>Deduplicated into <a href="#{e["duplicate_of"]}">{e["duplicate_of"]}</a></p>')
        add('<p>Source citations: ' + ', '.join(f'<a href="#{s["source"]}">{s["source"]}, VEVENT {s["event"]}</a>' for s in e['sources']) + '</p>')
        add('<p>Occurrence backreferences: ' + (', '.join(f'<a href="#{ident}">{ident}</a>' for ident in by_event[e['id']]) or 'none in window') + '</p></article>')
    add('<h2 id="sources" tabindex="-1">Source fingerprints</h2>')
    for s in report['sources']:
        add(f'<article class="card" id="{s["id"]}" tabindex="-1"><h3>{s["id"]}: {esc(s["name"])}</h3>'
            f'<p>{s["bytes"]} bytes · SHA-256 <code>{s["sha256"]}</code></p></article>')
    add('<p>Only scheduling fields, UID and summary are shown. This report can still contain private information. '
        'All processing and filtering are local; this page makes no network requests.</p></main>'
        '<footer><p>calendar-overlap-audit ' + esc(report['tool_version']) + ' · JSON schema 2</p></footer>'
        '<script>' + SCRIPT + '</script></body></html>\n')
    return ''.join(chunks).encode('utf-8')
