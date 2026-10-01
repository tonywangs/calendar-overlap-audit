#!/usr/bin/env python3
"""Reproduce inherited getrusage high-water accounting versus Linux VmHWM."""
import argparse
import json
from pathlib import Path
import platform
import subprocess
import sys

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--output', type=Path, required=True)
args = parser.parse_args()
# Bound the parent to one deliberate 100 MB allocation. The child immediately
# execs a fresh Python interpreter; it must not allocate that 100 MB itself.
allocation = bytearray(100_000_000)
code = '''import json,resource
status = dict(line.split(':',1) for line in open('/proc/self/status'))
print(json.dumps({'getrusage_maxrss_kib':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                  'proc_vmhwm_kib':int(status['VmHWM'].split()[0]),
                  'proc_vmrss_kib':int(status['VmRSS'].split()[0])}))
'''
run = subprocess.run([sys.executable,'-c',code],cwd='/tmp',check=True,capture_output=True,text=True)
result = dict(parent_allocation_bytes=len(allocation),python=platform.python_version(),
              platform=platform.platform(),child=json.loads(run.stdout))
args.output.write_text(json.dumps(result,sort_keys=True,indent=2)+'\n')
print(json.dumps(result))
