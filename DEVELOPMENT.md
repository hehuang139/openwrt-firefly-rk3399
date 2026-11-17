# 第一次给开发板定制 OpenWrt

面向熟悉 Linux 命令、Git 和基础网络，但没有做过 ARM 板级固件的研发。实例为原版 Firefly-RK3399 DDR3、主路由、TF 首启再装 eMMC。先完整重建固定输入，再分层修改，可以把问题定位到具体环节。

## 1. 四层模型

```text
上电 → BootROM → TPL/DDR → SPL → TF-A/U-Boot → boot.scr → FIT 内核+DTB
                                                         ↓
                                               根文件系统 → init/procd
                                                         ↓
                                            网络、防火墙、SSH、LuCI
```

| 层 | 解决的问题 | 本项目文件 |
| --- | --- | --- |
| 启动链 | 初始化 DDR，从正确存储读取下一阶段 | source/boot/ |
| 内核/设备树 | 驱动是否存在，控制器和 GPIO 如何接线 | source/board/、官方内核和模块 |
| 根文件系统 | 软件包、服务、默认配置 | source/packages.txt、source/network/overlay/、source/overlay/ |
| 镜像布局 | BootROM 偏移、分区、根分区定位、升级识别 | source/prepare-imagebuilder.py、source/assemble-release.py |

U-Boot 的 DTB 服务于启动器，Linux 的 DTB 服务于内核，二者分别构建。引导器的 mmc 编号与 Linux 的 `/dev/mmcblkN` 也可能不同。本项目 U-Boot `mmc0=eMMC/mmc1=TF`，Linux `mmcblk1=TF/mmcblk2=eMMC`。

## 2. 硬件调查和上游调查

第一次移植，先收集：板子准确型号/修订、DDR 类型、eMMC 容量、网口 PHY、USB Hub、无线模块、电源和串口规格。保存旧系统的 dmesg、设备树、分区表；有数据时先备份。芯片相同不保证开发板镜像通用。

再查上游：

1. OpenWrt 稳定版和目标目录 profiles.json，确认有无原板 profile。
2. `target/linux/rockchip/image/armv8.mk`，确认镜像流水线、DTB、U-Boot 名称和 supported_devices。
3. 内核实际 .config，确认 MMC、网口、PHY、稳压器、USB 和所需模块。
4. 同版本 Linux DTS 与 U-Boot 板级 defconfig，核对 DDR、启动介质、GPIO 和引脚。

