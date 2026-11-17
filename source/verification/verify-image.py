#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Independently read OpenWrt Firefly images; never mount or access block devices."""
import argparse
import hashlib
import json
import lzma
from pathlib import Path
import re
import shutil
import stat
import struct
import subprocess
import tempfile
import zlib

ROOT = Path(__file__).resolve().parents[2]
checks = []


def check(name, value, detail):
    checks.append({'name': name, 'pass': bool(value), 'detail': detail})
    if not value: raise ValueError(name + ': ' + str(detail))


def ordinary(path):
    if path.is_symlink() or not stat.S_ISREG(path.stat().st_mode):
        raise ValueError('Expected ordinary input: ' + str(path))


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(8388608), b''): h.update(block)
    return h.hexdigest()


def pinned(path, item, name):
    ordinary(path)
    actual = {'bytes': path.stat().st_size, 'sha256': digest(path)}
    check(name, actual['bytes'] == item['bytes'] and actual['sha256'] == item['sha256'], actual)
    return actual


def run(arguments):
    return subprocess.check_output([str(x) for x in arguments], stderr=subprocess.STDOUT)


def rel(value):
    path = Path(value)
    if path.is_absolute() or '..' in path.parts or not value:
        raise ValueError('Invalid relative path: ' + str(value))
    return path


def tool(name, ib):
    if ib:
        candidate = ib / 'staging_dir/host/bin' / name
        if candidate.is_file(): return candidate
    result = shutil.which(name)
    if not result: raise ValueError('Missing verification tool: ' + name)
    return Path(result)


def decode_gzip(source, target, has_metadata=True):
    """One gzip stream, preserving exactly the mode's declared footer policy."""
    ordinary(source)
    decoder, h, count, trailing = zlib.decompressobj(16 + zlib.MAX_WBITS), hashlib.sha256(), 0, bytearray()
    with source.open('rb') as stream, target.open('xb') as output:
        while True:
            block = stream.read(1048576)
            if not block: break
            if decoder.eof:
                trailing.extend(block)
            else:
                data = decoder.decompress(block)
                output.write(data); h.update(data); count += len(data)
                if decoder.eof: trailing.extend(decoder.unused_data)
        if not decoder.eof: raise ValueError('Truncated gzip stream')
    if has_metadata and not trailing: raise ValueError('Missing appended fwtool metadata')
    if not has_metadata and trailing: raise ValueError('Pure gzip image has unexpected trailing content')
    if len(trailing) > 1048576: raise ValueError('Unexpectedly large appended metadata')
    return {'bytes': count, 'sha256': h.hexdigest(), 'trailing_bytes': len(trailing)}


def fdt(data):
    """Minimal independent FDT parser returning exact property bytes per node."""
    if len(data) < 40: raise ValueError('Truncated FDT header')
    header = struct.unpack('>10I', data[:40])
    magic, total, structure, strings = header[:4]
    if magic != 0xd00dfeed or total > len(data) or total < 40:
        raise ValueError('Invalid FDT header')
    string_end = strings + header[8]
    end = structure + header[9]
    if not (0 <= strings <= string_end <= total and 0 <= structure <= end <= total):
        raise ValueError('Invalid FDT block offsets')
    nodes, stack, position = {}, [], structure
    while position < end:
        token = struct.unpack_from('>I', data, position)[0]; position += 4
        if token == 1:
            name_end = data.index(b'\0', position, end)
            name = data[position:name_end].decode(); position = (name_end + 4) & ~3
            stack.append(name)
            path = '/' + '/'.join(n for n in stack if n)
            if path in nodes: raise ValueError('Duplicate FDT node')
            nodes[path] = {}
        elif token == 2:
            if not stack: raise ValueError('Unbalanced FDT node')
            stack.pop()
        elif token == 3:
            if position + 8 > end or not stack: raise ValueError('Invalid FDT property')
            length, nameoff = struct.unpack_from('>II', data, position); position += 8
            start = strings + nameoff
            if not strings <= start < string_end or position + length > end:
                raise ValueError('Invalid FDT property range')
            name_end = data.index(b'\0', start, string_end)
            name = data[start:name_end].decode()
            path = '/' + '/'.join(n for n in stack if n)
            if name in nodes[path]: raise ValueError('Duplicate FDT property')
            nodes[path][name] = data[position:position + length]; position = (position + length + 3) & ~3
        elif token == 4: pass
        elif token == 9:
            if stack: raise ValueError('Unbalanced FDT tree')
            return nodes
        else: raise ValueError('Unknown FDT token')
    raise ValueError('Missing FDT end token')


