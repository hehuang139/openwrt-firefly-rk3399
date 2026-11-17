#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Add the original Firefly RK3399 profile and fixed BSP inputs to official ImageBuilder."""
import argparse, hashlib, json, lzma, os, shutil, subprocess
from pathlib import Path
HERE=Path(__file__).resolve().parent
PROFILE='firefly_firefly-rk3399'

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('imagebuilder',type=Path)
    p.add_argument('--dtb',type=Path,required=True)
    p.add_argument('--uboot',type=Path,required=True)
    args=p.parse_args(); ib=args.imagebuilder.resolve()
    os.environ['PATH']=str(ib/'staging_dir/host/bin')+os.pathsep+os.environ['PATH']
    os.environ['SOURCE_DATE_EPOCH']='1792273538'
    kernel=ib/'build_dir/target-aarch64_generic_musl/linux-rockchip_armv8'
    assert (kernel/'vmlinux').is_file()
    arm=ib/'target/linux/rockchip/image/armv8.mk'
    text=arm.read_text()
    if 'define Device/'+PROFILE not in text:
        text+='''
# Original Firefly-RK3399 DDR3; board-specific FIT and native TPL bootloader.
define Device/firefly_firefly-rk3399
  $(Device/rk3399)
  DEVICE_VENDOR := Firefly
  DEVICE_MODEL := Firefly-RK3399
  DEVICE_VARIANT := DDR3
  DEVICE_DTS := rk3399-firefly-openwrt
  UBOOT_DEVICE_NAME := firefly-rk3399
  SUPPORTED_DEVICES := firefly,firefly-rk3399
  FILESYSTEMS := ext4
  DEVICE_PACKAGES := kmod-brcmfmac brcmfmac-nvram-4356-sdio cypress-firmware-4356-sdio
endef
TARGET_DEVICES += firefly_firefly-rk3399
'''
        arm.write_text(text)
    info=ib/'.targetinfo';text=info.read_text()
    if 'Target-Profile: DEVICE_'+PROFILE not in text:
        start=text.index('Target: rockchip/armv8\n')
        end=text.find('\nTarget: ',start+1)
        if end<0:end=len(text)
        block='''
Target-Profile: DEVICE_firefly_firefly-rk3399
Target-Profile-Name: Firefly Firefly-RK3399 DDR3
Target-Profile-Packages: kmod-brcmfmac brcmfmac-nvram-4356-sdio cypress-firmware-4356-sdio
Target-Profile-hasImageMetadata: 1
Target-Profile-SupportedDevices: firefly,firefly-rk3399
Target-Profile-Description:
Original Firefly-RK3399 DDR3 with native board device tree and bootloader

'''
        info.write_text(text[:end]+block+text[end:])
    profiles=ib/'.profiles.mk'
    if profiles.exists():profiles.unlink()
    shutil.copyfile(args.dtb,kernel/'image-rk3399-firefly-openwrt.dtb')
    # The ImageBuilder does not rebuild its pre-generated FIT images. Build the new
    # Firefly FIT from the official raw kernel, preserving the kernel byte content.
    compressed=kernel/'firefly-kernel.lzma'
    subprocess.run([str(ib/'staging_dir/host/bin/lzma'),'e',str(kernel/'vmlinux'),str(compressed),'-lc1','-lp2','-pb2','-d20'],check=True)
    its=kernel/(PROFILE+'-kernel.bin.its')
    its.write_text('''/dts-v1/;
/ {
 description = "ARM64 OpenWrt Firefly RK3399 FIT";
 #address-cells = <1>;
 images {
  kernel-1 {
   description = "ARM64 OpenWrt Linux-6.12.112";
   data = /incbin/("'''+str(compressed)+'''");
   type = "kernel"; arch = "arm64"; os = "linux"; compression = "lzma";
   load = <0x03200000>; entry = <0x03200000>;
   hash-1 { algo = "crc32"; }; hash-2 { algo = "sha256"; };
  };
  fdt-1 {
   description = "Original Firefly RK3399 DDR3";
   data = /incbin/("'''+str(kernel/'image-rk3399-firefly-openwrt.dtb')+'''");
   type = "flat_dt"; arch = "arm64"; compression = "none";
   hash-1 { algo = "crc32"; }; hash-2 { algo = "sha256"; };
  };
 };
 configurations {
  default = "config-1";
  config-1 { description = "OpenWrt Firefly RK3399 DDR3"; kernel = "kernel-1"; fdt = "fdt-1"; };
 };
};
''')
    subprocess.run([str(ib/'staging_dir/host/bin/mkimage'),'-f',str(its),str(kernel/(PROFILE+'-kernel.bin'))],check=True)
    dest=ib/'staging_dir/target-aarch64_generic_musl/image/firefly-rk3399-u-boot-rockchip.bin'
    dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(args.uboot,dest)
    conf=ib/'.config'; text=conf.read_text()
    text=text.replace('CONFIG_TARGET_KERNEL_PARTSIZE=16','CONFIG_TARGET_KERNEL_PARTSIZE=32')
    conf.write_text(text)
    # Offline rebuilds use the frozen APK cache and retain signature verification.
    makefile=ib/'Makefile';text=makefile.read_text()
    original='--cache-dir $(DL_DIR)'
    replacement='--cache-dir $(DL_DIR) $(if $(filter 1,$(FIREFLY_OFFLINE)),--no-network)'
    text=text.replace('--cache-dir $(DL_DIR) $(if $(FIREFLY_OFFLINE),--no-network)',replacement)
    if replacement not in text:
        assert text.count(original)==1
        text=text.replace(original,replacement)
    makefile.write_text(text)
    print('Prepared '+PROFILE)
if __name__=='__main__':main()
