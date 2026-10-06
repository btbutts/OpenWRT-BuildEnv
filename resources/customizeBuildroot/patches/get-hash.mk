################################################################################
#
# get-hash.mk -- JIT kernel.org sha256 lines for linux / linux-headers
#
# Installed into linux/from-6.17/ by getBuildroot.sh --update-kernel-support
# and included from the top-level Makefile before package/*/*.mk so both
# linux and linux-headers see the PRE_DOWNLOAD_HOOKS. Those hooks run
# before the hash check, so a tarball that is on cdn.kernel.org but
# missing from linux.hash (e.g. linux-7.2.9.tar.xz) gets its official
# sum appended. linux.hash is never created; it already exists.
#
################################################################################

# Include time: MAKEFILE_LIST is this file. Do not use recursive = .
LINUX_HASH_FILE := $(dir $(lastword $(MAKEFILE_LIST)))linux.hash

# $(1) = tarball basename (linux-7.2.9.tar.xz). No-op when the sha256 line
# already exists. Otherwise wget v6.x / v7.x sha256sums.asc and insert the
# matching line under that series' "# From .../vN.x/sha256sums.asc" section.
define LINUX_APPEND_KERNEL_ORG_HASH
	tarball="$(strip $(1))"; \
	if [ -z "$$tarball" ]; then exit 0; fi; \
	if [ ! -f $(LINUX_HASH_FILE) ]; then \
		echo "ERROR: linux hash: missing $(LINUX_HASH_FILE)" >&2; \
		exit 1; \
	fi; \
	if awk -v f="$$tarball" \
		'$$1 == "sha256" && $$NF == f { found = 1 } END { exit !found }' \
		$(LINUX_HASH_FILE); then \
		exit 0; \
	fi; \
	major=$$(printf '%s\n' "$$tarball" | sed -n 's/^linux-\([0-9][0-9]*\)\..*/\1/p'); \
	case "$$major" in \
		6|7) ;; \
		*) echo "ERROR: linux hash: $$tarball is not a 6.x or 7.x tarball" >&2; exit 1 ;; \
	esac; \
	sums_url="https://cdn.kernel.org/pub/linux/kernel/v$$major.x/sha256sums.asc"; \
	section="# From https://www.kernel.org/pub/linux/kernel/v$$major.x/sha256sums.asc"; \
	tmp=$$(mktemp); \
	if ! wget -qO "$$tmp" --header='User-Agent: Buildroot-linux-hash' "$$sums_url"; then \
		rm -f "$$tmp"; \
		echo "ERROR: linux hash: failed to download $$sums_url" >&2; \
		exit 1; \
	fi; \
	sum=$$(awk -v f="$$tarball" '$$2 == f { print $$1; exit }' "$$tmp"); \
	rm -f "$$tmp"; \
	if [ -z "$$sum" ]; then \
		echo "ERROR: linux hash: $$tarball not listed at $$sums_url" >&2; \
		exit 1; \
	fi; \
	line="sha256  $$sum  $$tarball"; \
	out=$$(mktemp); \
	awk -v section="$$section" -v line="$$line" ' \
		$$0 == section { print; insec = 1; next } \
		insec && (/^$$/ || /^# /) { print line; print; inserted = 1; insec = 0; next } \
		!inserted && $$0 == "# Licenses hashes" { \
			print section; print line; print ""; inserted = 1 \
		} \
		{ print } \
		END { \
			if (insec && !inserted) print line; \
			if (!inserted) { print ""; print section; print line } \
		}' $(LINUX_HASH_FILE) > "$$out" || { rm -f "$$out"; exit 1; }; \
	mv "$$out" $(LINUX_HASH_FILE); \
	printf '%s\n' "--> Appended $$line to $(LINUX_HASH_FILE)"
endef

define LINUX_GET_HASH
	$(call LINUX_APPEND_KERNEL_ORG_HASH,$(LINUX_SOURCE))
endef

define LINUX_HEADERS_GET_HASH
	$(call LINUX_APPEND_KERNEL_ORG_HASH,$(LINUX_HEADERS_SOURCE))
endef

LINUX_PRE_DOWNLOAD_HOOKS += LINUX_GET_HASH
LINUX_HEADERS_PRE_DOWNLOAD_HOOKS += LINUX_HEADERS_GET_HASH
