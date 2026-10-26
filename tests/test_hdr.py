"""Tests for HDR grouping, fusion, and clean output. No raw files needed."""

from datetime import datetime, timedelta

import numpy as np
import pytest
from PIL import Image

from listing_partner import hdr


def _stamp_jpeg(path, when: datetime):
    img = Image.new("RGB", (32, 32), (10, 20, 30))
    exif = Image.Exif()
    exif[36867] = when.strftime("%Y:%m:%d %H:%M:%S")  # DateTimeOriginal
    img.save(path, format="JPEG", exif=exif)


def test_grouping_splits_on_eight_second_gaps(tmp_path):
    base = datetime(2026, 10, 12, 10, 0, 0)
    stamps = [0, 1, 2, 3, 4, 60, 61, 62, 63, 64, 200, 201, 202]
    paths = []
    for i, offset in enumerate(stamps):
        p = tmp_path / f"frame_{i:03d}.jpg"
        _stamp_jpeg(p, base + timedelta(seconds=offset))
        paths.append(p)
    sets = hdr.group_frames(paths)
    assert [len(s) for s in sets] == [5, 5, 3]
    flat = [p for s in sets for p in s]
    assert sorted(flat) == sorted(paths), "every frame in exactly one set"


def test_gap_boundary_stays_in_set(tmp_path):
    base = datetime(2026, 10, 12, 10, 0, 0)
    paths = []
    for i, offset in enumerate([0, 8]):
        p = tmp_path / f"b_{i}.jpg"
        _stamp_jpeg(p, base + timedelta(seconds=offset))
        paths.append(p)
    assert len(hdr.group_frames(paths)) == 1, "exactly 8s is not more than 8s"
    p2 = tmp_path / "b_2.jpg"
    _stamp_jpeg(p2, base + timedelta(seconds=17, microseconds=1))
    assert len(hdr.group_frames(paths + [p2])) == 2


def test_most_common_size_and_flag():
    sets = [[1] * 5] * 16 + [[1] * 6]
    assert hdr.most_common_size(sets) == 5
    flagged = [i for i, s in enumerate(sets) if len(s) != 5]
    assert flagged == [16]


def test_fuse_exposures_keeps_shape_and_range():
    base = np.tile(np.linspace(0, 255, 64, dtype=np.uint8), (48, 1))
    dark = np.clip(base * 0.25, 0, 255).astype(np.uint8)
    mid = base.copy()
    bright = np.clip(base * 2.0 + 40, 0, 255).astype(np.uint8)
    frames = [np.stack([c] * 3, axis=-1) for c in (dark, mid, bright)]
    out = hdr.fuse_exposures(frames)
    assert out.shape == (48, 64, 3)
    assert out.dtype == np.uint8
    assert out.min() > 0 and out.max() < 255, "fusion should compress extremes"
    assert out[:, -1].mean() > out[:, 0].mean(), "bright stays bright"


def test_save_clean_jpeg_strips_metadata(tmp_path):
    src = tmp_path / "dirty.jpg"
    img = Image.new("RGB", (16, 16), (1, 2, 3))
    exif = Image.Exif()
    exif[36867] = "2026:10:12 10:00:00"
    img.save(src, format="JPEG", exif=exif)
    assert len(Image.open(src).getexif()) > 0
    clean = tmp_path / "clean.jpg"
    hdr.save_clean_jpeg(np.asarray(img), clean)
    reopened = Image.open(clean)
    assert len(reopened.getexif()) == 0, "no EXIF at all: no GPS, no serial"
    assert reopened.size == (16, 16)


def test_read_exposure_seconds_parses_fraction(tmp_path):
    from PIL.Image import Exif
    from PIL.TiffImagePlugin import IFDRational

    p = tmp_path / "exp.jpg"
    img = Image.new("RGB", (8, 8), (1, 2, 3))
    exif = Exif()
    exif[33434] = IFDRational(1, 500)  # ExposureTime
    exif[36867] = "2026:10:12 10:00:00"
    img.save(p, format="JPEG", exif=exif)
    assert hdr.read_exposure_seconds(p) == pytest.approx(1 / 500)


def test_darkest_brightest_orders_by_exposure(tmp_path, monkeypatch):
    exposures = {"/a.nef": 1 / 200, "/b.nef": 1 / 50, "/c.nef": 1 / 13}
    monkeypatch.setattr(hdr, "read_exposure_seconds", lambda p: exposures[str(p)])
    from pathlib import Path

    dark, bright = hdr.darkest_and_brightest([Path("/c.nef"), Path("/a.nef"), Path("/b.nef")])
    assert dark.name == "a.nef" and bright.name == "c.nef"


def test_no_meta_imports_in_hdr():
    import inspect

    assert "meta_client" not in inspect.getsource(hdr), "merging stays local"
