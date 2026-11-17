#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Run selected final ARM64 binaries under Cortex-A72 QEMU without changing rootfs."""
import argparse,hashlib,json,os,posixpath,re,struct,subprocess,tempfile
from pathlib import Path
p=argparse.ArgumentParser(description=__doc__);p.add_argument('--rootfs',type=Path,required=True);p.add_argument('--report',type=Path,required=True);a=p.parse_args();root=a.rootfs.resolve();checks=[];limitations=[]
def record(name,ok,detail):
    checks.append({'name':name,'pass':bool(ok),'detail':detail})
    if not ok:raise RuntimeError(name+': '+str(detail))
def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def target(relative):
    parts=[];pending=relative.lstrip('/').split('/');hops=0
    while pending:
        part=pending.pop(0)
        if part in ('','.'):continue
        if part=='..':
            if not parts:raise ValueError('Target path escapes root')
            parts.pop();continue
        item=root.joinpath(*parts,part)
        if item.is_symlink():
            hops+=1
            if hops>40:raise ValueError('Symlink cycle')
            value=os.readlink(item)
            if value.startswith('/'):parts=[]
            pending=value.lstrip('/').split('/')+pending
        else:parts.append(part)
    return root.joinpath(*parts)
def run(binary,args=(),env=None,good=(0,)):
    command=['qemu-aarch64-static','-cpu','cortex-a72','-L',str(root),str(target(binary)),*args]
    values=dict(os.environ,PYTHONDONTWRITEBYTECODE='1',PYTHONHOME=str(root/'usr'),PYTHONPATH=str(root/'usr/lib/python3.13'),LC_ALL='C')
    if env:values.update(env)
    result=subprocess.run(command,env=values,text=True,capture_output=True,timeout=40)
    return {'command':command,'exit_code':result.returncode,'stdout':result.stdout[-7000:],'stderr':result.stderr[-7000:]},result.returncode in good

