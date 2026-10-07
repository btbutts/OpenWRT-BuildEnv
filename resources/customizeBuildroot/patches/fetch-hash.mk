################################################################################
#
# fetch-hash.mk -- JIT sha256 lines for package tarballs
#
# Installed into package/ by getBuildroot.sh --customize,
# --update-kernel-support, and --update-rust-version. Included from
# the top-level Makefile after every package .mk so $(PACKAGES_ALL)
# is complete.
#
# Heavy lifting is package/fetch_hash_helper.py (FETCH_HASH_URLS lives
# there). This fragment resolves Make variables and invokes system
# python3; host-python may not be built yet at PRE_DOWNLOAD.
#
################################################################################

define FETCH_HASH
	[ -n "$(PKG)" ] || exit 0; \
	case "$(strip $($(PKG)_SITE_METHOD))" in git|svn|bzr|cvs|hg|local|file) exit 0 ;; esac; \
	[ -z "$(call qstrip,$($(PKG)_OVERRIDE_SRCDIR))" ] || exit 0; \
	raw="$($(PKG)_RAWNAME)"; \
	tarball="$(strip $($(PKG)_SOURCE))"; \
	hash_file=""; \
	for f in $($(PKG)_HASH_FILES); do \
		[ -f "$$f" ] && { hash_file="$$f"; break; }; \
	done; \
	[ -n "$$hash_file" ] || hash_file="$($(PKG)_PKGDIR)/$($(PKG)_RAWNAME).hash"; \
	ver="$(call qstrip,$($(PKG)_VERSION))"; \
	ver="$${ver#v}"; \
	site="$(strip $($(PKG)_SITE))"; \
	src="$(strip $($(PKG)_SOURCE))"; \
	tarball_url=""; \
	if [ -n "$$site" ] && [ -n "$$src" ]; then \
		tarball_url="$$site/$$src"; \
	fi; \
	post="$(strip $($(PKG)_DOWNLOAD_POST_PROCESS))"; \
	post_bin=""; \
	if [ -n "$$post" ]; then \
		post_bin="$(TOPDIR)/support/download/$$post-post-process"; \
	fi; \
	TAR="$(TAR)" $(EXTRA_ENV) $($(PKG)_DL_ENV) \
	python3 "$(TOPDIR)/package/fetch_hash_helper.py" \
		--pkg "$$raw" \
		--version "$$ver" \
		--hash-file "$$hash_file" \
		--dl-dir "$($(PKG)_DL_DIR)" \
		--tarball "$$tarball" \
		--tarball-url "$$tarball_url" \
		--work-dir "$(BUILD_DIR)" \
		--no-check "$(BR_NO_CHECK_HASH_FOR)" \
		--post-process "$$post" \
		--post-process-bin "$$post_bin" \
		--post-process-name "$($(PKG)_DL_SUBDIR)-$($(PKG)_VERSION)" \
		--post-process-opts "$($(PKG)_DOWNLOAD_POST_PROCESS_OPTS)" \
		--subst bootlin_arch="$(GCC_STANDALONE_TOOLCHAIN_BOOTLIN_ARCH)" \
		--subst bootlin_libc="$(GCC_STANDALONE_TOOLCHAIN_BOOTLIN_LIBC)" \
		$(foreach u,$($(PKG)_EXTRA_DOWNLOADS),--extra "$(notdir $(u))" "$(if $(findstring ://,$(u)),$(u),$(strip $($(PKG)_SITE))/$(notdir $(u)))")
endef

ifeq ($(FETCH_HASH_REGISTERED),)
FETCH_HASH_REGISTERED := y
$(foreach p,$(PACKAGES_ALL), \
$(eval $(call UPPERCASE,$(p))_PRE_DOWNLOAD_HOOKS += FETCH_HASH))
endif
