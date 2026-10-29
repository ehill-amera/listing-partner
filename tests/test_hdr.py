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


def test_long_brackets_group_by_end_of_exposure(tmp_path, monkeypatch):
    # Nine frames whose starts are 10 seconds apart at the seam (old code
    # splits into 8 plus 1) but whose long brightest frames (2, 4, 8s) span
    # it: the 4s frame ending at t=11 means the t=17 frame starts only 6s
    # after the previous frame's end, so all nine belong to one set.
    base = datetime(2026, 10, 12, 10, 0, 0)
    starts = [0, 1, 2, 3, 4, 5, 6, 7, 17]
    exposures = [1 / 100] * 6 + [2.0, 4.0, 8.0]
    paths = []
    for i, offset in enumerate(starts):
        p = tmp_path / f"long_{i}.jpg"
        _stamp_jpeg(p, base + timedelta(seconds=offset))
        paths.append(p)
    by_name = {str(p): e for p, e in zip(paths, exposures)}
    monkeypatch.setattr(hdr, "read_exposure_seconds", lambda p: by_name[str(p)])
    sets = hdr.group_frames(paths)
    assert [len(s) for s in sets] == [9], "end-of-exposure gaps stay within 8s"


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


def _stub_merges(monkeypatch, **by_key):
    """Canned fused arrays per option key; the selection logic is the claim,
    the fusion itself is OpenCV's and already covered elsewhere."""
    monkeypatch.setattr(hdr, "merge_set", lambda subset: by_key[_subset_key(subset)])


def _subset_key(subset):
    return getattr(_subset_key, "map")[tuple(p.name for p in subset)]


def _flat(value, white_pixels=0, size=(64, 48)):
    img = np.full((*size[::-1], 3), value, np.uint8)
    img[:white_pixels, :1] = 255
    return img


def test_choose_frames_prefers_fewest_highlights(tmp_path, monkeypatch):
    paths = [tmp_path / f"f{i}.jpg" for i in range(3)]
    for p in paths:
        Image.new("RGB", (64, 48), (100, 100, 100)).save(p, format="JPEG")
    exposures = {str(paths[0]): 1 / 100, str(paths[1]): 1 / 50, str(paths[2]): 1 / 10}
    monkeypatch.setattr(hdr, "read_exposure_seconds", lambda p: exposures[str(p)])
    _subset_key.map = {
        tuple(p.name for p in paths): "full",
        (paths[0].name, paths[1].name): "drop_brightest",
        (paths[1].name, paths[2].name): "drop_darkest",
        (paths[1].name,): "drop_both",
    }
    _stub_merges(
        monkeypatch,
        full=_flat(100, white_pixels=20),
        drop_darkest=_flat(100, white_pixels=10),
        drop_brightest=_flat(100, white_pixels=2),
        drop_both=_flat(100, white_pixels=12),
    )
    best, key, reason = hdr.choose_frames(paths)
    assert key == "drop_brightest", reason
    assert best == [paths[0], paths[1]]
    assert "highlight" in reason and paths[2].name in reason


def test_choose_frames_breaks_clip_ties_by_mls_gap(tmp_path, monkeypatch):
    paths = [tmp_path / f"m{i}.jpg" for i in range(3)]
    for p in paths:
        Image.new("RGB", (64, 48), (100, 100, 100)).save(p, format="JPEG")
    exposures = {str(paths[0]): 1 / 100, str(paths[1]): 1 / 50, str(paths[2]): 1 / 10}
    monkeypatch.setattr(hdr, "read_exposure_seconds", lambda p: exposures[str(p)])
    _subset_key.map = {
        tuple(p.name for p in paths): "full",
        (paths[0].name, paths[1].name): "drop_brightest",
        (paths[1].name, paths[2].name): "drop_darkest",
        (paths[1].name,): "drop_both",
    }
    _stub_merges(
        monkeypatch,
        full=_flat(100),
        drop_darkest=_flat(140),
        drop_brightest=_flat(60),
        drop_both=_flat(100),
    )
    best, key, reason = hdr.choose_frames(paths, mls_median=140.0)
    assert key == "drop_darkest", reason


