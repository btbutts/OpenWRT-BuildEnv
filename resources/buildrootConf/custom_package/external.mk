# A list of filename patterns matching buildroot build-time artificates we
# want to exclude from being copied to the target rootfs during finalization
CUSTOM_PACKAGE_TARGET_DIR_EXCLUDES = \
	--exclude='/.stamp_*' \
	--exclude='/.applied_patches_list' \
	--exclude='/.files-list*'

BR2_EXTERNAL_OPENWRT_INSTALLER_CUSTOM_PACKAGE_VERSION = 0.1.0
include $(sort $(wildcard $(BR2_EXTERNAL_OPENWRT_INSTALLER_CUSTOM_PACKAGE_PATH)/*/*.mk))
