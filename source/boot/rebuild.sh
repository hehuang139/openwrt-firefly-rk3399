#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
set -euo pipefail
project=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)
cd "$project"
if [[ ${1:-} != --inside ]]; then
  image=${FIREFLY_BUILD_IMAGE:-firefly-openwrt-builder:20261117}
  exec docker run --rm --network none --user "$(id -u):$(id -g)" \
    -v "$project:/project" -w /project -e SOURCE_DATE_EPOCH=1759708800 -e TZ=UTC \
    -e KBUILD_BUILD_USER=firefly -e KBUILD_BUILD_HOST=buildhost \
    -e FIREFLY_BOOT_WORK="${FIREFLY_BOOT_WORK:-work/boot-native}" \
    -e FIREFLY_BOOT_REPORT="${FIREFLY_BOOT_REPORT:-source/boot/validation.json}" \
    "$image" bash source/boot/rebuild.sh --inside
fi
python3 - <<'PY'
from pathlib import Path
import hashlib
checks={'u-boot-2025.10.tar.bz2':'b4f032848e56cc8f213ad59f9132c084dbbb632bc29176d024e58220e0efdf4a','trusted-firmware-a-v2.13.tar.gz':'afb5c408392fcec840bd30de9b02a236b0108142024f9853b542b596b0d894e3'}
for n,h in checks.items(): assert hashlib.sha256((Path('source/boot')/n).read_bytes()).hexdigest()==h,n
PY
build=${FIREFLY_BOOT_WORK:-work/boot-native}
case "$build" in work/*) ;; *) echo "Build directory must be project-relative under work/" >&2; exit 1;; esac
[[ "$build" != *..* && "$build" != *$'\n'* && "$build" != *$'\r'* ]]
[[ ! -e "$build" && ! -L "$build" ]]
mkdir -p "$build/src" "$build/assets/sd" "$build/assets/emmc"
tar -xzf source/boot/trusted-firmware-a-v2.13.tar.gz -C "$build/src"
python3 - "$build" <<'PY'
from pathlib import Path
import sys
p=Path(sys.argv[1])/'src/trusted-firmware-a-2.13/plat/rockchip/rk3399/drivers/m0/Makefile'
s=p.read_text();a='CFLAGS\t\t\t:= -ffunction-sections';b='LDFLAGS\t\t\t:= -Wl,--gc-sections';assert a in s and b in s
p.write_text(s.replace(a,'CFLAGS\t\t\t:= -fno-pie -ffunction-sections').replace(b,'LDFLAGS\t\t\t:= -no-pie -Wl,--gc-sections'))
PY
make -C "$build/src/trusted-firmware-a-2.13" -j8 PLAT=rk3399 CROSS_COMPILE=aarch64-linux-gnu- \
  M0_CROSS_COMPILE=arm-linux-gnueabihf- BUILD_BASE="$project/$build/tfa" bl31
for mode in sd emmc; do
  mkdir "$build/src/$mode"
  tar -xjf source/boot/u-boot-2025.10.tar.bz2 -C "$build/src/$mode"
  tree="$build/src/$mode/u-boot-2025.10"
  output="$project/$build/$mode"
  python3 source/boot/prepare.py "$tree" "$mode"
  make -C "$tree" O="$output" CROSS_COMPILE=aarch64-linux-gnu- firefly-rk3399_defconfig
  "$tree/scripts/kconfig/merge_config.sh" -m -O "$output" "$output/.config" source/boot/boot-common.config
  make -C "$tree" O="$output" CROSS_COMPILE=aarch64-linux-gnu- olddefconfig
  make -C "$tree" O="$output" CROSS_COMPILE=aarch64-linux-gnu- \
    BL31="$project/$build/tfa/rk3399/release/bl31/bl31.elf" -j8
  cp "$output"/{idbloader.img,u-boot.itb,u-boot-rockchip.bin,u-boot.dtb} "$build/assets/$mode/"
  cp "$output/.config" "$build/assets/$mode/built.config"
done
python3 source/boot/validate.py --build "$build" --report "${FIREFLY_BOOT_REPORT:-source/boot/validation.json}"
