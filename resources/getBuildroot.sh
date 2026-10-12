#!/bin/bash
set -e

: "${BUILDER_ROOT_DIR:=/builder}"
: "${BUILDROOT_BUILDER_DIR:=/builder/Buildroot-Builder}"
: "${BUILDROOT_OUTPUT_DIR:=/builder/workspace/output/buildroot}"
: "${WORKSPACE_DIR:=/builder/workspace}"
: "${BR_VERSION_OVERRIDE:=}"

VERSION="${BR_VERSION_OVERRIDE}" # Define version override here
BUILDROOT_URL="https://buildroot.org/downloads/"
CUSTOMIZER="${BUILDER_ROOT_DIR%/}/customizeBuildroot/main.py"

# Argument Parser
UPGRADE_FLAG=false
FORCE_FLAG=false
CUSTOMIZE_FLAG=false
UPDATE_KERNEL_FLAG=false
UPDATE_RUST_FLAG=false
while [[ $# -gt 0 ]]; do
    case "$1" in
        -U|--upgrade)
            UPGRADE_FLAG=true
            shift
            ;;
        -f|--force)
            FORCE_FLAG=true
            shift
            ;;
        --customize)
            CUSTOMIZE_FLAG=true
            shift
            ;;
        --update-kernel-support)
            UPDATE_KERNEL_FLAG=true
            shift
            ;;
        --update-rust-version)
            UPDATE_RUST_FLAG=true
            shift
            ;;
        *)
            printf 'Error: Unknown option specified: %s\n' "$1" >&2
            exit 1
            ;;
    esac
done

get_br_version() {
    local url="$1"
    
    curl -s "$url" | python3 -c '
import sys, re
from html.parser import HTMLParser

class LinkExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []
    def handle_starttag(self, tag, attrs):
        if tag == "a":
            for attr, value in attrs:
                if attr == "href":
                    self.links.append(value)

parser = LinkExtractor()
parser.feed(sys.stdin.read())

# Matches buildroot-YYYY.MM.tar.gz and buildroot-YYYY.MM.X.tar.gz (excludes -rc)
pattern = re.compile(r"^buildroot-\d{4}\.\d{2}(?:\.\d+)?\.tar\.gz$")
stable_releases = [l for l in parser.links if pattern.match(l)]

if stable_releases:
    stable_releases.sort()
    print(stable_releases[-1])
'
}

get_br_dl_url() {
    local url
    if [ -z "$VERSION" ]; then
        echo "Determining the latest stable buildroot release..." >&2
        url="$BUILDROOT_URL$buildroot_version"
    else
        echo "Using user-defined buildroot version..." >&2
        url="$BUILDROOT_URL$VERSION"
    fi
    printf "%s" "$url"
}

get_buildroot() {
    if curl -sI --fail "$buildroot_dl_url" > /dev/null 2>&1; then
        printf '%s\n%s%s\n' "--> Buildroot download URL is accessible." \
            "--> Downloading Buildroot from:" "$buildroot_dl_url..."
        wget -qO- "$buildroot_dl_url" | tar -xz --strip-components=1 -C "${BUILDROOT_BUILDER_DIR%/}"
        printf '%s\n' "--> Buildroot source distribution successfully extracted!"
    else
        printf '%s\n%s\n' "Error: buildroot is not downloaded and we could not download:" \
            "$buildroot_dl_url" >&2
        return 1
    fi
}

purge_target_directory() {
    [[ "$FORCE_FLAG" = "true" ]] \
        && printf '%s%s\n' "--> Force flag detected." \
        "Sanitizing target framework directory..."
    sudo find "${BUILDROOT_BUILDER_DIR%/}" -mindepth 1 -delete
}

run_customizer() {
    # Parent of the customizeBuildroot package must be on PYTHONPATH so
    # `python3 .../customizeBuildroot/main.py` can import customizeBuildroot.*.
    PYTHONPATH="${BUILDER_ROOT_DIR%/}${PYTHONPATH:+:$PYTHONPATH}" \
        python3 "$CUSTOMIZER" "$@"
}

