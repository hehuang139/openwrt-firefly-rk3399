#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Compare release artifacts and complete rootfs inventories from two builds."""
import argparse
import hashlib
import json
import os
import stat
import struct
from pathlib import Path

IB = 'work/openwrt-imagebuilder-25.12.6-rockchip-armv8.Linux-x86_64'


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(8388608), b''):
            h.update(block)
    return h.hexdigest()


def inventory(root):
    if not root.is_dir():
        raise ValueError('Missing rootfs directory: ' + str(root))
    entries = {}
    def fail(error):
        raise error
    for base, directories, files in os.walk(root, followlinks=False, onerror=fail):
        for name in directories + files:
            path = Path(base) / name
            info = path.lstat()
            entry = {
                'type': stat.S_IFMT(info.st_mode),
                'mode': stat.S_IMODE(info.st_mode),
                'uid': info.st_uid,
                'gid': info.st_gid,
                'mtime_ns': info.st_mtime_ns,
            }
            if stat.S_ISLNK(info.st_mode):
                entry['link'] = os.readlink(path)
            elif stat.S_ISREG(info.st_mode):
                entry.update(bytes=info.st_size, sha256=digest(path))
            elif stat.S_ISBLK(info.st_mode) or stat.S_ISCHR(info.st_mode):
                entry['rdev'] = info.st_rdev
            entries[path.relative_to(root).as_posix()] = entry
    return entries


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--original', type=Path, required=True)
    parser.add_argument('--rebuilt', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    roots = [args.original.resolve(), args.rebuilt.resolve()]
    releases = [json.loads((root / 'outputs/test1/release.json').read_text()) for root in roots]
    checks = []

    def check(name, passed, detail):
        checks.append({'name': name, 'pass': bool(passed), 'detail': detail})

    check('release-identity', all(
        release['board'] == 'firefly-rk3399' and release['version'] == '25.12.6'
        and release['kernel'] == '6.12.112' for release in releases),
        [{key: release[key] for key in ['board', 'version', 'kernel']} for release in releases])
    for mode in ['sd', 'emmc']:
        check(mode + '-layout', releases[0]['partitions'] == releases[1]['partitions']
              and releases[0]['modes'][mode]['disk_signature'] == releases[1]['modes'][mode]['disk_signature'],
              {'partitions': releases[0]['partitions'], 'disk_signature': releases[0]['modes'][mode]['disk_signature']})
        for kind in ['image', 'compressed', 'sysupgrade', 'bootloader']:
            pins = [release['modes'][mode][kind] for release in releases]
            actual = [{'bytes': (root / pin['path']).stat().st_size,
                       'sha256': digest(root / pin['path'])} for root, pin in zip(roots, pins)]
            check(mode + '-' + kind + '-byte-identical', actual[0] == actual[1]
                  and all(value['sha256'] == pin['sha256'] and value['bytes'] == pin['bytes']
                          for value, pin in zip(actual, pins)),
                  {'path': pins[0]['path'], 'original': actual[0], 'rebuilt': actual[1]})
        clocks = []
        for build, (root, release) in enumerate(zip(roots, releases)):
            with (root / release['modes'][mode]['image']['path']).open('rb') as stream:
                for index, partition in enumerate(release['partitions'], 1):
                    stream.seek(partition['start_lba'] * 512 + 1024)
                    superblock = stream.read(1024)
                    clocks.append({'build': build, 'partition': index,
                                   'wtime': struct.unpack_from('<I', superblock, 48)[0],
                                   'lastcheck': struct.unpack_from('<I', superblock, 64)[0]})
        check(mode + '-fixed-filesystem-clock', all(
            value['wtime'] == value['lastcheck'] == 1792273538 for value in clocks), clocks)
    for name, relative in [
        ('imagebuilder-output', releases[0]['source_image']['path']),
        ('device-tree', 'source/board/assets/rk3399-firefly-openwrt.dtb'),
        ('kernel-fit', IB + '/build_dir/target-aarch64_generic_musl/linux-rockchip_armv8/firefly_firefly-rk3399-kernel.bin'),
    ]:
        values = [{'bytes': (root / relative).stat().st_size, 'sha256': digest(root / relative)} for root in roots]
        check(name + '-byte-identical', values[0] == values[1], {'path': relative, 'original': values[0], 'rebuilt': values[1]})
    relative = IB + '/build_dir/target-aarch64_generic_musl/root-rockchip'
    inventories = [inventory(root / relative) for root in roots]
    changed = [name for name in sorted(inventories[0].keys() | inventories[1].keys())
               if inventories[0].get(name) != inventories[1].get(name)]
    hashes = [hashlib.sha256(json.dumps(entries, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
              for entries in inventories]
    check('rootfs-complete-inventory-identical', not changed,
          {'entries': [len(entries) for entries in inventories], 'sha256': hashes,
           'changed_paths': changed, 'fields': ['type', 'mode', 'uid', 'gid', 'mtime_ns', 'bytes', 'sha256', 'link', 'rdev']})
    report = {
        'result': 'PASS' if all(item['pass'] for item in checks) else 'FAIL',
        'passed': sum(item['pass'] for item in checks), 'total': len(checks),
        'environment': 'Independent fresh offline source-kit build; comparison opens ordinary files read-only.',
        'checks': checks,
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'result': report['result'], 'passed': report['passed'], 'total': report['total']}))
    return 0 if report['result'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
