"""Bounded JSON and static-first HTML. Imported calendar text is never rendered."""
from html import escape
import json

from .core import AuditError


def json_bytes(report, budget):
    result = bytearray()
    for part in json.JSONEncoder(ensure_ascii=True, sort_keys=True, indent=2, allow_nan=False).iterencode(report):
        budget.check()
        raw = part.encode('utf-8')
        if len(result) + len(raw) + 1 > budget.limits.report_bytes:
            raise AuditError('report_bytes limit exceeded (JSON)')
        result.extend(raw)
    return bytes(result) + b'\n'


STYLE = '''
:root{font:16px/1.5 system-ui,sans-serif;color:#172b36;background:#f3f6f8}
*{box-sizing:border-box}body{margin:0}main,header{max-width:72rem;margin:auto;padding:1.2rem}
header{padding-top:2.5rem}h1{font-size:clamp(1.8rem,5vw,3rem);line-height:1.1}
h2{margin-top:2rem}a{color:#005e75}button,input{font:inherit;padding:.5rem;max-width:100%}
button,summary{cursor:pointer}label{display:block}fieldset{border:1px solid #819ca9;border-radius:.5rem}
.controls{display:flex;flex-wrap:wrap;gap:1rem;align-items:end}.card{background:white;border:1px solid #bacad2;
 border-left:4px solid #08746f;border-radius:.5rem;padding:1rem;margin:1rem 0;overflow-wrap:anywhere}
.unknown{border-left-color:#956000;background:#fffaf0}.muted{color:#425864}
:focus-visible{outline:3px solid #b34900;outline-offset:4px}details{margin:.6rem 0}
.skip{position:absolute;top:-5rem;left:1rem;background:white;padding:.7rem}.skip:focus{top:.5rem}
[hidden]{display:none!important}ul{padding-left:1.4rem}code{overflow-wrap:anywhere}
@media print{.controls,.skip{display:none}details>*{display:block}main,header{max-width:none}}
'''
SCRIPT = '''
'use strict';
const dateInput=document.getElementById('date-filter');
const durationInput=document.getElementById('length-filter');
const cards=[...document.querySelectorAll('[data-window]')];
function filter(){
 const day=dateInput.value;
 const lo=day?Date.parse(day+'T00:00:00Z'):null;
 const hi=lo===null?null:lo+86400000;
 const minimum=Number(durationInput.value)||0;
 let count=0;
 for(const card of cards){
  const intersects=lo===null||(Date.parse(card.dataset.start)<hi&&Date.parse(card.dataset.end)>lo);
  card.hidden=!(intersects&&Number(card.dataset.seconds)>=minimum);
  if(!card.hidden)count++;
 }
 document.getElementById('shown').textContent=count+' of '+cards.length+' candidate windows shown';
}
function clear(){dateInput.value='';durationInput.value='';filter();}
dateInput.addEventListener('input',filter);durationInput.addEventListener('input',filter);
document.getElementById('clear').addEventListener('click',clear);
document.addEventListener('keydown',event=>{if(event.key==='Escape'){clear();dateInput.focus();}});
function reveal(){const target=document.getElementById(location.hash.slice(1));
 if(target&&target.matches('[data-window]')&&target.hidden){clear();target.scrollIntoView();}}
window.addEventListener('hashchange',reveal);filter();reveal();
'''


