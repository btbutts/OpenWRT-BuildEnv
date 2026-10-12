################################################################################
#
# fdfind (github.com/sharkdp/fd, installed as fdfind)
#
################################################################################

FDFIND_VERSION = $(call qstrip,$(BR2_PACKAGE_FDFIND_VERSION))
ifeq ($(FDFIND_VERSION),)
FDFIND_VERSION = 10.5.0
endif

FDFIND_SITE = $(call github,sharkdp,fd,v$(FDFIND_VERSION))
FDFIND_SOURCE = fd-$(FDFIND_VERSION).tar.gz

FDFIND_LICENSE = MIT or Apache-2.0
FDFIND_LICENSE_FILES = LICENSE-MIT LICENSE-APACHE

# cargo-package omits --release when BR2_ENABLE_DEBUG=y (dev profile).
# Always build the release profile.
FDFIND_CARGO_PROFILE = release

define FDFIND_BUILD_CMDS
	cd $(@D) && \
	$(TARGET_MAKE_ENV) \
	$(TARGET_CONFIGURE_OPTS) \
	$(PKG_CARGO_ENV) \
	cargo build \
		--offline \
		--manifest-path Cargo.toml \
		--locked \
		--profile=$(FDFIND_CARGO_PROFILE)
endef

# Crate binary is fd; install as fdfind (no /usr/bin/fd symlink).
define FDFIND_INSTALL_TARGET_CMDS
	$(INSTALL) -D -m 0755 \
		$(@D)/target/$(RUSTC_TARGET_NAME)/$(FDFIND_CARGO_PROFILE)/fd \
		$(TARGET_DIR)/usr/bin/fdfind
endef

$(eval $(cargo-package))
