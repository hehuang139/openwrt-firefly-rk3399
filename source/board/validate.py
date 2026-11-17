#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Validate compiled Firefly wiring, mandatory release drivers and unchanged GMAC."""
import argparse,hashlib,json,pathlib,re,subprocess
HERE=pathlib.Path(__file__).resolve().parent
ROOT=HERE.parent.parent

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--build',type=pathlib.Path,required=True);p.add_argument('--report',type=pathlib.Path,required=True);a=p.parse_args()
    dtb=a.build/'rk3399-firefly-openwrt.dtb';base=a.build/'upstream-firefly.dtb';checks=[]
    def get(node,key,kind='s',path=dtb):
        return subprocess.check_output(['fdtget','-t',kind,str(path),node,key],text=True).strip()
    def check(name,condition,value=None):
        if not condition:raise AssertionError(name+': '+str(value))
        checks.append({'name':name,'result':'PASS','value':value})
    check('original-Firefly-compatible',get('/','compatible')=='firefly,firefly-rk3399 rockchip,rk3399')
    check('UART2-1500000',get('/chosen','stdout-path')=='serial2:1500000n8')
    check('Linux-SD-alias',get('/aliases','mmc1')=='/mmc@fe320000')
    check('Linux-eMMC-alias',get('/aliases','mmc2')=='/mmc@fe330000')
    for node in ['/mmc@fe310000','/mmc@fe320000','/mmc@fe330000','/syscon@ff770000/phy@f780']:
        check('MMC-enabled:'+node,get(node,'status')=='okay')
    check('eMMC-HS200',get('/mmc@fe330000','mmc-hs200-1_8v','x')=='')
    check('eMMC-200MHz-cap',get('/mmc@fe330000','max-frequency','u')=='200000000')
    for key in ['mmc-hs400-1_8v','mmc-hs400-enhanced-strobe']:
        result=subprocess.run(['fdtget',str(dtb),'/mmc@fe330000',key],capture_output=True)
        check('eMMC-remove:'+key,result.returncode!=0)
    check('USB-hub-reset-GPIO2A4-output-high',get('/pinctrl/usb2/hub-rst','rockchip,pins','u').split()[:3]==['2','4','0'])
    pin=get('/pinctrl/usb2/hub-rst','rockchip,pins','u').split()[-1]
    check('USB-reset-config-output-high',get('/pinctrl/pcfg-output-high','phandle','u')==pin and get('/pinctrl/pcfg-output-high','output-high','x')=='')
    check('USB-regulator-includes-hub-reset',len(get('/vcc5v0-host-regulator','pinctrl-0','u').split())==2)
    check('Linux6.12-native-FUSB302-match',get('/i2c@ff3d0000/typec-portc@22','compatible')=='fcs,fusb302')
    for key in ['assigned-clocks','assigned-clock-parents','clock_in_out','phy-supply','phy-mode','pinctrl-0','snps,reset-gpio','snps,reset-active-low','snps,reset-delays-us','tx_delay','rx_delay']:
        kind='s' if key in ['clock_in_out','phy-mode'] else 'x'
        check('retain-upstream-GMAC:'+key,get('/ethernet@fe300000',key,kind)==get('/ethernet@fe300000',key,kind,path=base))
    cfg=(HERE/'openwrt-25.12.6-config-6.12').read_text().splitlines()
    for option in ['CONFIG_DWMAC_ROCKCHIP','CONFIG_STMMAC_ETH','CONFIG_REALTEK_PHY','CONFIG_MMC_DW_ROCKCHIP','CONFIG_MMC_SDHCI_OF_ARASAN','CONFIG_PHY_ROCKCHIP_EMMC','CONFIG_USB_XHCI_HCD','CONFIG_USB_EHCI_HCD','CONFIG_USB_DWC3_HOST','CONFIG_TYPEC_FUSB302']:
        check('release-builtin:'+option,option+'=y' in cfg)
    def warnings(path):
        return sorted(re.findall(r'Warning \(([^)]+)\): ([^\n]+)',path.read_text()))
    actual=warnings(a.build/'dtc-warnings.txt');baseline=warnings(a.build/'upstream-dtc-warnings.txt')
    check('no-new-dtc-warnings',actual==baseline,{'upstream':len(baseline),'adapted':len(actual)})
    # A second true compile checks the pinned source path produces byte-identical DTB.
    pp=a.build/'rk3399-firefly-openwrt.pp.dts';again=a.build/'repeated.dtb'
    subprocess.run(['dtc','-I','dts','-O','dtb','-o',str(again),str(pp)],check=True,stderr=subprocess.DEVNULL)
    check('repeat-DTB-byte-identical',again.read_bytes()==dtb.read_bytes())
    result={'result':'PASS','count':len(checks),'linux':'6.12.112','dtb':{'path':str(dtb),'bytes':dtb.stat().st_size,'sha256':hashlib.sha256(dtb.read_bytes()).hexdigest()},'checks':checks}
    a.report.parent.mkdir(parents=True,exist_ok=True);a.report.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps({'result':'PASS','checks':len(checks),'dtb':result['dtb']},indent=2))
if __name__=='__main__':main()
