"""Separate offline CLI; legacy audit commands and output remain unchanged."""
import argparse
from dataclasses import fields
import os
from pathlib import Path
import sys

from .availability import availability, load_spec
from .availability_report import html_bytes
from .cli import deadline, write_bundle
from .core import AuditError, Budget, Limits
from .report import json_bytes


def parser():
    p = argparse.ArgumentParser(description='Find bounded candidate gaps in local ICS exports. Specification v1.')
    p.add_argument('inputs', nargs='+', type=Path)
    p.add_argument('--spec', type=Path, required=True, help='Version-1 working-window JSON specification')
    p.add_argument('--output', type=Path, required=True, help='New directory; never overwritten')
    p.add_argument('--max-days', type=int, default=90)
    for field in fields(Limits):
        default = getattr(Limits(), field.name)
        p.add_argument('--max-' + field.name.replace('_', '-'), type=type(default), default=default)
    return p


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        limits = Limits(**{f.name: getattr(args, 'max_' + f.name) for f in fields(Limits)})
        with deadline(limits.seconds):
            budget = Budget(limits)
            if os.path.lexists(args.output):
                raise AuditError('Output path already exists; choose a new directory')
            spec, fingerprint = load_spec(args.spec, args.max_days)
            report = availability(args.inputs, spec, limits, budget, fingerprint, args.max_days)
            data = json_bytes(report)
            if len(data) > limits.report_bytes:
                raise AuditError('report_bytes limit exceeded (JSON)')
            page = html_bytes(report, budget)
            write_bundle(args.output, {'report.json': data, 'report.html': page}, budget)
        if report['complete']:
            print(f'{len(report["candidates"])} candidate intervals; {report["candidate_seconds"]} elapsed seconds. '
                  'Only supplied exports and selected policies; not a booking guarantee.')
            return 0
        print('INCOMPLETE: candidate intervals withheld. See report issues.')
        return 2
    except KeyboardInterrupt:
        print('Availability cancelled.', file=sys.stderr)
        return 130
    except (AuditError, OSError, ValueError, TypeError, OverflowError) as exc:
        exhausted = isinstance(exc, AuditError) and ('limit exceeded' in str(exc) or 'exceeds max-days limit' in str(exc))
        message = str(exc) if isinstance(exc, AuditError) else 'Invalid value, serialization, or filesystem operation failed'
        print(('INCOMPLETE; no availability bundle: ' if exhausted else 'Availability failed: ') + message, file=sys.stderr)
        return 2 if exhausted else 1


if __name__ == '__main__':
    sys.exit(main())
