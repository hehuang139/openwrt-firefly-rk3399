#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Execute production shell logic against real pinned UCI and ordinary fake sysfs."""
import argparse,hashlib,json,os,shutil,subprocess,tempfile
from pathlib import Path
HERE=Path(__file__).resolve().parents[1]
p=argparse.ArgumentParser();p.add_argument('--uci',type=Path,required=True);p.add_argument('--report',type=Path,required=True);a=p.parse_args()
checks=[]
with tempfile.TemporaryDirectory(prefix='firefly-net-') as temporary:
    root=Path(temporary);config=root/'config';config.mkdir();delta=root/'delta';delta.mkdir();net=root/'sys/class/net';net.mkdir(parents=True);lock=root/'lock';lock.mkdir();drivers=root/'sys/bus/usb/drivers';drivers.mkdir(parents=True)
    usb_bus=root/'sys/bus/usb'
    binpath=root/'bin';binpath.mkdir()
    for name in ['logger','ubus']:
        f=binpath/name;f.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> '+str(root/(name+'.log'))+'\n');f.chmod(0o755)
    uci=binpath/'uci';uci.write_text('#!/bin/sh\nexec '+str(a.uci.resolve())+' -c '+str(config)+' -t '+str(delta)+' "$@"\n');uci.chmod(0o755)
    env=dict(os.environ,PATH=str(binpath)+':'+os.environ['PATH'])
    board=root/'board_name';board.write_text('firefly,firefly-rk3399\n')
    helper=root/'firefly-usb-wan';text=(HERE/'overlay/usr/sbin/firefly-usb-wan').read_text();text=text.replace('/tmp/sysinfo/board_name',str(board)).replace('/sys/class/net',str(net)).replace('/var/lock',str(lock));helper.write_text(text);helper.chmod(0o755)
    startup=root/'99-firefly-router';text=(HERE/'overlay/etc/uci-defaults/99-firefly-router').read_text();text=text.replace('/tmp/sysinfo/board_name',str(board)).replace('/etc/config/firefly_router',str(config/'firefly_router')).replace('/usr/sbin/firefly-usb-wan',str(helper));startup.write_text(text);startup.chmod(0o755)
    def command(*args,check=True):return subprocess.run([str(uci),*args],env=env,text=True,capture_output=True,check=check)
    def get(key):return command('-q','get',key,check=False).stdout.strip()
    def setval(key,value):command('set',key+'='+value);command('commit',key.split('.')[0])
    def run(script=helper):
        result=subprocess.run(['sh',str(script)],env=env,text=True,capture_output=True)
        assert result.returncode==0,result.stderr
    def initial():
        for f in config.iterdir():f.unlink()
        for f in delta.iterdir():f.unlink()
        (config/'network').write_text("config interface 'loopback'\n option device 'lo'\n option proto 'static'\n option ipaddr '127.0.0.1'\n option netmask '255.0.0.0'\nconfig device\n option name 'br-lan'\n option type 'bridge'\n list ports 'eth0'\nconfig interface 'lan'\n option device 'br-lan'\n option proto 'static'\n option ipaddr '192.168.1.1'\n")
        shutil.copyfile(HERE/'upstream/firewall.config',config/'firewall')
        (config/'dhcp').write_text("config dnsmasq\n option domainneeded '1'\nconfig dhcp 'lan'\n option interface 'lan'\nconfig odhcpd\n option maindhcp '0'\n")
        (config/'system').write_text("config system\n option hostname 'OpenWrt'\n")
        (config/'luci').write_text("config core 'main'\n option lang 'auto'\n")
        (config/'uhttpd').write_text("config uhttpd 'main'\n list listen_http '0.0.0.0:80'\n list listen_https '0.0.0.0:443'\n")
        for f in list(net.iterdir()):
            if f.is_symlink():f.unlink()
            elif f.is_dir():shutil.rmtree(f)
    def adapter(name,mac,usb=True,driver='r8152',wireless=False):
        device=root/'sys/devices'/name
        if device.exists():shutil.rmtree(device)
        physical=device/'1-1';interface=physical/'1-1:1.0';interface.mkdir(parents=True)
        if usb:
            (physical/'subsystem').symlink_to(usb_bus);(physical/'idVendor').write_text('0bda\n');(physical/'idProduct').write_text('8153\n')
        d=drivers/driver;d.mkdir(exist_ok=True);(interface/'driver').symlink_to(d)
        entry=net/name;entry.mkdir();(entry/'device').symlink_to(interface);(entry/'type').write_text('1\n');(entry/'address').write_text(mac+'\n')
        if wireless:(entry/'wireless').mkdir()
    def clear(name):shutil.rmtree(net/name)
    initial();adapter('eth0','02:11:22:33:44:00',usb=False);run(startup)
    assert get('network.lan.ipaddr')=='192.168.50.1' and get('network.lan.device')=='br-lan'
    assert get('network.@device[0].ports')=='eth0' and get('dhcp.lan.start')=='100' and get('dhcp.lan.limit')=='150'
    assert get('network.wan.proto')=='dhcp' and not get('network.wan.device')
    assert get('luci.main.lang')=='zh_cn' and get('uhttpd.main.redirect_https')=='1'
    assert get('network.loopback.ipaddr')=='127.0.0.1'
    checks.append('first boot LAN, DHCP range, LuCI language, HTTPS and loopback with real UCI')
    assert command('show','firewall').stdout.count(".name='lan'")==1 and command('show','firewall').stdout.count(".name='wan'")==1
    assert get('firewall.@zone[1].input')=='REJECT' and get('firewall.@zone[1].masq')=='1'
    assert get('firewall.@rule[0].name')=='Allow-DHCP-Renew'
    checks.append('upstream firewall zones and rules retained, WAN masquerade/reject')
    adapter('eth1','02:11:22:33:44:55');run()
    assert get('network.wan.device')=='eth1' and get('firefly_router.main.wan_mac')=='02:11:22:33:44:55'
    checks.append('single verified USB Ethernet auto-selects WAN')
    before={x.name:x.read_bytes() for x in config.iterdir()};run();assert before=={x.name:x.read_bytes() for x in config.iterdir()}
    checks.append('repeat events do not rewrite configuration')
    setval('network.wan.proto','pppoe');setval('network.wan.username','fixture-user');setval('network.wan.password','fixture-pass')
    clear('eth1');adapter('eth2','02:11:22:33:44:55');run()
    assert get('network.wan.device')=='eth2' and get('network.wan.proto')=='pppoe' and get('network.wan.username')=='fixture-user' and get('network.wan.password')=='fixture-pass'
    checks.append('same USB adapter renumber follows MAC and preserves PPPoE credentials')
    adapter('eth1','02:11:22:33:44:66');run();assert get('network.wan.device')=='eth2'
    checks.append('second USB adapter does not displace established WAN')
    clear('eth2');run();assert get('network.wan.device')=='eth2'
    checks.append('missing established adapter does not silently select another adapter')
    setval('network.wan.device','eth1');run();assert get('network.wan.device')=='eth1'
    checks.append('administrator WAN device override retained')
    initial();adapter('eth0','02:11:22:33:44:00',usb=True);adapter('wlan0','02:11:22:33:44:88',usb=True,wireless=True);adapter('eth3','02:11:22:33:44:99',usb=False);run(startup);assert not get('network.wan.device')
    checks.append('built-in LAN, Wi-Fi and non-USB Ethernet cannot become WAN')
    adapter('eth1','02:11:22:33:44:55');adapter('eth2','02:11:22:33:44:66');run();assert not get('network.wan.device')
    checks.append('ambiguous first-boot multiple USB adapters leave WAN unassigned')
    initial();adapter('eth1','02:11:22:33:44:55',driver='cdc_mbim');run(startup);assert not get('network.wan.device')
    checks.append('unsupported modem/net driver excluded')
    setval('network.lan.ipaddr','10.20.30.1');setval('network.wan.proto','pppoe');before={x.name:x.read_bytes() for x in config.iterdir()};run(startup);assert before=={x.name:x.read_bytes() for x in config.iterdir()}
    checks.append('initialized marker preserves later custom and restored upgrade settings')
    initial();board.write_text('pine64,rockpro64\n');before={x.name:x.read_bytes() for x in config.iterdir()};run(startup);assert before=={x.name:x.read_bytes() for x in config.iterdir()}
    checks.append('foreign board receives no Firefly defaults')
report={'result':'PASS','count':len(checks),'checks':checks,'environment':'Production shell bodies under host /bin/sh with only absolute sysfs/config paths redirected; real UCI CLI from pinned upstream commit66127cd76c5d0bd46d5a90302cc6110f53a4e2f8; temporary ordinary fake sysfs; logger and ubus mocked','uci_sha256':hashlib.sha256(a.uci.read_bytes()).hexdigest()}
a.report.write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))
