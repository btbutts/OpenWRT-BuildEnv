################################################################################
#
# dotnet10 (.NET 10 SDK, precompiled tarball)
#
################################################################################

DOTNET10_VERSION = $(call qstrip,$(BR2_PACKAGE_DOTNET10_VERSION))
ifeq ($(DOTNET10_VERSION),)
DOTNET10_VERSION = 10.0.401
endif

# BR2_NORMALIZED_ARCH is a quoted string in .config ("x86_64"), so it
# has to be qstripped before it compares equal. It is x86_64 for every
# x86-64 variant (v1..v4).
ifeq ($(call qstrip,$(BR2_NORMALIZED_ARCH)),x86_64)
DOTNET10_ARCH = x64
else ifeq ($(BR2_aarch64),y)
DOTNET10_ARCH = arm64
endif

ifeq ($(BR2_PACKAGE_DOTNET10),y)
ifeq ($(DOTNET10_ARCH),)
$(error dotnet10: only x86-64 and aarch64 are supported)
endif
endif

DOTNET10_SITE = https://builds.dotnet.microsoft.com/dotnet/Sdk/$(DOTNET10_VERSION)
DOTNET10_SOURCE = dotnet-sdk-$(DOTNET10_VERSION)-linux-$(DOTNET10_ARCH).tar.gz

# The tarball has no top-level directory; Buildroot strips one by default.
DOTNET10_STRIP_COMPONENTS = 0

DOTNET10_LICENSE = MIT
DOTNET10_LICENSE_FILES = LICENSE.txt

DOTNET10_DEPENDENCIES = ca-certificates openssl zlib brotli icu tzdata linux-pam \
	gcc-standalone-toolchain
# gcc-standalone-toolchain is a LATE_CUSTOM_PACKAGES_LIBS member (see
# custom-late.mk): it installs before every other custom package, so this
# dependency is not circular.
# krb5 is optional (Negotiate/NTLM); a build-order dependency only if
# something else enabled it.
ifeq ($(BR2_PACKAGE_KRB5),y)
DOTNET10_DEPENDENCIES += krb5
endif

# Prebuilt binaries: no arch scan, no stripping.
DOTNET10_BIN_ARCH_EXCLUDE = opt/dotnet10
ifeq ($(BR2_PACKAGE_DOTNET10),y)
ifeq ($(filter opt/dotnet10,$(call qstrip,$(BR2_STRIP_EXCLUDE_DIRS))),)
BR2_STRIP_EXCLUDE_DIRS += opt/dotnet10
endif
endif

# $(@D) also holds Buildroot's .stamp_* files; leave them out.
define DOTNET10_INSTALL_TARGET_CMDS
	rm -rf $(TARGET_DIR)/opt/dotnet10
	$(INSTALL) -d -m 0755 $(TARGET_DIR)/opt/dotnet10
	cp -a $(@D)/. $(TARGET_DIR)/opt/dotnet10/
	rm -f $(TARGET_DIR)/opt/dotnet10/.stamp_* \
		$(TARGET_DIR)/opt/dotnet10/.applied_patches_list
	$(INSTALL) -D -m 0644 $(DOTNET10_PKGDIR)/dotnet10.sh \
		$(TARGET_DIR)/etc/profile.d/dotnet10.sh
endef

$(eval $(generic-package))
