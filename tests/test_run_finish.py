"""Pipeline seam tests: build_inputs carries undistort validity to the crop."""

import glob
from pathlib import Path

import numpy as np

from listing_partner import geometry, hdr, run_finish


def _synthetic_frame(height=120, width=160):
    rows = np.linspace(40, 180, height, dtype=np.float64)[:, None]
    frame = np.repeat(rows, width, axis=1)
    frame[30:70, 60:110] = 220.0  # bright rectangle, a fake window
    return np.stack([frame, frame, frame], axis=-1).astype(np.uint8)


def test_build_inputs_keeps_undistort_invalid_out(monkeypatch):
    """Undistort-invalid borders must reach state['valid'] (and the crop).

    Only the pixel decode is stubbed (the far side); EXIF, the real lens
    profile, the real displacement math and the real combination run.
    Strength is fixed so the invalid-border path is deterministic.
    """
    members = [Path(p) for p in sorted(glob.glob("inputs/unit-a/raw/*.NEF"))[:5]]
    assert len(members) == 5
    fake = _synthetic_frame()
    monkeypatch.setattr(hdr, "decode_frame", lambda path: fake.copy())
    monkeypatch.setattr(geometry, "fit_strength", lambda gray, profile, focal: 0.5)

    record: dict = {"index": 1, "name": "001", "notes": []}
    state = run_finish.build_inputs(members, record)

    valid = state["valid"]
    assert valid.shape == fake.shape[:2]
    assert not valid.all(), "no invalid pixels: undistort validity was dropped"
    assert not valid[0, :].all(), "top border kept valid pixels it cannot have"
    assert not valid[-1, :].all(), "bottom border kept valid pixels it cannot have"
    assert not valid[:, 0].all(), "left border kept valid pixels it cannot have"
    assert not valid[:, -1].all(), "right border kept valid pixels it cannot have"
    assert record["distortion_strength"]


def _tail_state(n=100):
    balanced = np.full((n, n, 3), 150, np.uint8)
    balanced[20:80, 20:80] = 255  # the merge holds a blown window to replace
    blown = balanced.copy()
    clean = balanced.copy()
    view = np.tile(np.linspace(60, 200, 60, dtype=np.uint8), (60, 1))
    clean[20:80, 20:80] = view[:, :, None]
    union = np.zeros((n, n), bool)
    union[20:80, 20:80] = True
    members = [Path(f"frame{i}.NEF") for i in range(2)]
    return {
        "balanced": balanced,
        "aligned": [blown, clean],
        "members": members,
        "order": {p: i for i, p in enumerate(members)},
        "valid": np.ones((n, n), bool),
    }, union


def test_finish_tail_pulls_from_best_frame_not_darkest(tmp_path):
    from listing_partner import run_finish as rf

    state, union = _tail_state()
    dirs = {
        "finished": tmp_path / "finished",
        "review": tmp_path / "review",
        "masks": tmp_path / "masks",
    }
    for d in dirs.values():
        d.mkdir(parents=True)
    record = {
        "index": 1,
        "name": "001",
        "straight_before": 200.0,
        "straight_after": 210.0,
        "vertical_residual": 0.0,
    }
    rf.finish_tail(record, state, dirs, union)
    assert record["pull_frame"] == "frame1.NEF", (
        "the tail chooses the best-exposed frame, never assumes darkest"
    )
    assert record["clip_after"] == 0.0
    assert record["checks"]["highlights"][0] is True


def test_summarize_uses_median_noise_and_pooled_clip():
    from listing_partner import run_finish as rf

    records = [
        {
            "noise_before": 9.0,
            "noise_after": 4.0,
            "clip_before_n": 100,
            "clip_after_n": 10,
            "window_pixels": 1000,
        },
        {
            "noise_before": 3.0,
            "noise_after": 1.0,
            "clip_before_n": 0,
            "clip_after_n": 0,
            "window_pixels": 1000,
        },
        {
            "noise_before": 3.0,
            "noise_after": 2.0,
            "clip_before_n": 0,
            "clip_after_n": 0,
            "window_pixels": 0,
        },
    ]
    summary = rf._summarize(records, 12.0, 0.5)
    assert summary["noise_before"] == 3.0, "median, not mean"
    assert summary["noise_after"] == 2.0, "median, not mean"
    assert summary["clip_before_n"] == 100
    assert summary["window_pixels"] == 2000
    assert summary["clip_before_pct"] == 5.0, "pooled over window pixels"


def test_review_shows_merge_finished_outline_and_mls(tmp_path):
    from listing_partner import run_finish as rf

    manifest = {
        "summary": {
            "photos_finished": 1,
            "photos_failed": 0,
            "run_seconds": 3.0,
            "noise_before": 3.0,
            "noise_after": 1.5,
            "windows_found": 1,
            "windows_confirmed": 1,
            "windows_rejected": 0,
            "photos_with_windows": 1,
            "clip_before_n": 10,
            "clip_after_n": 1,
            "window_pixels": 1000,
            "clip_before_pct": 1.0,
            "clip_after_pct": 0.1,
            "unit_spend_usd": 0.0,
        },
        "sets": [
            {
                "index": 1,
                "name": "001",
                "frames_used": ["a.NEF"],
                "frames_reason": "full",
                "pull_frame": "a.NEF",
                "distortion_strength": {},
                "verticals": "level already",
                "vignetting": "skipped: x",
                "ghosting": 0.0,
                "clip_before": 0.01,
                "clip_after": 0.001,
                "window_pixels": 1000,
                "windows": [{"id": 0, "reason": "shows sky"}],
                "rejections": [{"id": 1, "reason": "a mirror"}],
                "checks": {
                    "highlights": (True, "clipped 0.0100 -> 0.0010 of window pixels"),
                    "verticals": (False, "not measured: no agreeing lines"),
                },
                "look": {"look_reason": "brightness 190 vs 192 (1.0%)"},
            }
        ],
    }
    page = rf.build_finish_review(tmp_path, manifest, {"m.jpg": {"set": 0}})
    html = page.read_text()
    for src in (
        "review/merged_001.jpg",
        "review/finished_001.jpg",
        "review/overlay_001.jpg",
        "review/mls_m.jpg",
    ):
        assert src in html, src
    assert "unit 1 merge" in html
    assert "window outline over the finished photo" in html
    assert "NOT MEASURED" in html
    assert "skipped: x" in html
