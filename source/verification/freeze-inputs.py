#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Freeze verification inputs from the completed release and fixed source assets."""
import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def pin(path):
    return {'path': str(path.relative_to(ROOT)), 'bytes': path.stat().st_size,
            'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--release', type=Path, default=ROOT / 'outputs/test1/release.json')
    p.add_argument('--imagebuilder', type=Path, required=True)
    p.add_argument('--output', type=Path, default=Path(__file__).with_name('inputs.json'))
    args = p.parse_args()
    release = json.loads(args.release.read_text())
    ib = args.imagebuilder.resolve()
    kdir = ib / 'build_dir/target-aarch64_generic_musl/linux-rockchip_armv8'
    boot = kdir / 'tmp/openwrt-25.12.6-rockchip-armv8-firefly_firefly-rk3399-ext4-sysupgrade.img.gz.boot/boot.scr'
    files = []
    for overlay in [ROOT / 'source/network/overlay', ROOT / 'source/overlay']:
        for path in sorted(overlay.rglob('*')):
            if path.is_symlink():
                files.append({'path': str(path.relative_to(overlay)), 'symlink': str(path.readlink())})
            elif path.is_file():
                item = pin(path); item['path'] = str(path.relative_to(overlay)); files.append(item)
    files.append({'path': 'lib/firmware/brcm/brcmfmac4356-sdio.firefly,firefly-rk3399.txt',
                  'symlink': 'brcmfmac4356-sdio.AP6356S.txt'})
    required = [line.strip() for line in (ROOT / 'source/packages.txt').read_text().splitlines()
                if line.strip() and not line.startswith('#') and not line.startswith('-')]
    data = {'version': '25.12.6', 'revision': 'r33311-981c978eff',
            'kernel_version': '6.12.112', 'kernel_vermagic': '5eacf764ba9415e5d7ff4aecb2e45c4d',
            'board': 'firefly,firefly-rk3399', 'target': 'rockchip/armv8', 'rootfs_type': 'ext4',
            'kernel': pin(kdir / 'vmlinux'), 'dtb': pin(ROOT / 'source/board/assets/rk3399-firefly-openwrt.dtb'),
            'files': files, 'required_packages': required, 'modes': {}}
    for medium in ['sd', 'emmc']:
        mode = release['modes'][medium]
        base = {'disk_signature': mode['disk_signature'], 'partitions': release['partitions'],
                'bootloader': mode['bootloader'], 'boot_script': pin(boot),
                'fit': pin(kdir / 'firefly_firefly-rk3399-kernel.bin')}
        data['modes'][medium] = dict(base, has_metadata=False)
        data['modes'][medium + '-sysupgrade'] = dict(base, has_metadata=True)
    args.output.write_text(json.dumps(data, indent=2) + '\n')
    print(str(args.output))


if __name__ == '__main__': main()
