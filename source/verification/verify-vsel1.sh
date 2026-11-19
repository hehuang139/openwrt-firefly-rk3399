#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
set -euo pipefail
cd -- "$(dirname -- "$0")/../.."
for mode in sd emmc sd-sysupgrade emmc-sysupgrade; do
  python3 source/verification/verify-image.py \
    --mode "$mode" \
    --image "outputs/vsel1-test2/openwrt-25.12.6-firefly-rk3399-$mode-vsel1-test2.img.gz" \
    --inputs source/verification/inputs-vsel1-test2.json \
    --imagebuilder work/openwrt-imagebuilder-25.12.6-rockchip-armv8.Linux-x86_64 \
    --scratch work/image-verification \
    --report "outputs/vsel1-test2/$mode-validation.json"
done
