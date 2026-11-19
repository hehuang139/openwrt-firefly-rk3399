#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Make fixed SD/eMMC factory and sysupgrade images from the native Firefly build."""
import argparse,gzip,hashlib,json,os,shutil,struct,subprocess,zlib
from pathlib import Path
HERE=Path(__file__).resolve().parent
ROOT=HERE.parent

def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(8388608),b''):h.update(block)
    return h.hexdigest()

def pin(path):
    return {'path':str(path.relative_to(ROOT)),'bytes':path.stat().st_size,'sha256':sha(path)}

def decode(path,output):
    dec=zlib.decompressobj(31);trailing=bytearray()
    with path.open('rb') as stream,output.open('xb') as target:
        for data in iter(lambda:stream.read(1048576),b''):
            if dec.eof:trailing.extend(data)
            else:
                target.write(dec.decompress(data))
                if dec.eof:trailing.extend(dec.unused_data)
    if not dec.eof:raise ValueError('Truncated source gzip')
    return bytes(trailing)

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('imagebuilder',type=Path);p.add_argument('output',type=Path);a=p.parse_args()
    ib=a.imagebuilder.resolve();out=a.output.resolve()
    if out.exists() or out.is_symlink():raise ValueError('Use a new release output directory')
    out.mkdir(parents=True)
    env=os.environ.copy();env['PATH']=str(ib/'staging_dir/host/bin')+os.pathsep+env['PATH']
    env['E2FSCK_TIME']='1792273538'
    original=ROOT/'work/imagebuilder-output/openwrt-25.12.6-rockchip-armv8-firefly_firefly-rk3399-ext4-sysupgrade.img.gz'
    metadata=out/'sysupgrade-metadata.json'
    subprocess.run([str(ib/'staging_dir/host/bin/fwtool'),'-i',str(metadata),str(original)],check=True,env=env)
    meta=json.loads(metadata.read_text())
    assert meta['supported_devices']==['firefly,firefly-rk3399']
    assert meta['version']['version']=='25.12.6'
    raw=out/'base.raw'
    trailing=decode(original,raw)
    assert trailing,'ImageBuilder source requires fwtool metadata'
    with raw.open('rb') as stream:first=stream.read(512)
    assert first[510:]==b'\x55\xaa'
    partitions=[]
    for i in range(2):
        row=first[446+i*16:462+i*16]
        partitions.append({'type':row[4],'start_lba':struct.unpack_from('<I',row,8)[0],'sectors':struct.unpack_from('<I',row,12)[0]})
    assert partitions==[{'type':131,'start_lba':65536,'sectors':65536},{'type':131,'start_lba':196608,'sectors':1048576}],partitions
    assert raw.stat().st_size==637534208
    # Official make_ext4fs leaves unused inode bitmap tail bits clear. Repair
    # with the pinned official e2fsck, using a fixed clock for repeatability,
    # then demand a clean read-only check before putting partitions back.
    filesystems=[]
    for index,part in enumerate(partitions,1):
        fs=out/f'partition-{index}.ext4'
        with raw.open('rb') as stream,fs.open('xb') as target:
            stream.seek(part['start_lba']*512);remaining=part['sectors']*512
            while remaining:
                data=stream.read(min(remaining,8388608));assert data
                target.write(data);remaining-=len(data)
        repair=subprocess.run([str(ib/'staging_dir/host/bin/e2fsck'),'-fy',str(fs)],env=env,capture_output=True,text=True)
        assert repair.returncode in (0,1),repair.stdout+repair.stderr
        clean=subprocess.run([str(ib/'staging_dir/host/bin/e2fsck'),'-fn',str(fs)],env=env,capture_output=True,text=True)
        assert clean.returncode==0,clean.stdout+clean.stderr
        filesystems.append({'partition':index,'repair_exit':repair.returncode,'repair':repair.stdout+repair.stderr,'readonly_exit':clean.returncode,'readonly':clean.stdout+clean.stderr,'sha256':sha(fs)})
        with raw.open('r+b') as target,fs.open('rb') as stream:
            target.seek(part['start_lba']*512);shutil.copyfileobj(stream,target,8388608)
        fs.unlink()
    (out/'filesystem-checks.json').write_text(json.dumps(filesystems,indent=2)+'\n')
    result={'board':'firefly-rk3399','version':'25.12.6','kernel':'6.12.112','source_image':pin(original),'partitions':partitions,'modes':{}}
    for mode,signature in [('sd',0xfc339901),('emmc',0xfc339902)]:
        name='openwrt-25.12.6-firefly-rk3399-'+mode+'-vsel1-test2.img'
        target=out/name
        shutil.copyfile(raw,target)
        boot=HERE/'boot/assets'/mode/'u-boot-rockchip.bin'
        with target.open('r+b') as stream:
            stream.seek(440);stream.write(struct.pack('<I',signature))
            # Start each bootloader region from zero, independent of loader length.
            stream.seek(512)
            remaining=partitions[0]['start_lba']*512-512
            zero=bytes(1048576)
            while remaining:
                size=min(remaining,len(zero));stream.write(zero[:size]);remaining-=size
            stream.seek(32768)
            data=boot.read_bytes()
            assert 32768+len(data)<partitions[0]['start_lba']*512
            stream.write(data)
        factory=out/(name+'.gz')
        with target.open('rb') as source,factory.open('xb') as compressed:
            with gzip.GzipFile(filename='',mode='wb',fileobj=compressed,mtime=0,compresslevel=6) as stream:
                shutil.copyfileobj(source,stream,8388608)
        with gzip.open(factory,'rb') as stream:
            h=hashlib.sha256();size=0
            for block in iter(lambda:stream.read(8388608),b''):h.update(block);size+=len(block)
        assert size==target.stat().st_size and h.hexdigest()==sha(target)
        upgrade=out/('openwrt-25.12.6-firefly-rk3399-'+mode+'-sysupgrade-vsel1-test2.img.gz')
        shutil.copyfile(factory,upgrade)
        subprocess.run([str(ib/'staging_dir/host/bin/fwtool'),'-I',str(metadata),str(upgrade)],check=True,env=env)
        result['modes'][mode]={'disk_signature':f'{signature:08x}','image':pin(target),'compressed':pin(factory),'sysupgrade':pin(upgrade),'bootloader':pin(boot)}
    raw.unlink()
    emmc=result['modes']['emmc']
    manifest={'board':'firefly-rk3399','medium':'emmc','image':{**emmc['image'],'name':Path(emmc['image']['path']).name},'compressed':{**emmc['compressed'],'name':Path(emmc['compressed']['path']).name}}
    for item in [manifest['image'],manifest['compressed']]:item.pop('path')
    (out/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    (out/'release.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))
if __name__=='__main__':main()
