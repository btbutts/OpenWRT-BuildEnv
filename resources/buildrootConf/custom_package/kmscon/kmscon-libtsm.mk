################################################################################
#
# libtsm, a dependency for kmscon providing terminal emulation capabilities
#
################################################################################

KMSCON_LIBTSM_VERSION = $(call qstrip,$(BR2_PACKAGE_KMSCON_LIBTSM_VERSION))
ifeq ($(KMSCON_LIBTSM_VERSION),)
KMSCON_LIBTSM_VERSION = 4.8.0
endif
KMSCON_LIBTSM_SITE = $(call github,kmscon,libtsm,v$(KMSCON_LIBTSM_VERSION))
# LICENSE_htable is the ccan hash table (LGPL-2.1+), everything else is MIT
KMSCON_LIBTSM_LICENSE = MIT, LGPL-2.1+ (htable)
KMSCON_LIBTSM_LICENSE_FILES = COPYING LICENSE_htable
KMSCON_LIBTSM_INSTALL_STAGING = YES

# xkbcommon is optional upstream (it falls back to a bundled keysym header);
# depend on it so detection is the same on every build.
KMSCON_LIBTSM_DEPENDENCIES = libxkbcommon

# libtsm is a Meson project (no CMake). tests needs "check" and gtktsm needs GTK.
KMSCON_LIBTSM_CONF_OPTS += \
	-Dextra_debug=false \
	-Dtests=false \
	-Dgtktsm=false

# Buildroot names a package after the directory of its .mk file, so the usual
# $(eval $(meson-package)) here would declare "kmscon" a second time. This file
# lives in the kmscon directory, so the package is declared by name instead.
# Its enable symbol is therefore BR2_PACKAGE_KMSCON_LIBTSM and its hash file is
# kmscon-libtsm.hash (next to kmscon.hash).
$(eval $(call inner-meson-package,kmscon-libtsm,KMSCON_LIBTSM,KMSCON_LIBTSM,target))
