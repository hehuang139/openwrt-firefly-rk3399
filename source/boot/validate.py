#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Inspect native U-Boot DDR3, medium policy, TF-A and packaged boot offsets."""
import argparse,hashlib,json,pathlib,subprocess
HERE=pathlib.Path(__file__).resolve().parent
ROOT=HERE.parent.parent

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--build',type=pathlib.Path,required=True);p.add_argument('--report',type=pathlib.Path,required=True);a=p.parse_args();checks=[]
    def check(name,value,detail=None):
        if not value:raise AssertionError(name+': '+str(detail))
        checks.append({'name':name,'result':'PASS','detail':detail})
    def fdt(path,node,key,kind='s'):
        return subprocess.check_output(['fdtget','-t',kind,str(path),node,key],text=True).strip()
    assets={}
    for mode in ['sd','emmc']:
        build=a.build/mode;bundle=a.build/'assets'/mode
        config=(build/'.config').read_text().splitlines()
        for key in ['CONFIG_ARM64=y','CONFIG_ROCKCHIP_RK3399=y','CONFIG_DEFAULT_DEVICE_TREE="rockchip/rk3399-firefly"','CONFIG_TPL=y','CONFIG_SPL=y','CONFIG_ENV_IS_NOWHERE=y','# CONFIG_ENV_IS_IN_MMC is not set','# CONFIG_VIDEO is not set','CONFIG_BAUDRATE=1500000','CONFIG_CMD_BOOTM=y','CONFIG_CMD_SOURCE=y','CONFIG_CMD_PART=y','CONFIG_CMD_FAT=y','CONFIG_CMD_EXT4=y','CONFIG_LZMA=y','CONFIG_FIT=y']:
            check(mode+':config:'+key.split('=')[0],key in config,key)
        check(mode+':no-external-DDR-TPL','CONFIG_ROCKCHIP_EXTERNAL_TPL=y' not in config)
        check(mode+':no-HS200-HS400','CONFIG_MMC_HS200_SUPPORT=y' not in config and 'CONFIG_MMC_HS400_SUPPORT=y' not in config)
        for dtb in [build/'u-boot.dtb',build/'spl/u-boot-spl.dtb']:
            check(mode+':native-Firefly:'+str(dtb.relative_to(build)),fdt(dtb,'/','compatible')=='firefly,firefly-rk3399 rockchip,rk3399')
            check(mode+':UBoot-eMMC-mmc0:'+dtb.name,fdt(dtb,'/aliases','mmc0')=='/mmc@fe330000')
            check(mode+':UBoot-SD-mmc1:'+dtb.name,fdt(dtb,'/aliases','mmc1')=='/mmc@fe320000')
            check(mode+':52MHz-eMMC:'+dtb.name,fdt(dtb,'/mmc@fe330000','max-frequency','u')=='52000000')
            for prop in ['mmc-hs400-1_8v','mmc-hs400-enhanced-strobe']:
                res=subprocess.run(['fdtget',str(dtb),'/mmc@fe330000',prop],capture_output=True)
                check(mode+':no-HS400:'+dtb.name+':'+prop,res.returncode!=0)
        expected='/mmc@fe320000' if mode=='sd' else '/mmc@fe330000'
        check(mode+':SPL-reads-own-medium',fdt(build/'spl/u-boot-spl.dtb','/chosen','u-boot,spl-boot-order')==expected)
        binary=(build/'u-boot.bin').read_bytes()
        target=b'boot_targets=mmc1\0' if mode=='sd' else b'boot_targets=mmc1 mmc0\0'
        check(mode+':U-Boot-targets',target in binary,target.decode().rstrip('\0'))
        check(mode+':bootscript-scanning',b'boot.scr' in binary and b'bootcmd=bootflow scan -lb\0' in binary and 'CONFIG_BOOTMETH_SCRIPT=y' in config and 'CONFIG_BOOTSTD_FULL=y' in config)
        tpl=(build/'tpl/u-boot-tpl.bin').read_bytes();spl=(build/'spl/u-boot-spl.bin').read_bytes()
        params=[int(x) for x in fdt(build/'tpl/u-boot-tpl.dtb','/memory-controller','rockchip,sdram-params','u').split()]
        check(mode+':native-DDR3-800MHz',params[34:36]==[800,3],params[34:36])
        combined=(bundle/'u-boot-rockchip.bin').read_bytes();idb=(bundle/'idbloader.img').read_bytes();fit=(bundle/'u-boot.itb').read_bytes()
        check(mode+':idb-at-LBA64',combined[:len(idb)]==idb)
        offset=8388608-32768
        check(mode+':FIT-at-LBA16384',combined[offset:offset+len(fit)]==fit)
        check(mode+':FIT-fits-before32MiB',len(fit)<24*1024*1024)
        check(mode+':idb-has-TPL',idb[2048:2052]==b'RK33' and idb[2052:2048+len(tpl)]==tpl[4:])
        check(mode+':idb-has-SPL',spl in idb)
        check(mode+':FIT-has-U-Boot', (build/'u-boot-nodtb.bin').read_bytes() in fit)
        check(mode+':FIT-has-Firefly-DTB',(build/'u-boot.dtb').read_bytes() in fit)
        listing=subprocess.check_output(['dumpimage','-l',str(bundle/'u-boot.itb')],text=True)
        (bundle/'fit-list.txt').write_text(listing)
        check(mode+':FIT-ATF-and-Firefly','ARM Trusted Firmware' in listing and 'rk3399-firefly' in listing)
        assets[mode]=[{'path':str(path.relative_to(ROOT)) if path.is_absolute() else str(path),'name':path.name,'bytes':path.stat().st_size,'sha256':hashlib.sha256(path.read_bytes()).hexdigest()} for path in sorted(bundle.iterdir()) if path.is_file()]
    for name in ['rk3399m0','rk3399m0pmu']:
        data=(a.build/'tfa/rk3399/release/m0'/ (name+'.elf')).read_bytes()
        check('TF-A-Cortex-M0:'+name,data[:5]==b'\x7fELF\x01' and int.from_bytes(data[16:18],'little')==2 and int.from_bytes(data[18:20],'little')==40,'ELF32 ARM ET_EXEC')
    bl31=a.build/'tfa/rk3399/release/bl31/bl31.elf';data=bl31.read_bytes()
    check('TF-A-BL31-AArch64',data[:5]==b'\x7fELF\x02' and int.from_bytes(data[18:20],'little')==183)
    report={'result':'PASS','count':len(checks),'uboot':'2025.10','tf_a':'2.13','board':'Original Firefly RK3399 DDR3','environment':'nowhere','placement_bytes':{'idbloader.img':32768,'u-boot.itb':8388608,'u-boot-rockchip.bin':32768},'assets':assets,'checks':checks}
    a.report.write_text(json.dumps(report,indent=2)+'\n');print(json.dumps({'result':'PASS','checks':len(checks),'assets':assets},indent=2))
if __name__=='__main__':main()
