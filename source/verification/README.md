# Independent image verification

Run in the build container, using ordinary image files only. No filesystem is mounted and no block device is opened.

```sh
python3 source/verification/verify-image.py \
  --mode sd --image outputs/IMAGE.img.gz \
  --inputs source/verification/inputs.json \
  --imagebuilder work/openwrt-imagebuilder-25.12.6-rockchip-armv8.Linux-x86_64 \
  --scratch work/image-verification \
  --report outputs/validation/sd-image.json
```

The fixed input JSON contains version/revision/kernel ABI/board, official raw ARM64 kernel, new Firefly DTB, intended source overlay file pins, required packages and mode-specific MBR geometry/bootloader/FIT/boot.scr pins. `freeze-inputs.py` recreates these pins from completed `release.json` and the fixed source assets. Paths in component pins are project-relative; paths in `files` are relative to the root filesystem. The verifier requires `rootfs_type: "ext4"` or `"squashfs"`.

It checks the complete gzip stream and declared fwtool footer policy, original Firefly support identity, exact MBR layout/disk ID, native DDR3 bootloader bytes, both ext4 filesystems with read-only e2fsck, direct inode UID/GID of boot and root system files, legacy boot script header/data CRC and PARTUUID medium binding, FIT hashes and decompressed official kernel/new DTB content, complete root filesystem extraction and fixed files, release and APK repository keys, every package architecture/kernel ABI dependency and every ARM64 kernel module vermagic.

`test-verifier.py` generates small files with actual dtc, mkimage, fwtool, mke2fs and debugfs. Its 20 fixtures cover valid formats and reject missing metadata, truncation, checksum corruption, changed kernel content, wrong ext4 ownership, missing inodes, symlink input and path escapes. `fixtures.json` records the results. Full image reports under `outputs/test1/validation/` record separate SD/eMMC factory and sysupgrade checks.

Each `modes` entry also declares `has_metadata`: `true` for OpenWrt sysupgrade images with appended fwtool metadata, `false` for a pure gzip installer payload. The latter rejects all trailing content. Frozen inputs provide `sd`, `emmc`, `sd-sysupgrade` and `emmc-sysupgrade` modes, each with its own exact components and disk signature.

To compare a fresh source-kit build, use `compare-rebuild.py` with `--original /path/to/first/project --rebuilt /path/to/fresh/project --report /path/to/comparison.json`. It checks all six image formats, boot assets, the generated FIT, fixed filesystem clocks and the full rootfs inventory. Run it as container root to read the target root-owned private directories. The completed comparison in `reproducibility.json` passes 17/17 checks with byte-identical images and 1,989 matching rootfs entries.
