# Firefly-RK3399 的 QEMU 板级验证

`firefly-rk3399` 是基于 QEMU 10.2.0 的独立实验板型。它按 RK3399 的地址映射放置 GICv3、UART2 和 eMMC SDHCI，启动 4 个 Cortex-A53、2 个 Cortex-A72，使用 2 GiB RAM。寄存器地址和中断号来自项目中的 Linux `rk3399-base.dtsi`；串口与 SDHCI 使用 QEMU 已有设备，设备树用固定时钟和兼容驱动代替未建模的控制器。实验设备树与实板设备树分开，不能互换。

测试脚本把发布的 eMMC 整盘镜像写到新建的普通文件，读回校验 SHA256 和 MBR；把虚拟芯片容量补齐至 QEMU 要求的 1 GiB，镜像前缀内容不变。随后从写入后的引导分区取出 `kernel.img`，校验并解压原版 Linux 内核，由 QEMU 加载。内核通过虚拟 SDHCI 识别 MMC，按 `PARTUUID` 挂载镜像的实际根分区。脚本通过串口检查 CPU、内核、根分区及 OpenWrt 服务，然后在来宾里写入一个标记，关闭模拟器并重新启动核对。

| 能覆盖 | 下一步仍需上板 |
| --- | --- |
| 整盘镜像写入和读回、Linux ARM64 内核、六核识别、eMMC 分区、ext4 读写和 OpenWrt 启动 | RK3399 BootROM、DDR 初始化、SPL、TF-A、U-Boot、实板设备树、真实 eMMC/TF 和 USB 烧录 |
| 系统启动后的 `ubus` 与 `nft` 命令 | 板载网口、USB 网卡、路由转发和吞吐；实验模型未挂载网卡，也不执行实板专用的 LAN/WAN 首次配置 |

## 复现

在仓库根目录执行。需要 Docker、`curl` 和约 4 GiB 磁盘空间。准备发布页的 `openwrt-25.12.6-firefly-rk3399-emmc-test1.img.gz` 和 `release.json`，放入 `outputs/test1/`。安装器配套的 `manifest.json` 和 `*-sysupgrade-test1.img.gz` 不能替代这两个文件。

```sh
mkdir -p work/qemu-rk3399/source
curl -fL https://download.qemu.org/qemu-10.2.0.tar.xz \
  -o work/qemu-rk3399/qemu-10.2.0.tar.xz
printf '%s  %s\n' \
  9e30ad1b8b9f7b4463001582d1ab297f39cfccea5d08540c0ca6d6672785883a \
  work/qemu-rk3399/qemu-10.2.0.tar.xz | sha256sum -c -
tar -xJf work/qemu-rk3399/qemu-10.2.0.tar.xz -C work/qemu-rk3399/source

docker build -t firefly-qemu:10.2.0 source/qemu
docker run --rm --network none --user "$(id -u):$(id -g)" \
  -v "$PWD:/project" -w /project firefly-qemu:10.2.0 \
  sh source/qemu/build.sh work/qemu-rk3399/source/qemu-10.2.0 work/qemu-rk3399/repro-build

docker run --rm --network none --user "$(id -u):$(id -g)" \
  -v "$PWD:/project" -w /project firefly-qemu:10.2.0 \
  python3 source/qemu/validate.py \
    --qemu work/qemu-rk3399/repro-build/qemu-system-aarch64 \
    --image outputs/test1/openwrt-25.12.6-firefly-rk3399-emmc-test1.img.gz \
    --manifest outputs/test1/release.json \
    --work work/qemu-rk3399/first-run
```

`--work` 必须指向尚不存在的目录。串口日志为 `serial-first.log` 和 `serial-reboot.log`；验证全部完成后写入 `validation.json`。项目内另存有[一次成功验证的结果](validation.json)。如果在性能较低的主机运行，增加 `--timeout 240`（每次启动的秒数）。模型 C 源码和 DTS 按文件头的 GPL-2.0-or-later 使用，构建及验证脚本按 MIT 使用。

跑完检查后，可以进入同一虚拟机的串口，手动查看 `ubus call system board`、`cat /proc/cpuinfo` 和 `cat /proc/mounts`。下面用快照保留已验证的虚拟盘文件：

```sh
docker run --rm -it --network none --user "$(id -u):$(id -g)" \
  -v "$PWD:/project" -w /project firefly-qemu:10.2.0 sh -ec '
    run=work/qemu-rk3399/first-run
    exec work/qemu-rk3399/repro-build/qemu-system-aarch64 \
      -machine firefly-rk3399,accel=tcg -m 2G -nographic -snapshot \
      -kernel "$run/Image" -dtb "$run/firefly-rk3399.dtb" \
      -append "console=ttyS0,1500000n8 root=PARTUUID=fc339902-02 rootwait rw" \
      -drive "file=$run/virtual-emmc.raw,if=none,id=firefly,format=raw" \
      -device emmc,drive=firefly
  '
```

在串口提示时按 Enter，退出 QEMU 按 `Ctrl+A`，再按 `X`。
