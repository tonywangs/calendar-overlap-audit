"""Strict, bounded VFREEBUSY subset; independent of icalendar's decoder."""
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat

from .core import AuditError, UTC, WEEKDAYS, get_zone

MAX_SECONDS = 90 * 86400


@dataclass(frozen=True)
class SharedLimits:
    input_bytes: int = 8 * 1024 * 1024
    manifest_bytes: int = 256 * 1024
    files: int = 32
    line_bytes: int = 65536
    periods: int = 20000
    operations: int = 2000000
    intervals: int = 100000
    windows: int = 20000
    report_bytes: int = 8 * 1024 * 1024
    seconds: float = 30.0

    def __post_init__(self):
        for key, value in asdict(self).items():
            ceiling = self.__dataclass_fields__[key].default
            valid_type = type(value) in (int, float) if key == 'seconds' else type(value) is int
            if not valid_type or not math.isfinite(value) or not 0 < value <= ceiling:
                raise AuditError(f'Limit {key} must be positive and at most {ceiling}')


def read_local(path, limit, budget):
    """Open nonblocking before fstat, so FIFOs and replacement races cannot hang."""
    budget.check()
    fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode):
            raise AuditError('Inputs must be regular local files')
        if info.st_size > limit:
            raise AuditError('input_bytes limit exceeded')
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise AuditError('input_bytes limit exceeded')
    budget.take('input_bytes', len(raw))
    return raw, (info.st_dev, info.st_ino)


def fingerprint(raw):
    return dict(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())


def instant(raw, *, basic=False):
    pattern = r'[0-9]{8}T[0-9]{6}Z' if basic else r'[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z'
    if not isinstance(raw, str) or not re.fullmatch(pattern, raw):
        raise AuditError('Times must be whole-second UTC date-times')
    try:
        return datetime.fromisoformat(raw).astimezone(UTC)
    except ValueError as exc:
        raise AuditError('Invalid UTC date-time') from exc


def span(a, b):
    if not 0 < (b - a).total_seconds() <= MAX_SECONDS:
        raise AuditError('Coverage and horizon must be positive and at most 90 elapsed days')


def exact(value, keys, label):
    if not isinstance(value, dict) or set(value) != set(keys.split()):
        raise AuditError(f'Invalid {label} keys; see docs/shared-windows.md')


def unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise AuditError('Duplicate manifest key')
        result[key] = value
    return result


def validate_manifest(value):
    exact(value, 'version start end duration_seconds participants', 'manifest')
    if type(value['version']) is not int or value['version'] != 1:
        raise AuditError('Manifest version must be 1')
    span(instant(value['start']), instant(value['end']))
    if type(value['duration_seconds']) is not int or not 1 <= value['duration_seconds'] <= MAX_SECONDS:
        raise AuditError('duration_seconds must be an integer from 1 to 7776000')
    participants = value['participants']
    if not isinstance(participants, list) or not 1 <= len(participants) <= 16:
        raise AuditError('Manifest requires 1 to 16 participants')
    seen = set()
    for person in participants:
        exact(person, 'alias timezone weekly sources', 'participant')
        alias = person['alias']
        if (not isinstance(alias, str) or not 1 <= len(alias) <= 64 or not alias.isprintable()
                or not alias.strip() or alias in seen):
            raise AuditError('Aliases must be unique printable labels of 1 to 64 characters')
        seen.add(alias)
        if not isinstance(person['timezone'], str):
            raise AuditError('timezone must be a string')
        get_zone(person['timezone'])
        weekly = person['weekly']
        if not isinstance(weekly, dict) or any(k not in WEEKDAYS for k in weekly):
            raise AuditError('weekly must map weekday codes MO through SU to windows')
        for windows in weekly.values():
            if not isinstance(windows, list) or len(windows) > 16:
                raise AuditError('At most 16 working windows per weekday')
            for pair in windows:
                if not isinstance(pair, list) or len(pair) != 2:
                    raise AuditError('Working windows must be [start, end] pairs')
                for index, clock in enumerate(pair):
                    if not isinstance(clock, str) or not (re.fullmatch(r'(?:[01][0-9]|2[0-3]):[0-5][0-9]', clock)
                                                          or index == 1 and clock == '24:00'):
                        raise AuditError('Working clocks must be HH:MM; only an end permits 24:00')
                if pair[0] == pair[1]:
                    raise AuditError('Equal working clocks are ambiguous; use 00:00 to 24:00 for a full day')
        if not isinstance(person['sources'], list) or not person['sources']:
            raise AuditError('Each participant needs at least one source')
        for source in person['sources']:
            exact(source, 'path complete_occupancy', 'source')
            path = source['path']
            if not isinstance(path, str) or not path or not path.isprintable() or '://' in path:
                raise AuditError('Source path must be a local file path')
            if source['complete_occupancy'] is not True:
                raise AuditError('Each source requires complete_occupancy: true; uncovered time is unknown')
    if sum(len(p['sources']) for p in participants) > 32:
        raise AuditError('files limit exceeded')
    return value


