"""Tests for the run command and review page. No raw files, no network, no key."""

from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
from PIL import Image

from listing_partner import hdr
from listing_partner.run_merge import build_review, match_mls, render_lightroom, run_merge


def _stamp(path: Path, when: datetime, exposure=(1, 100)):
    from PIL.Image import Exif
    from PIL.TiffImagePlugin import IFDRational

    img = Image.new("RGB", (64, 48), (40, 80, 120))
    exif = Exif()
    exif[36867] = when.strftime("%Y:%m:%d %H:%M:%S")
    exif[33434] = IFDRational(*exposure)
    img.save(path, format="JPEG", exif=exif)


def _manifest(n_sets=1):
    return {
        "summary": {
            "frames_found": 3,
            "sets_found": n_sets,
            "sets_merged": n_sets,
            "sets_failed": 0,
            "sets_flagged": 0,
            "merge_run_seconds": 1.0,
        },
        "sets": [
            {
                "index": i + 1,
                "flagged": False,
                "error": None,
                "darkest": "a.nef",
                "brightest": "b.nef",
            }
            for i in range(n_sets)
        ],
    }


def test_footer_shows_unknown_when_ledger_unreadable(tmp_path):
    page = build_review(tmp_path, _manifest(), {}, {"001": "full render"}, None)
    html = page.read_text()
    assert "Meta spend unknown, ledger unreadable" in html
    assert "$0.0000" not in html, "an unreadable ledger must never read as $0"


def test_footer_shows_measured_spend(tmp_path):
    page = build_review(tmp_path, _manifest(), {}, {"001": "full render"}, 0.0008)
    assert "$0.0008" in page.read_text()


def test_run_merge_discovers_jpeg_brackets(tmp_path):
    raw = tmp_path / "raw"
    raw.mkdir()
    base = datetime(2026, 10, 12, 10, 0, 0)
    for i in range(3):
        _stamp(raw / f"frame_{i}.jpg", base + timedelta(seconds=i))
    lightroom = tmp_path / "lightroom"
    lightroom.mkdir()
    mls = tmp_path / "mls"
    mls.mkdir()
    manifest = run_merge(raw, lightroom, mls, tmp_path / "out")
    assert manifest["summary"]["frames_found"] == 3
    assert manifest["summary"]["sets_found"] == 1
    assert manifest["summary"]["sets_merged"] == 1
    assert (tmp_path / "out" / "merged" / "001.jpg").exists()


def test_look_match_keeps_set_numbers_when_a_set_failed(tmp_path):
    # Three sets; set 2 failed so only 001.jpg and 003.jpg merged. A timeless
    # photo that looks like set 3 must match set index 2, not slide to 1.
    base = datetime(2026, 10, 12, 10, 0, 0)
    sets = []
    for s in range(3):
        frame = tmp_path / f"s{s}.jpg"
        _stamp(frame, base + timedelta(seconds=s * 60))
        sets.append([frame])
    merged = tmp_path / "merged"
    merged.mkdir()
    rng = np.random.default_rng(3)
    plain = np.tile(np.linspace(0, 255, 64, dtype=np.uint8), (64, 1))
    blobs = (rng.random((64, 64)) * 255).astype(np.uint8)
    Image.fromarray(np.stack([plain] * 3, -1)).save(merged / "001.jpg")
    Image.fromarray(np.stack([blobs] * 3, -1)).save(merged / "003.jpg")
    mls = tmp_path / "mls"
    mls.mkdir()
    near = np.clip(blobs.astype(int) + 4, 0, 255).astype(np.uint8)
    Image.fromarray(np.stack([near] * 3, -1)).save(mls / "timeless.jpg")
    matches = match_mls(sets, mls, merged)
    assert matches["timeless.jpg"]["set"] == 2
    assert matches["timeless.jpg"]["how"] == "matched by look"


def test_review_shows_every_mls_photo_on_a_shared_set(tmp_path):
    matches = {
        "a.jpg": {"set": 0, "how": "capture time"},
        "b.jpg": {"set": 0, "how": "matched by look"},
    }
    page = build_review(tmp_path, _manifest(), matches, {"001": "full render"}, 0.0)
    html = page.read_text()
    assert "mls_a.jpg" in html and "mls_b.jpg" in html, "a second match is shown, never dropped"


def test_lightroom_fallback_uses_largest_preview_label(tmp_path, monkeypatch):
    dng = tmp_path / "fake.dng"
    dng.write_text("not a dng at all")
    monkeypatch.setattr(
        hdr, "render_linear_dng", lambda p: (_ for _ in ()).throw(ValueError("no decode"))
    )
    preview = (np.zeros((8, 8, 3), dtype=np.uint8) + 9).copy()
    monkeypatch.setattr(hdr, "extract_preview", lambda p: preview)
    label = render_lightroom(dng, tmp_path / "out.jpg")
    assert label == "preview only"
    assert (tmp_path / "out.jpg").exists()


def test_lightroom_total_failure_never_crashes_run(tmp_path, monkeypatch):
    dng = tmp_path / "fake.dng"
    dng.write_text("not a dng at all")
    monkeypatch.setattr(
        hdr, "render_linear_dng", lambda p: (_ for _ in ()).throw(ValueError("no decode"))
    )
    monkeypatch.setattr(
        hdr, "extract_preview", lambda p: (_ for _ in ()).throw(ValueError("no preview"))
    )
    label = render_lightroom(dng, tmp_path / "out.jpg")
    assert label == "preview unavailable"
    assert (tmp_path / "out.jpg").exists(), "the page still gets a placeholder image"
