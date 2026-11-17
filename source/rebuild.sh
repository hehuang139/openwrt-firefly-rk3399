#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Run from a newly extracted source kit; never operates on a block device.
set -euo pipefail
project=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
cd "$project"
[[ ! -e work && ! -L work ]] || { echo 'Use a freshly extracted source kit without work/.' >&2; exit 1; }
[[ ! -e outputs/test1 && ! -L outputs/test1 ]] || { echo 'outputs/test1 already exists.' >&2; exit 1; }
image=${FIREFLY_BUILD_IMAGE:-firefly-openwrt-builder:20261117}
ib=work/openwrt-imagebuilder-25.12.6-rockchip-armv8.Linux-x86_64
archive=downloads/openwrt-imagebuilder-25.12.6-rockchip-armv8.Linux-x86_64.tar.zst
python3 source/check-inputs.py
mkdir -p work logs outputs
tar --zstd -xf "$archive" -C work
cp -a source/cache/apk/. "$ib/dl/"
docker run --rm --network none --user "$(id -u):$(id -g)" \
  -v "$project:/project" -w /project "$image" \
  python3 source/board/build.py --output work/board > logs/board-build.log 2>&1
cmp work/board/rk3399-firefly-openwrt.dtb source/board/assets/rk3399-firefly-openwrt.dtb
FIREFLY_BUILD_IMAGE="$image" bash source/boot/rebuild.sh > logs/boot-build.log 2>&1
for mode in sd emmc; do
  cmp "work/boot-native/assets/$mode/u-boot-rockchip.bin" "source/boot/assets/$mode/u-boot-rockchip.bin"
done
docker run --rm --network none --user 0:0 -v "$project:/project" -w /project \
  "$image" python3 source/prepare-imagebuilder.py "$ib" \
  --dtb source/board/assets/rk3399-firefly-openwrt.dtb \
  --uboot source/boot/assets/sd/u-boot-rockchip.bin > logs/prepare-imagebuilder.log 2>&1
mkdir -p work/image-files
cp -a source/network/overlay/. work/image-files/
cp -a source/overlay/. work/image-files/
mkdir -p work/image-files/lib/firmware/brcm
ln -s brcmfmac4356-sdio.AP6356S.txt \
  work/image-files/lib/firmware/brcm/brcmfmac4356-sdio.firefly,firefly-rk3399.txt
FIREFLY_BUILD_IMAGE="$image" FIREFLY_OFFLINE=1 bash source/build-image.sh > logs/imagebuilder-build.log 2>&1
python3 source/assemble-release.py "$ib" outputs/test1 > logs/assemble-release.log 2>&1
echo 'Images ready in outputs/test1. See README.md for independent verification.'