def closure(binary):
    pending=[binary];seen={};missing=[]
    while pending:
        name=pending.pop();path=target(name)
        if not path.is_file():missing.append(name);continue
        rel=path.relative_to(root).as_posix()
        if rel in seen:continue
        data=path.read_bytes();record('elf64-aarch64:'+rel,data[:5]==b'\x7fELF\x02' and int.from_bytes(data[18:20],'little')==183,{'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()})
        # OpenWrt strips section headers. Read the actual ELF program table/dynamic
        # segment directly; never rely on invented section headers from host readelf.
        phoff=struct.unpack_from('<Q',data,32)[0]
        entsize,count=struct.unpack_from('<HH',data,54)
        assert entsize==56
        headers=[struct.unpack_from('<IIQQQQQQ',data,phoff+i*entsize) for i in range(count)]
        needed_offsets=[];strtab=None;interpreters=[]
        for kind,flags,offset,vaddr,paddr,filesz,memsz,align in headers:
            if kind==3:interpreters.append(data[offset:offset+filesz].rstrip(b'\0').decode())
            if kind==2:
                for j in range(offset,offset+filesz,16):
                    tag,value=struct.unpack_from('<qQ',data,j)
                    if tag==0:break
                    if tag==1:needed_offsets.append(value)
                    if tag==5:strtab=value
        needed=[]
        if needed_offsets:
            assert strtab is not None
            mapped=next(offset+(strtab-vaddr) for kind,flags,offset,vaddr,paddr,filesz,memsz,align in headers if kind==1 and vaddr<=strtab<vaddr+filesz)
            for offset in needed_offsets:
                end=data.index(b'\0',mapped+offset);needed.append(data[mapped+offset:end].decode())
        for value in interpreters:pending.append(value)
        for lib in needed:
            found=next((base+'/'+lib for base in ['lib','usr/lib'] if target(base+'/'+lib).is_file()),None)
            if found:pending.append(found)
            else:missing.append(rel+':'+lib)
        seen[rel]={'sha256':hashlib.sha256(data).hexdigest(),'needed':needed}
    record('dependency-closure:'+binary,not missing,{'files':seen,'missing':missing})
report={}
try:
    project=Path(__file__).resolve().parents[2]
    for installed,source in [
        ('usr/sbin/firefly-install-emmc','source/flash/install-to-emmc.py'),
        ('etc/uci-defaults/99-firefly-router','source/network/overlay/etc/uci-defaults/99-firefly-router'),
        ('usr/sbin/firefly-usb-wan','source/network/overlay/usr/sbin/firefly-usb-wan'),
        ('etc/hotplug.d/net/95-firefly-usb-wan','source/network/overlay/etc/hotplug.d/net/95-firefly-usb-wan')]:
        path=target(installed)
        record('installed-source-parity:'+installed,path.read_bytes()==(project/source).read_bytes(),{'bytes':path.stat().st_size,'sha256':digest(path),'source':source})
    # BusyBox is built with direct applet entry points; run ash by argv0 explicitly.
    command=['qemu-aarch64-static','-cpu','cortex-a72','-L',str(root),'-0','ash',str(target('bin/busybox')),'-c','x=7; [ "$((x * 6))" = 42 ] && printf "A72 ash builtins PASS\\n"']
    result=subprocess.run(command,text=True,capture_output=True,timeout=20)
    record('busybox-ash-a72',result.returncode==0 and 'A72 ash builtins PASS' in result.stdout,{'command':command,'exit_code':result.returncode,'stdout':result.stdout,'stderr':result.stderr})
    for binary,args,marker,codes in [('usr/sbin/dnsmasq',['--version'],'Dnsmasq version',(0,)),('usr/sbin/uhttpd',['-h'],'Usage:',(0,1))]:
        item,ok=run(binary,args,good=codes);record('qemu-version:'+binary,ok and marker.lower() in (item['stdout']+item['stderr']).lower(),item)
    item,ok=run('usr/sbin/nft',['--version'])
    if not ok and 'Unable to initialize Netlink socket: Protocol not supported' in item['stderr']:
        limitations.append({'program':'nft','detail':'QEMU user mode does not expose NETLINK_NETFILTER for the nft frontend constructor; the complete AArch64 ELF dependency closure is checked separately.','attempt':item})
    else:
        record('qemu-nft-version',ok and 'nftables' in (item['stdout']+item['stderr']),item)
    with tempfile.TemporaryDirectory(prefix='firefly-runtime-') as temporary:
        scratch=Path(temporary);cfg=scratch/'config';cfg.mkdir();delta=scratch/'delta';delta.mkdir();(cfg/'network').write_text("config interface 'lan'\n option proto 'static'\n option ipaddr '192.168.50.1'\n")
        item,ok=run('sbin/uci',['-c',str(cfg),'-t',str(delta),'get','network.lan.ipaddr']);record('qemu-real-uci-parse',ok and item['stdout'].strip()=='192.168.50.1',item)
        item,ok=run('usr/bin/python3',['--version']);record('qemu-python-version',ok and 'Python 3.13' in item['stdout'],item)
        code='''import datetime,fcntl,gzip,hashlib,json,os,pathlib,struct,sys,tempfile\nassert sys.version_info[:2] == (3,13)\nassert hashlib.sha256(b"abc").hexdigest() == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"\nassert gzip.decompress(gzip.compress(b"Firefly RK3399")) == b"Firefly RK3399"\nassert struct.unpack("<I", struct.pack("<I",0xfc339901))[0] == 0xfc339901\nassert json.loads(json.dumps({"board":"firefly-rk3399"}))["board"] == "firefly-rk3399"\nprint("Python installer stdlib PASS",sys.version.split()[0])'''
        item,ok=run('usr/bin/python3',['-c',code]);record('qemu-python-installer-stdlib',ok and 'stdlib PASS' in item['stdout'],item)
        item,ok=run('usr/bin/python3',[str(root/'usr/sbin/firefly-install-emmc'),'--help']);record('qemu-installer-help',ok and '--backup-dir' in item['stdout'] and '--no-backup' in item['stdout'],item)
        for script in ['etc/uci-defaults/99-firefly-router','usr/sbin/firefly-usb-wan','etc/hotplug.d/net/95-firefly-usb-wan']:
            command=['qemu-aarch64-static','-cpu','cortex-a72','-L',str(root),'-0','ash',str(target('bin/busybox')),'-n',str(root/script)]
            result=subprocess.run(command,text=True,capture_output=True,timeout=20)
            record('qemu-ash-syntax:'+script,result.returncode==0,{'command':command,'exit_code':result.returncode,'stderr':result.stderr})
    for binary in ['bin/busybox','sbin/uci','usr/bin/python3.13','usr/sbin/nft','usr/sbin/uhttpd','usr/sbin/dnsmasq']:
        closure(binary)
    record('rootfs-release',"DISTRIB_RELEASE='25.12.6'" in (root/'etc/openwrt_release').read_text(),(root/'etc/openwrt_release').read_text())
except Exception as error:report['error']=str(error)
report.update({'result':'FAIL' if report.get('error') else 'PASS','passed':sum(x['pass'] for x in checks),'total':len(checks),'environment':{'emulator':'qemu-aarch64-static','cpu':'cortex-a72','rootfs':str(root),'writes':'Only ephemeral container temporary directories; project rootfs mount is read-only','network':'none'},'limitations':limitations,'checks':checks})
a.report.parent.mkdir(parents=True,exist_ok=True);a.report.write_text(json.dumps(report,indent=2)+'\n');print(json.dumps({'result':report['result'],'passed':report['passed'],'total':report['total'],'error':report.get('error')},indent=2));raise SystemExit(1 if report.get('error') else 0)
