# 安装与首启

适用：原版 Firefly-RK3399 DDR3，eMMC 标称 8 GB 或更大。先准备 TF 卡、读卡器、可靠电源、网线和 USB 千兆网卡。刷写 TF 会清空 TF；安装 eMMC 会覆盖原系统和数据。

## 1. 核验与写 TF

在发布目录核验：

```sh
sha256sum -c SHA256SUMS
```

用 balenaEtcher 选择 `openwrt-25.12.6-firefly-rk3399-sd-test1.img.gz`，仔细选择 TF 读卡器并完成写入、校验。Etcher 可以直接读取 gzip。也可解压后用你熟悉的 Linux 磁盘写入工具；确认目标设备容量和型号后再写。

断开板子电源，插 TF，板载 RJ45 接电脑，USB 网卡先不接运营商线路，接电启动。电脑设为自动获取地址，浏览器打开 <https://192.168.50.1>；初次证书为本机证书。用户名 `root`，首次设置密码。若电脑未获取地址，可临时设置 `192.168.50.2/24` 后访问管理页。

若管理页不可达，先看链路指示灯和电脑 IP，再使用 3.3 V USB-TTL 串口收集启动日志（`1500000 8N1`，不要接 VCC）。已有 SPI/eMMC 启动器可能影响 TF 启动优先级；本包不会主动擦除 SPI。保留 TF，按启动日志定位，避免盲目覆盖启动区。

## 2. 配置主路由

推荐 USB 3.0 RTL8153 网卡。先只连接一张 USB 网卡，再将其接光猫/上级网络。默认 WAN 自动获取 IP。需要拨号时，在“网络 → 接口 → WAN”选择 PPPoE，填写运营商账号密码。运营商要求 VLAN 时，按实际业务配置 VLAN。

检查 LAN、WAN 属于不同网段。第一次先验证网页访问、DNS、持续下载、重启；再把其他家用设备迁移到该路由。Wi-Fi 默认关闭；板载无线的覆盖能力和性能需要实测，家用覆盖可以配独立 AP。

## 3. 从 TF 安装 eMMC

先确保 TF 系统运行正常，eMMC 分区全部未挂载。安装器核对原板 compatible、TF 根分区、eMMC 控制器路径、CID、容量和占用情况。

电脑终端进入发布目录，上传 **不含 sysupgrade 的 eMMC 镜像** 和 manifest：

```sh
scp -O openwrt-25.12.6-firefly-rk3399-emmc-test1.img.gz manifest.json root@192.168.50.1:/root/
ssh root@192.168.50.1
```

新 OpenSSH 使用 SFTP 作为默认 scp 协议，`-O` 使用本固件 Dropbear 支持的传统协议。进入板子后，先只检查：

```sh
firefly-install-emmc \
  --image /root/openwrt-25.12.6-firefly-rk3399-emmc-test1.img.gz \
  --manifest /root/manifest.json
```

看到 `CHECK PASS` 代表目标和源镜像检查通过，此命令不写 eMMC。推荐把容量足够的外部 ext4 存储挂载到 `/mnt/backup`，备份完整原 eMMC 用户区后安装：

```sh
firefly-install-emmc \
  --image /root/openwrt-25.12.6-firefly-rk3399-emmc-test1.img.gz \
  --manifest /root/manifest.json \
  --write --backup-dir /mnt/backup
```

备份空间需要大于 eMMC 整体容量，FAT32 无法保存该大文件。如果已另行保存原数据并决定覆盖，可将最后一行换成 `--write --no-backup`。写入后自动完整读回 SHA256 并清除旧 GPT 尾部；日志保存在 `/root/emmc-install-logs/`。只有出现 `INSTALL PASS` 才关机：

```sh
poweroff
```

等待关闭后断电，取出 TF，再接电。eMMC 镜像为全新系统，需要再次设置密码和上网配置；TF 上的配置不会自动复制到 eMMC。把这张 TF 留作救援卡。

## 4. 后续升级

在中文 LuCI 的备份/升级页面上传对应启动介质的 `*-sysupgrade-test1.img.gz`。系统板型校验必须通过；不要强制刷入其他 RK3399 板型的镜像。工厂 `.img.gz` 用于写卡和 eMMC 安装，升级镜像还带有 OpenWrt 要求的元数据。

根分区固定 512 MiB，空余 eMMC 空间没有自动扩容。初版先完成主路由首板检查后再调整分区；更改布局前保存配置和原镜像。

## 5. 建议保存的首板记录

```sh
ubus call system board
cat /etc/openwrt_release
ip -br link
ip -br addr
ethtool eth0
lsusb -t
uci show network
logread
dmesg
```

`uci show network` 可能含拨号账号密码，对外分享前删除相关字段。确认 USB 网卡接口名后用 `ethtool 接口名` 检查协商，用 `lsusb -t` 检查是否跑在 USB 3.0。通过本地有线客户端和服务端运行 iperf3，分别验证 LAN 吞吐与跨 WAN 路由吞吐，并记录是否启用软件流量卸载。
