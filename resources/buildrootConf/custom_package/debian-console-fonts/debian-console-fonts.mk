################################################################################
#
# debian-console-fonts (console-setup's PSF console fonts)
#
################################################################################

DEBIAN_CONSOLE_FONTS_VERSION = $(call qstrip,$(BR2_PACKAGE_DEBIAN_CONSOLE_FONTS_VERSION))
ifeq ($(DEBIAN_CONSOLE_FONTS_VERSION),)
DEBIAN_CONSOLE_FONTS_VERSION = 1.242~deb13u1
endif

DEBIAN_CONSOLE_FONTS_SOURCE = console-setup_$(DEBIAN_CONSOLE_FONTS_VERSION).tar.xz
DEBIAN_CONSOLE_FONTS_SITE = https://deb.debian.org/debian/pool/main/c/console-setup

DEBIAN_CONSOLE_FONTS_LICENSE = GPL-2.0+ (bdf2psf), OFL-1.1 (Terminus), fonts: see Fonts/copyright
DEBIAN_CONSOLE_FONTS_LICENSE_FILES = GPL-2 COPYRIGHT copyright.fonts Fonts/copyright

# kbd owns /usr/share/consolefonts; bdf2psf is Perl, a required host tool
DEBIAN_CONSOLE_FONTS_DEPENDENCIES = kbd

# Use the Perl on PATH, not a hard-coded /usr/bin/perl
define DEBIAN_CONSOLE_FONTS_FIX_PERL
	$(SED) '1s|^#!.*perl.*|#!/usr/bin/env perl|' $(@D)/Fonts/bdf2psf
endef

# Newer than any system input, so make never tries to regenerate the bundled BDFs
define DEBIAN_CONSOLE_FONTS_TOUCH_BDFS
	find $(@D)/Fonts/bdf -name '*.bdf' -exec touch {} +
endef

DEBIAN_CONSOLE_FONTS_POST_EXTRACT_HOOKS += DEBIAN_CONSOLE_FONTS_FIX_PERL

ifeq ($(BR2_PACKAGE_DEBIAN_CONSOLE_FONTS_TERMINUS),y)
DEBIAN_CONSOLE_FONTS_TERMINUS_VERSION = $(call qstrip,$(BR2_PACKAGE_DEBIAN_CONSOLE_FONTS_TERMINUS_VERSION))
ifeq ($(DEBIAN_CONSOLE_FONTS_TERMINUS_VERSION),)
DEBIAN_CONSOLE_FONTS_TERMINUS_VERSION = 4.49.1
endif

# SourceForge dirs are <major>.<minor>: 4.49.1 is in terminus-font-4.49/
DEBIAN_CONSOLE_FONTS_TERMINUS_MAJOR = $(word 1,$(subst ., ,$(DEBIAN_CONSOLE_FONTS_TERMINUS_VERSION))).$(word 2,$(subst ., ,$(DEBIAN_CONSOLE_FONTS_TERMINUS_VERSION)))
DEBIAN_CONSOLE_FONTS_TERMINUS_TARBALL = terminus-font-$(DEBIAN_CONSOLE_FONTS_TERMINUS_VERSION).tar.gz

DEBIAN_CONSOLE_FONTS_EXTRA_DOWNLOADS = https://downloads.sourceforge.net/project/terminus-font/terminus-font-$(DEBIAN_CONSOLE_FONTS_TERMINUS_MAJOR)/$(DEBIAN_CONSOLE_FONTS_TERMINUS_TARBALL)

# Replace console-setup's older ter-u*.bdf with the release downloaded above
define DEBIAN_CONSOLE_FONTS_TERMINUS_BDFS
	$(TAR) -xzf $(DEBIAN_CONSOLE_FONTS_DL_DIR)/$(DEBIAN_CONSOLE_FONTS_TERMINUS_TARBALL) \
		-C $(@D)/Fonts/bdf --strip-components=1 --wildcards '*/ter-u*.bdf'
endef
DEBIAN_CONSOLE_FONTS_POST_EXTRACT_HOOKS += DEBIAN_CONSOLE_FONTS_TERMINUS_BDFS
endif

# Touch last, after the Terminus BDFs are in place
DEBIAN_CONSOLE_FONTS_POST_EXTRACT_HOOKS += DEBIAN_CONSOLE_FONTS_TOUCH_BDFS

