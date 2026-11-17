#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Install the matched OpenWrt Firefly image from TF to onboard eMMC.

Default: inspect and verify only. --write requires either --backup-dir or
--no-backup. Target identification is fixed and cannot be overridden by CLI.
"""
import argparse
import datetime
import fcntl
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import struct
import subprocess
import sys
import time

TARGET = Path('/dev/mmcblk2')
SYS = Path('/sys/class/block/mmcblk2')
IMAGE_BYTES = 637534208
MIN_EMMC_BYTES = 7 * 1024**3  # Covers real user capacity of nominal 8 GB devices.
TAIL_BYTES = 1024**2
BLOCK = 4 * 1024**2
BLKFLSBUF = 0x1261
LOGDIR = Path('/root/emmc-install-logs')


def require(ok, message):
    if not ok:
        raise ValueError(message)


def progress(label, count, total, state):
    now = time.monotonic()
    if now - state[0] >= 5 or count == total:
        print(f'{label}: {count // 1048576}/{total // 1048576} MiB', flush=True)
        state[0] = now


def unescape(value):
    return re.sub(r'\\([0-7]{3})', lambda m: chr(int(m[1], 8)), value)


def mounts(text=None):
    rows = []
    for line in (Path('/proc/self/mountinfo').read_text() if text is None else text).splitlines():
        fields = line.split()
        split = fields.index('-')
        rows.append({'device': fields[2], 'point': unescape(fields[4]),
                     'type': fields[split + 1], 'source': unescape(fields[split + 2])})
    return rows


def dev_sys_path(major_minor):
    return str(Path('/sys/dev/block', major_minor).resolve(strict=True))


def target_mounts(rows):
    found = []
    for row in rows:
        # FUSE mounts may have virtual major:minor but retain their block source.
        if re.fullmatch(r'/dev/mmcblk2(?:p[0-9]+)?', row['source']):
            found.append(row)
            continue
        source = Path(row['source'])
        try:
            attributes = source.stat()
            if stat.S_ISBLK(attributes.st_mode):
                device = attributes.st_rdev
                resolved_source = dev_sys_path(f'{os.major(device)}:{os.minor(device)}')
                if 'mmcblk2' in Path(resolved_source).parts:
                    found.append(row)
                    continue
        except FileNotFoundError:
            pass
        try:
            resolved = dev_sys_path(row['device'])
        except FileNotFoundError:
            continue  # Virtual filesystems such as overlay have no block node.
        if 'mmcblk2' in Path(resolved).parts:
            found.append(row)
    return found


def identity_snapshot():
    rows = mounts()
    info = {
        'compatible': Path('/proc/device-tree/compatible').read_bytes().split(b'\0'),
        'model': Path('/proc/device-tree/model').read_bytes().rstrip(b'\0').decode(),
        'path': str(SYS.resolve(strict=True)),
        'type': (SYS / 'device/type').read_text().strip(),
        'cid': (SYS / 'device/cid').read_text().strip(),
        'name': (SYS / 'device/name').read_text().strip(),
        'removable': (SYS / 'removable').read_text().strip(),
        'ro': (SYS / 'ro').read_text().strip(),
        'sector': int((SYS / 'queue/logical_block_size').read_text()),
        'bytes': int((SYS / 'size').read_text()) * 512,
        'dev': (SYS / 'dev').read_text().strip(),
        'root': [r for r in rows if r['point'] == '/'],
        'target_mounts': target_mounts(rows),
    }
    if len(info['root']) == 1:
        info['root_sys'] = dev_sys_path(info['root'][0]['device'])
    return info


def validate_identity(info):
    require(b'firefly,firefly-rk3399' in info['compatible'] and
            b'rockchip,rk3399' in info['compatible'], 'This installer is only for original Firefly-RK3399.')
    require(info['model'] == 'Firefly-RK3399 Board', 'Unexpected device-tree model.')
    require('fe330000' in info['path'] and '/mmcblk2' in info['path'] and
            info['type'] == 'MMC' and info['removable'] == '0',
            'mmcblk2 is not the expected non-removable fe330000 eMMC.')
    require(info['ro'] == '0' and info['sector'] == 512, 'eMMC must be writable with 512-byte sectors.')
    require(re.fullmatch(r'[0-9a-fA-F]{32}', info['cid']), 'Invalid eMMC CID.')
    require(info['bytes'] >= MIN_EMMC_BYTES and info['bytes'] - TAIL_BYTES > IMAGE_BYTES,
            'eMMC is too small; use nominal 8 GB or larger.')
    require(len(info['root']) == 1 and 'fe320000' in info.get('root_sys', '') and
            info.get('root_sys', '').endswith('/mmcblk1/mmcblk1p2') and info['root'][0]['type'] == 'ext4',
            'The running root filesystem must be this OpenWrt TF card mmcblk1p2 (ext4).')
    require(not info['target_mounts'], 'The eMMC is mounted; unmount all eMMC partitions before installation.')
    for line in Path('/proc/swaps').read_text().splitlines()[1:]:
        swap = Path(unescape(line.split()[0]))
        require(not str(swap).startswith('/dev/mmcblk2'), 'eMMC is being used as swap.')
        if swap.exists():
            attributes = swap.stat()
            device = attributes.st_rdev if stat.S_ISBLK(attributes.st_mode) else attributes.st_dev
            try:
                require('mmcblk2' not in Path(dev_sys_path(f'{os.major(device)}:{os.minor(device)}')).parts,
                        'A swap file is stored on eMMC.')
            except FileNotFoundError:
                pass
    for holder_dir in [SYS/'holders', *SYS.glob('mmcblk2p*/holders')]:
        require(not any(holder_dir.iterdir()), f'eMMC has active block holders: {holder_dir}')


def regular(path):
    require(path.is_file() and not path.is_symlink() and stat.S_ISREG(path.stat().st_mode),
            f'Expected a regular file, not a device or symlink: {path}')


def validate_manifest(manifest, image):
    require(manifest.get('board') == 'firefly-rk3399' and manifest.get('medium') == 'emmc',
            'Manifest is not the Firefly RK3399 eMMC release.')
    for key in ['image', 'compressed']:
        item = manifest[key]
        require(isinstance(item['bytes'], int) and not isinstance(item['bytes'], bool) and item['bytes'] > 0,
                'Invalid manifest size.')
        require(re.fullmatch('[0-9a-f]{64}', item['sha256']), 'Invalid manifest SHA256.')
        require(Path(item['name']).name == item['name'], 'Manifest filename must be a basename.')
    require(manifest['image']['bytes'] == IMAGE_BYTES, 'Unexpected raw image size.')
    require(image.name == manifest['compressed']['name'] and image.stat().st_size == manifest['compressed']['bytes'],
            'Compressed filename or size differs from manifest.')


def hash_stream(stream, count=None, label=None):
    h, size, clock = hashlib.sha256(), 0, [0.0]
    while count is None or size < count:
        data = stream.read(BLOCK if count is None else min(BLOCK, count - size))
        if not data:
            break
        h.update(data)
        size += len(data)
        if label:
            progress(label, size, count, clock)
    if count is not None:
        require(size == count, f'Short read: {size} of {count} bytes.')
    return h.hexdigest(), size


def verify_source(image, manifest):
    with image.open('rb') as f:
        compressed, _ = hash_stream(f, manifest['compressed']['bytes'], 'Compressed SHA256')
    require(compressed == manifest['compressed']['sha256'], 'Compressed image SHA256 mismatch.')
    with gzip.open(image, 'rb') as f:
        header = f.read(512)
        require(len(header) == 512 and header[510:] == b'\x55\xaa', 'Image MBR is invalid.')
        for i, expected in enumerate([(131, 65536, 65536), (131, 196608, 1048576)]):
            row = struct.unpack('<B3sB3sII', header[446+i*16:462+i*16])
            require((row[2], row[4], row[5]) == expected, 'Image partition layout differs.')
    with gzip.open(image, 'rb') as f:
        raw, size = hash_stream(f, IMAGE_BYTES, 'Raw image SHA256')
        require(f.read(1) == b'', 'Image is larger than manifest.')
    require(raw == manifest['image']['sha256'] and size == IMAGE_BYTES, 'Raw image SHA256 mismatch.')


def write_all(fd, data):
    view = memoryview(data)
    while view:
        n = os.write(fd, view)
        require(n > 0, 'Device write made no progress.')
        view = view[n:]


def write_payload(fd, image, manifest, capacity):
    os.lseek(fd, 0, os.SEEK_SET)
    h, count, clock = hashlib.sha256(), 0, [0.0]
    with gzip.open(image, 'rb') as src:
        while count < IMAGE_BYTES:
            data = src.read(min(BLOCK, IMAGE_BYTES-count))
            require(data, 'Truncated image during write.')
            h.update(data)
            write_all(fd, data)
            count += len(data)
            progress('Writing eMMC', count, IMAGE_BYTES, clock)
        require(src.read(1) == b'', 'Unexpected excess image data.')
    require(h.hexdigest() == manifest['image']['sha256'], 'Image changed during write.')
    os.lseek(fd, capacity - TAIL_BYTES, os.SEEK_SET)
    write_all(fd, bytes(TAIL_BYTES))
    os.fsync(fd)


def readback(fd, manifest, capacity, flush=True):
    if flush:
        fcntl.ioctl(fd, BLKFLSBUF, 0)  # Read device data after flushing cached blocks.
    os.lseek(fd, 0, os.SEEK_SET)
    with os.fdopen(os.dup(fd), 'rb', closefd=True) as stream:
        digest, size = hash_stream(stream, IMAGE_BYTES, 'Readback SHA256')
    require(digest == manifest['image']['sha256'], 'Written eMMC data failed full SHA256 readback.')
    require(os.pread(fd, TAIL_BYTES, capacity-TAIL_BYTES) == bytes(TAIL_BYTES), 'Old GPT tail was not cleared.')
    return digest, size


def backup(fd, directory, info):
    directory.mkdir(parents=True, exist_ok=True)
    require(directory.is_dir() and not directory.is_symlink(), 'Backup directory cannot be a symlink.')
    fs = os.statvfs(directory)
    require(fs.f_bavail*fs.f_frsize >= info['bytes'] + 64*1024**2, 'Insufficient space for full eMMC backup.')
    matching = [r for r in mounts() if directory.resolve().is_relative_to(Path(r['point']))]
    mount = max(matching, key=lambda r:len(r['point']))
    require(mount['type'] not in ['vfat', 'msdos'], 'Full backup requires a filesystem supporting files above 4 GB.')
    require('mmcblk2' not in dev_sys_path(mount['device']), 'Backup cannot be saved on the target eMMC.')
    name = 'firefly-emmc-before-' + datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ') + '.img'
    path = directory / name
    metadata = path.with_suffix('.json')
    require(not path.exists() and not path.is_symlink() and not metadata.exists() and not metadata.is_symlink(),
            'Backup filename or metadata already exists.')
    h, count, clock = hashlib.sha256(), 0, [0.0]
    os.lseek(fd, 0, os.SEEK_SET)
    with path.open('xb') as out:
        while count < info['bytes']:
            data = os.read(fd, min(BLOCK, info['bytes']-count))
            require(data, 'Short eMMC read while backing up.')
            out.write(data)
            h.update(data)
            count += len(data)
            progress('Backing up original eMMC', count, info['bytes'], clock)
        out.flush()
        os.fsync(out.fileno())
    with path.open('rb') as f:
        stored, size = hash_stream(f, info['bytes'], 'Verify backup')
    require(stored == h.hexdigest(), 'Backup file verification failed.')
    record = {'path':str(path), 'bytes':size, 'sha256':stored, 'cid':info['cid']}
    with metadata.open('x') as f:
        f.write(json.dumps(record, indent=2)+'\n')
        f.flush()
        os.fsync(f.fileno())
    return record


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--image', type=Path, default=Path(__file__).resolve().parent/'openwrt-25.12.6-firefly-rk3399-emmc-test1.img.gz')
    p.add_argument('--manifest', type=Path, default=Path(__file__).resolve().parent/'manifest.json')
    p.add_argument('--write', action='store_true', help='Overwrite onboard eMMC after validation.')
    group = p.add_mutually_exclusive_group()
    group.add_argument('--backup-dir', type=Path, help='Save and verify full original user-area backup before writing.')
    group.add_argument('--no-backup', action='store_true', help='Explicitly overwrite without saving original data.')
    a = p.parse_args()
    if a.write and not (a.backup_dir or a.no_backup):
        p.error('--write requires --backup-dir or --no-backup')
    require(os.geteuid() == 0, 'Run as root in Firefly OpenWrt booted from TF.')
    regular(a.image)
    regular(a.manifest)
    manifest = json.loads(a.manifest.read_text())
    validate_manifest(manifest, a.image)
    info = identity_snapshot()
    validate_identity(info)
    require(stat.S_ISBLK(TARGET.lstat().st_mode), 'Target is not the expected block device.')
    require(f'{os.major(TARGET.stat().st_rdev)}:{os.minor(TARGET.stat().st_rdev)}' == info['dev'], 'Device identity changed.')
    source_device = f'{os.major(a.image.stat().st_dev)}:{os.minor(a.image.stat().st_dev)}'
    require('mmcblk2' not in dev_sys_path(source_device), 'Image is stored on the target eMMC.')
    print(f"Board: {info['model']}\nTarget: {TARGET}  {info['name']}  {info['bytes']} bytes\nCID: {info['cid']}", flush=True)
    print('Writing will erase the existing onboard system and data.', flush=True)
    verify_source(a.image, manifest)
    if not a.write:
        print('CHECK PASS: no eMMC bytes changed. Add --write and a backup choice to install.', flush=True)
        return
    for row in sorted(info['target_mounts'], key=lambda r:len(r['point']), reverse=True):
        subprocess.run(['umount', '--', row['point']], check=True)
    require(not target_mounts(mounts()), 'eMMC partitions are still mounted.')
    # O_EXCL on a block device rejects mounted filesystems and prevents new mounts.
    fd = os.open(TARGET, os.O_RDWR | os.O_EXCL | os.O_NOFOLLOW)
    report = {'status':'started', 'target':str(TARGET), 'cid':info['cid'], 'capacity':info['bytes'],
              'image':manifest['image'], 'backup':None, 'timestamp':datetime.datetime.now(datetime.timezone.utc).isoformat()}
    LOGDIR.mkdir(parents=True, exist_ok=True)
    log = LOGDIR / ('emmc-install-' + datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ') + '.json')
    try:
        opened = os.fstat(fd)
        require(stat.S_ISBLK(opened.st_mode) and opened.st_rdev == TARGET.stat().st_rdev, 'Target changed during open.')
        again = identity_snapshot()
        validate_identity(again)
        require(again['cid'] == info['cid'] and again['bytes'] == info['bytes'], 'eMMC identity changed.')
        if a.backup_dir:
            report['backup'] = backup(fd, a.backup_dir, info)
        else:
            report['backup'] = 'explicitly skipped with --no-backup'
        write_payload(fd, a.image, manifest, info['bytes'])
        digest, count = readback(fd, manifest, info['bytes'])
        report.update(status='PASS', readback_sha256=digest, readback_bytes=count, tail_zero_bytes=TAIL_BYTES)
    except Exception as error:
        report.update(status='FAIL', error=str(error))
        raise
    finally:
        os.close(fd)
        with log.open('x') as f:
            json.dump(report, f, indent=2)
            f.write('\n')
            f.flush()
            os.fsync(f.fileno())
    print(f'INSTALL PASS: full readback verified. Report: {log}\nRun poweroff, wait until shutdown, disconnect power, remove the TF card, then power on.', flush=True)


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, KeyError, TypeError, EOFError, subprocess.CalledProcessError) as error:
        print(f'STOP: {error}\nInstallation did not complete. Keep the TF installer and inspect the error before retrying.', file=sys.stderr)
        raise SystemExit(1)
