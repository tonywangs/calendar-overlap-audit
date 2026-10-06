"""Bounded projection from complete occurrence analysis to metadata-free occupancy."""
from dataclasses import dataclass
from datetime import date, datetime, timezone
import re
from uuid import UUID, uuid4

from .availability import boundary
from .core import AuditError, Budget, Limits, analyze_occurrences, get_zone, window

UTC = timezone.utc
MAX_INTERVALS = 20000
PRODID = '-//Calendar Overlap Audit//Occupied Time 1//EN'


class IncompleteExport(AuditError):
    """No artifact may be emitted from incomplete analysis."""


@dataclass(frozen=True)
class Occupancy:
    start: datetime
    end: datetime
    periods: tuple[tuple[datetime, datetime], ...]


def interval_limit(value):
    if type(value) is not int or not 1 <= value <= MAX_INTERVALS:
        raise AuditError(f'Interval limit must be an integer from 1 to {MAX_INTERVALS}')
    return value


def occupied(paths, start, end, display, all_day, limits=Limits(), budget=None,
             max_intervals=MAX_INTERVALS):
    """Export only a complete, clipped union; retain no occurrence metadata."""
    interval_limit(max_intervals)
    if all_day not in ('block', 'ignore'):
        raise AuditError('All-day policy must explicitly be block or ignore')
    if not paths:
        raise AuditError('At least one input calendar is required')
    budget = budget or Budget(limits)
    zone = get_zone(display)
    first, last, _, _ = window(start, end, zone)
    lo, hi = boundary(first, '00:00', zone), boundary(last, '00:00', zone)
    if lo >= hi:
        raise AuditError('Horizon must have positive elapsed duration')
    audit = analyze_occurrences(paths, start, end, display, limits, budget)
    if not audit['complete']:
        raise IncompleteExport('Unsupported or ambiguous calendar data; no free/busy export')
    periods = []
    for item in audit['occurrences']:
        budget.check()
        if item['all_day']:
            if all_day == 'ignore':
                continue
            a = boundary(date.fromisoformat(item['clipped_start']), '00:00', zone)
            b = boundary(date.fromisoformat(item['clipped_end']), '00:00', zone)
        else:
            a = datetime.fromisoformat(item['clipped_start'])
            b = datetime.fromisoformat(item['clipped_end'])
        a, b = max(a, lo), min(b, hi)
        if a < b:
            periods.append((a, b))
    budget.check()
    periods.sort()
    merged = []
    for a, b in periods:
        budget.check()
        if merged and a <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(b, merged[-1][1]))
        else:
            if len(merged) >= max_intervals:
                raise AuditError('intervals limit exceeded')
            merged.append((a, b))
    return Occupancy(lo, hi, tuple(merged))


def export_identity(uid=None, created_at=None):
    """Restricted independent UUID4 identity and whole-second creation time."""
    if uid is None:
        uid = str(uuid4())
    try:
        parsed = UUID(uid)
        if str(parsed) != uid or parsed.version != 4:
            raise ValueError
    except (ValueError, TypeError, AttributeError) as exc:
        raise AuditError('Export UID must be a canonical lowercase UUID4') from exc
    if created_at is None:
        stamp = datetime.now(UTC).replace(microsecond=0)
    else:
        if not isinstance(created_at, str) or not re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z', created_at):
            raise AuditError('Creation time must be YYYY-MM-DDTHH:MM:SSZ')
        try:
            stamp = datetime.fromisoformat(created_at)
        except ValueError as exc:
            raise AuditError('Invalid creation time') from exc
    return 'urn:uuid:' + uid, stamp


def utc_text(value):
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None or value.microsecond:
        raise AuditError('Export times must be aware whole-second date-times')
    value = value.astimezone(UTC)
    return f'{value.year:04d}{value.month:02d}{value.day:02d}T{value.hour:02d}{value.minute:02d}{value.second:02d}Z'


def fold(line):
    """Fold UTF-8 at character boundaries; continuation space counts as an octet."""
    if '\r' in line or '\n' in line:
        raise AuditError('Invalid content line')
    lines, current = [], bytearray()
    for character in line:
        raw = character.encode('utf-8')
        if len(current) + len(raw) > 75:
            lines.append(bytes(current))
            current = bytearray(b' ')
        current.extend(raw)
    lines.append(bytes(current))
    return b'\r\n'.join(lines) + b'\r\n'


def calendar_bytes(occupancy, budget, *, uid=None, created_at=None,
                   max_intervals=MAX_INTERVALS):
    """Custom allowlist serializer; no source strings enter this boundary."""
    interval_limit(max_intervals)
    ident, stamp = export_identity(uid, created_at)
    lo, hi = occupancy.start, occupancy.end
    start_text, end_text = utc_text(lo), utc_text(hi)
    if lo >= hi:
        raise AuditError('Horizon must have positive elapsed duration')
    data = bytearray()

    def emit(line):
        budget.check()
        raw = fold(line)
        if len(data) + len(raw) > budget.limits.report_bytes:
            raise AuditError('report_bytes limit exceeded')
        data.extend(raw)

    for line in ('BEGIN:VCALENDAR', 'VERSION:2.0', 'PRODID:' + PRODID,
                 'BEGIN:VFREEBUSY', 'UID:' + ident, 'DTSTAMP:' + utc_text(stamp),
                 'DTSTART:' + start_text, 'DTEND:' + end_text):
        emit(line)
    previous = None
    for count, (a, b) in enumerate(occupancy.periods, 1):
        a_text, b_text = utc_text(a), utc_text(b)
        if count > max_intervals:
            raise AuditError('intervals limit exceeded')
        if not lo <= a < b <= hi or (previous is not None and a <= previous):
            raise AuditError('Export periods must be contained, positive, sorted and merged')
        emit(f'FREEBUSY;FBTYPE=BUSY:{a_text}/{b_text}')
        previous = b
    emit('END:VFREEBUSY')
    emit('END:VCALENDAR')
    budget.check()
    return bytes(data)
