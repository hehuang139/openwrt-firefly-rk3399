# Linux 6.12.112 Firefly RK3399 device tree

The source include closure is pinned to Linux stable `v6.12.112`, matching the kernel shipped by OpenWrt 25.12.6 rockchip/armv8. `upstream-manifest.json` records every source URL, file SHA256 and the one upstream header symlink. Original SPDX headers and licenses are retained.

`rk3399-firefly-openwrt.dts` keeps the original Firefly compatible and upstream GMAC wiring, gives the onboard USB hub GPIO2_A4 reset output high, enables a heartbeat LED, and uses conservative eMMC HS200. Both SD and eMMC controllers remain enabled. Native Linux 6.12 `fcs,fusb302` is deliberately retained because the current FUSB302 driver matches it.

Build in the supplied Docker builder:

```sh
python3 source/board/build.py --output work/new-board-build
python3 source/board/validate.py --build work/new-board-build --report work/new-board-validation.json
```

The actual release DTB is `work/board/rk3399-firefly-openwrt.dtb`. Validation checks the GMAC properties against the unmodified upstream DTB, required release kernel driver configuration, hub reset, MMC modes, serial console and repeated byte-identical compilation. Existing upstream DTC warning signatures are compared against the adapted tree.

Wi-Fi uses Ampak AP6356S. The OpenWrt package `brcmfmac-nvram-4356-sdio` supplies `brcmfmac4356-sdio.AP6356S.txt`; the image must also provide `brcmfmac4356-sdio.firefly,firefly-rk3399.txt` pointing to that NVRAM. Firmware and driver packages are `cypress-firmware-4356-sdio` and `kmod-brcmfmac`. Wi-Fi is optional and disabled in initial router settings; the primary LAN is the built-in Ethernet port.
