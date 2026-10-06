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
UUTILS_COREUTILS_TAGS_URL = https://api.github.com/repos/uutils/coreutils/tags?per_page=100
# Immediate assignment: recursive $(MAKEFILE_LIST) at download time is
# docs/manual/, not this package. Buildroot reads hashes from PKGDIR.
UUTILS_COREUTILS_HASH_FILE := $(dir $(lastword $(MAKEFILE_LIST)))uutils-coreutils.hash

UUTILS_COREUTILS_LICENSE = MIT
UUTILS_COREUTILS_LICENSE_FILES = LICENSE

# cargo-package omits --release when BR2_ENABLE_DEBUG=y (dev profile).
# Always build the release profile.
UUTILS_COREUTILS_CARGO_PROFILE = release

# feat_os_unix applets (Cargo.toml unix -> feat_os_unix). Keep in sync
# with 0.12.0; a missing symlink is easier to add than a dangling one.
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

ifeq ($(BR2_PACKAGE_BUSYBOX),y)
UUTILS_COREUTILS_DEPENDENCIES += busybox
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
		--features unix
endef

define UUTILS_COREUTILS_INSTALL_TARGET_CMDS
	$(INSTALL) -D -m 0755 \
		$(@D)/target/$(RUSTC_TARGET_NAME)/$(UUTILS_COREUTILS_CARGO_PROFILE)/coreutils \
		$(TARGET_DIR)/usr/bin/coreutils
	for util in $(UUTILS_COREUTILS_APPLETS); do \
		ln -sf coreutils $(TARGET_DIR)/usr/bin/$$util; \
	done
	ln -sf coreutils $(TARGET_DIR)/usr/bin/[
endef

# If uutils-coreutils.hash already has a sha256 line for this tarball, do
# nothing. Otherwise verify the GitHub tag, hash that one archive, and
# append the line (JIT, only the version being installed).
define UUTILS_COREUTILS_FETCH_HASH
	mkdir -p $(dir $(UUTILS_COREUTILS_HASH_FILE))
	if [ ! -f $(UUTILS_COREUTILS_HASH_FILE) ]; then \
		printf '%s\n' \
			'#' \
			'# Automatically generated file; DO NOT EDIT.' \
			'#' \
			> $(UUTILS_COREUTILS_HASH_FILE); \
	fi
	if ! awk -v f="$(UUTILS_COREUTILS_SOURCE)" \
		'$$1 == "sha256" && $$NF == f { found = 1 } END { exit !found }' \
		$(UUTILS_COREUTILS_HASH_FILE); then \
		tags=$$(wget -qO- --header='User-Agent: Buildroot-uutils-coreutils' \
			--header='Accept: application/vnd.github+json' \
			"$(UUTILS_COREUTILS_TAGS_URL)") || tags=""; \
		if ! echo "$$tags" | grep -qF '"name":"$(UUTILS_COREUTILS_VERSION)"' && \
		   ! echo "$$tags" | grep -qF '"name": "$(UUTILS_COREUTILS_VERSION)"'; then \
			echo "ERROR: uutils-coreutils: tag '$(UUTILS_COREUTILS_VERSION)' not found at $(UUTILS_COREUTILS_TAGS_URL)" >&2; \
			exit 1; \
		fi; \
		tmp=$$(mktemp); \
		if ! wget -qO "$$tmp" --header='User-Agent: Buildroot-uutils-coreutils' \
			"$(UUTILS_COREUTILS_SITE)/$(UUTILS_COREUTILS_SOURCE)"; then \
			rm -f "$$tmp"; \
			echo "ERROR: uutils-coreutils: failed to download $(UUTILS_COREUTILS_SITE)/$(UUTILS_COREUTILS_SOURCE)" >&2; \
			exit 1; \
		fi; \
		sum=$$(sha256sum "$$tmp" | awk '{print $$1}'); \
		rm -f "$$tmp"; \
		printf 'sha256  %s  %s\n' "$$sum" "$(UUTILS_COREUTILS_SOURCE)" \
			>> $(UUTILS_COREUTILS_HASH_FILE); \
	fi
endef
UUTILS_COREUTILS_PRE_DOWNLOAD_HOOKS += UUTILS_COREUTILS_FETCH_HASH

$(eval $(cargo-package))
