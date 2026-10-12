################################################################################
#
# libseat, seat management client library built from seatd's source for kmscon
#
################################################################################

KMSCON_LIBSEAT_VERSION = $(call qstrip,$(BR2_PACKAGE_KMSCON_LIBSEAT_VERSION))
ifeq ($(KMSCON_LIBSEAT_VERSION),)
KMSCON_LIBSEAT_VERSION = 0.9.3
endif
KMSCON_LIBSEAT_SITE = $(call github,kennylevinsen,seatd,$(KMSCON_LIBSEAT_VERSION))
KMSCON_LIBSEAT_LICENSE = MIT
KMSCON_LIBSEAT_LICENSE_FILES = LICENSE
KMSCON_LIBSEAT_INSTALL_STAGING = YES

# Client library only. Options come from seatd's meson_options.txt (0.9.3):
#   libseat-logind  combo   auto | disabled | elogind | systemd
#   libseat-seatd   combo   enabled | disabled   (client for an external seatd)
#   libseat-builtin combo   enabled | disabled   (seatd server inside libseat)
#   server          combo   enabled | disabled   (seatd + seatd-launch binaries)
#   examples        combo   enabled | disabled
#   man-pages       feature auto | enabled | disabled
#   defaultpath     string  seatd socket path; only used by the seatd backend,
#                           which is off, so it is left at its default
# -Dwerror=false: upstream builds with -Werror, which may trip newer toolchains
KMSCON_LIBSEAT_CONF_OPTS += \
	-Dserver=disabled \
	-Dlibseat-seatd=disabled \
	-Dexamples=disabled \
	-Dwerror=false

# libseat needs at least one backend or it does not compile. Prefer
# systemd-logind, which needs no extra daemon. Without logind, fall back to the
# built-in backend (the seatd server code linked into libseat, no daemon, root
# only) so libseat still builds.
ifeq ($(BR2_PACKAGE_SYSTEMD_LOGIND),y)
KMSCON_LIBSEAT_DEPENDENCIES += systemd
KMSCON_LIBSEAT_CONF_OPTS += \
	-Dlibseat-logind=systemd \
	-Dlibseat-builtin=disabled
else
KMSCON_LIBSEAT_CONF_OPTS += \
	-Dlibseat-logind=disabled \
	-Dlibseat-builtin=enabled
endif

# The man pages that "man-pages" controls belong to seatd and seatd-launch, which
# are only built with -Dserver=enabled (see meson.build: scdoc is not searched
# otherwise). With the server off this is accepted but has no effect; host-scdoc
# would be required here if the server were ever turned on.
ifeq ($(BR2_KEEP_MAN_PAGES_DOCS),y)
KMSCON_LIBSEAT_CONF_OPTS += -Dman-pages=enabled
else
KMSCON_LIBSEAT_CONF_OPTS += -Dman-pages=disabled
endif

# Buildroot names a package after the directory of its .mk file, so the usual
# $(eval $(meson-package)) here would declare "kmscon" a second time. This file
# lives in the kmscon directory, so the package is declared by name instead.
# Its enable symbol is therefore BR2_PACKAGE_KMSCON_LIBSEAT and its hash file is
# kmscon-libseat.hash (next to kmscon.hash).
$(eval $(call inner-meson-package,kmscon-libseat,KMSCON_LIBSEAT,KMSCON_LIBSEAT,target))
