# Firefly RK3399 OpenWrt boot components

This builds native Firefly DDR3 boot components from the same versions selected by OpenWrt 25.12.6: U-Boot 2025.10 and TF-A 2.13. Sources are pinned to the official OpenWrt SHA256 values. The Firefly U-Boot DTS includes `rk3399-sdram-ddr3-1600.dtsi` and uses native TPL DDR3 initialization.

Two policies are built:
- SD: SPL reads its U-Boot from SD, and U-Boot scans only SD.
- eMMC: SPL reads its U-Boot from eMMC, while U-Boot scans SD rescue media before eMMC.

U-Boot MMC aliases differ from Linux: U-Boot `mmc0` is eMMC and `mmc1` is SD. OpenWrt `boot.scr` obtains the root PARTUUID from the medium actually used to load the boot files, so the kernel is not tied to a changing Linux MMC index.

Persistent U-Boot environment storage is disabled. First-stage eMMC runs at no more than 52 MHz with HS400 disabled. Linux uses HS200 independently.

Build with the supplied builder image by running `bash source/boot/rebuild.sh`. Output is under `work/boot-native/`, with the validation report at `source/boot/validation.json`; the script refuses to reuse a previous build directory. Source archives, upstream licenses, patch details and a fixed manifest accompany this source directory.

For a fresh second build, set `FIREFLY_BOOT_WORK=work/new-boot-build` and `FIREFLY_BOOT_REPORT=work/new-boot-build-validation.json`. Both build locations must be new ordinary directories under project `work/`. The default build environment is `firefly-openwrt-builder:20261117`; set `FIREFLY_BUILD_IMAGE` to select another compatible image. The recorded native boot builds used its Ubuntu 22.04 board-builder base, with the same cross compilers.

The TF-A Cortex-M0 Makefile receives only `-fno-pie` / `-no-pie` host compiler fixes. The firmware remains fixed-address ARM ELF32 and has no userspace runtime dependency. Optional OP-TEE images are not included; the emitted U-Boot FIT contains U-Boot, BL31 and the native Firefly control DTB, checked from the compiled output.
