################################################################################
#
# sharutils
#
################################################################################

SHARUTILS_VERSION = $(call qstrip,$(BR2_PACKAGE_SHARUTILS_VERSION))
ifeq ($(SHARUTILS_VERSION),)
SHARUTILS_VERSION = 4.9
endif

SHARUTILS_SOURCE = sharutils-$(SHARUTILS_VERSION).tar.gz
SHARUTILS_SITE = $(BR2_GNU_MIRROR)/sharutils
# Immediate assignment: recursive $(MAKEFILE_LIST) at download time is
# docs/manual/, not this package. Buildroot reads hashes from PKGDIR.
SHARUTILS_HASH_FILE := $(dir $(lastword $(MAKEFILE_LIST)))sharutils.hash

SHARUTILS_LICENSE = GPLv3+
SHARUTILS_LICENSE_FILES = COPYING
SHARUTILS_DEPENDENCIES = openssl gnutls host-gettext
SHARUTILS_CONF_OPTS = --disable-dependency-tracking

# GCC 15 defaults to C23, where empty () means (void) and 4.9's K&R
# libc redecls conflict with glibc. gnu17 matches the language 4.9
# was written for and still allows gnulib's stdbool.h.
SHARUTILS_CFLAGS = -std=gnu17

# glibc malloc(0) returns non-NULL; skip AC_FUNC_MALLOC run tests if they
# appear. 4.9 still has a separate uncached popen("rb") AC_RUN_IFELSE
# (0001), gnulib stdio.in.h still poisons gets after glibc dropped it
# (0002), unlinkat.c calls malloc/free without stdlib.h (0003), and
# 0004 drops K&R libc redecls plus adds ctype.h for isspace.
SHARUTILS_CONF_ENV = \
	ac_cv_func_malloc_0_nonnull=yes \
	ac_cv_func_realloc_0_nonnull=yes

# If sharutils.hash already has a sha256 line for this tarball, do nothing.
# Otherwise confirm the tarball exists on the GNU mirror, hash that one
# archive, and append the line (JIT, only the version being installed).
define SHARUTILS_FETCH_HASH
	mkdir -p $(dir $(SHARUTILS_HASH_FILE))
	if [ ! -f $(SHARUTILS_HASH_FILE) ]; then \
		printf '%s\n' \
			'#' \
			'# Automatically generated file; DO NOT EDIT.' \
			'#' \
			> $(SHARUTILS_HASH_FILE); \
	fi
	if ! awk -v f="$(SHARUTILS_SOURCE)" \
		'$$1 == "sha256" && $$NF == f { found = 1 } END { exit !found }' \
		$(SHARUTILS_HASH_FILE); then \
		if ! wget --spider -q "$(SHARUTILS_SITE)/$(SHARUTILS_SOURCE)"; then \
			echo "ERROR: sharutils: $(SHARUTILS_SOURCE) not found at $(SHARUTILS_SITE)" >&2; \
			exit 1; \
		fi; \
		tmp=$$(mktemp); \
		if ! wget -qO "$$tmp" "$(SHARUTILS_SITE)/$(SHARUTILS_SOURCE)"; then \
			rm -f "$$tmp"; \
			echo "ERROR: sharutils: failed to download $(SHARUTILS_SITE)/$(SHARUTILS_SOURCE)" >&2; \
			exit 1; \
		fi; \
		sum=$$(sha256sum "$$tmp" | awk '{print $$1}'); \
		rm -f "$$tmp"; \
		printf 'sha256  %s  %s\n' "$$sum" "$(SHARUTILS_SOURCE)" \
			>> $(SHARUTILS_HASH_FILE); \
	fi
endef
SHARUTILS_PRE_DOWNLOAD_HOOKS += SHARUTILS_FETCH_HASH

$(eval $(autotools-package))