def strings(value): return value.rstrip(b'\0').decode().split('\0')


def fit_check(path, inputs):
    nodes = fdt(path.read_bytes())
    configs = nodes['/configurations']
    default = strings(configs['default'])[0]
    config = nodes['/configurations/' + default]
    kernel_name, dtb_name = strings(config['kernel'])[0], strings(config['fdt'])[0]
    result = {}
    for name, role in [(kernel_name, 'kernel'), (dtb_name, 'dtb')]:
        node_path = '/images/' + name
        node = nodes[node_path]
        check('fit-' + role + '-type', strings(node['type']) == ['kernel' if role == 'kernel' else 'flat_dt'], strings(node['type']))
        check('fit-' + role + '-arch', strings(node['arch']) == ['arm64'], strings(node['arch']))
        payload = node['data']
        hashes = [(p, n) for p, n in nodes.items() if p.startswith(node_path + '/hash')]
        algorithms = []
        for hash_path, item in hashes:
            algorithm = strings(item['algo'])[0]; algorithms.append(algorithm)
            if algorithm == 'sha1': actual = hashlib.sha1(payload).digest()
            elif algorithm == 'sha256': actual = hashlib.sha256(payload).digest()
            elif algorithm == 'crc32': actual = struct.pack('>I', zlib.crc32(payload))
            else: raise ValueError('Unsupported FIT hash algorithm: ' + algorithm)
            check('fit-hash:' + hash_path, actual == item['value'], algorithm)
        check('fit-' + role + '-hash-present', bool(algorithms), algorithms)
        compression = strings(node['compression'])[0]
        if role == 'kernel':
            check('fit-kernel-compression', compression == 'lzma', compression)
            payload = lzma.decompress(payload, format=lzma.FORMAT_ALONE)
            check('fit-kernel-arm64-image', payload[56:60] == b'ARM\x64', payload[56:60].hex())
            load = struct.unpack('>I', node['load'])[0]
            check('fit-rk3399-load-address', load == 0x03200000 and node['entry'] == node['load'], hex(load))
        else:
            check('fit-dtb-uncompressed', compression == 'none', compression)
            dtb_nodes = fdt(payload)
            compatible = strings(dtb_nodes['/']['compatible'])
            check('dtb-original-firefly-board', inputs['board'] in compatible and 'rockchip,rk3399' in compatible, compatible)
            check('dtb-original-model', 'Firefly' in strings(dtb_nodes['/']['model'])[0], strings(dtb_nodes['/']['model']))
        actual = {'bytes': len(payload), 'sha256': hashlib.sha256(payload).hexdigest()}
        check('fit-' + role + '-fixed-input', actual['bytes'] == inputs[role]['bytes'] and actual['sha256'] == inputs[role]['sha256'], actual)
        result[role] = actual
    return result


def boot_script_check(path):
    data = path.read_bytes()
    if len(data) < 72: raise ValueError('Truncated legacy boot script')
    magic, hcrc, timestamp, size, load, entry, dcrc = struct.unpack('>7I', data[:28])
    header = bytearray(data[:64]); header[4:8] = b'\0' * 4
    check('bootscript-legacy-header', magic == 0x27051956 and zlib.crc32(header) == hcrc and data[30] == 6,
          {'magic': hex(magic), 'type': data[30]})
    payload = data[64:]
    check('bootscript-length-crc', len(payload) == size and zlib.crc32(payload) == dcrc, size)
    code = payload[8:].decode()
    check('bootscript-binds-root-to-boot-medium', 'part uuid ${devtype} ${devnum}:2 uuid' in code and 'root=PARTUUID=${uuid}' in code, code)
    check('bootscript-serial-console', '1500000' in code and 'bootm' in code and 'kernel.img' in code, code)


