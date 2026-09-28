"""CLI with bounded execution and exclusive output-directory ownership."""
import argparse
from contextlib import contextmanager
from dataclasses import fields
import os
from pathlib import Path
import shutil
import signal
import sys
import tempfile

from . import __version__
from .core import AuditError, Budget, Limits, analyze
from .report import html_bytes, json_bytes


@contextmanager
def deadline(seconds):
    """POSIX wall-clock guard also interrupts parsing, IO and serialization."""
    if not hasattr(signal, 'setitimer'):
        raise AuditError('CLI requires POSIX setitimer for its execution-time guard')
    def expired(signum, frame):
        raise AuditError('Execution-time limit exceeded')
    def cancelled(signum, frame):
        raise KeyboardInterrupt
    old_alarm = signal.signal(signal.SIGALRM, expired)
    old_term = signal.signal(signal.SIGTERM, cancelled)
    old_timer = signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, *old_timer)
        signal.signal(signal.SIGALRM, old_alarm)
        signal.signal(signal.SIGTERM, old_term)


@contextmanager
def defer_signals():
    """Record ownership before a pending cancellation can start cleanup."""
    signals = {signal.SIGINT, signal.SIGTERM, signal.SIGALRM}
    previous = signal.pthread_sigmask(signal.SIG_BLOCK, signals)
    try:
        yield
    finally:
        signal.pthread_sigmask(signal.SIG_SETMASK, previous)


def write_bundle(destination: Path, content: dict[str, bytes], budget: Budget):
    """No overwrite, even of an empty directory; rollback ordinary failures.

    Stage first, then exclusively reserve the destination. The bundle becomes
    complete only on successful return. This is not a filesystem transaction for
    concurrent readers or hard kills; no existing destination is ever removed.
    """
    destination = Path(destination)
    if os.path.lexists(destination):
        raise AuditError('Output path already exists; choose a new directory')
    stage = None
    owned = False
    try:
        with defer_signals():
            stage = Path(tempfile.mkdtemp(prefix='.calendar-audit-', dir=destination.parent))
        for name, data in content.items():
            budget.check()
            if len(data) > budget.limits.report_bytes:
                raise AuditError('report_bytes limit exceeded')
            with (stage / name).open('xb') as out:
                os.chmod(stage / name, 0o600)
                out.write(data)
                out.flush()
                os.fsync(out.fileno())
        budget.check()
        with defer_signals():
            destination.mkdir(mode=0o700)  # exclusive reservation: collision safe
            owned = True
        for name in content:
            os.replace(stage / name, destination / name)
        budget.check()
    except BaseException:
        if owned:
            shutil.rmtree(destination)
        raise
    finally:
        if stage is not None:
            shutil.rmtree(stage)


def parser():
    p = argparse.ArgumentParser(description='Audit local ICS exports offline. Date bounds are start-inclusive/end-exclusive.')
    p.add_argument('inputs', nargs='+', type=Path)
    p.add_argument('--start', required=True, help='YYYY-MM-DD in display timezone')
    p.add_argument('--end', required=True, help='YYYY-MM-DD, exclusive; maximum 90 days')
    p.add_argument('--timezone', required=True, help='IANA display zone; also used for floating times')
    p.add_argument('--output', required=True, type=Path, help='New output directory; never overwritten')
    p.add_argument('--version', action='version', version=__version__)
    for field in fields(Limits):
        default = getattr(Limits(), field.name)
        p.add_argument('--max-' + field.name.replace('_', '-'), type=type(default), default=default,
                       help=f'Resource limit (default {default})')
    return p


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        limits = Limits(**{f.name: getattr(args, 'max_' + f.name) for f in fields(Limits)})
        with deadline(limits.seconds):
            budget = Budget(limits)
            if os.path.lexists(args.output):
                raise AuditError('Output path already exists; choose a new directory')
            report = analyze(args.inputs, args.start, args.end, args.timezone, limits, budget)
            data = json_bytes(report)
            if len(data) > limits.report_bytes:
                raise AuditError('report_bytes limit exceeded (JSON)')
            html = html_bytes(report, budget)
            write_bundle(args.output, {'report.html': html, 'report.json': data}, budget)
        print(f'{"Complete within subset" if report["complete"] else "INCOMPLETE"}: '
              f'{len(report["overlaps"])} overlap pairs; {report["occupied_seconds"]} occupied seconds. '
              'Wrote report.json and report.html.')
        return 0 if report['complete'] else 2
    except KeyboardInterrupt:
        print('Audit cancelled.', file=sys.stderr)
        return 130
    except (AuditError, OSError, ValueError) as exc:
        # Never echo parser internals or imported personal text in operational errors.
        message = str(exc) if isinstance(exc, (AuditError, ValueError)) and not isinstance(exc, OSError) else 'Output or filesystem operation failed'
        print(f'Audit failed: {message}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
