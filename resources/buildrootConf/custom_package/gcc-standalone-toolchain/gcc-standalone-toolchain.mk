################################################################################
#
# gcc-standalone-toolchain
#
# Prebuilt Bootlin gcc installed into the target rootfs. SITE/SOURCE are
# composed from this configuration's CPU variant, C library, and
# BR2_PACKAGE_GCC_STANDALONE_TOOLCHAIN_VERSION. generic-package then
# wget's that tarball during Extracting (SITE cannot be empty when
# SOURCE/VERSION are set).
#
################################################################################

GCC_URL_PREFIX = https://toolchains.bootlin.com/downloads/releases/toolchains/

GCC_STANDALONE_TOOLCHAIN_VERSION = $(call qstrip,$(BR2_PACKAGE_GCC_STANDALONE_TOOLCHAIN_VERSION))
ifeq ($(GCC_STANDALONE_TOOLCHAIN_VERSION),)
GCC_STANDALONE_TOOLCHAIN_VERSION = 2026.08-1
endif

GCC_STANDALONE_TOOLCHAIN_LICENSE = GPL-3.0+, LGPL-2.1+
GCC_STANDALONE_TOOLCHAIN_INSTALL_TARGET = YES
GCC_STANDALONE_TOOLCHAIN_INSTALL_STAGING = NO

# Map Buildroot CPU symbols onto Bootlin's tarball directory names.
ifeq ($(BR2_x86_x86_64_v4),y)
GCC_STANDALONE_TOOLCHAIN_BOOTLIN_ARCH = x86-64-v4
else ifeq ($(BR2_x86_x86_64_v3),y)
GCC_STANDALONE_TOOLCHAIN_BOOTLIN_ARCH = x86-64-v3
else ifeq ($(BR2_x86_x86_64_v2),y)
GCC_STANDALONE_TOOLCHAIN_BOOTLIN_ARCH = x86-64-v2
else ifeq ($(BR2_x86_x86_64),y)
GCC_STANDALONE_TOOLCHAIN_BOOTLIN_ARCH = x86-64
else ifeq ($(BR2_aarch64),y)
GCC_STANDALONE_TOOLCHAIN_BOOTLIN_ARCH = aarch64
else ifeq ($(BR2_aarch64_be),y)
GCC_STANDALONE_TOOLCHAIN_BOOTLIN_ARCH = aarch64be
endif

# glibc / musl / uclibc. Prefer the Kconfig bools; Bootlin uses "uclibc"
# (not uclibc-ng) in tarball names.
ifeq ($(BR2_TOOLCHAIN_BUILDROOT_GLIBC),y)
GCC_STANDALONE_TOOLCHAIN_BOOTLIN_LIBC = glibc
else ifeq ($(BR2_TOOLCHAIN_BUILDROOT_MUSL),y)
GCC_STANDALONE_TOOLCHAIN_BOOTLIN_LIBC = musl
else ifeq ($(BR2_TOOLCHAIN_BUILDROOT_UCLIBC),y)
GCC_STANDALONE_TOOLCHAIN_BOOTLIN_LIBC = uclibc
else
GCC_STANDALONE_TOOLCHAIN_BOOTLIN_LIBC = $(call qstrip,$(BR2_TOOLCHAIN_BUILDROOT_LIBC))
ifeq ($(GCC_STANDALONE_TOOLCHAIN_BOOTLIN_LIBC),uclibc-ng)
GCC_STANDALONE_TOOLCHAIN_BOOTLIN_LIBC = uclibc
endif
endif

ifeq ($(BR2_PACKAGE_GCC_STANDALONE_TOOLCHAIN),y)
ifeq ($(GCC_STANDALONE_TOOLCHAIN_BOOTLIN_ARCH),)
$(error gcc-standalone-toolchain: architecture must be x86-64, x86-64-v2, x86-64-v3, x86-64-v4, aarch64, or aarch64be)
endif
ifeq ($(filter glibc musl uclibc,$(GCC_STANDALONE_TOOLCHAIN_BOOTLIN_LIBC)),)
$(error gcc-standalone-toolchain: BR2_TOOLCHAIN_BUILDROOT_LIBC must be glibc, musl, or uclibc)
endif
endif

