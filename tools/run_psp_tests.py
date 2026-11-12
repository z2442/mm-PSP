#!/usr/bin/env python3
"""Run PSP host regressions in separate processes, including standalone scripts."""
from pathlib import Path
import subprocess
import sys


def main():
    root = Path(__file__).resolve().parents[1]
    failures = []
    tests = sorted((root / 'tools/tests').glob('test_psp_*.py'))
    for test in tests:
        print(f'Running {test.name}', flush=True)
        if subprocess.run([sys.executable, str(test)], cwd=root).returncode:
            failures.append(test.name)
    if failures:
        print('Failed: ' + ', '.join(failures), file=sys.stderr)
        return 1
    print(f'All {len(tests)} PSP regression scripts passed.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
