################################################################################
#
# terminus-font (Terminus console fonts, PSF only)
#
################################################################################

TERMINUS_FONT_VERSION = $(call qstrip,$(BR2_PACKAGE_TERMINUS_FONT_VERSION))
ifeq ($(TERMINUS_FONT_VERSION),)
TERMINUS_FONT_VERSION = 4.49.1
endif

# SourceForge dirs are <major>.<minor>: 4.49.1 is in terminus-font-4.49/
TERMINUS_FONT_MAJOR = $(word 1,$(subst ., ,$(TERMINUS_FONT_VERSION))).$(word 2,$(subst ., ,$(TERMINUS_FONT_VERSION)))

TERMINUS_FONT_SOURCE = terminus-font-$(TERMINUS_FONT_VERSION).tar.gz
TERMINUS_FONT_SITE = https://downloads.sourceforge.net/project/terminus-font/terminus-font-$(TERMINUS_FONT_MAJOR)

TERMINUS_FONT_LICENSE = OFL-1.1
TERMINUS_FONT_LICENSE_FILES = OFL.TXT

# kbd owns /usr/share/consolefonts
TERMINUS_FONT_DEPENDENCIES = kbd

# Prefer Buildroot's python3 if already built, or if the host has no usable one
ifneq ($(wildcard $(HOST_DIR)/bin/python3)$(BR2_PYTHON3_HOST_DEPENDENCY),)
TERMINUS_FONT_DEPENDENCIES += host-python3
TERMINUS_FONT_PYTHON = $(HOST_DIR)/bin/python3
else
TERMINUS_FONT_PYTHON = $(call suitable-host-package,python3,$(BR2_PYTHON3_VERSION_MIN) python3 python)
endif

# Variables go to make, not ./configure. psf = console fonts only, no X11 tools
TERMINUS_FONT_MAKE_OPTS = \
	INT="$(TERMINUS_FONT_PYTHON)" \
	psfdir=/usr/share/consolefonts

define TERMINUS_FONT_BUILD_CMDS
	$(TARGET_MAKE_ENV) $(MAKE) -C $(@D) $(TERMINUS_FONT_MAKE_OPTS) psf
endef

define TERMINUS_FONT_INSTALL_TARGET_CMDS
	$(TARGET_MAKE_ENV) $(MAKE) -C $(@D) $(TERMINUS_FONT_MAKE_OPTS) \
		DESTDIR=$(TARGET_DIR) install-psf
endef

$(eval $(generic-package))
