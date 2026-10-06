################################################################################
#
# hexedit
#
################################################################################

HEXEDIT_VERSION = $(call qstrip,$(BR2_PACKAGE_HEXEDIT_VERSION))
ifeq ($(HEXEDIT_VERSION),)
HEXEDIT_VERSION = 1.6
endif

HEXEDIT_SITE = $(call github,pixel,hexedit,$(HEXEDIT_VERSION))
HEXEDIT_SOURCE = hexedit-$(HEXEDIT_VERSION).tar.gz
HEXEDIT_TAGS_URL = https://api.github.com/repos/pixel/hexedit/tags?per_page=100
# Immediate assignment: recursive $(MAKEFILE_LIST) at download time is
# docs/manual/, not this package. Buildroot reads hashes from PKGDIR.
HEXEDIT_HASH_FILE := $(dir $(lastword $(MAKEFILE_LIST)))hexedit.hash

HEXEDIT_LICENSE = GPL-2.0+
HEXEDIT_LICENSE_FILES = COPYING

# GitHub tag archive has configure.ac / autogen.sh, not a generated configure.
HEXEDIT_AUTORECONF = YES
HEXEDIT_DEPENDENCIES = ncurses

# If hexedit.hash already has a sha256 line for this tarball, do nothing.
# Otherwise verify HEXEDIT_VERSION on the GitHub tags API, hash that one
# archive, and append the line (JIT, only the version being installed).
define HEXEDIT_FETCH_HASH
	mkdir -p $(dir $(HEXEDIT_HASH_FILE))
	if [ ! -f $(HEXEDIT_HASH_FILE) ]; then \
		printf '%s\n' \
			'#' \
			'# Automatically generated file; DO NOT EDIT.' \
			'#' \
			> $(HEXEDIT_HASH_FILE); \
	fi
	if ! awk -v f="$(HEXEDIT_SOURCE)" \
		'$$1 == "sha256" && $$NF == f { found = 1 } END { exit !found }' \
		$(HEXEDIT_HASH_FILE); then \
		tags=$$(wget -qO- --header='User-Agent: Buildroot-hexedit' \
			--header='Accept: application/vnd.github+json' \
			"$(HEXEDIT_TAGS_URL)") || tags=""; \
		if ! echo "$$tags" | grep -qF '"name":"$(HEXEDIT_VERSION)"' && \
		   ! echo "$$tags" | grep -qF '"name": "$(HEXEDIT_VERSION)"'; then \
			echo "ERROR: hexedit: tag '$(HEXEDIT_VERSION)' not found at $(HEXEDIT_TAGS_URL)" >&2; \
			exit 1; \
		fi; \
		tmp=$$(mktemp); \
		if ! wget -qO "$$tmp" --header='User-Agent: Buildroot-hexedit' \
			"$(HEXEDIT_SITE)/$(HEXEDIT_SOURCE)"; then \
			rm -f "$$tmp"; \
			echo "ERROR: hexedit: failed to download $(HEXEDIT_SITE)/$(HEXEDIT_SOURCE)" >&2; \
			exit 1; \
		fi; \
		sum=$$(sha256sum "$$tmp" | awk '{print $$1}'); \
		rm -f "$$tmp"; \
		printf 'sha256  %s  %s\n' "$$sum" "$(HEXEDIT_SOURCE)" \
			>> $(HEXEDIT_HASH_FILE); \
	fi
endef
HEXEDIT_PRE_DOWNLOAD_HOOKS += HEXEDIT_FETCH_HASH

$(eval $(autotools-package))
