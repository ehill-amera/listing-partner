#!/usr/bin/env python3
"""Public-hygiene image scan over tracked files.

Usage: hygiene_images.py <file> [<file> ...] (usually `git ls-files`).
Exit 0 when every file is clean, 1 with a loud listing otherwise.

Every file given is attempted as an image, whatever its extension, so
extensionless files and uncommon types are scanned too. A file Pillow
cannot open is not an image and is skipped, unless its suffix says it is
one: an unreadable image fails loudly instead of passing silently.
Tracked images must carry no GPS block and no camera serial.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import ExifTags, Image

# Suffixes that promise image content. A file with one of these that Pillow
# cannot read is reported, never skipped. SVG is text (covered by the secret
# and banned-string greps), so it is deliberately absent here.
IMAGE_SUFFIXES = frozenset(
    {
        ".jpg",
        ".jpeg",
        ".png",
        ".tif",
        ".tiff",
        ".dng",
        ".gif",
        ".bmp",
        ".webp",
        ".heic",
        ".heif",
        ".avif",
        ".nef",
        ".cr2",
        ".cr3",
        ".arw",
        ".orf",
        ".rw2",
        ".raf",
    }
)

SERIAL_TAGS = ("BodySerialNumber", "CameraSerialNumber", "SerialNumber")


def scan(paths: list[str]) -> list[str]:
    """Return one loud line per file that fails. Empty means clean."""
    bad: list[str] = []
    for name in paths:
        path = Path(name)
        if not path.is_file():
            bad.append(f"{name}: missing, cannot scan")
            continue
        try:
            with Image.open(path) as img:
                exif = img.getexif()
        except Exception:
            if path.suffix.lower() in IMAGE_SUFFIXES:
                bad.append(f"{name}: looks like an image but cannot be read")
            continue
        names = {ExifTags.TAGS.get(k, k) for k in exif}
        if "GPSInfo" in names or 34853 in exif:
            bad.append(f"{name}: GPS block")
        for serial in SERIAL_TAGS:
            if serial in names:
                bad.append(f"{name}: {serial}")
    return bad


def main(argv: list[str]) -> int:
    bad = scan(argv[1:])
    if bad:
        print("\n".join(bad))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
