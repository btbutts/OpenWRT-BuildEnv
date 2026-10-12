################################################################################
#
# groff
#
################################################################################

GROFF_VERSION = $(call qstrip,$(BR2_PACKAGE_GROFF_VERSION))
GROFF_SOURCE = groff-$(GROFF_VERSION).tar.gz
GROFF_SITE = $(BR2_GNU_MIRROR)/groff
GROFF_LICENSE = GPLv3+
GROFF_LICENSE_FILES = COPYING

# Force the build system to use the host's compiled groff tools for docs
GROFF_DEPENDENCIES = host-groff

# Note: groff calls itself during make install
# http://lists.gnu.org/archive/html/bug-groff/2009-08/msg00004.html
GROFF_MAKE_OPTS = \
	GROFF_BIN_PATH=$(HOST_DIR)/bin \
	GROFFBIN=$(HOST_DIR)/bin/groff

# Intercept groff's upstream hardcoded "test-groff" path bug
define GROFF_CREATE_TEST_GROFF_SYMLINK
	ln -sf $(HOST_DIR)/bin/groff $(HOST_DIR)/bin/test-groff
endef
GROFF_PRE_CONFIGURE_HOOKS += GROFF_CREATE_TEST_GROFF_SYMLINK

$(eval $(autotools-package))
$(eval $(host-autotools-package))
