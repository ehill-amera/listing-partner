"""Tests for the public-hygiene image scan. No network, no key."""

import importlib.util
import struct
from pathlib import Path

from PIL import Image
from PIL.Image import Exif


def _load_module():
    path = Path(__file__).resolve().parent.parent / "scripts" / "hygiene_images.py"
    spec = importlib.util.spec_from_file_location("hygiene_images", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _gps_exif_blob() -> bytes:
    """Minimal EXIF carrying a real GPS IFD (little-endian TIFF)."""
    tiff = b"II" + struct.pack("<H", 42) + struct.pack("<L", 8)
    ifd0 = struct.pack("<H", 1)
    ifd0 += struct.pack("<HHL", 0x8825, 4, 1) + struct.pack("<L", 26)
    ifd0 += struct.pack("<L", 0)
    gps = struct.pack("<H", 1)
    gps += struct.pack("<HHL", 0, 1, 4) + bytes((2, 3, 0, 0))
    gps += struct.pack("<L", 0)
    return b"Exif\x00\x00" + tiff + ifd0 + gps


def test_extensionless_image_with_gps_is_scanned(tmp_path):
    mod = _load_module()
    target = tmp_path / "noextension"
    Image.new("RGB", (16, 16), (1, 2, 3)).save(target, format="JPEG", exif=_gps_exif_blob())
    bad = mod.scan([str(target)])
    assert any("GPS" in line for line in bad), "files with no extension are scanned too"


def test_unreadable_image_fails_loudly(tmp_path):
    mod = _load_module()
    for suffix in (".jpg", ".png", ".tiff"):
        target = tmp_path / f"broken{suffix}"
        target.write_text("this is not image data")
        bad = mod.scan([str(target)])
        assert any("cannot be read" in line for line in bad), suffix


def test_unreadable_non_image_is_skipped(tmp_path):
    mod = _load_module()
    target = tmp_path / "notes.txt"
    target.write_text("this is not image data")
    assert mod.scan([str(target)]) == []


def test_camera_serial_is_flagged(tmp_path):
    mod = _load_module()
    target = tmp_path / "cam.jpg"
    exif = Exif()
    exif[42033] = "SN123"
    Image.new("RGB", (16, 16), (1, 2, 3)).save(target, format="JPEG", exif=exif)
    bad = mod.scan([str(target)])
    assert any("Serial" in line for line in bad)


def test_serial_only_in_exif_sub_ifd_is_flagged(tmp_path):
    # BodySerialNumber lives in the Exif sub-IFD, not the top level: a
    # top-level-only scan passes this file, the deep scan must flag it.
    mod = _load_module()
    target = tmp_path / "deep-serial.jpg"
    exif = Exif()
    exif[36867] = "2026:10:12 10:00:00"  # DateTimeOriginal, top level only
    sub = exif.get_ifd(0x8769)
    sub[0xA431] = "SN-DEEP-1"  # BodySerialNumber, Exif sub-IFD
    Image.new("RGB", (16, 16), (1, 2, 3)).save(target, format="JPEG", exif=exif)
    bad = mod.scan([str(target)])
    assert any("Serial" in line for line in bad), "deep serial must be flagged"


def test_clean_images_pass(tmp_path):
    mod = _load_module()
    files = []
    for name, fmt in (("clean.jpg", "JPEG"), ("clean.png", "PNG"), ("noext", "JPEG")):
        target = tmp_path / name
        Image.new("RGB", (16, 16), (1, 2, 3)).save(target, format=fmt)
        files.append(str(target))
    assert mod.scan(files) == []


def test_check_runs_the_image_scan_over_all_tracked_files():
    text = (Path(__file__).resolve().parent.parent / "scripts" / "check").read_text()
    assert "hygiene_images.py" in text, "the check must run the every-file image scan"
    assert "--include=" not in text, "secret greps must not skip file types"
