"""Conservative calendar decoding and bounded interval analysis.

No network APIs are used. Imported strings remain data, never markup or paths.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import date, datetime, time, timedelta, timezone
from functools import lru_cache
import hashlib
from importlib import metadata, resources
from pathlib import Path
import re
import stat
import time as clock
from zoneinfo import ZoneInfo

from icalendar.parser import Contentline
from icalendar.prop import vText

from . import __version__

UTC = timezone.utc
DAY = timedelta(days=1)
WEEKDAYS = {name: i for i, name in enumerate(('MO', 'TU', 'WE', 'TH', 'FR', 'SA', 'SU'))}


class AuditError(Exception):
    """A fatal operational error: do not publish a partial report."""


class Unsupported(ValueError):
    """An event or file cannot be fully interpreted."""


@dataclass(frozen=True)
class Limits:
    input_bytes: int = 8 * 1024 * 1024
    files: int = 32
    line_bytes: int = 65536
    events: int = 5000
    candidates: int = 200000
    resolutions: int = 200000
    occurrences: int = 20000
    pairs: int = 20000
    report_bytes: int = 8 * 1024 * 1024
    seconds: float = 30.0

    def __post_init__(self):
        import math
        for key, value in asdict(self).items():
            ceiling = self.__dataclass_fields__[key].default
            if (not isinstance(value, (int, float)) or value <= 0 or value > ceiling
                    or (isinstance(value, float) and not math.isfinite(value))):
                raise AuditError(f'Limit {key} must be positive, finite, and at most {ceiling}')


class Budget:
    def __init__(self, limits: Limits):
        self.limits = limits
        self.started = clock.monotonic()
        self.counts = defaultdict(int)

    def check(self):
        if clock.monotonic() - self.started > self.limits.seconds:
            raise AuditError('Execution-time limit exceeded')

    def take(self, name: str, amount: int = 1):
        self.check()
        self.counts[name] += amount
        if self.counts[name] > getattr(self.limits, name):
            raise AuditError(f'{name} limit exceeded')


@lru_cache(maxsize=128)
def get_zone(name: str) -> ZoneInfo:
    # Always use the pinned package, not the host's potentially different database.
    if not name or any(p in ('', '.', '..') for p in name.split('/')) or '\\' in name:
        raise Unsupported('Unknown or invalid timezone')
    try:
        with resources.files('tzdata.zoneinfo').joinpath(*name.split('/')).open('rb') as f:
            return ZoneInfo.from_file(f, key=name)
    except (OSError, ValueError) as exc:
        raise Unsupported('Unknown or invalid timezone') from exc


def iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace('+00:00', 'Z')


def local_midnight(value: date, zone: ZoneInfo) -> datetime:
    return datetime.combine(value, time.min, zone).astimezone(UTC)


def window(start: str, end: str, zone: ZoneInfo):
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', start) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', end):
        raise AuditError('Window bounds must be YYYY-MM-DD dates')
    try:
        first, last = date.fromisoformat(start), date.fromisoformat(end)
    except ValueError as exc:
        raise AuditError('Invalid window date') from exc
    if not 1 <= (last - first).days <= 90:
        raise AuditError('Window must contain 1 to 90 civil days')
    try:
        return first, last, local_midnight(first, zone), local_midnight(last, zone)
    except OverflowError as exc:
        raise AuditError('Window is outside representable UTC dates') from exc


@dataclass(frozen=True)
class Temporal:
    value: date | datetime
    kind: str  # date, floating, utc, zoned
    zone: str

    def instant(self):
        assert isinstance(self.value, datetime)
        return self.value.astimezone(UTC)


def decode_time(params, raw: str, display: str) -> Temporal:
    if set(params) - {'VALUE', 'TZID'}:
        raise Unsupported('Unsupported date/time parameters')
    tzid = params.get('TZID')
    if isinstance(tzid, list):
        raise Unsupported('Multiple timezone identifiers')
    typ = str(params.get('VALUE', 'DATE-TIME')).upper()
    if typ == 'DATE':
        if tzid or not re.fullmatch(r'\d{8}', raw):
            raise Unsupported('Invalid DATE or DATE timezone')
        return Temporal(datetime.strptime(raw, '%Y%m%d').date(), 'date', display)
    if typ != 'DATE-TIME' or not re.fullmatch(r'\d{8}T\d{6}Z?', raw):
        raise Unsupported('Unsupported or malformed DATE-TIME')
    is_utc = raw.endswith('Z')
    if is_utc and tzid:
        raise Unsupported('UTC DATE-TIME must not have TZID')
    naive = datetime.strptime(raw.rstrip('Z'), '%Y%m%dT%H%M%S')
    name = 'UTC' if is_utc else str(tzid or display)
    zone = get_zone(name)
    return Temporal(naive.replace(tzinfo=zone, fold=0),
                    'utc' if is_utc else ('zoned' if tzid else 'floating'), name)


def unpack(line):
    try:
        name, params, value = Contentline(line).parts()
        return name.upper(), params, value
    except (ValueError, AssertionError) as exc:
        raise Unsupported('Malformed content line') from exc


def scan(raw: bytes, budget: Budget):
    """Validate component boundaries before parsing any event properties.

    VTIMEZONE is not fed to icalendar, avoiding implicit custom-zone expansion.
    """
    try:
        text = raw.decode('utf-8-sig')
    except UnicodeDecodeError as exc:
        raise Unsupported('Input is not UTF-8') from exc
    if '\x00' in text:
        raise Unsupported('NUL byte in input')
    lines = []
    for physical in text.splitlines():
        budget.check()
        if len(physical.encode('utf-8')) > budget.limits.line_bytes:
            raise AuditError('line_bytes limit exceeded')
        if physical.startswith((' ', '\t')):
            if not lines:
                raise Unsupported('Folded line without predecessor')
            lines[-1] += physical[1:]
            if len(lines[-1].encode('utf-8')) > budget.limits.line_bytes:
                raise AuditError('line_bytes limit exceeded')
        elif physical:
            lines.append(physical)
    stack, events, current, warnings, calendar_props = [], [], None, [], {}
    roots = 0
    for line in lines:
        budget.check()
        name, params, value = unpack(line)
        if name == 'BEGIN':
            if params:
                raise Unsupported('Parameters on BEGIN')
            value = value.upper()
            if not stack:
                if value != 'VCALENDAR' or roots:
                    raise Unsupported('Expected exactly one VCALENDAR')
                roots += 1
            elif len(stack) == 1:
                if value == 'VEVENT':
                    budget.take('events')
                    current = []
                elif value == 'VTIMEZONE':
                    warnings.append('Embedded VTIMEZONE ignored; pinned IANA zones used provisionally')
                else:
                    warnings.append('Unsupported calendar component excluded')
            elif stack[-1] == 'VEVENT' and value != 'VALARM':
                raise Unsupported('Unsupported nested event component')
            elif not (stack[-1] == 'VEVENT' or
                      (stack[-1] == 'VTIMEZONE' and value in ('STANDARD', 'DAYLIGHT'))):
                raise Unsupported('Invalid component nesting')
            stack.append(value)
            if len(stack) > 3:
                raise Unsupported('Excessive component nesting')
            if current is not None:
                current.append(line)
        elif name == 'END':
            if params or not stack or value.upper() != stack[-1]:
                raise Unsupported('Mismatched component boundary')
            if current is not None:
                current.append(line)
            if stack.pop() == 'VEVENT':
                events.append(current)
                current = None
        else:
            if not stack:
                raise Unsupported('Content outside VCALENDAR')
            if current is not None:
                current.append(line)
            if len(stack) == 1:
                if name in calendar_props:
                    raise Unsupported('Duplicate calendar property')
                calendar_props[name] = value
    if stack or roots != 1:
        raise Unsupported('Unclosed or missing VCALENDAR')
    if calendar_props.get('VERSION') != '2.0':
        raise Unsupported('VERSION:2.0 required')
    if calendar_props.get('CALSCALE', 'GREGORIAN').upper() != 'GREGORIAN':
        raise Unsupported('Only Gregorian calendars supported')
    if calendar_props.get('METHOD', 'PUBLISH').upper() != 'PUBLISH':
        raise Unsupported('Scheduling METHOD other than PUBLISH unsupported; export a snapshot')
    return events, list(dict.fromkeys(warnings))


def properties(lines):
    props = defaultdict(list)
    depth = 0
    for line in lines:
        name, params, value = unpack(line)
        if name == 'BEGIN':
            depth += 1
        elif name == 'END':
            depth -= 1
        elif depth == 1:
            props[name].append((params, value))
    return props


def one(props, name, required=False):
    values = props.get(name, [])
    if len(values) > 1 or (required and not values):
        raise Unsupported(f'Expected exactly one {name}')
    return values[0] if values else None


def text_value(props, name, default=''):
    item = one(props, name)
    return str(vText.from_ical(item[1])) if item else default


@dataclass
class Event:
    start: Temporal
    duration: timedelta
    rule: dict
    excluded: set
    transparent: bool


def rule_value(params, raw, start: Temporal, display: str):
    if params:
        raise Unsupported('RRULE parameters unsupported')
    rule = {}
    for part in raw.upper().split(';'):
        if part.count('=') != 1:
            raise Unsupported('Malformed RRULE')
        key, value = part.split('=')
        if key in rule or not value:
            raise Unsupported('Duplicate or empty RRULE part')
        rule[key] = value
    if set(rule) - {'FREQ', 'INTERVAL', 'COUNT', 'UNTIL', 'BYDAY', 'WKST'}:
        raise Unsupported('Unsupported RRULE part')
    if rule.get('FREQ') not in ('DAILY', 'WEEKLY'):
        raise Unsupported('Only DAILY and WEEKLY recurrence supported')
    if rule['FREQ'] == 'DAILY' and ('BYDAY' in rule or 'WKST' in rule):
        raise Unsupported('BYDAY and WKST supported only for WEEKLY')
    for key in ('INTERVAL', 'COUNT'):
        if key in rule:
            if not re.fullmatch(r'[0-9]{1,9}', rule[key]) or int(rule[key]) < 1:
                raise Unsupported(f'{key} must be a positive integer of at most 9 digits')
            rule[key] = int(rule[key])
    if 'COUNT' in rule and 'UNTIL' in rule:
        raise Unsupported('COUNT and UNTIL cannot be combined')
    if 'UNTIL' in rule:
        until = decode_time({'VALUE': 'DATE'} if start.kind == 'date' else {}, rule['UNTIL'], display)
        expected = 'date' if start.kind == 'date' else ('floating' if start.kind == 'floating' else 'utc')
        if until.kind != expected:
            raise Unsupported('UNTIL type/timezone does not match DTSTART')
        if (until.value if expected == 'date' else until.instant()) < (
                start.value if expected == 'date' else start.instant()):
            raise Unsupported('UNTIL precedes DTSTART')
        rule['UNTIL'] = until
    rule['INTERVAL'] = rule.get('INTERVAL', 1)
    if rule['FREQ'] == 'WEEKLY':
        weekdays = rule.get('BYDAY', next(k for k, v in WEEKDAYS.items() if v == start.value.weekday())).split(',')
        if any(d not in WEEKDAYS for d in weekdays) or len(set(weekdays)) != len(weekdays):
            raise Unsupported('BYDAY requires unique unqualified weekdays')
        rule['BYDAY'] = {WEEKDAYS[d] for d in weekdays}
        if start.value.weekday() not in rule['BYDAY']:
            raise Unsupported('DTSTART does not match BYDAY')
        if rule.get('WKST', 'MO') not in WEEKDAYS:
            raise Unsupported('Invalid WKST')
        rule['WKST'] = WEEKDAYS[rule.get('WKST', 'MO')]
    return rule


def decode_event(props, display):
    for key in ('RDATE', 'EXRULE', 'RECURRENCE-ID', 'DURATION'):
        if key in props:
            raise Unsupported(f'{key} is unsupported')
    start = decode_time(*one(props, 'DTSTART', True), display)
    end_prop = one(props, 'DTEND')
    if end_prop:
        end = decode_time(*end_prop, display)
        if (start.kind == 'date') != (end.kind == 'date'):
            raise Unsupported('DTSTART and DTEND value types differ')
        if start.kind == 'floating' and end.kind != 'floating' or end.kind == 'floating' and start.kind != 'floating':
            raise Unsupported('Cannot mix floating and absolute event endpoints')
        duration = end.value - start.value if start.kind == 'date' else end.instant() - start.instant()
        if duration <= timedelta(0):
            raise Unsupported('Explicit DTEND must be later than DTSTART')
    else:
        duration = DAY if start.kind == 'date' else timedelta(0)
    r = one(props, 'RRULE')
    rule = rule_value(*r, start, display) if r else {}
    excluded = set()
    for params, values in props.get('EXDATE', []):
        for value in values.split(','):
            excluded_time = decode_time(params, value, display)
            if (start.kind == 'date') != (excluded_time.kind == 'date'):
                raise Unsupported('EXDATE value type differs from DTSTART')
            if (start.kind == 'floating') != (excluded_time.kind == 'floating'):
                raise Unsupported('EXDATE floating/absolute type differs from DTSTART')
            excluded.add(excluded_time.value if start.kind == 'date' else excluded_time.instant())
    transparency = text_value(props, 'TRANSP', 'OPAQUE').upper()
    if transparency not in ('OPAQUE', 'TRANSPARENT'):
        raise Unsupported('Invalid TRANSP')
    status = text_value(props, 'STATUS', 'CONFIRMED').upper()
    if status not in ('CONFIRMED', 'TENTATIVE', 'CANCELLED'):
        raise Unsupported('Invalid STATUS')
    return Event(start, duration, rule, excluded, transparency == 'TRANSPARENT')


def expand(event: Event, end_date: date, end_instant: datetime, budget: Budget, *,
           through=None, resolution=False):
    start, rule = event.start.value, event.rule
    candidate = start
    generated = 0
    while True:
        if resolution:
            budget.check()
            budget.counts['resolutions'] += 1
            if budget.counts['resolutions'] > budget.limits.resolutions:
                raise SeriesError('resolution_limit', 'Override resolution limit exhausted; entire UID excluded')
        else:
            budget.take('candidates')
        is_date = event.start.kind == 'date'
        # Include a seed in a DST gap per explicit DATE-TIME semantics. Generated
        # local gap times are invalid recurrence instances and do not consume COUNT.
        instant = candidate if is_date else candidate.astimezone(UTC)
        if (candidate >= end_date if is_date else instant >= end_instant) and (through is None or candidate > through):
            return
        eligible = True
        if rule.get('FREQ') == 'WEEKLY':
            offset = (start.weekday() - rule['WKST']) % 7
            delta = (candidate.date() - start.date()).days if not is_date else (candidate - start).days
            eligible = ((delta + offset) // 7) % rule['INTERVAL'] == 0 and candidate.weekday() in rule['BYDAY']
        if eligible and candidate != start and not is_date:
            eligible = instant.astimezone(candidate.tzinfo).replace(tzinfo=None) == candidate.replace(tzinfo=None)
        if 'UNTIL' in rule:
            until = rule['UNTIL']
            if instant > (until.value if is_date else until.instant()):
                return
        if eligible:
            generated += 1
            if instant not in event.excluded:
                yield candidate
            if generated >= rule.get('COUNT', float('inf')):
                return
        if not rule:
            return
        step = rule['INTERVAL'] if rule['FREQ'] == 'DAILY' else 1
        try:
            candidate += DAY * step
        except OverflowError:
            return  # beyond representable dates, hence beyond the window


class SeriesError(Unsupported):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def recurrence_identity(value, basis):
    """Civil identity retains floating fields and explicit nonexistent seed times."""
    if basis.kind == 'utc':
        return iso(value)
    if basis.kind == 'floating':
        return value.replace(tzinfo=None).isoformat()
    return value.isoformat()


def compatible(start, other):
    return ((start.kind == 'date') == (other.kind == 'date') and
            (start.kind == 'floating') == (other.kind == 'floating'))


def prepare_family(group, display):
    """Validate snapshot boundaries and deduplicate without selecting revisions."""
    snapshots = defaultdict(set)
    for record, props, fingerprint in group:
        text_value(props, 'SUMMARY')  # validate even a duplicate or cancelled component
        snapshots[record['sources'][0]['source']].add(fingerprint)
    if len({frozenset(s) for s in snapshots.values()}) != 1:
        raise SeriesError('conflicting_snapshots', 'Different UID snapshots across source files; entire UID excluded')
    unique = {}
    for record, props, fingerprint in group:
        if fingerprint in unique:
            original = unique[fingerprint][0]
            original['sources'].extend(record['sources'])
            record.update(disposition='duplicate', duplicate_of=original['id'])
        else:
            unique[fingerprint] = (record, props)
    masters = [item for item in unique.values() if 'RECURRENCE-ID' not in item[1]]
    exceptions = [item for item in unique.values() if 'RECURRENCE-ID' in item[1]]
    if len(masters) != 1:
        raise SeriesError('orphan_override' if not masters else 'conflicting_masters',
                          'Expected one master per UID; entire UID excluded')
    record, props = masters[0]
    record['role'] = 'master'
    if text_value(props, 'STATUS', '').upper() == 'CANCELLED':
        if exceptions:
            raise SeriesError('cancelled_master_with_overrides', 'Cancelled master has exceptions; entire UID excluded')
        record['disposition'] = 'cancelled'
        return record, None, {}
    event = decode_event(props, display)
    record.update(time_basis=event.start.kind, timezone=event.start.zone,
                  disposition='transparent' if event.transparent else 'included')
    if exceptions and not event.rule:
        raise SeriesError('nonrecurring_master', 'Overrides require a supported recurring master')
    overrides = {}
    for replacement, values in exceptions:
        replacement.update(role='override', master=record['id'])
        rid_prop = one(values, 'RECURRENCE-ID', True)
        if 'RANGE' in rid_prop[0]:
            raise SeriesError('unsupported_range', 'RECURRENCE-ID RANGE is unsupported')
        rid = decode_time(*rid_prop, display)
        if rid.kind != event.start.kind or rid.zone != event.start.zone:
            raise SeriesError('incompatible_identity', 'RECURRENCE-ID must use master value type and timezone form')
        identity = recurrence_identity(rid.value, event.start)
        replacement['recurrence_id'] = identity
        if identity in overrides:
            raise SeriesError('conflicting_overrides', 'Competing overrides for one original identity; entire UID excluded')
        if (rid.value if rid.kind == 'date' else rid.instant()) in event.excluded:
            raise SeriesError('exdate_override_collision', 'EXDATE and override target the same identity; entire UID excluded')
        for key in ('RRULE', 'EXDATE', 'RDATE', 'EXRULE', 'DURATION'):
            if key in values:
                raise SeriesError('unsupported_override', f'{key} on override is unsupported')
        effective = {k: v for k, v in values.items() if k != 'RECURRENCE-ID'}
        inherited = []
        for key in ('SUMMARY', 'TRANSP', 'STATUS'):
            if key not in values:
                inherited.append(key)
                if key in props:
                    effective[key] = props[key]
        cancelled = text_value(effective, 'STATUS', 'CONFIRMED').upper() == 'CANCELLED'
        if 'DTSTART' not in effective:
            if not cancelled:
                raise SeriesError('missing_override_start', 'Active override requires DTSTART')
            effective['DTSTART'] = [rid_prop]
        changed = decode_event(effective, display)
        if not compatible(event.start, changed.start):
            raise SeriesError('incompatible_timing', 'Override DTSTART type differs from master')
        if 'DTEND' not in values:
            changed.duration = event.duration
            inherited.append('duration')
        replacement.update(summary=text_value(effective, 'SUMMARY', '(untitled)'),
                           time_basis=changed.start.kind, timezone=changed.start.zone,
                           disposition='cancelled' if cancelled else ('transparent' if changed.transparent else 'included'),
                           inherited=inherited,
                           effective_start=recurrence_identity(changed.start.value, changed.start),
                           duration_seconds=int(changed.duration.total_seconds()))
        finish = (changed.start.value + changed.duration if changed.start.kind == 'date'
                  else changed.start.instant() + changed.duration)
        replacement['effective_end'] = finish.isoformat() if changed.start.kind == 'date' else iso(finish)
        overrides[identity] = (replacement, changed, rid.value, cancelled)
    return record, event, overrides


def family_occurrences(record, event, overrides, first, last, lo, hi, zone, budget):
    """Resolve every exception before publishing any part of a family."""
    if event is None or (event.transparent and not overrides):
        return [], []
    pending, cancellations, matched = [], [], set()
    through = max((item[2] for item in overrides.values()), default=None)
    for original in expand(event, last, hi, budget, through=through, resolution=bool(overrides)):
        budget.check()
        identity = recurrence_identity(original, event.start)
        replacement = overrides.get(identity)
        effective, owner, override_id = event, record, None
        candidate = original
        if replacement:
            owner, effective, _, cancelled = replacement
            matched.add(identity)
            override_id = owner['id']
            if cancelled:
                cancellations.append({'master': record['id'], 'override': override_id,
                                      'recurrence_id': identity, 'reason': 'STATUS:CANCELLED'})
                continue
            candidate = effective.start.value
        if effective.transparent:
            continue
        is_date = effective.start.kind == 'date'
        if is_date:
            finish = candidate + effective.duration
            a, b = max(candidate, first), min(finish, last)
            if a >= b:
                continue
            occurrence = {'start': candidate.isoformat(), 'end': finish.isoformat(),
                          'clipped_start': a.isoformat(), 'clipped_end': b.isoformat()}
        else:
            a0 = candidate.astimezone(UTC)
            b0 = a0 + effective.duration
            a, b = max(a0, lo), min(b0, hi)
            if a >= b and not (a0 == b0 and lo <= a0 < hi):
                continue
            occurrence = {'start': iso(a0), 'end': iso(b0), 'clipped_start': iso(a), 'clipped_end': iso(b),
                          'local_start': a0.astimezone(zone).isoformat(), 'local_end': b0.astimezone(zone).isoformat()}
        budget.take('occurrences')
        occurrence.update(event=owner['id'], master=record['id'], override=override_id,
                          recurrence_id=identity, all_day=is_date)
        pending.append((occurrence, a, b, is_date))
    if matched != set(overrides):
        raise SeriesError('orphan_override', 'Override identity is not a valid master recurrence; entire UID excluded')
    return pending, cancellations


def union_seconds(intervals):
    """Measure union of half-open intervals; works with datetimes or numbers."""
    total = 0
    left = right = None
    for start, end in sorted(intervals):
        if end <= start:
            continue
        if right is None:
            left, right = start, end
        elif start > right:
            span = right - left
            total += span.total_seconds() if isinstance(span, timedelta) else span
            left, right = start, end
        else:
            right = max(right, end)
    if right is not None:
        span = right - left
        total += span.total_seconds() if isinstance(span, timedelta) else span
    return total


def overlap_pairs(intervals, budget: Budget):
    """Sweep by start; positive intersections only, including nested intervals."""
    active = []
    result = []
    for start, end, ident in sorted(intervals):
        budget.check()
        if end <= start:
            continue
        active = [(a, b, i) for a, b, i in active if b > start]
        for a, b, i in active:
            budget.take('pairs')
            result.append((i, ident, start, min(b, end)))
        active.append((start, end, ident))
    return result


def analyze(paths, start: str, end: str, display: str, limits=Limits(), budget=None):
    """Legacy schema-2 overlap audit, including bounded pair enumeration."""
    return _analyze(paths, start, end, display, limits, budget, include_overlaps=True)


def analyze_occurrences(paths, start: str, end: str, display: str, limits=Limits(), budget=None):
    """Occurrence audit: identical expansion/diagnostics, no overlap enumeration.

    This distinct report type deliberately omits overlaps and the inapplicable
    pair limit; absence of a computation must never masquerade as zero overlaps.
    """
    return _analyze(paths, start, end, display, limits, budget, include_overlaps=False)


def _analyze(paths, start, end, display, limits, budget, *, include_overlaps):
    budget = budget or Budget(limits)
    zone = get_zone(display)
    first, last, lo, hi = window(start, end, zone)
    records, sources, issues, groups = [], [], [], defaultdict(list)
    for source_num, path in enumerate(paths, 1):
        budget.take('files')
        path = Path(path)
        try:
            if not stat.S_ISREG(path.stat().st_mode):
                raise AuditError('Inputs must be regular local files')
            with path.open('rb') as f:
                raw = f.read(limits.input_bytes - budget.counts['input_bytes'] + 1)
        except OSError as exc:
            raise AuditError(f'Cannot read input {source_num}') from exc
        budget.take('input_bytes', len(raw))
        source_id = f's{source_num}'
        sources.append({'id': source_id, 'name': path.name, 'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw)})
        try:
            events, warnings = scan(raw, budget)
        except (ValueError, AssertionError) as exc:
            issues.append({'source': source_id, 'code': 'invalid_calendar', 'message': str(exc) if isinstance(exc, Unsupported) else 'Malformed calendar'})
            continue
        for warning in warnings:
            issues.append({'source': source_id, 'code': 'unsupported_component', 'message': warning})
        for ordinal, lines in enumerate(events, 1):
            props = properties(lines)
            ident = f'e{len(records) + 1}'
            record = {'id': ident, 'uid': '', 'summary': '', 'sources': [{'source': source_id, 'event': ordinal}], 'disposition': 'pending'}
            records.append(record)
            try:
                record['uid'] = text_value(props, 'UID')
                record['summary'] = text_value(props, 'SUMMARY', '(untitled)')
                if not record['uid']:
                    raise Unsupported('Missing or empty UID')
            except (ValueError, AssertionError) as exc:
                record['disposition'] = 'unsupported'
                issues.append({'event': ident, 'code': 'invalid_identity', 'message': str(exc) if isinstance(exc, Unsupported) else 'Malformed event identity'})
                if not record['uid']:
                    continue
            # Compare complete unfolded components; metadata differences are also
            # ambiguous, rather than guessing whether two exports are equivalent.
            fingerprint = hashlib.sha256('\n'.join(lines).encode()).hexdigest()
            groups[record['uid']].append((record, props, fingerprint))
    occurrences, timed, all_day, cancellations = [], [], [], []
    for group in groups.values():
        budget.check()
        try:
            record, event, overrides = prepare_family(group, display)
            pending, cancelled = family_occurrences(record, event, overrides, first, last, lo, hi, zone, budget)
            for occurrence, a, b, is_date in pending:
                occurrence['id'] = f'o{len(occurrences)+1}'
                occurrences.append(occurrence)
                (all_day if is_date else timed).append((a, b, occurrence['id']))
            cancellations.extend(cancelled)
        except (ValueError, OverflowError, AssertionError) as exc:
            code = exc.code if isinstance(exc, SeriesError) else 'unsupported_event'
            message = str(exc) if isinstance(exc, Unsupported) else 'Malformed or out-of-range event value'
            for record, _, _ in group:
                record['disposition'] = 'ambiguous' if isinstance(exc, SeriesError) else 'unsupported'
                issues.append({'event': record['id'], 'code': code, 'message': message})
    pairs = [{'id': f'p{i}', 'left': left, 'right': right, 'start': iso(a), 'end': iso(b),
              'seconds': int((b-a).total_seconds())}
             for i, (left, right, a, b) in enumerate(overlap_pairs(timed, budget), 1)] if include_overlaps else None
    daily = []
    d = first
    while d < last:
        budget.check()
        a, b = local_midnight(d, zone), local_midnight(d + DAY, zone)
        intervals = [(max(x, a), min(y, b)) for x, y, _ in timed if x < b and y > a]
        daily.append({'date': d.isoformat(), 'day_seconds': int((b-a).total_seconds()),
                      'occupied_seconds': int(union_seconds(intervals)),
                      'timed_occurrences': sum(1 for x, y, _ in timed if (x < b and y > a) or (x == y and a <= x < b)),
                      'all_day_occurrences': sum(1 for x, y, _ in all_day if x <= d < y)})
        d += DAY
    budget.check()
    report = {'schema_version': 2, 'tool_version': __version__,
            'dependencies': {name: metadata.version(name) for name in ('icalendar', 'tzdata', 'python-dateutil', 'six')},
            'window': {'start': start, 'end': end, 'timezone': display, 'start_utc': iso(lo), 'end_utc': iso(hi)},
            'complete': not issues, 'issues': issues, 'limits': asdict(limits),
            'cancellations': cancellations, 'sources': sources, 'events': records, 'occurrences': occurrences, 'overlaps': pairs,
            'daily': daily, 'occupied_seconds': int(union_seconds((a, b) for a, b, _ in timed)),
            'counts': dict(sorted(budget.counts.items()))}
    if not include_overlaps:
        report['schema_version'] = 1
        report['report_type'] = 'occurrences'
        del report['overlaps']
        del report['limits']['pairs']
    return report