# Explicit SOURCE so pkg-generic does not invent
# gcc-standalone-toolchain-$(VERSION).tar.gz with an empty SITE.
GCC_STANDALONE_TOOLCHAIN_SITE = $(GCC_URL_PREFIX)$(GCC_STANDALONE_TOOLCHAIN_BOOTLIN_ARCH)/tarballs
GCC_STANDALONE_TOOLCHAIN_SOURCE = $(GCC_STANDALONE_TOOLCHAIN_BOOTLIN_ARCH)--$(GCC_STANDALONE_TOOLCHAIN_BOOTLIN_LIBC)--stable-$(GCC_STANDALONE_TOOLCHAIN_VERSION).tar.xz
GCC_STANDALONE_TOOLCHAIN_STRIP_COMPONENTS = 1
# Prebuilt ELFs; skip per-package arch scan (thousands of python/.so/gcc files).
GCC_STANDALONE_TOOLCHAIN_BIN_ARCH_EXCLUDE = opt/gcc-standalone-toolchain

# target-finalize strip uses BR2_STRIP_EXCLUDE_DIRS (Buildroot Makefile).
# Kconfig cannot select/append a string, so do it here whenever this
# package is enabled. Keep a user-supplied list and add our path once.
ifeq ($(BR2_PACKAGE_GCC_STANDALONE_TOOLCHAIN),y)
ifeq ($(filter opt/gcc-standalone-toolchain,$(call qstrip,$(BR2_STRIP_EXCLUDE_DIRS))),)
BR2_STRIP_EXCLUDE_DIRS += opt/gcc-standalone-toolchain
endif
ifeq ($(filter opt/gcc-standalone-toolchain,$(call qstrip,$(BR2_STRIP_exclude_dirs))),)
BR2_STRIP_exclude_dirs += opt/gcc-standalone-toolchain
endif
endif

GCC_STANDALONE_TOOLCHAIN_DESTDIR = $(TARGET_DIR)/opt/gcc-standalone-toolchain
GCC_STANDALONE_TOOLCHAIN_RUNTIME_PREFIX = /opt/gcc-standalone-toolchain
GCC_STANDALONE_TOOLCHAIN_LOCFILE = $(GCC_STANDALONE_TOOLCHAIN_DESTDIR)/share/buildroot/sdk-location

# Rewrite the Bootlin CI prefix only in files that can actually contain it
# (wrappers, pkgconfig, libtool). Scanning python + plugin headers is slow
# and those trees do not hold the old path.
define GCC_STANDALONE_TOOLCHAIN_RELOCATE
	if [ -r $(GCC_STANDALONE_TOOLCHAIN_LOCFILE) ]; then \
		oldpath=$$(cat $(GCC_STANDALONE_TOOLCHAIN_LOCFILE)); \
		if [ -n "$$oldpath" ] && [ "$$oldpath" != "$(GCC_STANDALONE_TOOLCHAIN_RUNTIME_PREFIX)" ]; then \
			echo ">>> gcc-standalone-toolchain: relocating $$oldpath -> $(GCC_STANDALONE_TOOLCHAIN_RUNTIME_PREFIX)"; \
			echo ">>> gcc-standalone-toolchain: scanning bin/, libexec/, share/buildroot, lib/pkgconfig"; \
			for dir in bin libexec share/buildroot lib/pkgconfig; do \
				[ -d $(GCC_STANDALONE_TOOLCHAIN_DESTDIR)/$$dir ] || continue; \
				find $(GCC_STANDALONE_TOOLCHAIN_DESTDIR)/$$dir -type f -print0 | \
				xargs -0 grep -l -- "$$oldpath" 2>/dev/null | \
				while IFS= read -r f; do \
					echo ">>> gcc-standalone-toolchain: rewrite $$f"; \
					sed -i "s|$$oldpath|$(GCC_STANDALONE_TOOLCHAIN_RUNTIME_PREFIX)|g" "$$f"; \
				done; \
			done; \
			printf '%s\n' "$(GCC_STANDALONE_TOOLCHAIN_RUNTIME_PREFIX)" > $(GCC_STANDALONE_TOOLCHAIN_LOCFILE); \
			echo ">>> gcc-standalone-toolchain: relocate done"; \
		fi; \
	fi
endef

