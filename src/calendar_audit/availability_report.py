"""Availability UI plus the unchanged schema-2 audit for full provenance."""
import json

from .core import AuditError
from .report import esc, html_bytes as audit_html

SCRIPT = '''
const dateFilter = document.getElementById('availability-date');
const dated = [...document.querySelectorAll('[data-availability-date]')];
function filterDates() {
  for (const row of dated) row.hidden = !!dateFilter.value && row.dataset.availabilityDate !== dateFilter.value;
  const count = document.querySelectorAll('[data-gap]:not([hidden])').length;
  document.getElementById('availability-status').textContent = `${count} candidate intervals shown. Totals remain unfiltered.`;
}
function clearDate() { dateFilter.value = ''; filterDates(); }
dateFilter.addEventListener('input', filterDates);
document.getElementById('clear-date').addEventListener('click', clearDate);
document.addEventListener('keydown', event => {
  if (event.key === 'Escape') { clearDate(); dateFilter.focus(); }
});
document.addEventListener('click', event => {
  const link = event.target.closest('a[href^="#"]');
  if (!link) return;
  const target = document.getElementById(link.getAttribute('href').slice(1));
  if (target && target.hidden && target.hasAttribute('data-availability-date')) clearDate();
});
filterDates();
'''


def html_bytes(report, budget):
    parts, size = [], 0
    def add(text):
        nonlocal size
        budget.check()
        size += len(text.encode('utf-8'))
        if size > budget.limits.report_bytes:
            raise AuditError('report_bytes limit exceeded (availability HTML)')
        parts.append(text)
    def links(ids):
        return ', '.join(f'<a href="#{esc(i)}">{esc(i)}</a>' for i in ids) or 'Working-window edge'
    def bounds(row):
        return (f'{esc(row["local_start"])} – {esc(row["local_end"])} · {row["seconds"]} elapsed seconds'
                f'<br><small>UTC: {esc(row["start"])} – {esc(row["end"])}</small>')
    add('<section aria-labelledby="availability-title"><h2 id="availability-title">Candidate availability</h2>')
    if report['complete']:
        add('<p class="warning"><strong>Complete for supplied exports and selected policies.</strong> '
            'Candidate gaps are not a booking guarantee; missing or outdated exports can hide commitments.</p>')
    else:
        add('<p class="warning" role="status"><strong>INCOMPLETE: candidate intervals withheld.</strong> '
            'Busy blocks below are provisional. An empty candidate list does not mean no availability.</p>')
    add(f'<p>{esc(report["scope"])}</p><h3>Working-window settings · specification v1</h3><pre>'
        + esc(json.dumps(report['spec'], indent=2, sort_keys=True)) + '</pre>')
    if report['spec_source']:
        s = report['spec_source']
        add(f'<p>Spec: {esc(s["name"])} · {s["bytes"]} bytes · SHA-256 <code>{esc(s["sha256"])}</code></p>')
    add(f'<p>Total qualifying candidate seconds: {esc(report["candidate_seconds"] if report["complete"] else "unknown")}</p>'
        '<div class="controls"><label for="availability-date">Working date<input type="date" id="availability-date"></label>'
        '<button type="button" id="clear-date">Clear date</button></div>'
        '<p id="availability-status" aria-live="polite"></p><p>Tab and Enter navigate; Escape clears all filters. '
        'The date filter affects working windows and candidates only. The audit below has separate occurrence filters.</p>'
        '<noscript>All dates are shown with JavaScript disabled.</noscript><h3>Candidate intervals</h3>')
    if report['complete'] and not report['candidates']:
        add('<p>No interval meets the selected minimum within the working windows.</p>')
    for g in report['candidates']:
        add(f'<article class="card" id="{g["id"]}" data-gap data-availability-date="{g["date"]}" tabindex="-1">'
            f'<h4>{g["date"]} · {g["id"]}</h4><p>{bounds(g)}</p>'
            f'<p>Preceding commitments: {links(g["before"])}<br>Following commitments: {links(g["after"])}</p>'
            f'<a href="#{g["window"]}">Working window {g["window"]}</a></article>')
    add('<h3>Working windows and merged busy blocks</h3>')
    for w in report['windows']:
        add(f'<article class="card" id="{w["id"]}" data-availability-date="{w["date"]}" tabindex="-1">'
            f'<h4>{w["date"]} · {w["id"]}</h4><p>{bounds(w)}</p>')
        for b in w['busy']:
            add(f'<p>Busy: {bounds(b)}<br>Contributing occurrences: {links(b["occurrences"])}</p>')
        if not w['busy']:
            add('<p>No supported busy occurrences in this window.</p>')
        add('</article>')
    add('</section><h2>Underlying commitment audit</h2>')
    original = audit_html(report['audit'], budget).decode('utf-8')
    original = original.replace('<title>Calendar overlap audit</title>', '<title>Calendar availability audit</title>')
    original = original.replace('<h1>Where commitments overlap</h1>', '<h1>Find time within working hours</h1>')
    marker = '<main id="main" tabindex="-1">'
    original = original.replace(marker, marker + ''.join(parts), 1)
    original = original.replace('</body>', '<script>' + SCRIPT + '</script></body>')
    data = original.encode('utf-8')
    budget.check()
    if len(data) > budget.limits.report_bytes:
        raise AuditError('report_bytes limit exceeded (combined HTML)')
    return data
