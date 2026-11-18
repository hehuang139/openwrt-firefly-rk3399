#!/bin/sh
# SPDX-License-Identifier: MIT
set -eu
src=$(realpath "$1")
build=$(realpath -m "$2")
model=$(dirname "$(realpath "$0")")
[ "$(cat "$src/VERSION")" = 10.2.0 ]
if ! cmp -s "$model/firefly-rk3399.c" "$src/hw/arm/firefly-rk3399.c"; then
    cp "$model/firefly-rk3399.c" "$src/hw/arm/firefly-rk3399.c"
fi
if ! grep -q 'CONFIG_FIREFLY_RK3399' "$src/hw/arm/meson.build"; then
    printf "\narm_ss.add(when: 'CONFIG_FIREFLY_RK3399', if_true: files('firefly-rk3399.c'))\n" >> "$src/hw/arm/meson.build"
fi
if ! grep -q '^config FIREFLY_RK3399$' "$src/hw/arm/Kconfig"; then
    cat >> "$src/hw/arm/Kconfig" <<'KCONFIG'

config FIREFLY_RK3399
    bool
    depends on AARCH64 && TCG
    select ARM_GIC
    select SERIAL_MM
    select SDHCI
KCONFIG
fi
config="$src/configs/devices/aarch64-softmmu/firefly.mak"
if [ ! -f "$config" ]; then
    printf 'CONFIG_FIREFLY_RK3399=y\n' > "$config"
fi
mkdir -p "$build"
cd "$build"
if [ ! -f build.ninja ]; then
    "$src/configure" --target-list=aarch64-softmmu \
        --with-devices-aarch64=firefly --without-default-devices \
        --without-default-features --enable-tcg --enable-fdt=system \
        --disable-download --disable-docs
fi
ninja -j "${JOBS:-16}" qemu-system-aarch64
