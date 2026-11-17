# 源码与固定输入

定制脚本、网络适配及文档采用 MIT。Linux 设备树及其头文件保留原 SPDX 和版权，U-Boot 为 GPL-2.0+，TF-A 为 BSD-3-Clause；镜像中的 OpenWrt 软件包和无线固件分别沿用原许可证。

- OpenWrt：`v25.12.6`，源码提交 `64900e756efa667774214f9c6b17c113222e01f7`，官方二进制版本 `r33311-981c978eff`。入口：<https://github.com/openwrt/openwrt/tree/v25.12.6>。
- Linux：`6.12.112`，官方源码 <https://cdn.kernel.org/pub/linux/kernel/v6.x/linux-6.12.112.tar.xz>；使用官方 Rockchip ARMv8 内核与同 ABI 模块，配置保存在 `source/board/openwrt-25.12.6-config-6.12`。本包保留构建设备树所需完整 include 闭包。
- U-Boot `2025.10` 与 TF-A `2.13`：原始源码归档、固定 SHA256 和实际修改脚本均在 `source/boot/`。
- 官方 ImageBuilder 原始归档在 `downloads/`，官方 APK 与索引缓存位于 `source/cache/apk/`，固定哈希在 `source/provenance/build-inputs.json`。软件包的源码及源归档可从 <https://sources.openwrt.org/> 和上游包定义取得；精确已安装版本见发布目录的 `.manifest` 与 `.bom.cdx.json`。

这里的源码包包含板级移植源码、引导器源码、构建输入和重建脚本。OpenWrt 官方工具链、内核及软件包以官方二进制重用；若要修改内核或包源码，应使用对应版本的完整 OpenWrt 构建树，并重新构建整套内核和模块。
