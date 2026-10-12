################################################################################
#
# jaq (github.com/01mf02/jaq)
#
################################################################################

JAQ_VERSION = $(call qstrip,$(BR2_PACKAGE_JAQ_VERSION))
ifeq ($(JAQ_VERSION),)
JAQ_VERSION = 3.1.1
endif

JAQ_SITE = $(call github,01mf02,jaq,v$(JAQ_VERSION))
JAQ_SOURCE = jaq-$(JAQ_VERSION).tar.gz

JAQ_LICENSE = MIT
JAQ_LICENSE_FILES = LICENSE-MIT

# cargo-package omits --release when BR2_ENABLE_DEBUG=y (dev profile).
# Always build the release profile.
JAQ_CARGO_PROFILE = release

# Workspace root has no default-members; build the jaq binary crate only.
# Default features (mimalloc) are kept.
define JAQ_BUILD_CMDS
	cd $(@D) && \
	$(TARGET_MAKE_ENV) \
	$(TARGET_CONFIGURE_OPTS) \
	$(PKG_CARGO_ENV) \
	cargo build \
		--offline \
		--manifest-path Cargo.toml \
		--locked \
		--profile=$(JAQ_CARGO_PROFILE) \
		--package jaq
endef

define JAQ_INSTALL_TARGET_CMDS
	$(INSTALL) -D -m 0755 \
		$(@D)/target/$(RUSTC_TARGET_NAME)/$(JAQ_CARGO_PROFILE)/jaq \
		$(TARGET_DIR)/usr/bin/jaq
endef

# Legacy jq name: only when GNU jq (BR2_PACKAGE_JQ) is not built, so the
# two never fight over /usr/bin/jq. Relative target keeps it valid with
# merged-usr.
ifneq ($(BR2_PACKAGE_JQ),y)
define JAQ_INSTALL_JQ_SYMLINK
	ln -sf jaq $(TARGET_DIR)/usr/bin/jq
endef
JAQ_POST_INSTALL_TARGET_HOOKS += JAQ_INSTALL_JQ_SYMLINK
endif

$(eval $(cargo-package))
