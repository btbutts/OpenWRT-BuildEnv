################################################################################
#
# kmscon
#
################################################################################

KMSCON_VERSION = $(call qstrip,$(BR2_PACKAGE_KMSCON_VERSION))
ifeq ($(KMSCON_VERSION),)
KMSCON_VERSION = 10.0.4
endif
KMSCON_SITE = $(call github,kmscon,kmscon,v$(KMSCON_VERSION))
# COPYING holds the MIT license plus the ccan htable (LGPL-2.1+) and Unifont
# (OFL-1.1) notices. Enabling font_unifont makes the result OFL-1.1 as a whole.
KMSCON_LICENSE = MIT, LGPL-2.1+ (htable), OFL-1.1 (Unifont)
KMSCON_LICENSE_FILES = COPYING

# Mandatory dependencies (upstream meson.build "Required dependencies"):
#   kmscon-libtsm (kmscon-libtsm.mk), libxkbcommon, libudev (added below), zlib
#   (psf/unifont modules) and
#   host-zlib (genunifont is built for the build machine: native zlib).
# libdrm is selected in Config.in; it backs video_drm2d.
# host-ncurses supplies `tic`, which build_terminfo.py runs at install time to
# put the "kmscon" terminfo entry on the target (TERM=kmscon needs it).
# host-xlib_libX11 is built so that its compose tables ($(HOST_DIR)/share/X11/locale) exist:
# post_build_script/append.sh copies the English one to the target, where libxkbcommon
# looks for it (dead keys and compose sequences in the console).
KMSCON_DEPENDENCIES = \
	host-ncurses \
	host-xlib_libX11 \
	host-zlib \
	kmscon-libtsm \
	libdrm \
	libxkbcommon \
	zlib

# Every -D option below exists in upstream meson.options (10.0.4):
#   boolean (extra_debug, tests) -> true | false
#   feature (all the others)     -> enabled | disabled | auto
#   string  (term)               -> free text
# "auto" is never used so that a stray library in staging cannot change the
# build: each optional feature is explicitly enabled or disabled from the
# Buildroot .config symbol that provides its dependency.
#
# tests needs the "check" library plus cross-built test binaries.
KMSCON_CONF_OPTS += \
	-Dextra_debug=false \
	-Dtests=false \
	-Dterm=kmscon

# Backends that need nothing beyond what is always present (zlib, kernel headers)
KMSCON_CONF_OPTS += \
	-Dfont_psf=enabled \
	-Dfont_unifont=enabled \
	-Dvideo_fbdev=enabled

# libudev is mandatory. systemd provides libudev.pc and systemd.pc (the latter
# gives meson the unit directory), otherwise take whichever libudev provider
# (eudev) is selected.
ifeq ($(BR2_PACKAGE_SYSTEMD),y)
KMSCON_DEPENDENCIES += systemd
else
KMSCON_DEPENDENCIES += libudev
endif

# Seat management through libseat; this replaces the old "multi-seat" idea, it is
# the only seat option kmscon has. kmscon only uses the libseat API, the backend
# (systemd-logind, seatd, built-in) is fixed when libseat is built. Two
# providers, never both (Config.in hides the first when seatd is selected):
#  - BR2_PACKAGE_KMSCON_LIBSEAT: kmscon-libseat (kmscon-libseat.mk), a client-only build of seatd's
#    library that picks logind from BR2_PACKAGE_SYSTEMD_LOGIND. That symbol
#    defaults to y when logind is enabled.
#  - BR2_PACKAGE_SEATD: Buildroot's own seatd package.
ifeq ($(BR2_PACKAGE_KMSCON_LIBSEAT),y)
KMSCON_DEPENDENCIES += kmscon-libseat
KMSCON_CONF_OPTS += -Dlibseat=enabled
else ifeq ($(BR2_PACKAGE_SEATD),y)
KMSCON_DEPENDENCIES += seatd
KMSCON_CONF_OPTS += -Dlibseat=enabled
else
KMSCON_CONF_OPTS += -Dlibseat=disabled
endif

ifeq ($(BR2_PACKAGE_DBUS),y)
KMSCON_DEPENDENCIES += dbus
KMSCON_CONF_OPTS += -Ddbus=enabled
else
KMSCON_CONF_OPTS += -Ddbus=disabled
endif

# kmscon has no PAM build option. PAM is only used at run time: with libseat
# enabled the installed unit has PAMName=kmscon and /etc/pam.d/kmscon is
# installed. Depend on it only so that it is built before kmscon.
ifeq ($(BR2_PACKAGE_LINUX_PAM),y)
KMSCON_DEPENDENCIES += linux-pam
endif

