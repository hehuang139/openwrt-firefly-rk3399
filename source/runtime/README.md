# ARM64 runtime checks

`verify-runtime.py` runs binaries from the final OpenWrt rootfs with `qemu-aarch64-static -cpu cortex-a72`. The project is mounted read-only. UCI input and runtime scratch files are created only in an ephemeral container directory; network access is disabled.

The final run passed **52 / 52** checks:

- Exact installed/source parity for the eMMC installer and the three network scripts.
- Actual AArch64 BusyBox ash execution, native target UCI parsing, dnsmasq version output and uhttpd usage output.
- Target Python 3.13.18 execution, installer standard-library imports plus SHA256/gzip/struct/JSON operations, and the installed eMMC installer `--help` command.
- Target ash syntax parsing of the network defaults, USB WAN selector and hotplug script.
- Recursive AArch64 ELF dependency closure for BusyBox, UCI, Python, nft, uhttpd and dnsmasq. Program headers and PT_DYNAMIC are parsed directly because OpenWrt strips section headers.
- OpenWrt release identity.

The actual `nft --version` attempt exits with `Unable to initialize Netlink socket: Protocol not supported` under QEMU user mode. Its output is retained in `validation.json` under `limitations`; the nft dependency closure passed. Packet filtering and board network traffic require the target kernel and hardware.

Reproduce from the project root after `source/build-image.sh` completes:

```sh
mkdir -p work/runtime-results
docker run --rm --network none \
  -v "$PWD:/project:ro" \
  -v "$PWD/work/runtime-results:/results" \
  -w /project firefly-openwrt-builder:20261117 \
  python3 source/runtime/verify-runtime.py \
    --rootfs work/openwrt-imagebuilder-25.12.6-rockchip-armv8.Linux-x86_64/build_dir/target-aarch64_generic_musl/root-rockchip \
    --report /results/validation.json
```

`validation.json` preserves executed commands, exit codes, output and all checked binary SHA256 values. The separate `source/network/validation.json` runs the production network logic with actual native UCI and controlled sysfs fixtures; `source/flash/validation.json` covers installer decisions and ordinary-file write/readback.