本次固定 OpenWrt 25.12.6、Linux 6.12.112。依据是 [官方首页](https://openwrt.org/) 的 Current stable release，以及 [官方 profiles.json](https://downloads.openwrt.org/releases/25.12.6/targets/rockchip/armv8/profiles.json) 的 version_number、target、linux_kernel.version 字段；2026-11-17 复核记录在 source/provenance/version-recheck-20261117.json。精确版本和哈希在 source/provenance/。官方 Rockchip 通用内核已包含关键驱动，因此重用其内核、同 ABI 的官方模块与用户空间，补齐 Firefly 板级配置。

## 3. 选择构建工具

| 工具 | 适用修改 | 输出 |
| --- | --- | --- |
| ImageBuilder | 增删现成包、默认配置、组合已有内核及板级文件 | 整机镜像 |
| SDK | 新增或修改用户态软件包 | APK 包 |
| 完整 OpenWrt 源码树 | 更改内核配置、驱动、工具链或正式增加上游设备支持 | 工具链、内核、包和镜像 |

ImageBuilder 不能像完整源码树一样自动编译新内核。本项目增加了 profile，并显式从官方原始内核和新 DTB 生成 FIT。修改内核时，要重新构建内核与模块，不能混用仅版本号相同、ABI 不同的 kmod。

## 4. 先重建固定版本

推荐 x86-64 Linux、Docker、约 20 GiB 可用空间；主机安装 python3、tar、zstd。从 [Release](https://github.com/hehuang139/openwrt-firefly-rk3399/releases/tag/v25.12.6-firefly-test1) 下载完整 source.tar.gz（含固定工具和软件包缓存），解压到新的可写目录，保留软链接。进入项目根目录：

```sh
# 如果需要代理，在执行前设置。
export http_proxy=http://127.0.0.1:7890
export https_proxy=http://127.0.0.1:7890

docker build --network host \
  --build-arg http_proxy --build-arg https_proxy \
  -t firefly-openwrt-builder:20261117 \
  -f source/build/Dockerfile.standalone .

python3 source/check-inputs.py
bash source/rebuild.sh
```

rebuild.sh 要求新目录中没有 work/ 和 outputs/test1/，避免旧中间文件掩盖问题。日志写到 logs/，产物在 outputs/test1/。

脚本实际执行：

1. 校验原始 ImageBuilder、APK 缓存和启动器源码归档。
2. 解压官方 ImageBuilder，放入冻结的软件包和索引缓存。
3. 用 GCC 预处理 DTS，再用 dtc 编译 DTB，与固定产物比较。
4. 交叉编译 TF-A 与两套 U-Boot，与固定启动器比较。
5. 添加 Firefly profile 和升级元数据，把官方内核与新 DTB 装入 FIT。
6. 合并两个 overlay，创建 Firefly 无线 NVRAM 别名。
7. 用 APK 保留正确 UID/GID，离线组合根文件系统和分区镜像。
8. 修复 make_ext4fs 的位图填充，再用只读 fsck 确认干净；装入各介质启动器、设置磁盘 ID、压缩和附加升级元数据。

ImageBuilder 的 APK 安装阶段在容器内用 root 构造目标文件所有权；U-Boot/TF-A 编译使用普通用户。容器只绑定项目目录，构建脚本只操作普通文件。

## 5. 从包和默认配置开始改

增加软件：修改 source/packages.txt，例如添加实际需要的 VPN 或诊断包。冻结缓存只包含本版所需包；新增包必须先在线下载其依赖，再重新生成输入清单。保留包签名检查。

默认文件：目标 `/etc/banner` 对应 source/overlay/etc/banner。文件执行权限、符号链接和属主要一起检查。

首次网络配置：编辑 source/network/overlay/etc/uci-defaults/99-firefly-router。OpenWrt 首次启动执行成功后会删除该脚本；已有配置不会因重启而重置。测试首次行为需要新镜像或恢复默认。

USB WAN 自动选择在 source/network/overlay/usr/sbin/firefly-usb-wan。它按 USB 父设备、驱动和 MAC 识别，处理重编号和用户手动配置。测试使用真实 UCI：

```sh
python3 source/network/tests/build-native-uci.py work/native-uci
python3 source/network/tests/test-network.py \
  --uci work/native-uci/uci --report work/network-validation.json
```

如果修改默认 LAN 地址，检查 DHCP 地址段、防火墙和文档一起更新。每次只改一个目标，记录改动及实际验证。

### 例子：先改 LAN 地址

首次完整重建成功后，将默认地址改成 `192.168.60.1`：

```sh
sed -i 's/192\.168\.50\.1/192.168.60.1/g' \
  source/network/overlay/etc/uci-defaults/99-firefly-router
cp -a source/network/overlay/. work/image-files/
# 当前已有缓存时可以离线；新增包需去掉 FIREFLY_OFFLINE=1 下载依赖。
FIREFLY_OFFLINE=1 bash source/build-image.sh
# 装配要求输出目录不存在，所以给这轮实验单独的名字。
python3 source/assemble-release.py \
  work/openwrt-imagebuilder-25.12.6-rockchip-armv8.Linux-x86_64 outputs/lan60
```

把新 TF 镜像写入卡，电脑自动取地址后访问 `192.168.60.1`。实验目录和镜像内部的固定 test1 名称是两回事；正式发布新版本时，需要统一修改脚本中的版本/产物名称，保存变更和新的验证基线。原有 pins 会拒绝发生变化的网络脚本，这是提醒你审阅差异。

## 6. 设备树怎么改

DTS 描述控制器是否启用、引脚复用、复位 GPIO、供电、时钟、总线设备地址。新软件包无法修复错误的 USB Hub 复位引脚；DTB 也无法增加没有编译进内核的驱动。

source/board/rk3399-firefly-openwrt.dts 包含同版本上游 Firefly DTS，再覆盖需调整的节点。主要处理 USB Hub 复位 GPIO2_A4 和 eMMC HS200；保留 Linux 6.12 驱动要求的 fcs,fusb302 compatible。编译：

```sh
docker run --rm --network none --user "$(id -u):$(id -g)" \
  -v "$PWD:/project" -w /project firefly-openwrt-builder:20261117 \
  python3 source/board/build.py --output work/my-dtb
```

查看 dtc 警告，与未修改的同版本上游 DTB 对照。修改 DTS 后更新固定资产、manifest 和验证输入，重做 FIT 和整盘镜像。

## 7. 启动器怎么改

TPL 负责 DDR 初始化，SPL 加载后续阶段，TF-A 提供安全监控和电源管理接口，U-Boot 读取 boot.scr 和 FIT。源归档及修改脚本在 source/boot/。不要使用另一块 RK3399 LPDDR 板子的 loader。

```sh
FIREFLY_BUILD_IMAGE=firefly-openwrt-builder:20261117 \
FIREFLY_BOOT_WORK=work/boot-experiment \
FIREFLY_BOOT_REPORT=work/boot-experiment-validation.json \
bash source/boot/rebuild.sh
```

这会从源码新建目录编译，不复用旧对象。eMMC 版本允许 TF 救援优先，TF 版本从 TF 读自己的系统。boot.scr 使用 U-Boot 提供的实际 devtype/devnum 查询第二分区 PARTUUID，避免固定 root=/dev/mmcblk0p2 导致多介质下选错盘。

## 8. 镜像布局和升级元数据

本版 raw 镜像共 637534208 字节（608 MiB）：

| 区域 | 起始字节 | 大小 |
| --- | --- | --- |
| MBR | 0 | 512 B |
| 合并启动器 | 32768（LBA64） | 约 9 MiB，位于首分区前 |
| ext4 启动分区 p1 | 33554432（LBA65536） | 32 MiB |
| 对齐间隔 | 67108864 | 32 MiB |
| ext4 根分区 p2 | 100663296（LBA196608） | 512 MiB |

偏移来自实际 ptgen 输出，不能只按分区标称大小猜。本次安装器曾按预估布局编写，实际构建后已改为上述布局并重新测试。

TF 磁盘 ID 为 fc339901，eMMC 为 fc339902。分别产生的 PARTUUID 使救援卡与 eMMC 同时存在时能区分根分区。

工厂镜像是纯 gzip；sysupgrade 在 gzip 后附有 fwtool 元数据，含 firefly,firefly-rk3399 板型。Python gzip.open() 读到底可能拒绝这些尾部数据，因此写入器和升级文件必须按格式区分，重新打包不能丢掉升级元数据。

## 9. 验证顺序

先检查：输入 SHA256、DTS 编译、引导器配置、FIT 解包、分区表、ext4 只读 fsck、rootfs 文件/权限、APK 架构和内核 ABI、模块 vermagic。再执行真实 UCI 测试、安装器普通文件写入和读回测试、ARM64 QEMU 程序测试。最终镜像检查示例：

```sh
docker run --rm --network none --user 0:0 \
  -v "$PWD:/project" -w /project firefly-openwrt-builder:20261117 \
  python3 source/verification/verify-image.py \
  --mode sd \
  --image outputs/test1/openwrt-25.12.6-firefly-rk3399-sd-test1.img.gz \
  --inputs source/verification/inputs.json \
  --imagebuilder work/openwrt-imagebuilder-25.12.6-rockchip-armv8.Linux-x86_64 \
  --scratch work/image-verification \
  --report outputs/test1/validation/sd-image.json
```

检查器按固定基线判断产物是否一致。你主动修改内核、DTB 或 overlay 后，需要审阅并更新相应 pin，不能只改哈希让检查变绿。

上板步骤见 INSTALL.md。按故障层定位：

| 现象 | 优先检查 |
| --- | --- |
| 无串口输出 | 电源、TTL 电平/线序、1500000 波特率、TPL、DDR、启动介质 |
| U-Boot 找不到系统 | 分区、ext4 支持、boot.scr 路径、启动顺序 |
| 内核无法挂根 | PARTUUID、介质编号、MMC 驱动、文件系统类型 |
| 系统运行但 LAN 不通 | PHY/时钟/复位、驱动、链路、UCI、网段 |
| LAN 正常而 WAN 不通 | USB3 链路/供电、驱动、WAN 设备、DHCP/PPPoE、VLAN、NAT/DNS |
| 大流量掉线 | 供电、温度、网卡驱动、线材、内核日志 |

本项目还做了全新目录离线重建，并比较 TF/eMMC 的 raw、gzip、sysupgrade、启动器、DTB、FIT 和 1989 项根文件系统记录，17 项比较通过。装配中的 e2fsck 使用实际生效的 `E2FSCK_TIME=1792273538` 固定时间戳；只设置 SOURCE_DATE_EPOCH 不会固定这个工具写入的时间。

## 10. 如果需要完整源码编译

例如你要改内核驱动，就从对应版本重新建树：

```sh
git clone --branch v25.12.6 --depth 1 https://github.com/openwrt/openwrt.git openwrt-full
cd openwrt-full
./scripts/feeds update -a
./scripts/feeds install -a
make menuconfig
# 选择 Target System: Rockchip / Subtarget: ARMv8。
# 原板 profile 需要按本项目配置移入源码树；它未内置在官方版本。
make defconfig
make download -j8
make -j"$(nproc)"
# 失败后用 make -j1 V=s 看首个真正错误。
```

严格重复构建还要按官方 feeds.buildinfo 固定各 feed 提交；仅执行 feeds update -a 会受到仓库分支后续更新影响。

完整树中加入 Firefly Device profile、DTS、U-Boot 设备定义和包内默认配置，让构建系统负责生成 FIT。上面是完整构建流程入口，不能省略板级补丁后直接选择其他板型刷写。正式做长期维护时，建议将本项目显式装配步骤逐步整合成上游风格的设备支持补丁。

## 11. 维护与开源

Git 保留 DTS、引导器改动、软件包列表、overlay、装配脚本和验证记录。大镜像放 Release，输入归档/缓存用固定 SHA256，构建中间目录不提交。

发布记录上游版本、板型、默认网络、镜像格式、刷写步骤、实际测试结果和具体剩余问题；保留上游许可证，用 manifest/BOM 追溯软件包版本。升级 OpenWrt 要重新核对 DT 绑定、内核 ABI、包管理器、启动脚本和 sysupgrade，再跑整个验证流程。

## 12. 查证“最新版本”的操作

不要从版本号的大小推断哪个稳定版最新。先看官方主页对 Current stable release 的声明，再查看该版目标目录的元数据，最后核对实际下载文件的 SHA256：

```sh
curl -fL https://openwrt.org/ -o openwrt-home.html
curl -fL https://downloads.openwrt.org/releases/25.12.6/targets/rockchip/armv8/profiles.json -o profiles.json
python3 - <<'PY'
import json
p = json.load(open('profiles.json'))
for key in ['version_number', 'version_code', 'target', 'arch_packages', 'linux_kernel']:
    print(key, p[key])
print([name for name in p['profiles'] if 'firefly' in name])
PY
```

本次记录对应 2026-11-17：官方首页声明稳定版 25.12.6、2026-10-18 发布；profiles.json 声明目标 rockchip/armv8、内核 6.12.112。未来重做项目时，应重新查询并保存原始元数据，不能把这份文档中的版本永久视为最新。