def copy_region(stream, offset, size, target):
    with target.open('xb') as output:
        stream.seek(offset)
        while size:
            block = stream.read(min(8388608, size))
            if not block: raise ValueError('Short raw image region')
            output.write(block); size -= len(block)


def ext4_owners_check(partition, paths, ib, prefix):
    """Read inode ownership directly; extraction can hide incorrect target IDs."""
    metadata = {}
    for path in paths:
        text = run([tool('debugfs', ib), '-R', 'stat ' + path, partition]).decode(errors='replace')
        found = re.search(r'User:\s+(\d+)\s+Group:\s+(\d+)', text)
        check(prefix + '-inode-present:' + path, found is not None, text[-1200:])
        owner = [int(found[1]), int(found[2])]
        check(prefix + '-root-owned:' + path, owner == [0, 0], owner)
        metadata[path] = {'uid': owner[0], 'gid': owner[1]}
    return metadata


def verify_rootfs(partition, inputs, scratch, ib):
    root = scratch / 'rootfs'
    kind = inputs['rootfs_type']
    if kind == 'ext4':
        with partition.open('rb') as stream:
            stream.seek(1080); magic = stream.read(2)
        check('rootfs-ext4-magic', magic == b'\x53\xef', magic.hex())
        result = subprocess.run([str(tool('e2fsck', ib)), '-fn', str(partition)], stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        check('rootfs-ext4-readonly-fsck', result.returncode == 0, result.stdout.decode(errors='replace')[-2200:])
        ext4_owners_check(partition, ['/', '/etc/passwd', '/etc/shadow', '/bin/busybox', '/usr/sbin/firefly-install-emmc'], ib, 'rootfs')
        root.mkdir()
        result = subprocess.run([str(tool('debugfs', ib)), '-R', 'rdump / ' + str(root), str(partition)], stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        check('rootfs-complete-readonly-extraction', result.returncode == 0 and (root / 'etc/openwrt_release').is_file(), result.stdout.decode(errors='replace')[-2200:])
    elif kind == 'squashfs':
        with partition.open('rb') as stream: magic = stream.read(4)
        check('rootfs-squashfs', magic == b'hsqs', magic.hex())
        result = subprocess.run([str(tool('unsquashfs4', ib)), '-processors', '4', '-no-progress', '-d', str(root), str(partition)],
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        check('rootfs-full-decompression', result.returncode == 0, result.stdout.decode(errors='replace')[-2200:])
    else: raise ValueError('Unsupported rootfs type: ' + kind)
    release = (root / 'etc/openwrt_release').read_text()
    for key, expected in [('DISTRIB_RELEASE', inputs['version']), ('DISTRIB_REVISION', inputs['revision']), ('DISTRIB_TARGET', inputs['target'])]:
        check('release-' + key, re.search(r'^' + key + r"=['\"]?" + re.escape(expected) + r"['\"]?$", release, re.M) is not None, expected)
    for item in inputs['files']:
        path = root / rel(item['path'])
        if path.is_symlink():
            check('rootfs-symlink:' + item['path'], item.get('symlink') == str(path.readlink()), str(path.readlink()))
        else: pinned(path, item, 'rootfs-file:' + item['path'])
    repos = (root / 'etc/apk/repositories.d/distfeeds.list')
    if not repos.exists(): repos = root / 'etc/apk/repositories'
    text = repos.read_text()
    check('apk-fixed-release-repositories', inputs['version'] in text and '/snapshots/' not in text, text)
    keys = list((root / 'etc/apk/keys').glob('*'))
    check('apk-repository-keys', bool(keys), [p.name for p in keys])
    database = (root / 'lib/apk/db/installed').read_text()
    records = {}
    for entry in database.split('\n\n'):
        fields = {}
        for line in entry.splitlines():
            if len(line) >= 2 and line[1] == ':' and line[0] in ['P', 'V', 'A', 'D']:
                if line[0] in fields: raise ValueError('Duplicate package database field')
                fields[line[0]] = line[2:]
        if 'P' in fields:
            if fields['P'] in records: raise ValueError('Duplicate package name')
            records[fields['P']] = fields
    packages = set(records)
    missing = sorted(set(inputs['required_packages']) - packages)
    check('required-packages-present', not missing, {'installed_count': len(packages), 'missing': missing})
    kernel_package = inputs['kernel_version'] + '~' + inputs['kernel_vermagic'] + '-r1'
    check('kernel-apk-fixed-abi', records.get('kernel', {}).get('V') == kernel_package,
          records.get('kernel', {}))
    invalid_arch = [name for name, item in records.items() if item.get('A') not in ['aarch64_generic', 'noarch']]
    check('all-packages-correct-architecture', not invalid_arch, invalid_arch)
    invalid_kmods = [name for name, item in records.items() if name.startswith('kmod-')
                     and ('kernel=' + kernel_package) not in item.get('D', '').split()]
    check('all-kmod-package-abi-dependencies', not invalid_kmods, invalid_kmods)
    modules = sorted((root / 'lib/modules').rglob('*.ko'))
    check('kernel-modules-present', bool(modules), len(modules))
    bad = []
    for path in modules:
        data = path.read_bytes()
        if data[:4] != b'\x7fELF' or struct.unpack_from('<H', data, 18)[0] != 183:
            bad.append(str(path.relative_to(root)) + ': not ARM64 ELF'); continue
        found = re.search(rb'vermagic=([^\0]+)', data)
        if not found or not found[1].startswith((inputs['kernel_version'] + ' ').encode()):
            bad.append(str(path.relative_to(root)) + ': wrong vermagic')
    check('all-kernel-modules-arm64-matching-version', not bad, {'count': len(modules), 'bad': bad})
    for name in ['bin/busybox', 'sbin/uci', 'usr/sbin/uhttpd', 'usr/sbin/dropbear', 'usr/sbin/dnsmasq']:
        path = root / name
        if not path.exists():
            alternatives = [p for p in root.rglob(Path(name).name) if p.is_file()]
            check('program-present:' + name, bool(alternatives), name)
            path = alternatives[0]
        data = path.read_bytes()[:64]
        check('program-aarch64:' + name, data[:4] == b'\x7fELF' and data[4:6] == b'\x02\x01' and struct.unpack_from('<H', data, 18)[0] == 183, str(path.relative_to(root)))
    return {'packages': len(packages), 'kernel_modules': len(modules)}


def main(args):
    ordinary(args.image); ordinary(args.inputs)
    inputs = json.loads(args.inputs.read_text())
    mode = inputs['modes'][args.mode]
    scratch_parent = args.scratch
    scratch_parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='verify-' + args.mode + '-', dir=scratch_parent) as temporary:
        scratch = Path(temporary)
        raw = scratch / 'image.raw'
        decoded = decode_gzip(args.image, raw, mode['has_metadata'])
        check('gzip-complete-stream-and-declared-footer', bool(decoded['trailing_bytes']) == mode['has_metadata'], decoded)
        metadata = None
        if mode['has_metadata']:
            metadata_path = scratch / 'metadata.json'
            run([tool('fwtool', args.imagebuilder), '-i', metadata_path, args.image])
            metadata = json.loads(metadata_path.read_text())
            check('metadata-supported-board', metadata.get('supported_devices') == [inputs['board']], metadata.get('supported_devices'))
            for key, expected in [('version', inputs['version']), ('revision', inputs['revision']), ('target', inputs['target'])]:
                check('metadata-' + key, metadata['version'].get(key) == expected, metadata['version'].get(key))
        with raw.open('rb') as stream:
            mbr = stream.read(512)
            check('mbr-signature', mbr[510:512] == b'\x55\xaa', mbr[510:512].hex())
            actual_signature = f'{struct.unpack_from("<I", mbr, 440)[0]:08x}'
            check('mbr-disk-signature', actual_signature == mode['disk_signature'].lower(), actual_signature)
            parts = []
            for index in range(4):
                entry = mbr[446 + 16 * index:462 + 16 * index]
                kind, start, count = entry[4], *struct.unpack_from('<II', entry, 8)
                if index < 2: parts.append({'type': kind, 'start_lba': start, 'sectors': count})
                else: check('mbr-unused-partition-' + str(index), not any(entry), entry.hex())
            check('mbr-fixed-layout', parts == mode['partitions'], parts)
            check('image-exact-partition-length', raw.stat().st_size == (parts[1]['start_lba'] + parts[1]['sectors']) * 512, raw.stat().st_size)
            bootloader = ROOT / rel(mode['bootloader']['path'])
            pinned(bootloader, mode['bootloader'], 'bootloader-source-pin')
            stream.seek(32768)
            actual = stream.read(mode['bootloader']['bytes'])
            check('raw-ddr3-bootloader', hashlib.sha256(actual).hexdigest() == mode['bootloader']['sha256'], len(actual))
            check('bootloader-before-partition', 32768 + len(actual) <= parts[0]['start_lba'] * 512, parts[0]['start_lba'])
            boot = scratch / 'boot.ext4'
            copy_region(stream, parts[0]['start_lba'] * 512, parts[0]['sectors'] * 512, boot)
            rootfs = scratch / 'root.squashfs'
            copy_region(stream, parts[1]['start_lba'] * 512, parts[1]['sectors'] * 512, rootfs)
        fsck = subprocess.run([str(tool('e2fsck', args.imagebuilder)), '-fn', str(boot)], stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        check('boot-ext4-readonly-fsck', fsck.returncode == 0, fsck.stdout.decode(errors='replace')[-2000:])
        ext4_owners_check(boot, ['/kernel.img', '/boot.scr'], args.imagebuilder, 'boot')
        bootfiles = {}
        for name, key in [('kernel.img', 'fit'), ('boot.scr', 'boot_script')]:
            path = scratch / name
            run([tool('debugfs', args.imagebuilder), '-R', 'dump /' + name + ' ' + str(path), boot])
            pinned(path, mode[key], 'boot-file:' + name)
            bootfiles[key] = path
        boot_script_check(bootfiles['boot_script'])
        embedded = fit_check(bootfiles['fit'], inputs)
        root_result = verify_rootfs(rootfs, inputs, scratch, args.imagebuilder)
    return {'image': str(args.image), 'image_sha256': digest(args.image), 'image_bytes': args.image.stat().st_size,
            'mode': args.mode, 'inputs_sha256': digest(args.inputs), 'decompressed': decoded, 'fit': embedded,
            'metadata': metadata, 'rootfs': root_result}


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--image', type=Path, required=True)
    p.add_argument('--mode', choices=['sd', 'emmc', 'sysupgrade', 'sd-sysupgrade', 'emmc-sysupgrade'], required=True)
    p.add_argument('--inputs', type=Path, default=Path(__file__).with_name('inputs.json'))
    p.add_argument('--imagebuilder', type=Path)
    p.add_argument('--scratch', type=Path, required=True)
    p.add_argument('--report', type=Path, required=True)
    a = p.parse_args()
    report = {}
    try: report.update(main(a))
    except Exception as error: report['error'] = type(error).__name__ + ': ' + str(error)
    report.update({'result': 'FAIL' if 'error' in report else 'PASS', 'checks': checks,
                   'passed': sum(item['pass'] for item in checks), 'total': len(checks)})
    a.report.parent.mkdir(parents=True, exist_ok=True)
    a.report.write_text(json.dumps(report, indent=2) + '\n')
    print(f"Image verification: {report['passed']}/{report['total']} {report['result']}")
    if report.get('error'): print(report['error']); raise SystemExit(1)
