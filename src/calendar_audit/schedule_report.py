"""Schedule explanations for schema 3; v1 HTML stays byte-identical."""

LABELS = {'closed': 'Closed', 'incomplete': 'Incomplete analysis',
          'fully_booked': 'Fully booked', 'below_minimum': 'Free gaps below minimum',
          'available': 'Available gaps'}


def explanations(report, add):
    def clocks(pairs):
        return ', '.join(f'{a}–{b}' for a, b in pairs) or 'Closed'
    def amount(value):
        return 'unknown' if value is None else str(value)
    add('<h3 id="schedule-explanations">Effective schedule and date replacements</h3>'
        '<p>Date replacements override weekly hours completely. Empty replacements close a date. '
        'Adjacent declared windows merge; separate windows never bridge a break. '
        'Intervals include their start and exclude their end. Minimum gaps use elapsed seconds.</p>')
    add(f'<p>Working seconds: {report["working_seconds"]}; occupied seconds: {amount(report["occupied_seconds"])}; '
        f'free seconds (including gaps below minimum): {amount(report["free_seconds"])}. '
        f'Observed occupied seconds: {report["observed_occupied_seconds"]} '
        '(provisional when analysis is incomplete).</p>')
    add('<nav aria-label="Date replacements">Applied exceptions: ')
    exceptions = [d for d in report['days'] if d['applied_exception']]
    if not exceptions:
        add('None')
    for d in exceptions:
        add(f'<a href="#{d["id"]}">{d["date"]}</a> ')
    add('</nav>')
    for d in report['days']:
        add(f'<article class="card" id="{d["id"]}" data-schedule-day data-availability-date="{d["date"]}" tabindex="-1">'
            f'<h4>{d["date"]} · {LABELS[d["status"]]}</h4>'
            f'<p>Weekly {d["weekday"]}: {clocks(d["weekly_windows"])}</p>')
        if d['applied_exception']:
            add(f'<p>Applied date replacement: {clocks(d["replacement"])}. Replaces weekly hours.</p>')
        else:
            add('<p>No date replacement; weekly hours apply.</p>')
        add(f'<p>Selected declaration: {clocks(d["declared_windows"])}</p><p>Effective windows: ')
        for wid in d['windows']:
            add(f'<a href="#{wid}">{wid}</a> ')
        if not d['windows']:
            add('None (closed date)')
        add(f'</p><p>Working: {d["working_seconds"]}; occupied: {amount(d["occupied_seconds"])}; '
            f'free: {amount(d["free_seconds"])}; qualifying candidate: {amount(d["candidate_seconds"])} seconds.</p>')
        if not d['analysis_complete']:
            add('<p>Calendar analysis incomplete; all candidate intervals withheld. '
                f'Observed occupied seconds (provisional): {d["observed_occupied_seconds"]}.</p>')
        add('</article>')
