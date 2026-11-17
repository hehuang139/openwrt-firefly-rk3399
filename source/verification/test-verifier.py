#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Exercise actual image-format parsers with small generated ordinary files."""
import argparse
import gzip
import hashlib
import importlib.util
import json
import lzma
from pathlib import Path
import subprocess
import sys
import tempfile
sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('verifier', HERE / 'verify-image.py')
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
checks = []


def passed(name, function):
    function(); checks.append({'name': name, 'result': 'PASS'})


def rejected(name, function):
    try: function()
    except (ValueError, zlib.error, lzma.LZMAError, OSError, KeyError):
        checks.append({'name': name, 'result': 'PASS'}); return
    raise AssertionError('Bad fixture accepted: ' + name)


import zlib
p = argparse.ArgumentParser()
p.add_argument('--imagebuilder', type=Path, required=True)
p.add_argument('--report', type=Path, required=True)
a = p.parse_args()
with tempfile.TemporaryDirectory(prefix='openwrt-format-fixtures-') as temporary:
    root = Path(temporary)
    raw = bytes(range(256)) * 32
    compressed = root / 'fixture.img.gz'; compressed.write_bytes(gzip.compress(raw, mtime=0))
    pure = m.decode_gzip(compressed, root / 'pure.raw', has_metadata=False)
    assert pure['trailing_bytes'] == 0 and (root / 'pure.raw').read_bytes() == raw
    checks.append({'name':'pure-gzip-install-payload', 'result':'PASS'})
    rejected('missing-fwtool-footer', lambda: m.decode_gzip(compressed, root / 'missing.raw'))
    meta = root / 'meta.json'; meta.write_text(json.dumps({'supported_devices':['firefly,firefly-rk3399'],'version':{'version':'25.12.6'}}))
    m.run([m.tool('fwtool', a.imagebuilder), '-I', meta, compressed])
    rejected('install-payload-rejects-trailing-footer',lambda:m.decode_gzip(compressed,root/'footer.raw',has_metadata=False))
    decoded = m.decode_gzip(compressed, root / 'valid.raw')
    assert (root / 'valid.raw').read_bytes() == raw and decoded['sha256'] == hashlib.sha256(raw).hexdigest()
    checks.append({'name':'gzip-stream-and-appended-fwtool', 'result':'PASS'})
    extract = root / 'meta-extracted.json'; m.run([m.tool('fwtool', a.imagebuilder), '-i', extract, compressed])
    assert json.loads(extract.read_text()) == json.loads(meta.read_text())
    checks.append({'name':'fwtool-independent-metadata-extraction','result':'PASS'})
    truncated = root / 'truncated.gz'; truncated.write_bytes(gzip.compress(raw)[:15])
    rejected('truncated-gzip',lambda:m.decode_gzip(truncated,root/'truncated.raw'))
    bad = root / 'corrupt.gz'; data=bytearray(compressed.read_bytes());data[12]^=0xff;bad.write_bytes(data)
    rejected('corrupt-gzip-crc-or-stream',lambda:m.decode_gzip(bad,root/'corrupt.raw'))
    link = root / 'link.gz';link.symlink_to(compressed)
    rejected('symlink-input',lambda:m.ordinary(link))
    rejected('parent-relative-path',lambda:m.rel('../escape'))
    rejected('absolute-relative-path',lambda:m.rel('/etc/escape'))
    ext4 = root / 'ownership.ext4'
    with ext4.open('wb') as stream: stream.truncate(8388608)
    m.run(['mke2fs', '-q', '-t', 'ext4', '-F', ext4])
    m.run(['debugfs', '-w', '-R', 'write ' + str(root / 'pure.raw') + ' /fixture', ext4])
    passed('ext4-direct-root-inode-ownership', lambda: m.ext4_owners_check(ext4, ['/', '/fixture'], a.imagebuilder, 'fixture'))
    m.run(['debugfs', '-w', '-R', 'set_inode_field /fixture uid 1000', ext4])
    rejected('ext4-wrong-target-file-owner', lambda: m.ext4_owners_check(ext4, ['/fixture'], a.imagebuilder, 'fixture'))
    rejected('ext4-missing-required-inode', lambda: m.ext4_owners_check(ext4, ['/absent'], a.imagebuilder, 'fixture'))
    dts=root/'board.dts';dtb=root/'board.dtb'
    dts.write_text('/dts-v1/; / { model="Firefly-RK3399 Board"; compatible="firefly,firefly-rk3399", "rockchip,rk3399"; };\n')
    m.run(['dtc','-I','dts','-O','dtb','-o',dtb,dts])
    nodes=m.fdt(dtb.read_bytes());assert m.strings(nodes['/']['compatible'])==['firefly,firefly-rk3399','rockchip,rk3399']
    checks.append({'name':'actual-dtc-device-tree-parser','result':'PASS'})
    rejected('bad-fdt-magic',lambda:m.fdt(b'XXXX'+dtb.read_bytes()[4:]))
    kernel=root/'kernel';kernel.write_bytes(b'\0'*56+b'ARM\x64'+b'\0'*8)
    lz=root/'kernel.lzma';lz.write_bytes(lzma.compress(kernel.read_bytes(),format=lzma.FORMAT_ALONE))
    its=root/'image.its';fit=root/'kernel.fit'
    its.write_text('''/dts-v1/; / { description="fixture"; #address-cells=<1>; images {
      kernel-1 { data=/incbin/("'''+str(lz)+'''"); type="kernel"; arch="arm64"; os="linux"; compression="lzma"; load=<0x03200000>; entry=<0x03200000>; hash-1 { algo="sha1"; }; hash-2 { algo="crc32"; }; };
      fdt-1 { data=/incbin/("'''+str(dtb)+'''"); type="flat_dt"; arch="arm64"; compression="none"; hash-1 { algo="sha1"; }; };
    }; configurations { default="config-1"; config-1 { kernel="kernel-1"; fdt="fdt-1"; }; }; };''')
    m.run([m.tool('mkimage',a.imagebuilder),'-f',its,fit])
    inputs={'board':'firefly,firefly-rk3399','kernel':{'bytes':kernel.stat().st_size,'sha256':m.digest(kernel)},'dtb':{'bytes':dtb.stat().st_size,'sha256':m.digest(dtb)}}
    passed('actual-mkimage-fit-and-all-component-hashes',lambda:m.fit_check(fit,inputs))
    wrong=dict(inputs,kernel={'bytes':kernel.stat().st_size,'sha256':'0'*64})
    rejected('wrong-official-kernel-content',lambda:m.fit_check(fit,wrong))
    data=bytearray(fit.read_bytes());offset=data.index(lz.read_bytes());data[offset+10]^=0xff
    corrupt=root/'bad.fit';corrupt.write_bytes(data)
    rejected('corrupt-fit-component-hash',lambda:m.fit_check(corrupt,inputs))
    script=root/'boot.txt';legacy=root/'boot.scr'
    script.write_text('part uuid ${devtype} ${devnum}:2 uuid\nsetenv bootargs "console=ttyS2,1500000 root=PARTUUID=${uuid} rw rootwait"\nload ${devtype} ${devnum}:1 ${kernel_addr_r} kernel.img\nbootm ${kernel_addr_r}\n')
    m.run([m.tool('mkimage',a.imagebuilder),'-A','arm','-O','linux','-T','script','-C','none','-a','0','-e','0','-d',script,legacy])
    passed('actual-mkimage-boot-script-medium-binding',lambda:m.boot_script_check(legacy))
    code=bytearray(legacy.read_bytes());code[-4]^=0xff;(root/'bad.scr').write_bytes(code)
    rejected('boot-script-payload-crc-corruption',lambda:m.boot_script_check(root/'bad.scr'))
report={'result':'PASS','count':len(checks),'checks':checks,'environment':'Generated ordinary files; actual dtc/mkimage/fwtool; no block device'}
a.report.write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report,indent=2))
