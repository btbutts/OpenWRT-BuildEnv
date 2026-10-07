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

$(eval $(autotools-package))
