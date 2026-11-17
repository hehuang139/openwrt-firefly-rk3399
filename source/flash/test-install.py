#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Offline installer checks with real file I/O; never opens a block device."""
import sys
sys.dont_write_bytecode=True
import copy,gzip,hashlib,importlib.util,json,os,stat,struct,subprocess,tempfile
from pathlib import Path
from unittest.mock import patch
HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('firefly_installer',HERE/'install-to-emmc.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
checks=[]
def success(name,fn):fn();checks.append(name)
def rejects(name,fn):
    try:fn()
    except (ValueError,OSError,EOFError,KeyError,TypeError):checks.append(name)
    else:raise AssertionError('Unexpected acceptance: '+name)
with tempfile.TemporaryDirectory(prefix='openwrt-install-test-') as temporary:
    root=Path(temporary);sysroot=root/'mmcblk2';(sysroot/'holders').mkdir(parents=True);m.SYS=sysroot
    actual_read=Path.read_text
    def no_swap(path,*args,**kwargs):
        if path==Path('/proc/swaps'):return 'Filename Type Size Used Priority\n'
        return actual_read(path,*args,**kwargs)
    info={'compatible':[b'firefly,firefly-rk3399',b'rockchip,rk3399'], 'model':'Firefly-RK3399 Board',
          'path':'/sys/devices/platform/fe330000.mmc/mmc_host/mmc2/mmc2:0001/block/mmcblk2',
          'type':'MMC','cid':'0123456789abcdef'*2,'name':'fixture','removable':'0','ro':'0','sector':512,'bytes':8*1024**3,'dev':'179:64',
          'root':[{'point':'/','device':'179:34','source':'/dev/mmcblk1p2','type':'ext4'}],
          'root_sys':'/sys/devices/platform/fe320000.mmc/mmc_host/mmc1/mmc1:0001/block/mmcblk1/mmcblk1p2','target_mounts':[]}
    with patch.object(Path,'read_text',no_swap):
        success('original Firefly, TF ext4 root and onboard eMMC accepted',lambda:m.validate_identity(info))
        invalid=[('compatible',[b'pine64,rockpro64']),('model','ROC-RK3399-PC'),('type','SD'),('path','/sys/fe320000.mmc/block/mmcblk2'),('removable','1'),('ro','1'),('sector',4096),('bytes',4*1024**3),('cid','invalid'),('root',[]),('root_sys','/sys/fe330000.mmc/mmcblk2/mmcblk2p2'),('root_sys',info['root_sys'].replace('fe320000','fe330000')),('root_sys',info['root_sys'].replace('mmcblk1p2','mmcblk1p1')),('target_mounts',[{'point':'/mnt/old-system'}])]
        for key,value in invalid:
            changed=copy.deepcopy(info);changed[key]=value
            rejects('invalid '+key+' '+str(value)+' rejected',lambda x=changed:m.validate_identity(x))
        changed=copy.deepcopy(info);changed['root'][0]['type']='overlay'
        rejects('overlay root cannot act as TF installer',lambda:m.validate_identity(changed))
        (sysroot/'holders/dm-0').touch();rejects('active whole-device block holder rejected',lambda:m.validate_identity(info));(sysroot/'holders/dm-0').unlink()
        (sysroot/'mmcblk2p1/holders').mkdir(parents=True);(sysroot/'mmcblk2p1/holders/dm-1').touch();rejects('active partition block holder rejected',lambda:m.validate_identity(info));(sysroot/'mmcblk2p1/holders/dm-1').unlink()
    swap=root/'swapfile';swap.touch()
    def swap_read(path,*args,**kwargs):
        if path==Path('/proc/swaps'):return 'Filename Type Size Used Priority\n'+str(swap)+' file 1 0 -2\n'
        return actual_read(path,*args,**kwargs)
    with patch.object(Path,'read_text',swap_read),patch.object(m,'dev_sys_path',return_value=info['path']):
        rejects('swap file backed by target eMMC rejected',lambda:m.validate_identity(info))
    oldstat=Path.stat
    class BlockStat:
        st_mode=stat.S_IFBLK|0o600;st_rdev=os.makedev(179,64);st_dev=os.makedev(0,6)
    def fake_stat(path,*args,**kwargs):
        if path==swap:return BlockStat()
        return oldstat(path,*args,**kwargs)
    resolved=[]
    def resolve_target(device):resolved.append(device);return info['path']
    with patch.object(Path,'read_text',swap_read),patch.object(Path,'stat',fake_stat),patch.object(m,'dev_sys_path',resolve_target):
        rejects('swap block alias backed by target eMMC rejected',lambda:m.validate_identity(info))
    assert resolved==['179:64'];checks.append('swap aliases resolved with st_rdev rather than virtual filesystem st_dev')
    rows=m.mounts('42 1 0:65 / /media/OLD\\040SYSTEM rw - fuseblk /dev/mmcblk2p3 rw\n')
    assert rows[0]['point']=='/media/OLD SYSTEM' and len(m.target_mounts(rows))==1;checks.append('escaped mount points and FUSE target source detected')
    aliasrows=[{'device':'0:65','point':'/mnt/old','type':'fuseblk','source':str(swap)}]
    with patch.object(Path,'stat',fake_stat),patch.object(m,'dev_sys_path',return_value=info['path']):
        assert len(m.target_mounts(aliasrows))==1;checks.append('FUSE block source alias resolved to target')
    image=root/'fixture.img.gz';raw=bytearray(8192);raw[510:512]=b'\x55\xaa'
    for i,(kind,start,count) in enumerate([(131,65536,65536),(131,196608,1048576)]):raw[446+i*16:462+i*16]=struct.pack('<B3sB3sII',0,b'\0'*3,kind,b'\0'*3,start,count)
    raw[512:]=bytes(range(256))*30
    with gzip.open(image,'wb') as stream:stream.write(raw)
    m.IMAGE_BYTES=len(raw)
    manifest={'board':'firefly-rk3399','medium':'emmc','image':{'name':'fixture.img','bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()},'compressed':{'name':image.name,'bytes':image.stat().st_size,'sha256':hashlib.sha256(image.read_bytes()).hexdigest()}}
    success('valid pinned eMMC manifest accepted',lambda:m.validate_manifest(manifest,image))
    for group,key,value in [('','medium','sd'),('','board','rockpro64'),('image','bytes',True),('image','name','../fixture.img'),('compressed','sha256','bad'),('compressed','bytes',1)]:
        wrong=copy.deepcopy(manifest);(wrong[group] if group else wrong)[key]=value
        rejects('manifest '+group+'.'+key+' invalid value rejected',lambda x=wrong:m.validate_manifest(x,image))
    success('actual gzip/raw SHA256 and OpenWrt MBR layout verified',lambda:m.verify_source(image,manifest))
    for group in ['compressed','image']:
        wrong=copy.deepcopy(manifest);wrong[group]['sha256']='0'*64
        rejects(group+' hash corruption rejected',lambda x=wrong:m.verify_source(image,x))
    oldraw=bytes(raw);raw[450]=12
    corrupt=root/'wrong-layout.img.gz'
    with gzip.open(corrupt,'wb') as stream:stream.write(raw)
    wrong=copy.deepcopy(manifest);wrong['compressed'].update(name=corrupt.name,bytes=corrupt.stat().st_size,sha256=hashlib.sha256(corrupt.read_bytes()).hexdigest());wrong['image']['sha256']=hashlib.sha256(raw).hexdigest()
    rejects('foreign FAT boot partition rejected despite matching hashes',lambda:m.verify_source(corrupt,wrong))
    link=root/'link';link.symlink_to(image);rejects('symlink payload rejected',lambda:m.regular(link));rejects('device payload rejected',lambda:m.regular(Path('/dev/null')))
    target=root/'ordinary-target';capacity=4*1024**2;target.write_bytes(b'X'*capacity);fd=os.open(target,os.O_RDWR)
    try:
        m.write_payload(fd,image,manifest,capacity)
        success('real file write, complete readback and old GPT tail clearing',lambda:m.readback(fd,manifest,capacity,flush=False))
        assert os.pread(fd,64,len(oldraw))==b'X'*64;checks.append('gap outside image and tail preserved')
        os.pwrite(fd,b'Q',100);rejects('readback catches written image corruption',lambda:m.readback(fd,manifest,capacity,flush=False))
        os.pwrite(fd,oldraw[100:101],100);os.pwrite(fd,b'Q',capacity-1);rejects('readback catches uncleared GPT tail corruption',lambda:m.readback(fd,manifest,capacity,flush=False))
    finally:os.close(fd)
    class PartialWrite:
        def __init__(self):self.data=bytearray()
        def __call__(self,fd,data):part=data[:3];self.data.extend(part);return len(part)
    writer=PartialWrite()
    with patch.object(os,'write',writer):m.write_all(99,b'abcdefghij')
    assert writer.data==b'abcdefghij';checks.append('partial writes retried without byte loss')
    with patch.object(os,'write',return_value=0):rejects('zero-progress device write rejected',lambda:m.write_all(99,b'a'))
    source=root/'backup-source';source.write_bytes(bytes(range(256))*256);backupdir=root/'backup';backupdir.mkdir();fd=os.open(source,os.O_RDONLY);small={'bytes':source.stat().st_size,'cid':info['cid']}
    fake=[{'point':str(root),'type':'ext4','device':'179:34','source':'/dev/mmcblk1p2'}]
    try:
        with patch.object(m,'mounts',return_value=fake),patch.object(m,'dev_sys_path',return_value=info['root_sys']):record=m.backup(fd,backupdir,small)
        assert Path(record['path']).read_bytes()==source.read_bytes();assert json.loads(Path(record['path']).with_suffix('.json').read_text())['sha256']==record['sha256'];checks.append('full backup data and metadata independently read back')
        with patch.object(m,'mounts',return_value=fake),patch.object(m,'dev_sys_path',return_value=info['path']):rejects('backup on target eMMC rejected',lambda:m.backup(fd,backupdir,small))
        with patch.object(m,'mounts',return_value=[dict(fake[0],type='vfat')]):rejects('FAT backup destination rejected',lambda:m.backup(fd,backupdir,small))
    finally:os.close(fd)
    script=HERE/'install-to-emmc.py'
    nochoice=subprocess.run([sys.executable,str(script),'--write'],capture_output=True,text=True);assert nochoice.returncode==2 and '--write requires' in nochoice.stderr;checks.append('write without backup choice rejected before any device access')
    conflict=subprocess.run([sys.executable,str(script),'--write','--no-backup','--backup-dir',str(backupdir)],capture_output=True,text=True);assert conflict.returncode==2;checks.append('conflicting backup options rejected before device access')
    unknown=subprocess.run([sys.executable,str(script),'--target','/dev/sda'],capture_output=True,text=True);assert unknown.returncode==2;checks.append('target device cannot be overridden by CLI')
report={'result':'PASS','count':len(checks),'checks':checks,'environment':'Host Python, actual compressed/regular file writes and readback with ordinary temporary target; synthetic sysfs/identity/holders/mounts; no block device opened','source_sha256':hashlib.sha256((HERE/'install-to-emmc.py').read_bytes()).hexdigest(),'fixture_note':'IMAGE_BYTES temporarily reduced to8192 for file I/O fixture; MBR entries retain actual release geometry'}
(HERE/'validation.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))
