################################################################################
#
# brush (github.com/reubeno/brush, binary from crate brush-shell)
#
################################################################################

BRUSH_VERSION = $(call qstrip,$(BR2_PACKAGE_BRUSH_VERSION))
ifeq ($(BRUSH_VERSION),)
BRUSH_VERSION = 0.4.0
endif

BRUSH_SITE = $(call github,reubeno,brush,brush-shell-v$(BRUSH_VERSION))
BRUSH_SOURCE = brush-$(BRUSH_VERSION).tar.gz

BRUSH_LICENSE = MIT
BRUSH_LICENSE_FILES = LICENSE

# cargo-package omits --release when BR2_ENABLE_DEBUG=y (dev profile).
# Always build the release profile.
BRUSH_CARGO_PROFILE = release

# Workspace default-members is brush-shell; the binary is named brush.
# Default cargo features only (basic, reedline, minimal).
define BRUSH_BUILD_CMDS
	cd $(@D) && \
	$(TARGET_MAKE_ENV) \
	$(TARGET_CONFIGURE_OPTS) \
	$(PKG_CARGO_ENV) \
	cargo build \
		--offline \
		--manifest-path brush-shell/Cargo.toml \
		--locked \
		--profile=$(BRUSH_CARGO_PROFILE)
endef

define BRUSH_INSTALL_TARGET_CMDS
	$(INSTALL) -D -m 0755 \
		$(@D)/target/$(RUSTC_TARGET_NAME)/$(BRUSH_CARGO_PROFILE)/brush \
		$(TARGET_DIR)/usr/bin/brush
endef

# Extra files without :// are fetched from SITE (the GitHub archive),
# so the docs asset must be the full releases/download URL.
ifeq ($(BR2_PACKAGE_BRUSH_DOCS),y)
BRUSH_EXTRA_DOWNLOADS = \
	https://github.com/reubeno/brush/releases/download/brush-shell-v$(BRUSH_VERSION)/brush-docs.tar.gz

# Release tarball members are ./man/brush.1 and ./md/brush.md.
# TAR_OPTIONS is -xf (no --strip-components); that keeps man/ and md/.
define BRUSH_EXTRACT_DOCS
	mkdir -p $(@D)/docs-extracted
	$(call suitable-extractor,brush-docs.tar.gz) \
		$(BRUSH_DL_DIR)/brush-docs.tar.gz | \
		$(TAR) -C $(@D)/docs-extracted $(TAR_OPTIONS) -
endef
BRUSH_POST_EXTRACT_HOOKS += BRUSH_EXTRACT_DOCS

define BRUSH_INSTALL_TARGET_DOCS
	$(INSTALL) -D -m 0644 $(@D)/docs-extracted/man/brush.1 \
		$(TARGET_DIR)/usr/share/man/man1/brush.1
	$(INSTALL) -D -m 0644 $(@D)/docs-extracted/md/brush.md \
		$(TARGET_DIR)/usr/share/doc/brush/brush.md
endef
BRUSH_POST_INSTALL_TARGET_HOOKS += BRUSH_INSTALL_TARGET_DOCS
endif

$(eval $(cargo-package))
