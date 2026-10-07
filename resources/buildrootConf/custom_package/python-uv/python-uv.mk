################################################################################
#
# python-uv (github.com/astral-sh/uv)
#
################################################################################

PYTHON_UV_VERSION = $(call qstrip,$(BR2_PACKAGE_PYTHON_UV_VERSION))
ifeq ($(PYTHON_UV_VERSION),)
PYTHON_UV_VERSION = 0.12.23
endif

PYTHON_UV_SITE = $(call github,astral-sh,uv,$(PYTHON_UV_VERSION))
PYTHON_UV_SOURCE = uv-$(PYTHON_UV_VERSION).tar.gz

PYTHON_UV_LICENSE = MIT or Apache-2.0
PYTHON_UV_LICENSE_FILES = LICENSE-MIT LICENSE-APACHE

# cargo-package omits --release when BR2_ENABLE_DEBUG=y (dev profile).
# Always build the release profile.
PYTHON_UV_CARGO_PROFILE = release

# Extra cargo env. PKG_CARGO_ENV sets CARGO_PROFILE_RELEASE_DEBUG=1;
# this later assignment wins. Dropping debuginfo cuts compile and link time.
PYTHON_UV_CARGO_ENV += CARGO_PROFILE_RELEASE_DEBUG=0

# Workspace members are crates/*; build only the uv crate (bins uv and
# uvx). Default features are test-only switches plus "performance"
# (jemalloc), so keep just "performance". self-update stays off, as
# upstream recommends for distro packages.
#
# -vv: print every rustc/linker invocation and build-script output
# (e.g. jemalloc's configure/make).
define PYTHON_UV_BUILD_CMDS
	cd $(@D) && \
	$(TARGET_MAKE_ENV) \
	$(TARGET_CONFIGURE_OPTS) \
	$(PKG_CARGO_ENV) \
	$(PYTHON_UV_CARGO_ENV) \
	cargo build \
		-vv \
		--offline \
		--manifest-path Cargo.toml \
		--locked \
		--profile=$(PYTHON_UV_CARGO_PROFILE) \
		--package uv \
		--no-default-features \
		--features performance
endef

define PYTHON_UV_INSTALL_TARGET_CMDS
	$(INSTALL) -D -m 0755 \
		$(@D)/target/$(RUSTC_TARGET_NAME)/$(PYTHON_UV_CARGO_PROFILE)/uv \
		$(TARGET_DIR)/usr/bin/uv
	$(INSTALL) -D -m 0755 \
		$(@D)/target/$(RUSTC_TARGET_NAME)/$(PYTHON_UV_CARGO_PROFILE)/uvx \
		$(TARGET_DIR)/usr/bin/uvx
endef

$(eval $(cargo-package))
