#!/bin/bash
set -e

TARGET_DIR="/builder/OpenWRT-ImageBuilder"
TARBALL_PATTERN="/builder/openwrt-imagebuilder-*.tar.zst"
MARKER_FILE="$TARGET_DIR/.extracted_marker"

# 1. Create the target directory structure if it doesn't exist
mkdir -p "$TARGET_DIR"

# 2. Check if the extraction has already been completed in a previous run
if [ ! -f "$MARKER_FILE" ]; then

    # Set permissions so the 'builder' user owns OpenWRT Image Builder
    sudo mkdir -p /builder/OpenWRT-ImageBuilder
    sudo chown -R builder:builder /builder

    echo "First boot detected: Extracting OpenWRT Image Builder..."
    
    # Expand the wildcard pattern to find the actual tarball filename
    TARBALL=$(find /builder -maxdepth 1 -type f -name 'openwrt-imagebuilder-*.tar.zst' | head -n 1)

    if [ -z "$TARBALL" ] || [ ! -f "$TARBALL" ]; then
        echo "Error: No OpenWRT Image Builder tarball found matching $TARBALL_PATTERN"
        exit 1
    fi

    # Perform the extraction. 
    # Because your Mac volume is mounted at /builder/OpenWRT-ImageBuilder/build_dir,
    # any extracted files matching that path will stream directly onto your Mac's storage.
    tar --zstd -xvf "$TARBALL" -C "$TARGET_DIR" --strip-components=1
        
    # Place a hidden marker file so we safely skip this on subsequent container starts
    touch "$MARKER_FILE"
    
    # Optional: Delete the internal tarball to save container disk space
    rm -f "$TARBALL"
    echo "Extraction complete!"
else
    echo "OpenWRT Image Builder already extracted. Skipping."
    sudo chown -R builder:builder /builder
fi
