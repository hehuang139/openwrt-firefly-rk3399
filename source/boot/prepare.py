#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Apply only board boot order and host compiler fixes to pinned upstream trees."""
import argparse,json,pathlib
HERE=pathlib.Path(__file__).resolve().parent
p=argparse.ArgumentParser();p.add_argument('source',type=pathlib.Path);p.add_argument('mode',choices=['sd','emmc']);a=p.parse_args()
root=a.source
path=root/'arch/arm/dts/rk3399-firefly-u-boot.dtsi'
s=path.read_text()
assert 'u-boot,spl-boot-order' not in s
boot='sdmmc' if a.mode=='sd' else 'sdhci'
s+='''
/* Keep the SPL/U-Boot stages on the requested physical medium. */
&{/chosen} {
    u-boot,spl-boot-order = &'''+boot+''';
};
/* Conservative first-stage eMMC; Linux negotiates HS200 separately. */
&sdhci {
    /delete-property/ mmc-hs400-1_8v;
    /delete-property/ mmc-hs400-enhanced-strobe;
    max-frequency = <52000000>;
};
'''
path.write_text(s)
path=root/'include/configs/rockchip-common.h';s=path.read_text()
before='#define BOOT_TARGETS\t"mmc1 mmc0 nvme scsi usb pxe dhcp spi"'
assert s.count(before)==1
s=s.replace(before,'#define BOOT_TARGETS\t"'+('mmc1' if a.mode=='sd' else 'mmc1 mmc0')+'"')
path.write_text(s)
