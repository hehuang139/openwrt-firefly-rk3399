#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Build the actual pinned OpenWrt UCI CLI for host-only configuration tests."""
import argparse,hashlib,subprocess,tarfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]
SOURCE=ROOT/'source/network/upstream/uci-66127cd7.tar.gz'
p=argparse.ArgumentParser();p.add_argument('output',type=Path);a=p.parse_args()
if a.output.exists():raise ValueError('Use new output directory')
a.output.mkdir(parents=True)
with tarfile.open(SOURCE,'r:gz') as archive:
    for member in archive.getmembers():
        if not member.isfile():continue
        parts=Path(member.name).parts
        if len(parts)!=2:continue
        if '..' in parts:raise ValueError('Unsafe member')
        target=a.output/parts[1];target.write_bytes(archive.extractfile(member).read())
(a.output/'uci_config.h').touch()
files=['libuci.c','file.c','util.c','delta.c','parse.c','cli.c']
# CLI does not use libuci's optional libubox blob-conversion interface.
subprocess.run(['gcc','-Os','-std=gnu99','-DUCI_PREFIX="/usr"','-I'+str(a.output),*[str(a.output/x) for x in files],'-o',str(a.output/'uci')],check=True)
print(a.output/'uci')