def html_bytes(report, budget):
    data = bytearray()

    def emit(text):
        budget.check()
        raw = text.encode('utf-8')
        if len(data) + len(raw) > budget.limits.report_bytes:
            raise AuditError('report_bytes limit exceeded (HTML)')
        data.extend(raw)

    def e(value):
        return escape(str(value), quote=True)

    def when(item):
        return f'{e(item["start"])} → {e(item["end"])} ({item["seconds"]:,} seconds)'

    emit('<!doctype html><html lang="en"><head><meta charset="utf-8">'
         '<meta name="viewport" content="width=device-width,initial-scale=1">'
         '<meta http-equiv="Content-Security-Policy" content="default-src &#39;none&#39;; '
         'script-src &#39;unsafe-inline&#39;; style-src &#39;unsafe-inline&#39;; '
         'base-uri &#39;none&#39;; form-action &#39;none&#39;; connect-src &#39;none&#39;">'
         '<title>Shared meeting windows</title><style>'+STYLE+'</style></head><body>'
         '<a class="skip" href="#main">Skip to report</a><header><p>OFFLINE · ASSERTED OCCUPANCY</p>'
         '<h1>Shared meeting windows</h1><p>Candidate ranges for everyone’s working hours and known coverage. '
         'These are not booked meetings.</p>')
    emit(f'<p>{when(report["horizon"])} · UTC horizon</p>'
         f'<p>{len(report["participants"])} participants · {report["duration_seconds"]:,}-second meeting · '
         f'{len(report["windows"])} candidate windows</p>')
    if not report['coverage_complete']:
        emit('<p class="card unknown"><strong>Coverage has gaps.</strong> Unknown time is excluded. '
             'Inspect each participant below; an empty list of candidates does not prove everyone is busy.</p>')
    emit('</header><main id="main" tabindex="-1"><h2>Candidate windows</h2>'
         '<fieldset class="controls"><legend>Filter candidates</legend><label>UTC date '
         '<input id="date-filter" type="date"></label><label>At least this many seconds '
         '<input id="length-filter" type="number" min="1" step="1"></label>'
         '<button id="clear" type="button">Clear filters</button></fieldset>'
         '<p id="shown" role="status" aria-live="polite"></p>'
         '<noscript>All windows are shown. Filtering requires JavaScript; inspection works without it.</noscript>')
    aliases = {p['id']: p['alias'] for p in report['participants']}
    if not report['windows']:
        emit('<p>No candidate window meets the requested duration within shared known working time.</p>')
    for w in report['windows']:
        emit(f'<article class="card" id="{w["id"]}" tabindex="-1" data-window '
             f'data-start="{w["start"]}" data-end="{w["end"]}" data-seconds="{w["seconds"]}">'
             f'<h3><a href="#{w["id"]}">{e(w["id"].upper())}</a> · {when(w)}</h3>'
             f'<p>Latest meeting start: {e(w["latest_start"])} (UTC, inclusive)</p>'
             '<details><summary>Inspect participant-local times</summary><ul>')
        for local in w['local']:
            pid = local['participant']
            emit(f'<li><a href="#{pid}">{e(aliases[pid])}</a>: {e(local["start"])} → {e(local["end"])}; '
                 f'latest start {e(local["latest_start"])}</li>')
        emit('</ul></details></article>')
    emit('<h2>Participant coverage and evidence</h2><p>All intervals below use UTC and exclude their ending '
         'instant. Input descriptions and identities are omitted. Hashes identify bytes, not people or freshness.</p>')
    for p in report['participants']:
        emit(f'<section class="card" id="{p["id"]}" tabindex="-1"><h3>{e(p["alias"])} · {e(p["timezone"])}</h3>')
        emit('<h4>Coverage gaps — unknown time</h4>')
        if not p['coverage_gaps']:
            emit('<p>None within the requested horizon.</p>')
        else:
            emit('<ul>')
            for item in p['coverage_gaps']:
                emit('<li>'+when(item)+'</li>')
            emit('</ul>')
        emit('<details><summary>Inspect working schedule and interval evidence</summary><h4>Weekly schedule</h4><ul>')
        for day, pairs in p['weekly'].items():
            emit(f'<li>{e(day)}: '+(e(', '.join(a+'–'+b for a, b in pairs)) or 'closed')+'</li>')
        emit('</ul>')
        for key, label in [('coverage', 'Known coverage'), ('busy', 'Merged blocking occupancy'),
                           ('working', 'Working shifts'), ('known_working', 'Covered working time'), ('free', 'Known free working time')]:
            emit(f'<h4>{label}</h4><ul>')
            for item in p[key]:
                emit('<li>'+when(item)+'</li>')
            emit('</ul>' if p[key] else '</ul><p>None.</p>')
        for s in p['sources']:
            emit(f'<h4>{s["id"]}</h4><p>Complete occupancy asserted: true. Coverage: {when(s["coverage"])}</p>'
                 f'<p>{s["bytes"]:,} bytes · SHA-256 <code>{s["sha256"]}</code></p><ul>')
            for kind, count in s['period_counts'].items():
                emit(f'<li>{kind}: {count} periods</li>')
            emit('</ul>')
        emit('</details></section>')
    emit('<h2>Analysis limitations</h2><ul>')
    for limitation in report['limitations']:
        emit('<li>'+e(limitation)+'</li>')
    emit('</ul><p>Manifest SHA-256: <code>'+report['manifest_source']['sha256']+'</code></p>'
         '<p class="muted">Shared-windows schema 1 · '+e(report['timezone_database'])+'</p></main>'
         '<script>'+SCRIPT+'</script></body></html>\n')
    return bytes(data)
