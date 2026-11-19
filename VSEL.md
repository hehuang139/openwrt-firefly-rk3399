# 原版 Firefly-RK3399 DDR3 的 CPU VSEL 修订

Rev 1.0、2 GiB DDR3 实板的 CPU 大核稳压器使用 VSEL0 运行。上游板级 DT 在 `0x40` 同时指定 VSEL0 作为休眠 bank，并设置 `regulator-off-in-suspend`。相同板上的 Ubuntu 在驱动注册时因此关闭运行供电；详细的[实板复盘](https://github.com/hehuang139/ubuntu-firefly-rk3399/blob/v22.04.5-vsel1-test2/docs/vsel.md)列出了隔离测试和 GPIO 测量。此项目 test1 的 TF、eMMC 与两种 sysupgrade 中，`/boot.scr` 的 `bootm` 使用 `/kernel.img` 的默认 FIT，Linux 6.12.112 使用内建 `CONFIG_REGULATOR_FAN53555=y`，选中旧 DTB SHA-256 `6c49750c84089def462b8d01479eae9789277941d05c5a8fb49b5cd3cc62ea40`，配置为 `0/1`。U-Boot 自身的控制树单独保留，其配置没有启用 FAN53555 PMIC 驱动。

本次只在 OpenWrt 板级 DTS 覆盖 CPU `0x40` 的 selector 为 1，GPU `0x41` 及两路 suspend-off 保持原样。原版 25.12.6 ImageBuilder 离线生成四份新镜像，分区布局和系统版本不变。构建尾部从每份成品的启动分区读回默认 Linux FIT 并验证 FIT 数据哈希、稳压器身份、供电 phandle、`1/1` 和休眠关断属性。全量检查也会验证设备、分区、内核 ABI 和 sysupgrade 元数据。

从 [VSEL1 test2](https://github.com/hehuang139/openwrt-firefly-rk3399/releases/tag/v25.12.6-firefly-vsel1-test2) 下载。新刷优先选 TF 工厂镜像；已在对应介质运行本项目的，可备份配置后选相同介质的 sysupgrade。旧 test1 只用于追溯。修订版以文件、FIT 和文件系统级检查验证；板上请先确认开机、LAN 和 USB WAN，再安装到 eMMC。
