# SPDX-License-Identifier: MIT
# Standalone ImageBuilder, Linux DTB, native U-Boot and TF-A environment.
FROM ubuntu:22.04
ENV DEBIAN_FRONTEND=noninteractive
ARG http_proxy
ARG https_proxy
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential flex bison gawk gettext git libncurses-dev libssl-dev \
    gcc-aarch64-linux-gnu gcc-arm-linux-gnueabihf libgnutls28-dev \
    python3 python3-dev python3-distutils python3-setuptools python3-pyelftools \
    rsync swig unzip zlib1g-dev file wget curl ca-certificates subversion \
    libelf-dev pkg-config zstd xz-utils bzip2 lz4 time jq patch perl \
    bc cpio dosfstools e2fsprogs mtools device-tree-compiler u-boot-tools \
    squashfs-tools qemu-user-static gpg xxd fakeroot fdisk kmod \
    && rm -rf /var/lib/apt/lists/*
RUN groupadd --gid 1000 builder && useradd --uid 1000 --gid builder --create-home builder
USER 1000:1000
WORKDIR /project
ENV LC_ALL=C.UTF-8 LANG=C.UTF-8