# Short names (gcc, g++, ld, …) live next to the tuple-prefixed binaries
# in /opt/.../bin. Relative links stay inside the SDK; nothing is written
# to /usr/bin. profile.d appends that bin dir so a login shell finds gcc
# after /usr/bin (BusyBox/binutils keep the short names that already exist).
define GCC_STANDALONE_TOOLCHAIN_SHORT_LINKS
	if [ -d $(GCC_STANDALONE_TOOLCHAIN_DESTDIR)/bin ]; then \
		echo ">>> gcc-standalone-toolchain: short names in bin/"; \
		for gccbin in $(GCC_STANDALONE_TOOLCHAIN_DESTDIR)/bin/*-gcc; do \
			[ -e "$$gccbin" ] || continue; \
			tuple=$$(basename "$$gccbin" | sed 's/-gcc$$//'); \
			[ -n "$$tuple" ] || continue; \
			for f in $(GCC_STANDALONE_TOOLCHAIN_DESTDIR)/bin/$$tuple-*; do \
				[ -e "$$f" ] || continue; \
				base=$$(basename "$$f"); \
				short=$${base#$$tuple-}; \
				[ -n "$$short" ] && [ "$$short" != "$$base" ] || continue; \
				dest=$(GCC_STANDALONE_TOOLCHAIN_DESTDIR)/bin/$$short; \
				if [ ! -e "$$dest" ]; then \
					ln -sfn "$$base" "$$dest"; \
					echo ">>> gcc-standalone-toolchain: $$short -> $$base"; \
				fi; \
			done; \
			if [ -e $(GCC_STANDALONE_TOOLCHAIN_DESTDIR)/bin/gcc ] && \
			   [ ! -e $(GCC_STANDALONE_TOOLCHAIN_DESTDIR)/bin/cc ]; then \
				ln -sfn gcc $(GCC_STANDALONE_TOOLCHAIN_DESTDIR)/bin/cc; \
				echo ">>> gcc-standalone-toolchain: cc -> gcc"; \
			fi; \
			break; \
		done; \
	fi
endef

# Copy the SDK into the target rootfs only. Do not symlink gcc/as/ld/strip
# into /usr/bin: those names collide with the Buildroot cross toolchain if
# anything in the build looks at TARGET_DIR.
define GCC_STANDALONE_TOOLCHAIN_INSTALL_TARGET_CMDS
	echo ">>> gcc-standalone-toolchain: installing SDK into $(GCC_STANDALONE_TOOLCHAIN_DESTDIR)"
	rm -rf $(GCC_STANDALONE_TOOLCHAIN_DESTDIR)
	mkdir -p $(GCC_STANDALONE_TOOLCHAIN_DESTDIR) $(TARGET_DIR)/etc/profile.d
	echo ">>> gcc-standalone-toolchain: copying extract (large tree, can take a minute)"
	cp -a $(@D)/. $(GCC_STANDALONE_TOOLCHAIN_DESTDIR)/
	echo ">>> gcc-standalone-toolchain: copy complete"
	$(GCC_STANDALONE_TOOLCHAIN_RELOCATE)
	$(GCC_STANDALONE_TOOLCHAIN_SHORT_LINKS)
	echo ">>> gcc-standalone-toolchain: writing /etc/profile.d/gcc-standalone-toolchain.sh"
	printf '%s\n' \
		'# Bootlin gcc for the booted image. Buildroot compiles packages' \
		'# with output/host; this directory is not on that PATH.' \
		'if [ -d /opt/gcc-standalone-toolchain/bin ]; then' \
		'	PATH="$$PATH:/opt/gcc-standalone-toolchain/bin"' \
		'	export PATH' \
		'fi' \
		> $(TARGET_DIR)/etc/profile.d/gcc-standalone-toolchain.sh
	echo ">>> gcc-standalone-toolchain: target install finished"
endef

# .NET (libcoreclr) and PowerShell load libstdc++/libgcc_s at run time.
# Append the SDK's runtime lib dirs to the target's ld.so.conf. Only
# <tuple>/lib64 and <tuple>/lib are added, never <tuple>/sysroot: that
# holds the SDK's own libc and would shadow the image's. The tuple is
# read from the tree (x86_64-... / aarch64-...), not hardcoded, and
# lines are added once so a rebuild does not duplicate them.
define GCC_STANDALONE_TOOLCHAIN_APPEND_LDCONFIG
	$(INSTALL) -d -m 0755 $(TARGET_DIR)/etc
	touch $(TARGET_DIR)/etc/ld.so.conf
	for d in lib $$(cd $(GCC_STANDALONE_TOOLCHAIN_DESTDIR) && \
			ls -d *-linux-*/lib64 *-linux-*/lib 2>/dev/null); do \
		if [ "$$d" != lib ] && \
		   ! ls $(GCC_STANDALONE_TOOLCHAIN_DESTDIR)/$$d/libstdc++.so* >/dev/null 2>&1; then \
			continue; \
		fi; \
		p=$(GCC_STANDALONE_TOOLCHAIN_RUNTIME_PREFIX)/$$d; \
		grep -qxF "$$p" $(TARGET_DIR)/etc/ld.so.conf || \
			echo "$$p" >> $(TARGET_DIR)/etc/ld.so.conf; \
		echo ">>> gcc-standalone-toolchain: ld.so.conf += $$p"; \
	done
endef
GCC_STANDALONE_TOOLCHAIN_POST_INSTALL_TARGET_HOOKS += GCC_STANDALONE_TOOLCHAIN_APPEND_LDCONFIG

$(eval $(generic-package))
