#!/usr/bin/env python3
"""Fetch the exact Linux stable DTS include closure needed by Firefly."""
import hashlib,json,pathlib,re,urllib.request,os
BASE='https://raw.githubusercontent.com/gregkh/linux/v6.12.112/'
ROOT=pathlib.Path(__file__).resolve().parent/'upstream'
queue=['arch/arm64/boot/dts/rockchip/rk3399-firefly.dts','COPYING','LICENSES/preferred/GPL-2.0','LICENSES/preferred/MIT']
seen={}
opener=urllib.request.build_opener(urllib.request.ProxyHandler({'https':'http://127.0.0.1:7890','http':'http://127.0.0.1:7890'}))
while queue:
    name=queue.pop(0)
    if name in seen:continue
    p=ROOT/name;p.parent.mkdir(parents=True,exist_ok=True)
    data=opener.open(BASE+name,timeout=60).read()
    if data.startswith(b'../') and len(data)<150:
        # Git's raw endpoint returns the link text; preserve the tracked symlink.
        target=data.decode().strip();q=pathlib.PurePosixPath(name).parent/target
        resolved=os.path.normpath(str(q));queue.append(resolved)
        if p.exists() or p.is_symlink():p.unlink()
        p.symlink_to(target)
        seen[name]={'type':'symlink','target':target,'url':BASE+name}
        continue
    p.write_bytes(data)
    seen[name]={'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest(),'url':BASE+name}
    if name.endswith(('.dts','.dtsi','.h')):
        for match in re.finditer(rb'^\s*#include\s*[<"]([^>"\n]+)[>"]',data,re.M):
            include=match.group(1).decode()
            if include.startswith('dt-bindings/'):
                dep='include/'+include
            else:
                dep=str(pathlib.PurePosixPath(name).parent/include)
            queue.append(dep)
(ROOT.parent/'upstream-manifest.json').write_text(json.dumps({'linux':'6.12.112','repository':'https://github.com/gregkh/linux','tag':'v6.12.112','files':seen},indent=2)+'\n')
print('Fetched',len(seen),'pinned files')
