################################################################################
#
# uutils-coreutils
#
################################################################################

UUTILS_COREUTILS_VERSION = $(call qstrip,$(BR2_PACKAGE_UUTILS_COREUTILS_VERSION))
ifeq ($(UUTILS_COREUTILS_VERSION),)
UUTILS_COREUTILS_VERSION = 0.12.0
endif

UUTILS_COREUTILS_SITE = $(call github,uutils,coreutils,$(UUTILS_COREUTILS_VERSION))
UUTILS_COREUTILS_SOURCE = coreutils-$(UUTILS_COREUTILS_VERSION).tar.gz

UUTILS_COREUTILS_LICENSE = MIT
UUTILS_COREUTILS_LICENSE_FILES = LICENSE

# cargo-package omits --release when BR2_ENABLE_DEBUG=y (dev profile).
# Always build the release profile.
UUTILS_COREUTILS_CARGO_PROFILE = release

# feat_os_unix applets (Cargo.toml unix -> feat_os_unix). Keep in sync
# with 0.12.0; a missing symlink is easier to add than a dangling one.
# 0.12.0 has no b3sum, hashsum, sha3-*sum, shake*sum, or relpath
# crates. Those mailing-list names are either later than 0.12.0 or
# reachable as `cksum --algorithm`. `[` is the `test` applet and is
# installed separately (it is not a crate name).
UUTILS_COREUTILS_APPLETS = \
	arch b2sum base32 base64 basename basenc cat chgrp chmod chown chroot \
	cksum comm cp csplit cut date dd df dir dircolors dirname du echo env \
	expand expr factor false fmt fold groups head hostid hostname id install \
	join kill link ln logname ls md5sum mkdir mkfifo mknod mktemp more mv \
	nice nl nohup nproc numfmt od paste pathchk pinky pr printenv printf ptx \
	pwd readlink realpath rm rmdir seq sha1sum sha224sum sha256sum sha384sum \
	sha512sum shred shuf sleep sort split stat stdbuf stty sum sync tac tail \
	tee test timeout touch tr true truncate tsort tty uname unexpand uniq \
	unlink uptime users vdir wc who whoami yes

UUTILS_COREUTILS_CARGO_FEATURES = unix

# feat_selinux is optional: compile chcon/runcon only when libselinux
# is already in the image. Do not list libselinux as a required dep.
ifeq ($(BR2_PACKAGE_LIBSELINUX),y)
UUTILS_COREUTILS_DEPENDENCIES += libselinux
UUTILS_COREUTILS_CARGO_FEATURES += feat_selinux
UUTILS_COREUTILS_APPLETS += chcon runcon
endif

ifeq ($(BR2_PACKAGE_BUSYBOX),y)
UUTILS_COREUTILS_DEPENDENCIES += busybox
endif

ifeq ($(BR2_PACKAGE_UUTILS_COREUTILS_INDIVIDUAL_BINARIES),y)
UUTILS_COREUTILS_CARGO_PACKAGES = \
	$(foreach applet,$(UUTILS_COREUTILS_APPLETS),-p uu_$(applet))
endif

define UUTILS_COREUTILS_BUILD_CMDS
	cd $(@D) && \
	$(TARGET_MAKE_ENV) \
	$(TARGET_CONFIGURE_OPTS) \
	$(PKG_CARGO_ENV) \
	cargo build \
		--offline \
		--manifest-path Cargo.toml \
		--locked \
		--profile=$(UUTILS_COREUTILS_CARGO_PROFILE) \
		$(addprefix --features ,$(UUTILS_COREUTILS_CARGO_FEATURES)) \
		$(UUTILS_COREUTILS_CARGO_PACKAGES)
endef

ifeq ($(BR2_PACKAGE_UUTILS_COREUTILS_INDIVIDUAL_BINARIES),y)
define UUTILS_COREUTILS_INSTALL_TARGET_CMDS
	$(foreach applet,$(UUTILS_COREUTILS_APPLETS), \
		$(INSTALL) -D -m 0755 \
			$(@D)/target/$(RUSTC_TARGET_NAME)/$(UUTILS_COREUTILS_CARGO_PROFILE)/$(applet) \
			$(TARGET_DIR)/usr/bin/$(applet)
	)
	$(INSTALL) -D -m 0755 \
		$(@D)/target/$(RUSTC_TARGET_NAME)/$(UUTILS_COREUTILS_CARGO_PROFILE)/test \
		$(TARGET_DIR)/usr/bin/[
endef
else
define UUTILS_COREUTILS_INSTALL_TARGET_CMDS
	$(INSTALL) -D -m 0755 \
		$(@D)/target/$(RUSTC_TARGET_NAME)/$(UUTILS_COREUTILS_CARGO_PROFILE)/coreutils \
		$(TARGET_DIR)/usr/bin/coreutils
	for util in $(UUTILS_COREUTILS_APPLETS); do \
		ln -sf coreutils $(TARGET_DIR)/usr/bin/$$util; \
	done
	ln -sf coreutils $(TARGET_DIR)/usr/bin/[
endef
endif

$(eval $(cargo-package))