# kmscon installs its "kmscon" terminfo entry into /usr/share/terminfo. When the
# target ncurses is selected, its post-install hook deletes that whole directory
# and reinstalls only its own list, so kmscon has to be installed after ncurses
# or TERM=kmscon silently loses its entry. (The tic that compiles the entry is
# host-ncurses, already a dependency above; target ncurses is not needed for it.)
ifeq ($(BR2_PACKAGE_NCURSES),y)
KMSCON_DEPENDENCIES += ncurses
endif

# TrueType/OpenType text rendering. Upstream's font_freetype needs BOTH
# freetype2 and fontconfig (there is no separate fontconfig option).
ifeq ($(BR2_PACKAGE_FREETYPE)$(BR2_PACKAGE_FONTCONFIG),yy)
KMSCON_DEPENDENCIES += freetype fontconfig
KMSCON_CONF_OPTS += -Dfont_freetype=enabled
else
KMSCON_CONF_OPTS += -Dfont_freetype=disabled
endif

# Pango text rendering (pangoft2). kmscon itself does not use pixman, so it is
# not listed; pango brings in whatever it needs.
ifeq ($(BR2_PACKAGE_PANGO),y)
KMSCON_DEPENDENCIES += pango
KMSCON_CONF_OPTS += -Dfont_pango=enabled
else
KMSCON_CONF_OPTS += -Dfont_pango=disabled
endif

# Software DRM backend ("dumb buffers"): needs libdrm only
ifeq ($(BR2_PACKAGE_LIBDRM),y)
KMSCON_CONF_OPTS += -Dvideo_drm2d=enabled
else
KMSCON_CONF_OPTS += -Dvideo_drm2d=disabled
endif

# GPU renderers come with a GL provider (e.g. mesa3d with GBM, EGL and GLES).
# gltex needs glesv2; drm3d needs libdrm, gbm, egl and glesv2.
ifeq ($(BR2_PACKAGE_HAS_LIBGLES),y)
KMSCON_DEPENDENCIES += libgles
KMSCON_CONF_OPTS += -Drenderer_gltex=enabled
else
KMSCON_CONF_OPTS += -Drenderer_gltex=disabled
endif

ifeq ($(BR2_PACKAGE_LIBDRM)$(BR2_PACKAGE_HAS_LIBEGL)$(BR2_PACKAGE_HAS_LIBGBM)$(BR2_PACKAGE_HAS_LIBGLES),yyyy)
KMSCON_DEPENDENCIES += libegl libgbm libgles
KMSCON_CONF_OPTS += -Dvideo_drm3d=enabled
else
KMSCON_CONF_OPTS += -Dvideo_drm3d=disabled
endif

# Man pages (kmscon.1, kmscon.conf.5), only when man pages are kept. They are
# rendered by xsltproc (host-libxslt) with the DocBook XSL stylesheets
# (host-docbook-xsl, docbook-xsl.mk), which also brings the DocBook XML 4.2 DTD
# (host-docbook-xml, docbook-xml.mk). kmscon looks the stylesheet up by URL with
# --nonet both when configuring and when building, so the catalog that maps it
# to the installed copy (and chains to the DTD) has to be in the environment of
# both steps.
ifeq ($(BR2_KEEP_MAN_PAGES_DOCS),y)
KMSCON_DEPENDENCIES += host-docbook-xsl host-libxslt
KMSCON_CONF_OPTS += -Ddocs=enabled
KMSCON_CONF_ENV += XML_CATALOG_FILES=$(HOST_DOCBOOK_XSL_CATALOG)
KMSCON_NINJA_ENV += XML_CATALOG_FILES=$(HOST_DOCBOOK_XSL_CATALOG)
else
KMSCON_CONF_OPTS += -Ddocs=disabled
endif

# Upstream's own "meson install" already installs kmscon.service and
# kmsconvt@.service (rendered from scripts/systemd/*.service.in) into the unit
# directory reported by systemd.pc. This hook runs only when init is systemd and
# installs the same two rendered units explicitly, so they are on the target
# even if systemd.pc was not found at configure time. The files are not enabled
# here (kmsconvt@tty1 replaces getty on tty1; kmscon.service is multi-user).
define KMSCON_INSTALL_INIT_SYSTEMD
	$(INSTALL) -D -m 0644 $(@D)/buildroot-build/kmscon.service \
		$(TARGET_DIR)/usr/lib/systemd/system/kmscon.service
	$(INSTALL) -D -m 0644 $(@D)/buildroot-build/kmsconvt@.service \
		$(TARGET_DIR)/usr/lib/systemd/system/kmsconvt@.service
endef

$(eval $(meson-package))
