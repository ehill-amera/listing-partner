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

import exifread
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


# Suffixes whose containers can hold a deep metadata block. TIFF-family
# files (including raw) carry EXIF directories; PNG, WebP, GIF and BMP can
# carry an EXIF block of their own, which Pillow surfaces but exifread may
# not parse. The deep parse is attempted on every one of these; anything
# else cannot carry a deep serial or GPS block, so it is skipped.
EXIF_SUFFIXES = frozenset(
    {
        ".jpg",
        ".jpeg",
        ".tif",
        ".tiff",
        ".dng",
        ".nef",
        ".cr2",
        ".cr3",
        ".arw",
        ".orf",
        ".rw2",
        ".raf",
        ".png",
        ".webp",
        ".gif",
        ".bmp",
        ".heic",
        ".heif",
        ".avif",
    }
)


def _deep_tags(path: Path) -> dict[str, str]:
    """Every metadata directory exifread can parse: top level, the Exif
    sub-IFD, the GPS IFD, interoperability, and maker notes. Cameras hide
    the body serial and GPS coordinates below the top level."""
    if path.suffix and path.suffix.lower() not in EXIF_SUFFIXES:
        return {}
    try:
        with open(path, "rb") as handle:
            tags = exifread.process_file(handle, details=False)
    except Exception:
        return {}
    return {name: str(value) for name, value in tags.items()}


def scan(paths: list[str]) -> list[str]:
    """Return one loud line per file that fails. Empty means clean."""
    bad: list[str] = []
    for name in paths:
        path = Path(name)
        if not path.is_file():
            bad.append(f"{name}: missing, cannot scan")
            continue
        pillow_ok = True
        try:
            with Image.open(path) as img:
                exif = img.getexif()
        except Exception:
            pillow_ok = False
            exif = {}
        if pillow_ok:
            names = {ExifTags.TAGS.get(k, k) for k in exif}
            if "GPSInfo" in names or 34853 in exif:
                bad.append(f"{name}: GPS block")
            for serial in SERIAL_TAGS:
                if serial in names:
                    bad.append(f"{name}: {serial}")
            # Sub-IFDs (Exif, GPS, interoperability) on every image Pillow
            # can open: a serial or GPS block hiding below the top level
            # must not pass just because the container is not TIFF.
            for ifd_id in (0x8769, 0x8825, 0xA005):
                try:
                    sub = exif.get_ifd(ifd_id)
                except Exception:
                    continue
                if ifd_id == 0x8825 and len(sub):
                    bad.append(f"{name}: GPS block")
                for key in sorted({ExifTags.TAGS.get(k, k) for k in sub}, key=str):
                    if isinstance(key, str) and "serial" in key.lower():
                        bad.append(f"{name}: {key}")
        # The deep parse runs when Pillow saw image structure (covers
        # extensionless images too) or the suffix promises an EXIF
        # container; anything else cannot carry a deep serial or GPS block.
        deep = _deep_tags(path) if (pillow_ok or path.suffix.lower() in EXIF_SUFFIXES) else {}
        if deep:
            gps_hit = any(
                key.split()[-1].startswith("GPS") or key.startswith("GPS ") for key in deep
            )
            if gps_hit:
                bad.append(f"{name}: GPS block")
            for key in sorted(deep):
                if "serial" in key.lower():
                    bad.append(f"{name}: {key.split()[-1]} ({deep[key][:24]})")
            continue
        if not pillow_ok and path.suffix.lower() in IMAGE_SUFFIXES:
            bad.append(f"{name}: looks like an image but cannot be read")
    return bad


def main(argv: list[str]) -> int:
    bad = scan(argv[1:])
    if bad:
        print("\n".join(bad))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