def test_choose_frames_breaks_late_ties_by_noise(tmp_path, monkeypatch):
    paths = [tmp_path / f"n{i}.jpg" for i in range(3)]
    for p in paths:
        Image.new("RGB", (64, 48), (100, 100, 100)).save(p, format="JPEG")
    exposures = {str(paths[0]): 1 / 100, str(paths[1]): 1 / 50, str(paths[2]): 1 / 10}
    monkeypatch.setattr(hdr, "read_exposure_seconds", lambda p: exposures[str(p)])
    _subset_key.map = {
        tuple(p.name for p in paths): "full",
        (paths[0].name, paths[1].name): "drop_brightest",
        (paths[1].name, paths[2].name): "drop_darkest",
        (paths[1].name,): "drop_both",
    }
    rng = np.random.default_rng(7)
    _stub_merges(
        monkeypatch,
        full=_flat(100),
        drop_darkest=_flat(100) + rng.integers(0, 30, (48, 64, 3)).astype(np.uint8),
        drop_brightest=_flat(100),
        drop_both=_flat(100) + rng.integers(0, 30, (48, 64, 3)).astype(np.uint8),
    )
    best, key, reason = hdr.choose_frames(paths)
    assert key in ("full", "drop_brightest"), reason
    assert "noise" in reason or key == "full"


def test_choose_frames_runs_on_real_merges(tmp_path, monkeypatch):
    paths = [tmp_path / f"r{i}.jpg" for i in range(3)]
    for p, v in zip(paths, (40, 110, 190)):
        Image.new("RGB", (64, 48), (v, v, v)).save(p, format="JPEG")
    exposures = {str(paths[0]): 1 / 100, str(paths[1]): 1 / 50, str(paths[2]): 1 / 10}
    monkeypatch.setattr(hdr, "read_exposure_seconds", lambda p: exposures[str(p)])
    best, key, reason = hdr.choose_frames(paths)
    assert key in ("full", "drop_darkest", "drop_brightest", "drop_both")
    assert reason and set(best) <= set(paths)


def test_choose_frames_names_darkest_for_windows(tmp_path, monkeypatch):
    paths = [tmp_path / f"w{i}.jpg" for i in range(3)]
    for p, v in zip(paths, (30, 120, 255)):
        Image.new("RGB", (64, 48), (v, v, v)).save(p, format="JPEG")
    exposures = {str(paths[0]): 1 / 100, str(paths[1]): 1 / 50, str(paths[2]): 1 / 10}
    monkeypatch.setattr(hdr, "read_exposure_seconds", lambda p: exposures[str(p)])
    best, key, reason = hdr.choose_frames(paths)
    assert hdr.darkest_for_windows(paths) == paths[0], (
        "the window pull uses the darkest frame even when it leaves the merge"
    )


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


def test_extract_preview_returns_largest_embedded(tmp_path):
    """A file holding a small thumbnail and a large preview must yield large.

    Regression: the review page showed the 256-pixel thumbnail while every
    unit-a DNG also holds a 1024-pixel preview.
    """
    import tifffile

    small = np.zeros((34, 51, 3), dtype=np.uint8) + 10
    large = np.zeros((136, 205, 3), dtype=np.uint8) + 200
    p = tmp_path / "two-previews.tiff"
    with tifffile.TiffWriter(p) as writer:
        writer.write(small, photometric="rgb")
        writer.write(large, photometric="rgb")
    out = hdr.extract_preview(p)
    assert out.shape == (136, 205, 3), f"must pick the largest preview, got {out.shape}"
    assert float(out.mean()) > 100.0, "must be the bright large preview, not the dark thumb"


