#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
set -euo pipefail
project=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
cd "$project"
ib="$project/work/openwrt-imagebuilder-25.12.6-rockchip-armv8.Linux-x86_64"
if [[ ${1:-} != --inside ]]; then
  network=host
  [[ ${FIREFLY_OFFLINE:-0} != 1 ]] || network=none
  exec docker run --rm --network "$network" --user 0:0 -v "$project:/project" -w /project \
    -e FIREFLY_OFFLINE="${FIREFLY_OFFLINE:-0}" \
    -e http_proxy="${http_proxy:-http://127.0.0.1:7890}" \
    -e https_proxy="${https_proxy:-http://127.0.0.1:7890}" \
    -e HTTP_PROXY="${HTTP_PROXY:-http://127.0.0.1:7890}" \
    -e HTTPS_PROXY="${HTTPS_PROXY:-http://127.0.0.1:7890}" \
    "${FIREFLY_BUILD_IMAGE:-firefly-openwrt-builder:20261117}" bash source/build-image.sh --inside
fi
packages=$(sed '/^#/d; /^$/d' source/packages.txt | tr '\n' ' ')
offline=()
[[ ${FIREFLY_OFFLINE:-0} != 1 ]] || offline=(FIREFLY_OFFLINE=1)
make -C "$ib" image FORCE=1 PROFILE=firefly_firefly-rk3399 \
  PACKAGES="$packages" FILES="$project/work/image-files" ROOTFS_PARTSIZE=512 \
  BIN_DIR="$project/work/imagebuilder-output" V=s "${offline[@]}"
