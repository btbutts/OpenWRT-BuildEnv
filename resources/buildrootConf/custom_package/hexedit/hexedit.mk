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

HEXEDIT_LICENSE = GPL-2.0+
HEXEDIT_LICENSE_FILES = COPYING

# GitHub tag archive has configure.ac / autogen.sh, not a generated configure.
HEXEDIT_AUTORECONF = YES
HEXEDIT_DEPENDENCIES = ncurses

$(eval $(autotools-package))
