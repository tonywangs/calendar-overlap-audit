"""Offline CLI for bounded meeting-window discovery from local VFREEBUSY."""
import argparse
from dataclasses import fields
import os
from pathlib import Path
import sys

from .cli import deadline, write_bundle
from .core import AuditError, Budget
from .shared import discover
from .shared_input import SharedLimits
from .shared_report import html_bytes, json_bytes


def parser():
    p = argparse.ArgumentParser(description='Find shared meeting windows from asserted complete local VFREEBUSY and explicit working schedules.')
    p.add_argument('--manifest', required=True, type=Path, help='Version-1 manifest; source paths are relative to this file')
    p.add_argument('--output', required=True, type=Path, help='New report directory; never overwritten')
    for field in fields(SharedLimits):
        default = getattr(SharedLimits(), field.name)
        p.add_argument('--max-'+field.name.replace('_', '-'), type=type(default), default=default,
                       help=f'Positive resource limit, at most {default}')
    return p


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        limits = SharedLimits(**{f.name: getattr(args, 'max_'+f.name) for f in fields(SharedLimits)})
        with deadline(limits.seconds):
            budget = Budget(limits)
            if os.path.lexists(args.output):
                raise AuditError('Output path already exists; choose a new directory')
            report = discover(args.manifest, limits, budget)
            data = json_bytes(report, budget)
            page = html_bytes(report, budget)
            write_bundle(args.output, {'report.json': data, 'report.html': page}, budget)
        print(f'{len(report["windows"])} shared candidate windows; {report["window_seconds"]} elapsed seconds. '
              'Uncovered time is unknown; candidates are not booked meetings.')
        return 0
    except KeyboardInterrupt:
        print('Shared-window discovery cancelled.', file=sys.stderr)
        return 130
    except (AuditError, OSError, ValueError, TypeError, OverflowError, RecursionError) as exc:
        message = str(exc) if isinstance(exc, AuditError) else 'Invalid value, serialization, or filesystem operation failed'
        exhausted = isinstance(exc, AuditError) and 'limit exceeded' in str(exc)
        print('Shared-window discovery failed; no bundle: '+message, file=sys.stderr)
        return 2 if exhausted else 1


if __name__ == '__main__':
    sys.exit(main())
