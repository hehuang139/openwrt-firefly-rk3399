#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Write the release to a new file and boot it on the Firefly QEMU model."""
import argparse
import gzip
import hashlib
import importlib.util
import json
import lzma
import os
from pathlib import Path
import re
import selectors
import stat
import struct
import subprocess
import time

ROOT = Path(__file__).resolve().parents[2]
MODEL = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location('verify_image', ROOT / 'source/verification/verify-image.py')
FORMAT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(FORMAT)


def require(value, message):
    if not value:
        raise ValueError(message)


def flash(image, manifest, work):
    require(stat.S_ISREG(image.lstat().st_mode), 'Image must be a regular file')
    mode = manifest['modes']['emmc']
    compressed = image.suffix == '.gz'
    info = mode['compressed' if compressed else 'image']
    require(image.stat().st_size == info['bytes'] and FORMAT.digest(image) == info['sha256'],
            'Release image size or SHA256 mismatch')
    storage = work / 'virtual-emmc.raw'
    with (gzip.open(image, 'rb') if compressed else image.open('rb')) as src, storage.open('xb') as out:
        size = 0
        while block := src.read(1 << 20):
            size += len(block)
            require(size <= mode['image']['bytes'], 'Uncompressed image exceeds expected size')
            out.write(block)
        out.flush()
        os.fsync(out.fileno())
    readback = FORMAT.digest(storage)
    require(size == mode['image']['bytes'] and readback == mode['image']['sha256'],
            'Virtual eMMC readback differs from release')
    with storage.open('rb') as disk:
        mbr = disk.read(512)
        require(mbr[510:512] == b'\x55\xaa', 'Bad MBR signature')
        require(f'{struct.unpack_from("<I", mbr, 440)[0]:08x}' == mode['disk_signature'], 'Wrong disk ID')
        for i, p in enumerate(manifest['partitions']):
            offset = 446 + i * 16
            start, sectors = struct.unpack_from('<II', mbr, offset + 8)
            require((mbr[offset+4], start, sectors) == (p['type'], p['start_lba'], p['sectors']),
                    'Unexpected partition layout')
        boot = work / 'boot.ext4'
        first = manifest['partitions'][0]
        FORMAT.copy_region(disk, first['start_lba'] * 512, first['sectors'] * 512, boot)
    fit = work / 'kernel.fit'
    subprocess.run(['debugfs', '-R', f'dump /kernel.img {fit.name}', boot], cwd=work, check=True)
    nodes = FORMAT.fdt(fit.read_bytes())
    conf = FORMAT.strings(nodes['/configurations']['default'])[0]
    kernel = FORMAT.strings(nodes['/configurations/' + conf]['kernel'])[0]
    item = nodes['/images/' + kernel]
    require(FORMAT.strings(item['compression']) == ['lzma'], 'Unsupported kernel compression')
    payload = lzma.decompress(item['data'], format=lzma.FORMAT_ALONE)
    require(payload[56:60] == b'ARM\x64', 'FIT payload is not a raw ARM64 kernel')
    pinned = json.loads((ROOT / 'source/verification/inputs.json').read_text())['kernel']
    digest = hashlib.sha256(payload).hexdigest()
    require(digest == pinned['sha256'] and len(payload) == pinned['bytes'], 'FIT kernel differs from pinned input')
    kernel_file = work / 'Image'
    kernel_file.write_bytes(payload)
    # QEMU eMMC requires a power-of-two capacity, like a larger physical chip.
    # The original image occupies the unchanged prefix of this sparse file.
    capacity = 1 << (size - 1).bit_length()
    with storage.open('r+b') as out:
        out.truncate(capacity)
        os.fsync(out.fileno())
    return storage, kernel_file, {'bytes': size, 'readback_sha256': readback,
                                  'virtual_capacity': capacity, 'kernel_sha256': digest}


