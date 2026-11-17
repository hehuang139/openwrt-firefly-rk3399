#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Probe the standalone build dependencies with actual cross compilation."""
import argparse
import importlib
import json
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--report', type=Path, required=True)
p.add_argument('--imagebuilder', type=Path)
a = p.parse_args()
checks = []


def check(name, passed, detail):
    checks.append({'name': name, 'pass': bool(passed), 'detail': detail})
    if not passed: raise ValueError(name + ': ' + str(detail))


report = {}
try:
    for name in ['gcc', 'g++', 'make', 'flex', 'bison', 'dtc', 'swig', 'rsync', 'xz', 'zstd',
                 'mkimage', 'e2fsck', 'debugfs', 'qemu-aarch64-static', 'tar', 'patch', 'gawk']:
        path = shutil.which(name)
        check('host-tool:' + name, path is not None, path)
    for name in ['elftools.elf.elffile', 'setuptools', 'distutils', 'ssl']:
        module = importlib.import_module(name)
        check('host-python:' + name, True, str(module.__file__))
    with tempfile.TemporaryDirectory(prefix='firefly-build-probe-') as temporary:
        root = Path(temporary)
        source = root / 'fixture.c'
        source.write_text('int firefly(void) { return 42; }\n')
        for compiler, expected_machine in [('aarch64-linux-gnu-gcc', 183), ('arm-linux-gnueabihf-gcc', 40)]:
            output = root / (compiler + '.o')
            result = subprocess.run([compiler, '-ffreestanding', '-c', str(source), '-o', str(output)],
                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            check('cross-compile:' + compiler, result.returncode == 0, result.stdout.decode(errors='replace'))
            data = output.read_bytes()
            machine = struct.unpack_from('<H', data, 18)[0]
            check('cross-elf-machine:' + compiler, data[:4] == b'\x7fELF' and machine == expected_machine, machine)
            version = subprocess.check_output([compiler, '--version'], text=True).splitlines()[0]
            checks.append({'name': 'compiler-version:' + compiler, 'pass': True, 'detail': version})
    if a.imagebuilder:
        for name, arguments in [('mkimage', ['-V']), ('apk', ['--version'])]:
            executable = a.imagebuilder / 'staging_dir/host/bin' / name
            result = subprocess.run([str(executable), *arguments], stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            check('official-ib-wrapper:' + name, result.returncode == 0, result.stdout.decode(errors='replace'))
except Exception as error:
    report['error'] = type(error).__name__ + ': ' + str(error)
report.update({'result': 'FAIL' if 'error' in report else 'PASS', 'passed': sum(c['pass'] for c in checks),
               'total': len(checks), 'checks': checks})
a.report.parent.mkdir(parents=True, exist_ok=True)
a.report.write_text(json.dumps(report, indent=2) + '\n')
print(json.dumps(report, indent=2))
if 'error' in report: raise SystemExit(1)
