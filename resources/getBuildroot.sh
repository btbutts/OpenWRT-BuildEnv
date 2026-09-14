#!/bin/bash
set -e

TARGET_DIR="/builder/Buildroot-Builder"
VERSION="" # Define version override here
BUILDROOT_URL="https://buildroot.org/downloads/"

# Argument Parser
UPGRADE_FLAG=false
FORCE_FLAG=false
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
        wget -qO- "$buildroot_dl_url" | tar -xz --strip-components=1 -C "$TARGET_DIR"
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
    sudo find "${TARGET_DIR:?}" -mindepth 1 -delete
}

# Ensure target directories exist without relying on Docker layers
mkdir -p "$TARGET_DIR"
mkdir -p "/builder/workspace/output/buildroot"
sudo chown -R builder:builder /builder

buildroot_version="$(get_br_version "$BUILDROOT_URL")"
buildroot_dl_url="$(get_br_dl_url)"

if [ "$UPGRADE_FLAG" = true ]; then
    echo "--> User requested buildroot upgrade..."
    if [ -f "${TARGET_DIR}/Makefile" ] && [ "$FORCE_FLAG" = false ]; then
        printf '%s\n%s\n' "--> Buildroot source found in cache." \
            "    To override this configuration, please re-run with: -U --force"
        exit 0
    elif [ "$FORCE_FLAG" = true ]; then
        purge_target_directory
        get_buildroot
    else
        # Upgrade requested but directory is empty, proceed with download
        get_buildroot
    fi
elif [ -f "${TARGET_DIR}/Makefile" ]; then
    # Standard boot guard: skip download if active framework exists and no flags passed
    echo "--> Buildroot source folder is already active. Skipping download phase."
    exit 0
else
    # First-time automatic script deployment fallback: directory is uninitialized
    printf '%s\n%s\n' "--> Target folder uninitialized or incomplete." \
        "    Proceeding with Buildroot download..."
    purge_target_directory
    get_buildroot
fi

exit 0
