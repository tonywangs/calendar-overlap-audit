"""Offline free/busy CLI with fail-closed analysis and exclusive output ownership."""
import argparse
from dataclasses import fields
import os
from pathlib import Path
import sys

from .cli import deadline, write_bundle
from .core import AuditError, Budget, Limits
from .freebusy import (IncompleteExport, MAX_INTERVALS, calendar_bytes,
                       export_identity, interval_limit, occupied)


def parser():
    p = argparse.ArgumentParser(description='Export merged occupied time offline; precise times remain disclosed.')
    p.add_argument('inputs', nargs='+', type=Path)
    p.add_argument('--start', required=True, help='YYYY-MM-DD, inclusive in selected timezone')
    p.add_argument('--end', required=True, help='YYYY-MM-DD, exclusive; horizon 1–90 days')
    p.add_argument('--timezone', required=True, help='IANA timezone; also interprets floating times and DATE events')
    p.add_argument('--all-day', required=True, choices=('block', 'ignore'))
    p.add_argument('--output', required=True, type=Path, help='New directory containing only busy.ics; never overwritten')
    p.add_argument('--uid', help='Independent canonical UUID4; default: new random UUID4')
    p.add_argument('--created-at', help='YYYY-MM-DDTHH:MM:SSZ; default: current UTC second')
    p.add_argument('--max-intervals', type=int, default=MAX_INTERVALS)
    for field in fields(Limits):
        if field.name == 'pairs':
            continue
        default = getattr(Limits(), field.name)
        p.add_argument('--max-' + field.name.replace('_', '-'), type=type(default), default=default)
    return p


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        limits = Limits(**{f.name: getattr(args, 'max_' + f.name) for f in fields(Limits) if f.name != 'pairs'})
        interval_limit(args.max_intervals)
        with deadline(limits.seconds):
            budget = Budget(limits)
            export_identity(args.uid, args.created_at)  # Validate before reading inputs.
            if os.path.lexists(args.output):
                raise AuditError('Output path already exists; choose a new directory')
            result = occupied(args.inputs, args.start, args.end, args.timezone,
                              args.all_day, limits, budget, args.max_intervals)
            data = calendar_bytes(result, budget, uid=args.uid, created_at=args.created_at,
                                  max_intervals=args.max_intervals)
            write_bundle(args.output, {'busy.ics': data}, budget)
        print(f'{len(result.periods)} merged BUSY periods exported. Precise occupied times remain disclosed; '
              'unoccupied time is not working-hour availability.')
        return 0
    except KeyboardInterrupt:
        print('Free/busy export cancelled.', file=sys.stderr)
        return 130
    except (AuditError, OSError, ValueError, TypeError, OverflowError) as exc:
        incomplete = isinstance(exc, IncompleteExport) or (isinstance(exc, AuditError) and 'limit exceeded' in str(exc))
        message = str(exc) if isinstance(exc, AuditError) else 'Invalid value, serialization, or filesystem operation failed'
        print(('INCOMPLETE; no free/busy export: ' if incomplete else 'Free/busy export failed: ') + message, file=sys.stderr)
        return 2 if incomplete else 1


if __name__ == '__main__':
    sys.exit(main())
