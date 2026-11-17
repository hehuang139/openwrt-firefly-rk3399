#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Verify Linux stable DTS input closure, then compile Firefly OpenWrt DTB."""
import argparse,hashlib,json,os,pathlib,subprocess
HERE=pathlib.Path(__file__).resolve().parent

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',type=pathlib.Path,required=True)
    a=p.parse_args()
    if a.output.exists() or a.output.is_symlink():raise ValueError('Use a new output directory')
    manifest=json.loads((HERE/'upstream-manifest.json').read_text())
    for name,item in manifest['files'].items():
        path=HERE/'upstream'/name
        if item.get('type')=='symlink':
            assert path.is_symlink() and os.readlink(path)==item['target'],name
        else:
            assert not path.is_symlink() and path.stat().st_size==item['bytes'],name
            assert hashlib.sha256(path.read_bytes()).hexdigest()==item['sha256'],name
    a.output.mkdir(parents=True)
    upstream=HERE/'upstream'
    includes=['-I'+str(upstream/'include'),'-I'+str(upstream/'arch/arm64/boot/dts/rockchip')]
    source=HERE/'rk3399-firefly-openwrt.dts'
    pp=a.output/'rk3399-firefly-openwrt.pp.dts'
    with pp.open('wb') as stream:
        subprocess.run(['gcc','-E','-P','-nostdinc','-undef','-D__DTS__','-x','assembler-with-cpp',*includes,str(source)],stdout=stream,check=True)
    output=a.output/'rk3399-firefly-openwrt.dtb'
    warnings=a.output/'dtc-warnings.txt'
    with warnings.open('wb') as stream:
        subprocess.run(['dtc','-I','dts','-O','dtb','-o',str(output),str(pp)],stderr=stream,check=True)
    for original,target in [('arch/arm64/boot/dts/rockchip/rk3399-firefly.dts','upstream.pp.dts')]:
        with (a.output/target).open('wb') as stream:
            subprocess.run(['gcc','-E','-P','-nostdinc','-undef','-D__DTS__','-x','assembler-with-cpp',*includes,str(upstream/original)],stdout=stream,check=True)
        with (a.output/'upstream-dtc-warnings.txt').open('wb') as stream:
            subprocess.run(['dtc','-I','dts','-O','dtb','-o',str(a.output/'upstream-firefly.dtb'),str(a.output/target)],stderr=stream,check=True)
    print(json.dumps({'dtb':str(output),'bytes':output.stat().st_size,'sha256':hashlib.sha256(output.read_bytes()).hexdigest()},indent=2))
if __name__=='__main__':main()
