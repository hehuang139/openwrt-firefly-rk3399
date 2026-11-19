# Firefly RK3399 · OpenWrt 25.12.6

> **原版 DDR3 Rev 1.0：请使用 VSEL1 test2。** 旧 test1 的 TF、eMMC 和两份 sysupgrade 中，Linux FIT 的 CPU 休眠 bank 都是 0。相同接线在 Ubuntu 实板上已复现启动故障。详见 [VSEL 修复、校验和下载说明](VSEL.md)。

原版 **Firefly-RK3399 DDR3** 的主路由固件。2026-11-17 核对并选用 OpenWrt 最新稳定版 **25.12.6**，官方内核 **6.12.112**、匹配 ABI 驱动和 APK 软件包；新增原板设备树、原生 DDR3 U-Boot、USB WAN 选择和 eMMC 安装器。当前发布代号 `test1`。

## 下载与开始

- [test1 发布页](https://github.com/hehuang139/openwrt-firefly-rk3399/releases/tag/v25.12.6-firefly-test1)：TF/eMMC 镜像、刷机包、完整源码包及 SHA256SUMS。
- 首次使用下载 `*-flash-kit.zip`，按 [INSTALL.md](INSTALL.md) 先写 TF，再安装 eMMC。
- 重新构建请下载 Release 中的 `*-source.tar.gz`，解压到新的目录；其中包含被冻结的官方 ImageBuilder、APK 缓存、启动器源码和所有脚本。Git 仓库保留适配源码及固定资产，下载工具和 APK 缓存由 Release 源码包提供。
- 初次开发阅读 [DEVELOPMENT.md](DEVELOPMENT.md)。

## 默认配置

| 项目 | 配置 |
| --- | --- |
| 板载 RJ45 | LAN，`192.168.50.1/24` |
| LAN DHCP | `192.168.50.100–249` |
| USB 千兆网卡 | WAN，默认 DHCP；中文 LuCI 可改 PPPoE |
| 建议网卡 | USB 3.0 RTL8153；同时包含 AX88179、ASIX、CDC Ethernet/NCM 驱动 |
| 管理 | 中文 LuCI，`https://192.168.50.1`，SSH 用户 `root` |
| 初始密码 | 无预设密码，首次登录立即设置 |
| Wi-Fi | 默认关闭，启用时设置地区、加密和密码 |
| 存储 | TF/eMMC 独立镜像；512 MiB 根分区 |
| 启动器 | U-Boot 2025.10 + TF-A 2.13，eMMC 启动器先扫描 TF 救援卡 |

接线：`光猫/上级网络 → USB 网卡（WAN）`，`板载 RJ45（LAN）→ 电脑/内网交换机`。首次只插一张 USB 网卡，系统按 USB 父设备、驱动和 MAC 识别，重编号后跟随原网卡；多个候选首次同时出现时，在 LuCI 手动选择。WAN 默认拒绝管理连接。上级网络若也使用 `192.168.50.0/24`，先修改本机 LAN 网段。

## 刷机文件

文件在 `outputs/test1/`：

- `openwrt-25.12.6-firefly-rk3399-sd-test1.img.gz`：首次启动，Etcher 写入 TF。
- `openwrt-25.12.6-firefly-rk3399-emmc-test1.img.gz`：从本项目 TF 系统安装到 eMMC，配合 `manifest.json`。
- 名称含 `sd-sysupgrade` / `emmc-sysupgrade`：已运行本项目 OpenWrt 后升级，按当前启动介质选择，附有 OpenWrt 板型元数据。

首次从 TF 验证启动、板载网口、USB WAN 和重启，再安装 eMMC。详细命令见 [INSTALL.md](INSTALL.md)。这是整盘 raw 镜像，不能在 Rockchip 工具中当作 `update.img` 使用。

## 构建与开发

步骤和原理见 [DEVELOPMENT.md](DEVELOPMENT.md)，固定输入与许可证见 [SOURCE-NOTICE.md](SOURCE-NOTICE.md)。在新解压的源码包中：

```sh
docker build --network host -t firefly-openwrt-builder:20261117 \
  -f source/build/Dockerfile.standalone .
bash source/rebuild.sh
```

脚本校验固定输入，重编设备树和引导器，使用冻结 APK 缓存离线生成根文件系统，装配 TF/eMMC 工厂与升级镜像。构建过程只操作普通文件。Docker 需要主机正常可用；构建容器的初始依赖安装需要联网。可通过环境变量设置代理。

## 验证与首板检查

实际记录保存在 `source/{board,boot,network,flash,runtime,verification}/` 和 `outputs/test1/validation/`。覆盖设备树、两套引导器的重复构建、真实 UCI 网络逻辑、安装器普通文件写入/读回、ARM64 QEMU 用户态及最终镜像检查。QEMU 用户态不能提供 nft 的 Netfilter 内核接口，相关动态依赖已逐项检查。

另有 [QEMU 板级验证](source/qemu/README.md)，使用发布版原内核和虚拟 eMMC 验证 Linux 启动与根分区读写。

固定输入在全新目录完成了一次离线完整重建，TF/eMMC 的 raw、gzip 和 sysupgrade 产物 SHA256 均相同；记录见 source/verification/reproducibility.json。

首板仍需执行：TF 启动、LAN DHCP/LuCI、USB 网卡千兆协商、DHCP 或 PPPoE 上网、持续下载和双向转发、断电重启、eMMC 安装与拔卡启动。吞吐量和无线稳定性以这些实测结果为准。HDMI 桌面不在本主路由固件的软件包中，管理入口为网口。