def load_manifest(path, budget):
    raw, _ = read_local(path, min(budget.limits.manifest_bytes, budget.limits.input_bytes), budget)
    try:
        value = json.loads(raw.decode('utf-8'), object_pairs_hook=unique)
    except (UnicodeError, ValueError, RecursionError) as exc:
        raise AuditError('Manifest must be valid UTF-8 JSON') from exc
    return validate_manifest(value), fingerprint(raw)


def lines(raw, budget):
    """Unfold bytes before UTF-8 decode (also permits a fold inside a code point)."""
    if b'\r' in raw.replace(b'\r\n', b''):
        raise AuditError('Bare CR is not an ICS line ending')
    pending = None
    physical = raw.split(b'\n')
    if physical[-1] == b'':
        physical.pop()
    for item in physical:
        budget.take('operations')
        if item.endswith(b'\r'):
            item = item[:-1]
        if not item or any(c < 32 and c != 9 or c == 127 for c in item):
            raise AuditError('Invalid ICS line or control byte')
        if len(item) > budget.limits.line_bytes:
            raise AuditError('line_bytes limit exceeded')
        if item.startswith((b' ', b'\t')):
            if pending is None:
                raise AuditError('ICS continuation without content line')
            if len(pending) + len(item) - 1 > budget.limits.line_bytes:
                raise AuditError('line_bytes limit exceeded')
            pending += item[1:]
        else:
            if pending is not None:
                yield pending.decode('utf-8')
            pending = item
    if pending is not None:
        yield pending.decode('utf-8')


def property_parts(line):
    # Only token parameters are in the subset, so quoted punctuation is rejected.
    head, sep, value = line.partition(':')
    if not sep:
        raise AuditError('Malformed ICS content line')
    parts = head.split(';')
    if not re.fullmatch(r'[A-Za-z][A-Za-z0-9-]*', parts[0]):
        raise AuditError('Invalid ICS property name')
    name = parts[0].upper()
    params = {}
    for item in parts[1:]:
        match = re.fullmatch(r'([A-Za-z][A-Za-z0-9-]*)=(?:([A-Za-z0-9-]+)|"([A-Za-z0-9-]+)")', item)
        if not match:
            raise AuditError('Unsupported ICS parameter syntax')
        key = match[1].upper()
        if key in params:
            raise AuditError('Duplicate ICS parameter')
        params[key] = (match[2] or match[3]).upper()
    return name, params, value


def duration(raw):
    match = re.fullmatch(r'\+?P(?:([0-9]{1,9})W|(?:([0-9]{1,9})D)?(?:T(?:([0-9]{1,9})H)?(?:([0-9]{1,9})M)?(?:([0-9]{1,9})S)?)?)', raw)
    if not match or not any(match.groups()) or raw.endswith('T'):
        raise AuditError('Unsupported period duration')
    seconds = sum(int(n or 0) * factor for n, factor in zip(match.groups(), (604800, 86400, 3600, 60, 1)))
    if not 0 < seconds <= MAX_SECONDS:
        raise AuditError('Period duration must be positive and at most 90 days')
    return timedelta(seconds=seconds)


