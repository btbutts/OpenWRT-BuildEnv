FROM debian:trixie-slim

ARG TARGETARCH

# Install build environment dependencies
RUN sed -i '/^Components:/ s/$/ non-free/' \
    /etc/apt/sources.list.d/debian.sources && \
    sed -i 's|path-exclude /usr/share/man/\*|path-include /usr/share/man/\*|g' \
    /etc/dpkg/dpkg.cfg.d/docker && \
    apt-get update && DEBIAN_FRONTEND=noninteractive \
    apt-get install -y man-db manpages manpages-posix \
    manpages-posix-dev less && \
    # Install packages by architecture
    if [ "$TARGETARCH" = "arm64" ]; then \
        GRUB_PKGS="grub-efi-arm64-bin"; \
        printf "Building GRUB binaries for '%s'" "$TARGETARCH" >&2; \
    elif [ "$TARGETARCH" = "amd64" ]; then \
        GRUB_PKGS="grub-efi-amd64-bin grub-pc-bin"; \
        printf "Building GRUB binaries for '%s'" "$TARGETARCH" >&2; \
    else \
        printf "Error: Unsupported build architecture" && \
        printf " '%s' for GRUB binaries.\n" "$TARGETARCH" >&2; \
        exit 1; \
    fi && \
    DEBIAN_FRONTEND=noninteractive \
    apt-get install -y --no-install-recommends \
    bc binutils-gold bison ccache ecj fastjar flex \
    build-essential gcc g++ help2man texinfo vim nano \
    libbsd-dev libelf-dev libncurses-dev zlib1g-dev \
    liblzma-dev mtd-utils meson mold ninja-build \
    pigz pkg-config python3-dev subversion swig \
    gettext libssl-dev xsltproc wget unzip python3 \
    grub-common dosfstools time rsync gawk file \
    python3-setuptools curl net-tools bind9-dnsutils \
    git iputils-ping traceroute mtr rclone zstd \
    u-boot-tools gzip xxd make libc6-dev pbzip2 \
    gcc-aarch64-linux-gnu binutils-aarch64-linux-gnu \
    g++-aarch64-linux-gnu device-tree-compiler htop \
    openssh-server sudo zsh lsb-release gnupg \
    ${GRUB_PKGS} mtools dosfstools \
    && apt-get clean && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /var/run/sshd

# Copy local LLVM installation script, execute, and clean up
COPY resources/llvm.sh /tmp/llvm.sh
RUN chmod +x /tmp/llvm.sh \
    && /tmp/llvm.sh 21 all \
    && rm -f /tmp/llvm.sh \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# Programmatically Standardize System-Wide PATH
RUN FULL_PATH=$(printf '%s' "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:$(getconf PATH)" | \
        awk -v RS=: -v ORS=: '!a[$0]++ {if (length($0)) print $0}' | sed 's/:$//') && \
    echo "PATH=\"${FULL_PATH}\"" > /etc/environment && \
    sed -i "s|^ENV_PATH.*|ENV_PATH    PATH=${FULL_PATH}|g" /etc/login.defs && \
    sed -i "s|^ENV_SUPATH.*|ENV_SUPATH  PATH=${FULL_PATH}|g" /etc/login.defs && \
    mkdir -p /etc/zsh && \
    echo "export PATH=\"${FULL_PATH}\"" >> /etc/profile && \
    echo "export PATH=\"${FULL_PATH}\"" >> /etc/zsh/zshenv

# Configure Zsh
RUN touch /etc/skel/.zshrc /etc/skel/.zshenv /etc/skel/.zprofile && \
    echo 'autoload -Uz compinit && compinit -C' >> /etc/skel/.zshrc && \
    echo 'setopt autocd autopushd pushdignoredups' >> /etc/skel/.zshrc

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

# Setup OpenWRT Image Builder
USER builder
WORKDIR /builder
#RUN mkdir -p /builder/OpenWRT-ImageBuilder && \
#    tar --zstd -xvf /builder/openwrt-imagebuilder-*.tar.zst \
#    -C /builder/OpenWRT-ImageBuilder --strip-components=1 && \
#    rm /builder/openwrt-imagebuilder-*.tar.zst
COPY --chown=builder:builder \
    resources/openwrt-imagebuilder-*.tar.zst \
    resources/extractImageBuilder.sh \
    resources/buildImages.sh \
    /builder/
COPY --chown=builder:builder entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x \
    /usr/local/bin/entrypoint.sh \
    /builder/extractImageBuilder.sh \
    /builder/buildImages.sh
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["bash"]