def _xmp_only_jpeg(path, create_date: str):
    """JPEG with an XMP CreateDate and no EXIF, shaped like MLS 007.jpg."""
    Image.new("RGB", (32, 32), (1, 2, 3)).save(path, format="JPEG")
    raw = path.read_bytes()
    assert raw[:2] == b"\xff\xd8"
    packet = (
        '<x:xmpmeta xmlns:x="adobe:ns:meta/">'
        '<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">'
        f'<rdf:Description xmlns:xmp="http://ns.adobe.com/xap/1.0/" xmp:CreateDate="{create_date}">'
        "</rdf:Description></rdf:RDF></x:xmpmeta>"
    ).encode("utf-8")
    segment = b"http://ns.adobe.com/xap/1.0/\x00" + packet
    app1 = b"\xff\xe1" + (len(segment) + 2).to_bytes(2, "big") + segment
    path.write_bytes(raw[:2] + app1 + raw[2:])


def test_read_capture_time_reads_xmp_block(tmp_path):
    """MLS 007.jpg carries its capture time only in XMP: exifread misses it."""
    p = tmp_path / "007.jpg"
    _xmp_only_jpeg(p, "2026-10-12T13:49:17.101")
    assert hdr.read_capture_time(p) == datetime(2026, 10, 12, 13, 49, 17)


def test_read_capture_time_prefers_exif_over_xmp(tmp_path):
    """When both blocks exist, EXIF DateTimeOriginal still wins."""
    from PIL.Image import Exif

    p = tmp_path / "both.jpg"
    img = Image.new("RGB", (32, 32), (1, 2, 3))
    exif = Exif()
    exif[36867] = "2026:10:12 14:03:05"  # DateTimeOriginal
    img.save(p, format="JPEG", exif=exif)
    raw = p.read_bytes()
    packet = (
        '<x:xmpmeta xmlns:x="adobe:ns:meta/">'
        '<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">'
        '<rdf:Description xmlns:xmp="http://ns.adobe.com/xap/1.0/"'
        ' xmp:CreateDate="2020-01-01T00:00:00">'
        "</rdf:Description></rdf:RDF></x:xmpmeta>"
    ).encode("utf-8")
    segment = b"http://ns.adobe.com/xap/1.0/\x00" + packet
    app1 = b"\xff\xe1" + (len(segment) + 2).to_bytes(2, "big") + segment
    p.write_bytes(raw[:2] + app1 + raw[2:])
    assert hdr.read_capture_time(p) == datetime(2026, 10, 12, 14, 3, 5)


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


def test_linear_dng_render_applies_color_matrix(tmp_path):
    """A known camera-red patch must render blue, not red.

    The synthetic DNG's color matrix maps camera red to sRGB blue (the way
    a real Nikon matrix remaps its native primaries). Rendering the raw
    channel values as sRGB — the old code — shows red; the matrix path
    shows blue.
    """
    import tifffile

    srgb_to_xyz = np.array(
        [
            [0.4124564, 0.3575761, 0.1804375],
            [0.2126729, 0.7151522, 0.0721750],
            [0.0193339, 0.1191920, 0.9503041],
        ]
    )
    swap_rb = np.array([[0, 0, 1], [0, 1, 0], [1, 0, 0]])
    matrix = (srgb_to_xyz @ swap_rb).ravel()

    def _rat(value):
        from fractions import Fraction

        frac = Fraction(value).limit_denominator(1000000)
        return (frac.numerator, frac.denominator)

    img = np.zeros((16, 16, 3), dtype=np.float16)
    img[:, :] = (1.0, 0.0, 0.0)
    dng = tmp_path / "patch.dng"
    tifffile.imwrite(
        dng,
        img,
        photometric="rgb",
        extratags=[
            (50728, 5, 3, tuple(_rat(1.0) for _ in range(3))),  # AsShotNeutral
            (50722, 10, 9, tuple(_rat(float(v)) for v in matrix)),  # ColorMatrix2
            (50779, 3, 1, (21,)),  # CalibrationIlluminant2 is D65
        ],
    )
    out = hdr.render_linear_dng(dng)
    mean = out.reshape(-1, 3).astype(float).mean(axis=0)
    assert mean[2] > 170.0, f"blue channel must dominate, got {mean}"
    assert mean[0] < 80.0 and mean[1] < 80.0, f"red/green must stay low, got {mean}"


def test_no_meta_imports_in_hdr():
    import inspect

    assert "meta_client" not in inspect.getsource(hdr), "merging stays local"