def parse_freebusy(raw, budget):
    """Return only coverage, blocking periods and counts; never source metadata."""
    state, seen, calendar_seen, blocks = 'start', set(), set(), []
    bounds, counts = {}, dict(BUSY=0, **{'BUSY-TENTATIVE': 0, 'BUSY-UNAVAILABLE': 0, 'FREE': 0})
    all_periods = []
    try:
        for line in lines(raw, budget):
            name, params, value = property_parts(line)
            upper = value.upper()
            if name in ('BEGIN', 'END'):
                if params or not value.isascii():
                    raise AuditError('Component markers cannot have parameters')
                transition = {
                    ('start', 'BEGIN', 'VCALENDAR'): 'calendar',
                    ('calendar', 'BEGIN', 'VFREEBUSY'): 'busy',
                    ('busy', 'END', 'VFREEBUSY'): 'after',
                    ('after', 'END', 'VCALENDAR'): 'done',
                }.get((state, name, upper))
                if transition is None:
                    raise AuditError('Expected exactly one VCALENDAR containing one VFREEBUSY')
                state = transition
                continue
            if state == 'calendar':
                if name not in {'VERSION', 'PRODID', 'CALSCALE', 'METHOD'} or params or name in calendar_seen:
                    raise AuditError('Unsupported or duplicate calendar property')
                calendar_seen.add(name)
                if (not value or name in {'VERSION', 'CALSCALE', 'METHOD'} and not value.isascii()
                        or name == 'VERSION' and value != '2.0' or name == 'CALSCALE' and upper != 'GREGORIAN'
                        or name == 'METHOD' and upper != 'PUBLISH'):
                    raise AuditError('Unsupported calendar version, scale or method')
            elif state == 'busy':
                if name == 'FREEBUSY':
                    if set(params) - {'FBTYPE', 'VALUE'} or params.get('VALUE', 'PERIOD') != 'PERIOD':
                        raise AuditError('Unsupported FREEBUSY parameters')
                    kind = params.get('FBTYPE', 'BUSY')
                    if kind not in counts:
                        raise AuditError('Unsupported busy type')
                    for token in value.split(','):
                        budget.take('periods')
                        pair = token.split('/')
                        if len(pair) != 2:
                            raise AuditError('Malformed free/busy period')
                        a = instant(pair[0], basic=True)
                        b = a + duration(pair[1]) if pair[1].upper().startswith(('P', '+P')) else instant(pair[1], basic=True)
                        if a >= b:
                            raise AuditError('Free/busy periods must have positive duration')
                        all_periods.append((a, b))
                        counts[kind] += 1
                        if kind != 'FREE':
                            blocks.append((a, b))
                elif name in {'DTSTART', 'DTEND', 'DTSTAMP', 'UID', 'ORGANIZER', 'CONTACT', 'URL', 'COMMENT'}:
                    if name != 'COMMENT' and name in seen:
                        raise AuditError('Duplicate VFREEBUSY property')
                    seen.add(name)
                    if name in {'DTSTART', 'DTEND', 'DTSTAMP'}:
                        if params and params != {'VALUE': 'DATE-TIME'}:
                            raise AuditError('Unsupported date-time parameters')
                        bounds[name] = instant(value, basic=True)
                    elif params or not value:
                        raise AuditError('Unsupported metadata parameters or empty value')
                else:
                    raise AuditError('Unsupported VFREEBUSY property or ownership semantics')
            else:
                raise AuditError('Property outside supported component')
    except (UnicodeError, OverflowError) as exc:
        raise AuditError('Invalid UTF-8 or overflowing free/busy time') from exc
    if state != 'done' or not {'VERSION', 'PRODID'} <= calendar_seen or not {'UID', 'DTSTAMP', 'DTSTART', 'DTEND'} <= seen:
        raise AuditError('Missing required calendar, identity or coverage bounds')
    lo, hi = bounds['DTSTART'], bounds['DTEND']
    span(lo, hi)
    for a, b in all_periods:
        budget.take('operations')
        if not lo <= a < b <= hi:
            raise AuditError('Period lies outside asserted coverage')
    return (lo, hi), blocks, counts
