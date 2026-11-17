# Build container

`Dockerfile` starts from Ubuntu 22.04 and contains the ImageBuilder, DTB, U-Boot and TF-A prerequisites, including both AArch64 and ARMHF cross compilers and Python pyelftools. The default container user is UID/GID1000; the APK installation phase requires the root override below.

```sh
docker build --network host \
  --build-arg http_proxy=http://127.0.0.1:7890 \
  --build-arg https_proxy=http://127.0.0.1:7890 \
  -t firefly-openwrt-builder:20261117 -f source/build/Dockerfile .
```

`Dockerfile.standalone` keeps the equivalent dependency definition for compatibility. `Dockerfile.local` is an optional cache shortcut for the earlier local builder; the public build uses `Dockerfile`.

For the actual ImageBuilder `make image`/`make manifest` installation phase, run this container with `--user 0:0` so APK3 can preserve package UID/GID metadata. The default UID1000 is sufficient for `make info` and ordinary host tools. This root override is for constructing the target directory in ImageBuilder; full OpenWrt source compilation should still run as an unprivileged user.

Probe host tools, Python dependencies and actual AArch64/ARMHF object compilation:

```sh
docker run --rm --network none \
  -v "$PWD:/project" -w /project firefly-openwrt-builder:20261117 \
  python3 source/build/probe.py --report source/build/probe-validation.json
```

After extracting ImageBuilder, add `--imagebuilder work/openwrt-imagebuilder-25.12.6-rockchip-armv8.Linux-x86_64` to also execute its bundled mkimage and APK host wrappers.
