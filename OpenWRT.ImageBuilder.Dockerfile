FROM debian:trixie-slim

ARG TARGETARCH

# Install build environment dependencies
RUN apt-get update && \
    # Intall packages by architecture
    if [ "$TARGETARCH" = "arm64" ]; then \
        GRUB_PKGS="grub-efi-arm64-bin"; \
    elif [ "$TARGETARCH" = "amd64" ]; then \
        GRUB_PKGS="grub-efi-amd64-bin"; \
    else \
        printf "Error: Unsupported build architecture" && \
        printf " '%s' for GRUB binaries.\n" "$TARGETARCH" >&2; \
        exit 1; \
    fi && \
    apt-get install -y --no-install-recommends \
    bc binutils-gold bison ccache ecj fastjar flex \
    build-essential gcc g++ help2man texinfo \
    libbsd-dev libelf-dev libncurses-dev zlib1g-dev \
    liblzma-dev mtd-utils meson mold ninja-build \
    pigz pkg-config python3-dev subversion swig \
    gettext libssl-dev xsltproc wget unzip python3 \
    grub-common dosfstools time rsync gawk file \
    python3-setuptools curl net-tools bind9-dnsutils \
    git iputils-ping traceroute mtr rclone zstd \
    u-boot-tools gzip xsltproc xxd make libc6-dev \
    gcc-aarch64-linux-gnu binutils-aarch64-linux-gnu \
    g++-aarch64-linux-gnu device-tree-compiler \
    openssh-server sudo zsh lsb-release gnupg pbzip2 \
    && apt-get clean && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /var/run/sshd

# Download, execute, and clean up the LLVM installation script automatically
RUN wget https://apt.llvm.org/llvm.sh \
    && chmod +x llvm.sh \
    && ./llvm.sh 21 all \
    && rm llvm.sh \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# Add global 'lsnum' shell function for both Bash and Zsh users
RUN printf '\nlsnum() {\n    local parse_perms='\''{k=0;for(i=0;i<=8;i++)k+=((substr($1,i+2,1)~/[rwx]/)*2^(8-i));if(k)printf("%%0o ",k);print}'\''\n    ls -alh "${@:-.}" | awk "$parse_perms"\n}\n' >> /etc/bash.bashrc \
    && printf '\nlsnum() {\n    local parse_perms='\''{k=0;for(i=0;i<=8;i++)k+=((substr($1,i+2,1)~/[rwx]/)*2^(8-i));if(k)printf("%%0o ",k);print}'\''\n    ls -alh "${@:-.}" | awk "$parse_perms"\n}\n' >> /etc/zsh/zshrc

# Create builder user, assign sudo group,
# and configure password-less sudo
RUN useradd -m -s /bin/zsh -G sudo builder && \
    echo "builder:password" | chpasswd && \
    chage -d 0 builder && \
    echo "builder ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/builder && \
    chmod 0440 /etc/sudoers.d/builder && \
    mkdir -p /builder && \
    chown -R builder:builder /builder

# Explicitly ensure password authentication and PAM are permitted in SSH config
RUN sed -i -e 's/#PasswordAuthentication yes/PasswordAuthentication yes/' \
           -e 's/#UsePAM yes/UsePAM yes/' /etc/ssh/sshd_config || \
    (echo "PasswordAuthentication yes" >> /etc/ssh/sshd_config && echo "UsePAM yes" >> /etc/ssh/sshd_config)

# Document container port
EXPOSE 22

USER builder
WORKDIR /builder

# Entrypoint Script
COPY --chown=builder:builder entrypoint.sh /builder/entrypoint.sh
RUN chmod +x /builder/entrypoint.sh
ENTRYPOINT ["/builder/entrypoint.sh"]
CMD ["bash"]

