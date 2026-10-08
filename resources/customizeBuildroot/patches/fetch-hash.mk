################################################################################
#
# fetch-hash.mk -- JIT sha256 lines for package tarballs
#
# Installed into package/ by getBuildroot.sh --customize,
# --update-kernel-support, and --update-rust-version. Included from
# the top-level Makefile after every package .mk so $(PACKAGES_ALL)
# is complete.
#
# Before a package is downloaded, each file it fetches (the main tarball and
# $(PKG)_EXTRA_DOWNLOADS) needs a "sha256" line in its .hash file. For a file
# that has none, package/fetch_hash_helper.py (host python3 if built, else system
# python3) appends one, taking the digest from
# FETCH_HASH_URL.<key> when that is set and otherwise from the tarball itself,
# which it leaves in $($(PKG)_DL_DIR) so dl-wrapper reuses the same bytes.
#
################################################################################

# Buildroot's host python3, but only once host-ca-certificates has installed
# its bundle (written last, so it marks a finished install): the host OpenSSL
# has no other trust store, and without it every https download fails with
# CERTIFICATE_VERIFY_FAILED. Until then, the distro python3. Chosen per
# package, when its hook runs, so it follows build order. Never a bare
# "python3": EXTRA_ENV puts host/bin first on PATH, so that would pick the
# host one without any check.
FETCH_HASH_HOST_PYTHON = $(HOST_DIR)/bin/python3
FETCH_HASH_HOST_CA = $(HOST_DIR)/etc/ssl/certs/ca-certificates.crt
FETCH_HASH_PYTHON ?= $(if $(and $(wildcard $(FETCH_HASH_HOST_PYTHON)),$(wildcard $(FETCH_HASH_HOST_CA))),$(FETCH_HASH_HOST_PYTHON),/usr/bin/python3)

# Published checksum files. <key> is $(PKG)_RAWNAME for a package's main
# tarball, or the file's basename for an EXTRA_DOWNLOADS entry. Values are
# expanded per package, so $(FETCH_HASH_VERSION) is that package's version.
FETCH_HASH_VERSION = $(patsubst v%,%,$(call qstrip,$($(PKG)_VERSION)))
FETCH_HASH_MAJOR = $(firstword $(subst ., ,$(FETCH_HASH_VERSION)))
FETCH_HASH_BOOTLIN = https://toolchains.bootlin.com/downloads/releases/toolchains/$(GCC_STANDALONE_TOOLCHAIN_BOOTLIN_ARCH)/tarballs

FETCH_HASH_URL.rust = https://static.rust-lang.org/dist/rustc-$(FETCH_HASH_VERSION)-src.tar.xz.sha256
FETCH_HASH_URL.usbutils = https://www.kernel.org/pub/linux/utils/usb/usbutils/sha256sums.asc
FETCH_HASH_URL.linux = https://www.kernel.org/pub/linux/kernel/v$(FETCH_HASH_MAJOR).x/sha256sums.asc
FETCH_HASH_URL.linux-headers = $(FETCH_HASH_URL.linux)
FETCH_HASH_URL.gcc-standalone-toolchain = $(FETCH_HASH_BOOTLIN)/$(GCC_STANDALONE_TOOLCHAIN_BOOTLIN_ARCH)--$(GCC_STANDALONE_TOOLCHAIN_BOOTLIN_LIBC)--stable-$(FETCH_HASH_VERSION).sha256
FETCH_HASH_URL.brush-docs.tar.gz = https://github.com/reubeno/brush/releases/download/brush-shell-v$(FETCH_HASH_VERSION)/brush-docs.tar.gz.sha256

# The main tarball is the only file $(PKG)_DOWNLOAD_POST_PROCESS applies to.
FETCH_HASH_POST = $(if $(strip $($(PKG)_DOWNLOAD_POST_PROCESS)),$(TOPDIR)/support/download/$(strip $($(PKG)_DOWNLOAD_POST_PROCESS))-post-process -n $($(PKG)_DL_SUBDIR)-$($(PKG)_VERSION) $($(PKG)_DOWNLOAD_POST_PROCESS_OPTS))

# An EXTRA_DOWNLOADS entry is a full URL, or a name relative to the package site.
FETCH_HASH_EXTRA_URL = $(if $(findstring ://,$(1)),$(1),$(strip $($(PKG)_SITE))/$(notdir $(1)))

# $(1) FETCH_HASH_URL key  $(2) file name  $(3) download URL  $(4) post-process
define FETCH_HASH_ONE
	$(if $(filter $(2),$(BR_NO_CHECK_HASH_FOR)),, \
	awk -v f="$(2)" '$$1 == "sha256" && $$NF == f { found = 1 } END { exit !found }' \
		"$$hash_file" 2>/dev/null || \
	TAR="$(TAR)" $(EXTRA_ENV) $($(PKG)_DL_ENV) \
	"$(FETCH_HASH_PYTHON)" "$(TOPDIR)/package/fetch_hash_helper.py" "$$hash_file" "$(2)" "$(3)" \
		--dl-dir "$($(PKG)_DL_DIR)" \
		$(if $(FETCH_HASH_URL.$(1)),--sidecar "$(FETCH_HASH_URL.$(1))") \
		$(if $(4),--post-process "$(4)") || exit 1;)
endef

define FETCH_HASH
	[ -n "$(PKG)" ] || exit 0; \
	case "$(strip $($(PKG)_SITE_METHOD))" in git|svn|bzr|cvs|hg|local|file) exit 0 ;; esac; \
	[ -z "$(call qstrip,$($(PKG)_OVERRIDE_SRCDIR))" ] || exit 0; \
	hash_file=""; \
	for f in $($(PKG)_HASH_FILES); do \
		[ -f "$$f" ] && { hash_file="$$f"; break; }; \
	done; \
	[ -n "$$hash_file" ] || hash_file="$($(PKG)_PKGDIR)/$($(PKG)_RAWNAME).hash"; \
	$(if $(strip $($(PKG)_SOURCE)),$(call FETCH_HASH_ONE,$($(PKG)_RAWNAME),$(strip $($(PKG)_SOURCE)),$(if $(strip $($(PKG)_SITE)),$(strip $($(PKG)_SITE))/$(strip $($(PKG)_SOURCE))),$(FETCH_HASH_POST))) \
	$(foreach u,$($(PKG)_EXTRA_DOWNLOADS),$(call FETCH_HASH_ONE,$(notdir $(u)),$(notdir $(u)),$(call FETCH_HASH_EXTRA_URL,$(u)),))
endef

ifeq ($(FETCH_HASH_REGISTERED),)
FETCH_HASH_REGISTERED := y
$(foreach p,$(PACKAGES_ALL), \
$(eval $(call UPPERCASE,$(p))_PRE_DOWNLOAD_HOOKS += FETCH_HASH))
endif
