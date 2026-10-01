################################################################################
#
# gcc-standalone-toolchain
#
# Prebuilt Bootlin gcc installed into the target rootfs. The download
# URL is built from this configuration's CPU variant, C library, and
# BR2_PACKAGE_GCC_STANDALONE_TOOLCHAIN_VERSION.
#
################################################################################

GCC_URL_PREFIX = https://toolchains.bootlin.com/downloads/releases/toolchains/

GCC_STANDALONE_TOOLCHAIN_VERSION = $(call qstrip,$(BR2_PACKAGE_GCC_STANDALONE_TOOLCHAIN_VERSION))
GCC_STANDALONE_TOOLCHAIN_LICENSE = GPL-3.0+, LGPL-2.1+
GCC_STANDALONE_TOOLCHAIN_INSTALL_TARGET = YES

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
ifeq ($(GCC_STANDALONE_TOOLCHAIN_VERSION),)
$(error gcc-standalone-toolchain: BR2_PACKAGE_GCC_STANDALONE_TOOLCHAIN_VERSION is empty)
endif
endif

GCC_STANDALONE_TOOLCHAIN_TARBALL = $(GCC_STANDALONE_TOOLCHAIN_BOOTLIN_ARCH)--$(GCC_STANDALONE_TOOLCHAIN_BOOTLIN_LIBC)--stable-$(GCC_STANDALONE_TOOLCHAIN_VERSION).tar.xz
GCC_STANDALONE_TOOLCHAIN_URL = $(GCC_URL_PREFIX)$(GCC_STANDALONE_TOOLCHAIN_BOOTLIN_ARCH)/tarballs/$(GCC_STANDALONE_TOOLCHAIN_TARBALL)
GCC_STANDALONE_TOOLCHAIN_DL_FILE = $(DL_DIR)/$(GCC_STANDALONE_TOOLCHAIN_TARBALL)
GCC_STANDALONE_TOOLCHAIN_BZ2_FILE = $(GCC_STANDALONE_TOOLCHAIN_DL_FILE:.tar.xz=.tar.bz2)
GCC_STANDALONE_TOOLCHAIN_DESTDIR = $(TARGET_DIR)/opt/gcc-standalone-toolchain

# wget + extract live here (not SITE/SOURCE) so the URL can be composed
# from BR2_* options. Recent Bootlin releases are .tar.xz; older ones
# are .tar.bz2 and are used as a fallback.
define GCC_STANDALONE_TOOLCHAIN_INSTALL_TARGET_CMDS
	mkdir -p $(DL_DIR) $(GCC_STANDALONE_TOOLCHAIN_DESTDIR)
	if [ ! -f $(GCC_STANDALONE_TOOLCHAIN_DL_FILE) ] && [ ! -f $(GCC_STANDALONE_TOOLCHAIN_BZ2_FILE) ]; then \
		echo "--> wget $(GCC_STANDALONE_TOOLCHAIN_URL)"; \
		if wget --no-verbose -O $(GCC_STANDALONE_TOOLCHAIN_DL_FILE).tmp $(GCC_STANDALONE_TOOLCHAIN_URL); then \
			mv $(GCC_STANDALONE_TOOLCHAIN_DL_FILE).tmp $(GCC_STANDALONE_TOOLCHAIN_DL_FILE); \
		else \
			rm -f $(GCC_STANDALONE_TOOLCHAIN_DL_FILE).tmp; \
			echo "--> xz tarball missing, trying .tar.bz2"; \
			wget --no-verbose -O $(GCC_STANDALONE_TOOLCHAIN_BZ2_FILE).tmp \
				$(GCC_STANDALONE_TOOLCHAIN_URL:.tar.xz=.tar.bz2); \
			mv $(GCC_STANDALONE_TOOLCHAIN_BZ2_FILE).tmp $(GCC_STANDALONE_TOOLCHAIN_BZ2_FILE); \
		fi; \
	fi
	if [ -f $(GCC_STANDALONE_TOOLCHAIN_DL_FILE) ]; then \
		tar -C $(GCC_STANDALONE_TOOLCHAIN_DESTDIR) --strip-components=1 -xJf $(GCC_STANDALONE_TOOLCHAIN_DL_FILE); \
	else \
		tar -C $(GCC_STANDALONE_TOOLCHAIN_DESTDIR) --strip-components=1 -xjf $(GCC_STANDALONE_TOOLCHAIN_BZ2_FILE); \
	fi
	if [ -x $(GCC_STANDALONE_TOOLCHAIN_DESTDIR)/relocate-sdk.sh ]; then \
		sh $(GCC_STANDALONE_TOOLCHAIN_DESTDIR)/relocate-sdk.sh /opt/gcc-standalone-toolchain; \
	fi
	mkdir -p $(TARGET_DIR)/usr/bin $(TARGET_DIR)/etc/profile.d
	if [ -d $(GCC_STANDALONE_TOOLCHAIN_DESTDIR)/bin ]; then \
		for gccbin in $(GCC_STANDALONE_TOOLCHAIN_DESTDIR)/bin/*-gcc; do \
			[ -e "$$gccbin" ] || continue; \
			tuple=$$(basename "$$gccbin" | sed 's/-gcc$$//'); \
			for tool in gcc g++ cpp c++ gcov as ld ar ranlib strip nm objcopy objdump readelf size; do \
				if [ -e $(GCC_STANDALONE_TOOLCHAIN_DESTDIR)/bin/$$tuple-$$tool ]; then \
					ln -sfn /opt/gcc-standalone-toolchain/bin/$$tuple-$$tool \
						$(TARGET_DIR)/usr/bin/$$tool; \
				fi; \
			done; \
			break; \
		done; \
	fi
	printf '%s\n' 'export PATH=/opt/gcc-standalone-toolchain/bin:$$PATH' \
		> $(TARGET_DIR)/etc/profile.d/gcc-standalone-toolchain.sh
endef

$(eval $(generic-package))
