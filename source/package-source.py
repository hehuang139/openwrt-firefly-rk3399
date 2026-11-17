#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Bundle the board source, frozen rebuild inputs, and documentation."""
import argparse,hashlib,json,re,tarfile
from pathlib import Path
root=Path(__file__).resolve().parent.parent
p=argparse.ArgumentParser(description=__doc__);p.add_argument('output',type=Path);a=p.parse_args()
assert not a.output.exists() and not a.output.is_symlink()
selected=['README.md','INSTALL.md','DEVELOPMENT.md','SOURCE-NOTICE.md','LICENSE','.gitignore','source','downloads']
entries=[]
for name in selected:
    path=root/name
    entries.extend([path] if path.is_file() else [path,*sorted(path.rglob('*'))])
entries=[p for p in entries if '__pycache__' not in p.parts and p.suffix!='.pyc']
for path in entries:
    assert path.name not in ['local-private-key.pem','id_rsa','id_ed25519'],str(path)
    if path.is_file() and path.suffix not in ['.gz','.bz2','.zst','.apk','.dtb','.bin','.itb','.img','.elf']:
        assert not re.search(br'^-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----',path.read_bytes(),re.M),str(path)
    if path.is_symlink():
        assert path.resolve().is_relative_to(root/'source/board/upstream'),str(path)
manifest={'files':[]}
for path in entries:
    rel=path.relative_to(root).as_posix()
    if path.is_symlink():
        manifest['files'].append({'path':rel,'symlink':path.readlink().as_posix()})
    elif path.is_file():
        manifest['files'].append({'path':rel,'bytes':path.stat().st_size,'sha256':hashlib.sha256(path.read_bytes()).hexdigest()})
with tarfile.open(a.output,'w:gz',format=tarfile.PAX_FORMAT) as archive:
    for path in entries:archive.add(path,arcname='firefly-rk3399-openwrt/'+path.relative_to(root).as_posix(),recursive=False)
with tarfile.open(a.output,'r:gz') as archive:
    names=archive.getnames()
    for item in manifest['files']:
        name='firefly-rk3399-openwrt/'+item['path'];assert name in names,name
        member=archive.getmember(name)
        if 'symlink' in item:assert member.issym() and member.linkname==item['symlink']
        else:
            with archive.extractfile(member) as stream:assert hashlib.sha256(stream.read()).hexdigest()==item['sha256'],name
manifest['archive']={'name':a.output.name,'bytes':a.output.stat().st_size,'sha256':hashlib.sha256(a.output.read_bytes()).hexdigest()}
a.output.with_suffix(a.output.suffix+'.manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
print(json.dumps(manifest['archive'],indent=2))
