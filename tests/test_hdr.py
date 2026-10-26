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


def _smooth_scene(height: int = 120, width: int = 160) -> np.ndarray:
    """Smooth gradient-plus-blobs scene ECC converges on (deterministic)."""
    yy, xx = np.mgrid[0:height, 0:width].astype(np.float32)
    scene = 0.4 * xx / width + 0.3 * yy / height
    for cx, cy, s, a in [(40, 40, 25, 0.5), (120, 80, 30, 0.4), (80, 30, 15, 0.35)]:
        scene += a * np.exp(-((xx - cx) ** 2 + (yy - cy) ** 2) / (2 * s * s))
    gray = (np.clip(scene, 0, 1) * 255).astype(np.uint8)
    return np.stack([gray] * 3, axis=-1)


def test_align_to_first_undoes_known_shift():
    # Two crops of one larger scene, offset by a known (dx, dy): the honest
    # model of tripod shift, with content in every pixel (no zero borders).
    scene = _smooth_scene(144, 184)
    base = scene[12:132, 12:172].copy()
    dx, dy = 7, -5
    shifted = scene[12 + dy : 132 + dy, 12 + dx : 172 + dx].copy()
    assert np.abs(shifted.astype(int) - base.astype(int)).mean() > 2.0, "shift must be visible"
    aligned = hdr.align_to_first([base, shifted])
    assert aligned[0] is base, "the reference frame is untouched"
    # Compare the interior only: realigning shifts content, so a border of
    # unwritten pixels is expected at the edges.
    margin = 12
    residual = np.abs(
        aligned[1][margin:-margin, margin:-margin].astype(int)
        - base[margin:-margin, margin:-margin].astype(int)
    ).mean()
    assert residual < 2.0, f"alignment must bring the frame back, residual {residual:.2f}"


def test_merge_set_accepts_jpeg_brackets(tmp_path):
    paths = []
    for i, shade in enumerate((60, 120, 200)):
        p = tmp_path / f"frame_{i}.jpg"
        Image.new("RGB", (64, 48), (shade, shade, shade)).save(p, format="JPEG")
        paths.append(p)
    out = hdr.merge_set(paths)
    assert out.shape == (48, 64, 3) and out.dtype == np.uint8


def test_fusion_sees_true_exposures_window_keeps_detail(tmp_path, monkeypatch):
    """Synthetic brackets through decode_raw and fusion.

    The scene has a dim interior and a bright window with a left-to-right
    gradient. The fake sensor clips above 1.0; its postprocess mimics
    rawpy: no_auto_bright=False lifts each frame toward mid gray (the old
    call), True keeps one global gain (true exposure). The fused window
    must keep the gradient, which only survives at true exposure.
    """
    h, w = 96, 128
    scene = np.full((h, w), 0.05, dtype=np.float32)
    scene[24:72, 80:120] = np.tile(np.linspace(0.7, 1.1, 40, dtype=np.float32), (48, 1))
    scene = np.clip(scene, 0, 1.0)
    frames = {"dark.nef": scene * 1.0, "bright.nef": np.clip(scene * 4.0, 0, 1.0)}

    class _FakeRaw:
        def __init__(self, linear):
            self.linear = linear

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def postprocess(self, **kwargs):
            if kwargs.get("no_auto_bright"):
                out = np.clip(self.linear, 0, 1)
            else:
                gain = 0.25 / max(float(self.linear.mean()), 1e-6)
                out = np.clip(self.linear * gain, 0, 1)
            rgb = np.stack([out] * 3, axis=-1)
            return (rgb * 255.0 + 0.5).astype(np.uint8)

    def _fake_imread(path):
        return _FakeRaw(frames[Path(path).name])

    from pathlib import Path

    monkeypatch.setattr(hdr.rawpy, "imread", _fake_imread)
    # Alignment is covered by its own test; here it would only add warp
    # noise to the gradient measurement.
    monkeypatch.setattr(hdr, "align_to_first", lambda images: list(images))
    dark = tmp_path / "dark.nef"
    bright = tmp_path / "bright.nef"
    dark.write_bytes(b"fake")
    bright.write_bytes(b"fake")
    out = hdr.merge_set([dark, bright])
    # Per-column brightness across the window band (rows, then channels).
    band = out[40:56, 82:118].astype(float).mean(axis=0).mean(axis=1)
    assert band[-1] - band[0] > 20.0, (
        "window gradient must survive fusion; auto-brightened frames clip it flat"
    )


def test_no_meta_imports_in_hdr():
    import inspect

    assert "meta_client" not in inspect.getsource(hdr), "merging stays local"