def serial_test(cmd, log, command, timeout):
    with log.open('wb') as trace, subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                                  stderr=subprocess.STDOUT) as vm, selectors.DefaultSelector() as sel:
        sel.register(vm.stdout, selectors.EVENT_READ)
        data = bytearray()
        sent = False
        entered = time.monotonic()
        deadline = entered + timeout
        try:
            while time.monotonic() < deadline:
                if sel.select(timeout=0.5):
                    block = os.read(vm.stdout.fileno(), 65536)
                    if not block:
                        break
                    trace.write(block)
                    trace.flush()
                    data.extend(block)
                if b'root@OpenWrt' in data and not sent:
                    vm.stdin.write(("printf '\\nFIREFLY_%s\\n' PROBE; " + command +
                                    "; rc=$?; printf '\\nFIREFLY_%s=%s\\n' RESULT \"$rc\"\n").encode())
                    vm.stdin.flush()
                    sent = True
                elif not sent and b'press enter' in data.lower() and time.monotonic() - entered > 2:
                    vm.stdin.write(b'\n')
                    vm.stdin.flush()
                    entered = time.monotonic()
                if re.search(rb'\nFIREFLY_RESULT=\d+\r?\n', data):
                    break
        finally:
            if vm.poll() is None:
                vm.terminate()
            try:
                vm.wait(timeout=5)
            except subprocess.TimeoutExpired:
                vm.kill()
                vm.wait()
    text = data.decode(errors='replace').replace('\r', '')
    probe = re.search(r'\nFIREFLY_PROBE\n(.*?)\nFIREFLY_RESULT=(\d+)\n', text, flags=re.S)
    require(probe and probe[2] == '0', f'Guest check did not pass; see {log}')
    return probe[1]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--qemu', type=Path, required=True)
    p.add_argument('--dtc', default='dtc')
    p.add_argument('--image', type=Path, required=True)
    p.add_argument('--manifest', type=Path, required=True)
    p.add_argument('--work', type=Path, required=True, help='new directory for a virtual eMMC disk and serial logs')
    p.add_argument('--timeout', type=int, default=120)
    args = p.parse_args()
    work = args.work.resolve()
    work.mkdir(mode=0o700)
    manifest = json.loads(args.manifest.read_text())
    disk, kernel, checks = flash(args.image, manifest, work)
    print(f'Virtual eMMC write and SHA256 readback verified: {checks["readback_sha256"]}', flush=True)
    dtb = work / 'firefly-rk3399.dtb'
    subprocess.run([args.dtc, '-I', 'dts', '-O', 'dtb', '-o', dtb, MODEL / 'firefly-rk3399.dts'], check=True)
    cmd = [str(args.qemu.resolve()), '-machine', 'firefly-rk3399,accel=tcg', '-m', '2G',
           '-display', 'none', '-serial', 'stdio', '-monitor', 'none', '-no-reboot',
           '-kernel', str(kernel), '-dtb', str(dtb),
           '-append', f'console=ttyS0,1500000n8 earlycon=uart8250,mmio32,0xff1a0000,1500000 root=PARTUUID={manifest["modes"]["emmc"]["disk_signature"]}-02 rootwait rw',
           '-drive', f'file={str(disk).replace(",", ",,")},if=none,id=firefly,format=raw',
           '-device', 'emmc,drive=firefly']
    start = (f'test "$(uname -r)" = {manifest["kernel"]} && '
             'test "$(grep -c "^processor" /proc/cpuinfo)" = 6 && '
             'test "$(grep -c "^CPU part.*0xd03$" /proc/cpuinfo)" = 4 && '
             'test "$(grep -c "^CPU part.*0xd08$" /proc/cpuinfo)" = 2 && '
             'test "$(cat /sys/block/mmcblk0/device/type)" = MMC && '
             'test -b /dev/mmcblk0p2 && grep -E "^[^ ]+ / ext4 " /proc/mounts && '
             'ubus call system board && nft list tables && '
             'echo emmc-write-ok > /root/.firefly-qemu-probe && sync')
    first = serial_test(cmd, work / 'serial-first.log', start, args.timeout)
    print(first, flush=True)
    second = serial_test(cmd, work / 'serial-reboot.log',
                         'test "$(cat /root/.firefly-qemu-probe)" = emmc-write-ok && '
                         'cat /root/.firefly-qemu-probe', args.timeout)
    print(second, flush=True)
    report = {'model': 'firefly-rk3399', 'boot_method': 'direct kernel from release FIT; emulation DTB',
              'qemu': subprocess.check_output([cmd[0], '--version'], text=True).splitlines()[0],
              'flash': checks, 'guest': first, 'cold_boot_marker': second,
              'post_boot_sha256': FORMAT.digest(disk)}
    (work / 'validation.json').write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__':
    main()