# Selection for select.makefile: faces as <Face>% (all sizes), code sets by name
DEBIAN_CONSOLE_FONTS_FACE_PATTERNS = \
	$(if $(BR2_PACKAGE_DEBIAN_CONSOLE_FONTS_TERMINUS),Terminus%) \
	$(if $(BR2_PACKAGE_DEBIAN_CONSOLE_FONTS_VGA),VGA%) \
	$(if $(BR2_PACKAGE_DEBIAN_CONSOLE_FONTS_DEJAVU),DejaVu%) \
	$(if $(BR2_PACKAGE_DEBIAN_CONSOLE_FONTS_FIXED),Fixed%)

DEBIAN_CONSOLE_FONTS_CODESETS = \
	$(if $(BR2_PACKAGE_DEBIAN_CONSOLE_FONTS_UNICODE),Uni1 Uni2 Uni3) \
	$(if $(BR2_PACKAGE_DEBIAN_CONSOLE_FONTS_LATIN),Lat15) \
	$(if $(BR2_PACKAGE_DEBIAN_CONSOLE_FONTS_LATIN2),Lat2) \
	$(if $(BR2_PACKAGE_DEBIAN_CONSOLE_FONTS_LATIN7),Lat7) \
	$(if $(BR2_PACKAGE_DEBIAN_CONSOLE_FONTS_LATIN38),Lat38) \
	$(if $(BR2_PACKAGE_DEBIAN_CONSOLE_FONTS_GREEK),Greek) \
	$(if $(BR2_PACKAGE_DEBIAN_CONSOLE_FONTS_CYRILLIC),CyrSlav CyrKoi CyrAsia) \
	$(if $(BR2_PACKAGE_DEBIAN_CONSOLE_FONTS_ARABIC),Arabic) \
	$(if $(BR2_PACKAGE_DEBIAN_CONSOLE_FONTS_HEBREW),Hebrew) \
	$(if $(BR2_PACKAGE_DEBIAN_CONSOLE_FONTS_VIETNAMESE),Vietnamese) \
	$(if $(BR2_PACKAGE_DEBIAN_CONSOLE_FONTS_ARMENIAN),Armenian) \
	$(if $(BR2_PACKAGE_DEBIAN_CONSOLE_FONTS_GEORGIAN),Georgian) \
	$(if $(BR2_PACKAGE_DEBIAN_CONSOLE_FONTS_ETHIOPIAN),Ethiopian) \
	$(if $(BR2_PACKAGE_DEBIAN_CONSOLE_FONTS_LAO),Lao) \
	$(if $(BR2_PACKAGE_DEBIAN_CONSOLE_FONTS_THAI),Thai) \
	$(if $(BR2_PACKAGE_DEBIAN_CONSOLE_FONTS_SCREEN_READER),FullGreek FullCyrSlav FullCyrAsia)

# Faces to leave out, as <Face><size> (one % allowed), e.g. TerminusBoldVGA16
#DEBIAN_CONSOLE_FONTS_SKIP_PATTERNS = TerminusBoldVGA16

ifeq ($(BR2_PACKAGE_DEBIAN_CONSOLE_FONTS),y)
ifeq ($(strip $(DEBIAN_CONSOLE_FONTS_FACE_PATTERNS)),)
$(error debian-console-fonts: select at least one font face)
endif
ifeq ($(strip $(DEBIAN_CONSOLE_FONTS_CODESETS)),)
$(error debian-console-fonts: select at least one code set)
endif
endif

define DEBIAN_CONSOLE_FONTS_BUILD_CMDS
	$(TARGET_MAKE_ENV) $(MAKE) -C $(@D)/Fonts -f $(DEBIAN_CONSOLE_FONTS_PKGDIR)/select.makefile \
		FACE_PATTERNS="$(DEBIAN_CONSOLE_FONTS_FACE_PATTERNS)" \
		CODESETS="$(DEBIAN_CONSOLE_FONTS_CODESETS)" \
		SKIP_PATTERNS="$(DEBIAN_CONSOLE_FONTS_SKIP_PATTERNS)" \
		selected
endef

define DEBIAN_CONSOLE_FONTS_INSTALL_TARGET_CMDS
	$(INSTALL) -d -m 0755 $(TARGET_DIR)/usr/share/consolefonts
	rsync -a --include='*.psf.gz' --exclude='*' \
		$(@D)/Fonts/ $(TARGET_DIR)/usr/share/consolefonts/
endef

$(eval $(generic-package))
