################################################################################
#
# debian-console-fonts (Debian console-setup style PSF console fonts)
#
################################################################################

# A release of github.com/btbutts/debian-console-fonts: the fonts' sources, the code
# set tables and the Python tool (psf_font_maker) that builds the PSF fonts from them.
# Its Makefile does the work; this file only chooses faces and code sets and says where
# things are, so that nothing is downloaded while building (see make source).
DEBIAN_CONSOLE_FONTS_VERSION = $(call qstrip,$(BR2_PACKAGE_DEBIAN_CONSOLE_FONTS_VERSION))
ifeq ($(DEBIAN_CONSOLE_FONTS_VERSION),)
DEBIAN_CONSOLE_FONTS_VERSION = 0.0.4
endif

# The release asset: one top-level directory, so Buildroot's default extraction works.
# (Not GitHub's "Source code" archive of the tag, which holds the whole repository.)
DEBIAN_CONSOLE_FONTS_SOURCE = debian-console-fonts-$(DEBIAN_CONSOLE_FONTS_VERSION).tar.gz
DEBIAN_CONSOLE_FONTS_SITE = \
	https://github.com/btbutts/debian-console-fonts/releases/download/v$(DEBIAN_CONSOLE_FONTS_VERSION)

DEBIAN_CONSOLE_FONTS_LICENSE = GPL-2.0+ (tool, tables), fonts: see data/fontsets/*/LICENSE.md
DEBIAN_CONSOLE_FONTS_LICENSE_FILES = \
	LICENSE \
	data/LICENSE.md \
	data/fontsets/debian-legacy-fonts/LICENSE.md \
	data/fontsets/dejavu/LICENSE.md \
	data/fontsets/terminus-font/LICENSE.md \
	data/fontsets/ucs-fonts/LICENSE.md \
	data/fontsets/uni-vga/LICENSE.md

# kbd owns /usr/share/consolefonts. The tool is Python 3.12 or later, standard library
# only, and runs on the host; the fonts are built here and only the results are installed.
DEBIAN_CONSOLE_FONTS_DEPENDENCIES = kbd host-python3

# Faces as <Face>% (all sizes), code sets by name
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

# Faces to leave out, as <Face><size> (one % allowed), e.g. TerminusBoldVGA16. Left
# undefined it is not passed on, so the tool's own defaults apply.
#DEBIAN_CONSOLE_FONTS_SKIP_PATTERNS = TerminusBoldVGA16

ifeq ($(BR2_PACKAGE_DEBIAN_CONSOLE_FONTS),y)
ifeq ($(strip $(DEBIAN_CONSOLE_FONTS_FACE_PATTERNS)),)
$(error debian-console-fonts: select at least one font face)
endif
ifeq ($(strip $(DEBIAN_CONSOLE_FONTS_CODESETS)),)
$(error debian-console-fonts: select at least one code set)
endif
endif

# Only DejaVu is drawn from TrueType files, with the freetype-py package and FreeType 2.13.3
# or later: Buildroot's host packages. The tool finds them itself (the Python it is run with
# is $(HOST_DIR)/bin/python3, and Buildroot exports HOST_DIR), so nothing is passed on.
ifeq ($(BR2_PACKAGE_DEBIAN_CONSOLE_FONTS_DEJAVU),y)
DEBIAN_CONSOLE_FONTS_DEPENDENCIES += host-freetype host-python-freetype-py
endif

# The tool runs on the build machine, with the host's compiler and environment, never the
# target's cross toolchain. It first writes down its configuration and checks its
# requirements, all of it written to the log. QUIET=1 only says less while the fonts are made
# (VERBOSE=1: more, every conversion warning included).
define DEBIAN_CONSOLE_FONTS_BUILD_CMDS
	$(HOST_MAKE_ENV) $(HOST_CONFIGURE_OPTS) $(MAKE1) -C $(@D) fonts \
		PYTHON="$(HOST_DIR)/bin/python3" \
		OUT="$(@D)/out" \
		FACES="$(strip $(DEBIAN_CONSOLE_FONTS_FACE_PATTERNS))" \
		CODESETS="$(strip $(DEBIAN_CONSOLE_FONTS_CODESETS))" \
		JOBS="$(PARALLEL_JOBS)" \
		$(if $(strip $(DEBIAN_CONSOLE_FONTS_SKIP_PATTERNS)),SKIP="$(DEBIAN_CONSOLE_FONTS_SKIP_PATTERNS)")
endef

# The fonts are built into $(@D)/out above; install only those, as before.
define DEBIAN_CONSOLE_FONTS_INSTALL_TARGET_CMDS
	$(INSTALL) -d -m 0755 $(TARGET_DIR)/usr/share/consolefonts
	$(INSTALL) -m 0644 $(@D)/out/*.psf.gz $(TARGET_DIR)/usr/share/consolefonts/
endef

$(eval $(generic-package))
