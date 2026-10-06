"""Hand-specified expectations for complete, reproducible synthetic examples."""
EXAMPLES = [
    dict(name='ordinary', source='examples/freebusy/ordinary.ics', start='2026-03-03', end='2026-03-04',
         timezone='UTC', lo='2026-03-03T00:00:00Z', hi='2026-03-04T00:00:00Z',
         periods=[('2026-03-03T09:00:00Z','2026-03-03T11:00:00Z')]),
    dict(name='recurring', source='tests/fixtures/overrides.ics', start='2026-03-03', end='2026-03-06',
         timezone='UTC', lo='2026-03-03T00:00:00Z', hi='2026-03-06T00:00:00Z',
         periods=[('2026-03-03T09:00:00Z','2026-03-03T11:30:00Z')]),
    dict(name='spring', source='tests/fixtures/dst-spring.ics', start='2026-03-07', end='2026-03-11',
         timezone='America/New_York', lo='2026-03-07T05:00:00Z', hi='2026-03-11T04:00:00Z', periods=[
             ('2026-03-07T07:30:00Z','2026-03-07T08:30:00Z'),
             ('2026-03-08T04:00:00Z','2026-03-08T08:00:00Z'),
             ('2026-03-09T03:00:00Z','2026-03-09T07:30:00Z'),
             ('2026-03-10T06:30:00Z','2026-03-10T07:30:00Z')]),
    dict(name='fall', source='tests/fixtures/dst-fall.ics', start='2026-10-31', end='2026-11-03',
         timezone='America/New_York', lo='2026-10-31T04:00:00Z', hi='2026-11-03T05:00:00Z', periods=[
             ('2026-10-31T05:30:00Z','2026-10-31T06:30:00Z'),
             ('2026-11-01T05:30:00Z','2026-11-01T07:30:00Z'),
             ('2026-11-02T06:30:00Z','2026-11-02T07:30:00Z')]),
]
