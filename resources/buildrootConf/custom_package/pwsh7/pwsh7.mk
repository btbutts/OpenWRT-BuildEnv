################################################################################
#
# pwsh7 (PowerShell 7, precompiled tarball with bundled .NET runtime)
#
################################################################################

PWSH7_VERSION = $(call qstrip,$(BR2_PACKAGE_PWSH7_VERSION))
ifeq ($(PWSH7_VERSION),)
PWSH7_VERSION = 7.6.6
endif

# BR2_NORMALIZED_ARCH is a quoted string in .config ("x86_64"), so it
# has to be qstripped before it compares equal. It is x86_64 for every
# x86-64 variant (v1..v4).
ifeq ($(call qstrip,$(BR2_NORMALIZED_ARCH)),x86_64)
PWSH7_ARCH = x64
else ifeq ($(BR2_aarch64),y)
PWSH7_ARCH = arm64
endif

ifeq ($(BR2_PACKAGE_PWSH7),y)
ifeq ($(PWSH7_ARCH),)
$(error pwsh7: only x86-64 and aarch64 are supported)
endif
endif

PWSH7_SITE = https://github.com/PowerShell/PowerShell/releases/download/v$(PWSH7_VERSION)
PWSH7_SOURCE = powershell-$(PWSH7_VERSION)-linux-$(PWSH7_ARCH).tar.gz

# The tarball has no top-level directory; Buildroot strips one by default.
PWSH7_STRIP_COMPONENTS = 0

PWSH7_LICENSE = MIT
PWSH7_LICENSE_FILES = LICENSE.txt

# Libraries the bundled .NET runtime loads at run time.
PWSH7_DEPENDENCIES = ca-certificates openssl zlib brotli icu tzdata linux-pam \
	gcc-standalone-toolchain
# gcc-standalone-toolchain is a LATE_CUSTOM_PACKAGES_LIBS member (see
# custom-late.mk): it installs before every other custom package, so this
# dependency is not circular.
# krb5 is optional (Negotiate/NTLM); a build-order dependency only if
# something else enabled it.
ifeq ($(BR2_PACKAGE_KRB5),y)
PWSH7_DEPENDENCIES += krb5
endif

# Prebuilt binaries: no arch scan, no stripping.
PWSH7_BIN_ARCH_EXCLUDE = opt/pwsh7
ifeq ($(BR2_PACKAGE_PWSH7),y)
ifeq ($(filter opt/pwsh7,$(call qstrip,$(BR2_STRIP_EXCLUDE_DIRS))),)
BR2_STRIP_EXCLUDE_DIRS += opt/pwsh7
endif
endif

# $(@D) also holds Buildroot's .stamp_* files; leave them out. The
# tarball does not set the execute bit on pwsh.
define PWSH7_INSTALL_TARGET_CMDS
	rm -rf $(TARGET_DIR)/opt/pwsh7
	$(INSTALL) -d -m 0755 $(TARGET_DIR)/opt/pwsh7
	cp -a $(@D)/. $(TARGET_DIR)/opt/pwsh7/
	rm -f $(TARGET_DIR)/opt/pwsh7/.stamp_* \
		$(TARGET_DIR)/opt/pwsh7/.applied_patches_list
	chmod 0755 $(TARGET_DIR)/opt/pwsh7/pwsh
	ln -sf /opt/pwsh7/pwsh $(TARGET_DIR)/usr/bin/pwsh
endef

$(eval $(generic-package))
