# Firefly RK3399 主路由网络适配

将 `overlay/` 合并到 ImageBuilder 的 `FILES` 目录，添加 `packages.txt` 中的包。板载千兆口 `eth0` 作为 LAN，管理地址 `https://192.168.50.1`，DHCP 分配 `192.168.50.100–249`；USB 千兆网卡作为 WAN，默认 DHCP，从 LuCI 的 WAN 接口可改为 PPPoE 并填写运营商账号。Wi-Fi 沿用 OpenWrt 默认关闭状态。

`99-firefly-router` 只在 `firefly,firefly-rk3399` 首次初始化时设置网络。保留原有防火墙默认 DHCP/ICMP/IPv6 规则，LAN→WAN 转发及 WAN NAT；WAN 默认拒绝管理连接。以后重启、重新插拔或保留配置升级时不会重置管理员改动。LAN、WAN 必须连接两个不同的网络；板载 LAN 应接电脑或内网交换机，USB WAN 接光猫或上级网络。

`firefly-usb-wan` 根据真实 sysfs USB 父设备和网卡驱动判断候选，仅接受 r8152、ax88179_178a、asix、cdc_ether、cdc_ncm。板载 eth0、Wi-Fi、虚拟接口和 PCIe 网卡均不参与自动 WAN 选择。首次只有一个 USB 网卡时自动选择；同时插多个网卡时留空，需在 LuCI 里指定 WAN 设备。选定后记住网卡 MAC，系统重新编号时跟随同一网卡，同时保留 WAN 的 DHCP/PPPoE 协议及账号设置。原网卡拔下后，不会偷偷改用另一张已连接的网卡。

更换 USB WAN 网卡时，可在 LuCI 中将 WAN 设备改成新的网卡；此后自动选择器尊重手动设备设置。也可以通过 SSH 关闭自动选择：

```sh
uci set firefly_router.main.usb_wan_autoselect=0
uci commit firefly_router
```

需要重新自动识别单个新 USB 网卡时：

```sh
uci -q delete network.wan.device
uci -q delete firefly_router.main.managed_device
uci -q delete firefly_router.main.wan_mac
uci set firefly_router.main.usb_wan_autoselect=1
uci commit network
uci commit firefly_router
/usr/sbin/firefly-usb-wan
```

验证使用从固定 OpenWrt UCI 源码提交构建的实际 CLI，执行生产 shell 逻辑，只将绝对路径改到测试临时目录。测试覆盖首次配置、端口筛选、多个 USB 网卡、拔插重编号、PPPoE 参数保留、手动配置及防火墙规则；结果在 `validation.json`。

```sh
python3 source/network/tests/build-native-uci.py work/native-uci
python3 source/network/tests/test-network.py --uci work/native-uci/uci --report source/network/validation.json
```

脚本不改动上游升级机制。Firefly 的 `supported_devices` 由设备 profile 和整盘镜像元数据提供；原生 `platform.sh` 按当前启动盘确定升级位置，不能刷入其他型号的通用固件。
