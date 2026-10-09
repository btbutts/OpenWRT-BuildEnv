#!/usr/bin/env python3
"""Install the built ter-*.psf console fonts gzipped and renamed to

    <Set>-Terminus[Bold|BoldVGA]<height>[x<width>].psf.gz

e.g. ter-v20n -> Uni-Terminus20x10, ter-h28n -> Hebrew-Terminus28x14.
The width is left out when it is 8, as console-setup does.

usage: install-psf.py <build dir> <font dir>
"""

import gzip
import os
import re
import sys

# Upstream's charset letter: set name used in the installed file name.
SETS = {
    "1": "Latin1",
    "2": "Latin2",
    "7": "Greek",
    "9": "Turkish",
    "c": "Cyrillic",
    "d": "Baltic",
    "g": "Latin10",
    "h": "Hebrew",
    "i": "CP437",
    "k": "KOI8R",
    "m": "MIK",
    "p": "PT154",
    "u": "KOI8U",
    "v": "Uni",
}
# Font height -> cell width.
WIDTHS = {12: 6, 14: 8, 16: 8, 18: 10, 20: 10, 22: 11, 24: 12, 28: 14, 32: 16}
# Upstream's style letter: n normal, b bold, v CRT VGA bold.
WEIGHTS = {"n": "", "b": "Bold", "v": "BoldVGA"}

NAME = re.compile(r"^ter-(.)(\d\d)(.)\.psf$")


def installed_name(built):
    """Return the installed file name for a built font such as ter-v20n.psf."""
    match = NAME.match(built)
    if not match:
        raise ValueError("not a Terminus font name: " + built)
    code, height, style = match.group(1), int(match.group(2)), match.group(3)
    if code not in SETS:
        raise ValueError("unknown charset '{0}' in {1}".format(code, built))
    if height not in WIDTHS:
        raise ValueError("unknown height '{0}' in {1}".format(height, built))
    if style not in WEIGHTS:
        raise ValueError("unknown style '{0}' in {1}".format(style, built))
    size = str(height)
    if WIDTHS[height] != 8:
        size += "x{0}".format(WIDTHS[height])
    return "{0}-Terminus{1}{2}.psf.gz".format(SETS[code], WEIGHTS[style], size)


def main(argv):
    if len(argv) != 3:
        sys.stderr.write(__doc__)
        return 2
    src, dst = argv[1], argv[2]
    built = sorted(f for f in os.listdir(src) if f.startswith("ter-") and f.endswith(".psf"))
    if not built:
        sys.stderr.write("install-psf.py: no ter-*.psf fonts in {0}\n".format(src))
        return 1
    try:
        names = [(f, installed_name(f)) for f in built]
    except ValueError as err:
        sys.stderr.write("install-psf.py: {0}\n".format(err))
        return 1

    os.makedirs(dst, exist_ok=True)
    for old, new in names:
        with open(os.path.join(src, old), "rb") as source:
            data = source.read()
        # No file name or mtime in the gzip header: same input, same bytes.
        with open(os.path.join(dst, new), "wb") as target:
            with gzip.GzipFile(filename="", mode="wb", compresslevel=9, fileobj=target, mtime=0) as gz:
                gz.write(data)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