customize_buildroot() {
    if [ ! -f "$CUSTOMIZER" ]; then
        printf '%s\n' "Error: customizeBuildroot/main.py not found at ${CUSTOMIZER}" >&2
        return 1
    fi
    if [ ! -f "${BUILDROOT_BUILDER_DIR%/}/Config.in" ]; then
        printf '%s\n' "Error: Buildroot is not extracted at ${BUILDROOT_BUILDER_DIR%/} (missing Config.in)." >&2
        return 1
    fi
    printf '%s\n' "--> Applying Buildroot customizations via ${CUSTOMIZER}..."
    run_customizer \
        --br-path "${BUILDROOT_BUILDER_DIR%/}" \
        --custom-package-dir "${BUILDER_ROOT_DIR%/}/buildrootConf/custom_package"
}

update_kernel_support() {
    if [ ! -f "$CUSTOMIZER" ]; then
        printf '%s\n' "Error: customizeBuildroot/main.py not found at ${CUSTOMIZER}" >&2
        return 1
    fi
    if [ ! -f "${BUILDROOT_BUILDER_DIR%/}/Config.in" ]; then
        printf '%s\n' "Error: Buildroot is not extracted at ${BUILDROOT_BUILDER_DIR%/} (missing Config.in)." >&2
        return 1
    fi
    printf '%s\n' "--> Updating kernel/header latest to 7.2.9 via ${CUSTOMIZER}..."
    run_customizer \
        --br-path "${BUILDROOT_BUILDER_DIR%/}" \
        --update-kernel-support
}

update_rust_version() {
    if [ ! -f "$CUSTOMIZER" ]; then
        printf '%s\n' "Error: customizeBuildroot/main.py not found at ${CUSTOMIZER}" >&2
        return 1
    fi
    if [ ! -f "${BUILDROOT_BUILDER_DIR%/}/Config.in" ]; then
        printf '%s\n' "Error: Buildroot is not extracted at ${BUILDROOT_BUILDER_DIR%/} (missing Config.in)." >&2
        return 1
    fi
    printf '%s\n' "--> Updating rust/rust-bin/rust-bindgen versions via ${CUSTOMIZER}..."
    run_customizer \
        --br-path "${BUILDROOT_BUILDER_DIR%/}" \
        --update-rust-version
}

if [ "$UPDATE_KERNEL_FLAG" = true ]; then
    if [ "$CUSTOMIZE_FLAG" = true ] || [ "$UPGRADE_FLAG" = true ] || [ "$FORCE_FLAG" = true ] \
        || [ "$UPDATE_RUST_FLAG" = true ]; then
        printf '%s\n' "Error: --update-kernel-support must be used by itself." >&2
        exit 1
    fi
    update_kernel_support
    exit 0
fi

if [ "$UPDATE_RUST_FLAG" = true ]; then
    if [ "$CUSTOMIZE_FLAG" = true ] || [ "$UPGRADE_FLAG" = true ] || [ "$FORCE_FLAG" = true ] \
        || [ "$UPDATE_KERNEL_FLAG" = true ]; then
        printf '%s\n' "Error: --update-rust-version must be used by itself." >&2
        exit 1
    fi
    update_rust_version
    exit 0
fi

# Ensure target directories exist without relying on Docker layers
mkdir -p "${BUILDROOT_BUILDER_DIR%/}"
mkdir -p "${BUILDROOT_OUTPUT_DIR%/}"
sudo chown -R builder:builder "${BUILDER_ROOT_DIR%/}"

buildroot_version="$(get_br_version "$BUILDROOT_URL")"
buildroot_dl_url="$(get_br_dl_url)"

if [ "$UPGRADE_FLAG" = true ]; then
    echo "--> User requested buildroot upgrade..."
    if [ -f "${BUILDROOT_BUILDER_DIR%/}/Makefile" ] && [ "$FORCE_FLAG" = false ]; then
        printf '%s\n%s\n' "--> Buildroot source found in cache." \
            "    To override this configuration, please re-run with: -U --force"
    elif [ "$FORCE_FLAG" = true ]; then
        purge_target_directory
        get_buildroot
    else
        # Upgrade requested but directory is empty, proceed with download
        get_buildroot
    fi
elif [ -f "${BUILDROOT_BUILDER_DIR%/}/Makefile" ]; then
    # Standard boot guard: skip download if active framework exists and no flags passed
    echo "--> Buildroot source folder is already active. Skipping download phase."
else
    # First-time automatic script deployment fallback: directory is uninitialized
    printf '%s\n%s\n' "--> Target folder uninitialized or incomplete." \
        "    Proceeding with Buildroot download..."
    purge_target_directory
    get_buildroot
fi

if [ "$CUSTOMIZE_FLAG" = true ]; then
    customize_buildroot
fi

exit 0
