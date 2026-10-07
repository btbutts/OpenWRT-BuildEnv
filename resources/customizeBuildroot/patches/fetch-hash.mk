################################################################################
#
# fetch-hash.mk -- JIT sha256 lines for package tarballs
#
# Installed into package/ by getBuildroot.sh --customize,
# --update-kernel-support, and --update-rust-version. Included from
# the top-level Makefile after every package .mk so $(PACKAGES_ALL)
# is complete.
#
# FETCH_HASH_URLS is "pkg|url". $$major / $$minor are filled from
# $(PKG)_VERSION (first dot splits major from the rest).
#
# No matching entry -> wget $SITE/$SOURCE, run $(PKG)_DOWNLOAD_POST_PROCESS
# when set (cargo vendor, go modules, ...), sha256sum that file, and
# leave it in $($(PKG)_DL_DIR) so dl-wrapper reuses the same bytes.
#
################################################################################

FETCH_HASH_URLS = \
	"brush-docs|https://github.com/reubeno/brush/archive/refs/tags/brush-shell-v0.4.0.tar.gz.sha256" \
	"rust|https://static.rust-lang.org/dist/rustc-$(RUST_VERSION)-src.tar.xz.sha256" \
	"usbutils|https://www.kernel.org/pub/linux/utils/usb/usbutils/sha256sums.asc" \
	"linux|https://www.kernel.org/pub/linux/kernel/v$$major.x/sha256sums.asc" \
	"linux-headers|https://www.kernel.org/pub/linux/kernel/v$$major.x/sha256sums.asc" \
	"gcc-standalone-toolchain|https://toolchains.bootlin.com/downloads/releases/toolchains/$(GCC_STANDALONE_TOOLCHAIN_BOOTLIN_ARCH)/tarballs/$(GCC_STANDALONE_TOOLCHAIN_BOOTLIN_ARCH)--$(GCC_STANDALONE_TOOLCHAIN_BOOTLIN_LIBC)--stable-$$major.$$minor.sha256"

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
	if [ ! -f "$$hash_file" ]; then \
		case "$$raw" in linux|linux-headers) \
			echo "ERROR: fetch-hash: missing $$hash_file" >&2; exit 1 ;; \
		esac; \
		mkdir -p "$$(dirname "$$hash_file")"; \
		printf '%s\n' '#' '# Automatically generated file; DO NOT EDIT.' '#' \
			> "$$hash_file"; \
	fi; \
	ver="$(call qstrip,$($(PKG)_VERSION))"; \
	ver="$${ver#v}"; \
	major="$${ver%%.*}"; \
	minor="$${ver#*.}"; \
	[ "$$major" = "$$ver" ] && minor=""; \
	url=""; \
	for e in $(FETCH_HASH_URLS); do \
		[ "$${e%%|*}" = "$$raw" ] && { url="$${e#*|}"; break; }; \
	done; \
	post="$(strip $($(PKG)_DOWNLOAD_POST_PROCESS))"; \
	fetch_sum() { \
		_tb="$$1"; _src="$$2"; _sums="$$3"; _do_post="$$4"; \
		[ -n "$$_tb" ] || return 0; \
		case " $(BR_NO_CHECK_HASH_FOR) " in *" $$_tb "*) return 0 ;; esac; \
		awk -v f="$$_tb" '$$1 == "sha256" && $$NF == f { found = 1 } END { exit !found }' \
			"$$hash_file" && return 0; \
		if [ -n "$$_sums" ]; then \
			tmp=$$(mktemp); \
			if ! $(or $(call qstrip,$(BR2_WGET)),wget) -qO "$$tmp" "$$_sums"; then \
				rm -f "$$tmp"; \
				echo "ERROR: fetch-hash: failed to download $$_sums" >&2; \
				return 1; \
			fi; \
			sum=$$(awk -v f="$$_tb" ' \
				$$2 == f || $$2 == "./" f { print $$1; exit } \
				NF == 1 && $$1 ~ /^[0-9a-fA-F]{64}$$/ { print $$1; exit } \
			' "$$tmp"); \
			rm -f "$$tmp"; \
			if [ -z "$$sum" ]; then \
				echo "ERROR: fetch-hash: $$_tb not listed at $$_sums" >&2; \
				return 1; \
			fi; \
			grep -qxF "# From $$_sums" "$$hash_file" || \
				printf '\n# From %s\n' "$$_sums" >> "$$hash_file"; \
		else \
			if [ -z "$$_src" ] || [ "$$_src" = "/" ]; then \
				echo "ERROR: fetch-hash: no URL for $$_tb" >&2; \
				return 1; \
			fi; \
			tmpd=$$(mktemp -d "$(BUILD_DIR)/.fetch-hash.XXXXXX"); \
			tmpf="$$tmpd/output"; \
			if ! $(or $(call qstrip,$(BR2_WGET)),wget) -O "$$tmpf" "$$_src"; then \
				rm -rf "$$tmpd"; \
				echo "ERROR: fetch-hash: failed to download $$_src" >&2; \
				return 1; \
			fi; \
			if [ "$$_do_post" = y ] && [ -n "$$post" ]; then \
				if ! ( cd "$$tmpd" && \
					TAR="$(TAR)" $(EXTRA_ENV) $($(PKG)_DL_ENV) \
					"$(TOPDIR)/support/download/$$post-post-process" \
						-o "$$tmpf" \
						-n "$($(PKG)_DL_SUBDIR)-$($(PKG)_VERSION)" \
						$($(PKG)_DOWNLOAD_POST_PROCESS_OPTS) ); then \
					rm -rf "$$tmpd"; \
					echo "ERROR: fetch-hash: $$post-post-process failed for $$_tb" >&2; \
					return 1; \
				fi; \
			fi; \
			sum=$$(sha256sum "$$tmpf" | awk '{ print $$1 }'); \
			mkdir -p "$($(PKG)_DL_DIR)"; \
			mv "$$tmpf" "$($(PKG)_DL_DIR)/$$_tb"; \
			rm -rf "$$tmpd"; \
		fi; \
		printf 'sha256  %s  %s\n' "$$sum" "$$_tb" >> "$$hash_file"; \
		printf '%s\n' "--> Appended sha256  $$sum  $$_tb to $$hash_file"; \
	}; \
	fetch_sum "$$tarball" "$($(PKG)_SITE)/$($(PKG)_SOURCE)" "$$url" y || exit 1; \
	$(foreach u,$($(PKG)_EXTRA_DOWNLOADS),fetch_sum "$(notdir $(u))" "$(u)" "" n || exit 1; )
endef

ifeq ($(FETCH_HASH_REGISTERED),)
FETCH_HASH_REGISTERED := y
$(foreach p,$(PACKAGES_ALL), \
$(eval $(call UPPERCASE,$(p))_PRE_DOWNLOAD_HOOKS += FETCH_HASH))
endif
