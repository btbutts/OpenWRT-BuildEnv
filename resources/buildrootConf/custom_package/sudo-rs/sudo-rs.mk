################################################################################
#
# sudo-rs
#
################################################################################

SUDO_RS_VERSION = $(call qstrip,$(BR2_PACKAGE_SUDO_RS_VERSION))
ifeq ($(SUDO_RS_VERSION),)
SUDO_RS_VERSION = 0.2.15
endif

SUDO_RS_SITE = $(call github,trifectatechfoundation,sudo-rs,v$(SUDO_RS_VERSION))
SUDO_RS_SOURCE = sudo-rs-$(SUDO_RS_VERSION).tar.gz

SUDO_RS_LICENSE = Apache-2.0 or MIT
SUDO_RS_LICENSE_FILES = LICENSE-APACHE LICENSE-MIT

# cargo-package omits --release when BR2_ENABLE_DEBUG=y (dev profile).
# Always build the release profile.
SUDO_RS_CARGO_PROFILE = release

# Links libpam via #[link(name = "pam")]; cargo-package adds host-rustc.
SUDO_RS_DEPENDENCIES = linux-pam

# v0.2.15 has no etc/sudoers or etc/sudo.conf in the tarball.
SUDO_RS_SUDOERS = $(SUDO_RS_PKGDIR)/sudoers
SUDO_RS_SUDO_PAM = $(SUDO_RS_PKGDIR)/sudo.pam
SUDO_RS_SU_PAM = $(SUDO_RS_PKGDIR)/su.pam

define SUDO_RS_BUILD_CMDS
	cd $(@D) && \
	$(TARGET_MAKE_ENV) \
	$(TARGET_CONFIGURE_OPTS) \
	$(PKG_CARGO_ENV) \
	cargo build \
		--offline \
		--manifest-path Cargo.toml \
		--locked \
		--profile=$(SUDO_RS_CARGO_PROFILE)
endef

define SUDO_RS_INSTALL_TARGET_CMDS
	$(INSTALL) -D -m 0755 \
		$(@D)/target/$(RUSTC_TARGET_NAME)/$(SUDO_RS_CARGO_PROFILE)/sudo \
		$(TARGET_DIR)/usr/bin/sudo
	$(INSTALL) -D -m 0755 \
		$(@D)/target/$(RUSTC_TARGET_NAME)/$(SUDO_RS_CARGO_PROFILE)/su \
		$(TARGET_DIR)/usr/sbin/su
	$(INSTALL) -D -m 0755 \
		$(@D)/target/$(RUSTC_TARGET_NAME)/$(SUDO_RS_CARGO_PROFILE)/visudo \
		$(TARGET_DIR)/usr/sbin/visudo
	$(INSTALL) -D -m 0640 $(SUDO_RS_SUDOERS) $(TARGET_DIR)/etc/sudoers
	$(INSTALL) -d -m 0750 $(TARGET_DIR)/etc/sudoers.d
	$(INSTALL) -D -m 0644 $(SUDO_RS_SUDO_PAM) $(TARGET_DIR)/etc/pam.d/sudo
	$(INSTALL) -D -m 0644 $(SUDO_RS_SU_PAM) $(TARGET_DIR)/etc/pam.d/su
endef

define SUDO_RS_USERS
	sudo -1 sudo -1 * - - - Sudo group
endef

# target-finalize applies these after the copy into TARGET_DIR.
define SUDO_RS_PERMISSIONS
	/usr/bin/sudo f 4755 0 0 - - - - -
	/usr/sbin/su f 4755 0 0 - - - - -
	/etc/sudoers f 0640 0 0 - - - - -
endef

$(eval $(cargo-package))
