# Final image validation

The four final compressed images pass 300 independent checks:

| Image | Result |
|---|---|
| TF factory |73/73 PASS|
| eMMC factory |73/73 PASS|
| TF sysupgrade |77/77 PASS|
| eMMC sysupgrade |77/77 PASS|

The verifier's 20/20 format fixtures also pass. Each final rootfs contains 195 packages and 52 kernel modules with the correct AArch64 architecture and exact official 6.12.112 APK/kernel ABI. Both EXT4 filesystems pass read-only e2fsck. Direct inode ownership checks confirm root UID/GID for system and boot files. Rootfs file pins match the intended source overlays, corrected 608 MiB installer geometry and original Firefly Wi-Fi NVRAM symlink.

Full reports: `outputs/test1/validation/*-image.json`. Compact results: `image-validation.json`. Fixed inputs: `inputs.json`. Reproduction: `freeze-inputs.py` and `verify-image.py`.

The verifier found two integration defects before finalization: the official ptgen adds a 32 MiB gap before rootfs, and official make_ext4fs leaves inode bitmap tail padding unset. The installer was corrected and rebuilt; release assembly now repairs both ordinary EXT4 images with pinned e2fsck and requires clean read-only checks before compression.

An independent fresh source-kit build passes 17/17 reproduction checks. Both SD/eMMC raw images, factory gzip and sysupgrade gzip are byte identical; all 1,989 rootfs entries match in type, mode, UID/GID, timestamp and content. `reproducibility.json` records the results. `assembly-review.json` separately records 47/47 checks of the final profile, FIT, scripts, geometry and deterministic filesystem repair.
