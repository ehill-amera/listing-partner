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
        "preshoulder": balanced.copy(),
        "aligned": [blown, clean],
        "members": members,
        "order": {p: i for i, p in enumerate(members)},
        "valid": np.ones((n, n), bool),
    }, union


def _tail_dirs(tmp_path):
    dirs = {
        "finished": tmp_path / "finished",
        "review": tmp_path / "review",
        "masks": tmp_path / "masks",
    }
    for d in dirs.values():
        d.mkdir(parents=True)
    return dirs


def test_finish_tail_pulls_from_best_frame_not_darkest(tmp_path):
    from listing_partner import run_finish as rf

    state, union = _tail_state()
    record = {
        "index": 1,
        "name": "001",
        "straight_before": 200.0,
        "straight_after": 210.0,
        "vertical_residual": 0.0,
        "windows": [{"id": 0, "reason": "shows sky"}],
    }
    rf.finish_tail(record, state, _tail_dirs(tmp_path), {0: union}, union)
    assert record["pull_frame"] == "frame1.NEF", (
        "the tail chooses the frame that fixes blown glass, never assumes darkest"
    )
    assert record["windows"][0]["pull"] == "pulled"
    # The flat room fails texture, so its halo keeps a thin merge ring at
    # the mask borders (the trim zone in production): most of the glass
    # fills, the border ring stays honestly white.
    assert 0.1 < record["clip_after"] < 0.25
    assert record["clip_after"] < 1.0
    assert record["checks"]["highlights"][0] is True


def test_finish_tail_with_no_mask_reports_not_measured(tmp_path):
    from listing_partner import checks, run_finish as rf

    state, _ = _tail_state()
    record = {
        "index": 2,
        "name": "002",
        "straight_before": 360.0,
        "straight_after": 360.0,
        "distortion_applied": False,
        "vertical_residual": None,
        "windows": [],
    }
    rf.finish_tail(record, state, _tail_dirs(tmp_path), {}, np.zeros((100, 100), bool))
    assert record["pull_frame"] is None
    for label in ("highlights", "outside", "straightness"):
        ok, reason = record["checks"][label]
        assert ok is False and "not measured" in reason, label
    assert record["checks"]["verticals"] == checks.check_verticals(record["vertical_final"]), (
        "verticals are measured on the finished file, whatever it reads"
    )


def test_finish_tail_keeps_a_failed_window_from_merge(tmp_path):
    import cv2
    from listing_partner import run_finish as rf

    state, union = _tail_state()
    state["aligned"] = [state["balanced"].copy()]  # only the merge itself: no view
    state["members"] = [Path("frame0.NEF")]
    record = {
        "index": 3,
        "name": "003",
        "straight_before": 360.0,
        "straight_after": 360.0,
        "distortion_applied": False,
        "vertical_residual": None,
        "windows": [{"id": 0, "reason": "shows sky"}],
    }
    rf.finish_tail(record, state, _tail_dirs(tmp_path), {0: union}, union)
    assert record["windows"][0]["pull"] == "kept from merge", (
        "a window no frame can fix keeps the merge, with the reason"
    )
    assert record["windows"][0]["pull_reason"]
    assert record["changed_outside"] == 0
    reread = cv2.imread(str(tmp_path / "finished" / "003.jpg"))
    reread = cv2.cvtColor(reread, cv2.COLOR_BGR2RGB)
    # The valid-pixel crop shaves one border pixel: reread[i] is
    # balanced[i + 1]. The window interior is flat white either way.
    kept = reread[25:75, 25:75].astype(int)
    assert (kept == 255).mean() > 0.99, "a kept window ships merge pixels, not a new view"
    ok, reason = record["checks"]["highlights"]
    assert ok is False and "kept from merge" in reason


def test_build_inputs_measures_straightness_on_the_same_frame(monkeypatch):
    """Lens straightness compares the middle frame raw vs corrected.

    Only the pixel decode is stubbed (the far side); EXIF, the real lens
    profile, the real displacement math and the real merge run. Strength
    is fixed so the corrected side is deterministic.
    """
    members = [Path(p) for p in sorted(glob.glob("inputs/unit-a/raw/*.NEF"))[:5]]
    assert len(members) == 5
    fake = _synthetic_frame()
    monkeypatch.setattr(hdr, "decode_frame", lambda path: fake.copy())
    monkeypatch.setattr(geometry, "fit_strength", lambda gray, profile, focal: 0.5)

    record: dict = {"index": 1, "name": "001", "notes": []}
    run_finish.build_inputs(members, record)

    assert record["straight_before"] == geometry.line_measure(fake)
    profile = geometry.load_profile()
    mid_focal = geometry.read_focal(members[len(members) // 2]) or 10.0
    expected_after, _ = geometry.correct_distortion(fake, profile, mid_focal, strength=0.5)
    assert record["straight_after"] == geometry.line_measure(expected_after)
    assert record["distortion_applied"] is True


def test_build_inputs_skips_lens_without_profile(monkeypatch):
    """A lens with no profile skips geometry and still finishes the photo.

    Contract A0: skip the step for that photo and say so on the page,
    instead of failing the whole photo. Only the profile match is
    stubbed (the far side); EXIF reads and everything downstream run.
    """
    members = [Path(p) for p in sorted(glob.glob("inputs/unit-a/raw/*.NEF"))[:5]]
    assert len(members) == 5
    fake = _synthetic_frame()
    monkeypatch.setattr(hdr, "decode_frame", lambda path: fake.copy())
    monkeypatch.setattr(geometry, "match_profile", lambda identity: None)

    record: dict = {"index": 1, "name": "001", "notes": []}
    state = run_finish.build_inputs(members, record)

    assert state["balanced"].shape == fake.shape
    assert record["distortion_applied"] is False
    assert record["straight_after"] is None
    assert "skip" in record["lens"].lower(), "the page must name the skipped step"
    assert "skip" in record["vignetting"].lower()


def test_build_inputs_names_uncorrected_frames_not_measured(monkeypatch):
    from listing_partner import checks

    members = [Path(p) for p in sorted(glob.glob("inputs/unit-a/raw/*.NEF"))[:5]]
    fake = _synthetic_frame()
    monkeypatch.setattr(hdr, "decode_frame", lambda path: fake.copy())
    monkeypatch.setattr(geometry, "fit_strength", lambda gray, profile, focal: 0.0)
    monkeypatch.setattr(geometry, "tca_params", lambda profile, focal: None)

    record: dict = {"index": 1, "name": "001", "notes": []}
    run_finish.build_inputs(members, record)

    assert record["distortion_applied"] is False
    assert record["straight_after"] is None
    ok, reason = checks.check_straightness(
        record["straight_before"], record["straight_after"], record["distortion_applied"]
    )
    assert ok is False and "not measured" in reason


def test_unit_spend_counts_actuals_and_open_reservations(tmp_path):
    import json

    from listing_partner import run_finish as rf

    ledger = tmp_path / "ledger.jsonl"
    ledger.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "ts": "2026-10-29T10:00:00+00:00",
                        "model": "muse-spark-1.3",
                        "estimated_usd": 1.0,
                        "actual_usd": None,
                        "request_id": None,
                        "call_id": "a",
                        "status": "reserved",
                    }
                ),
                json.dumps(
                    {
                        "ts": "2026-10-29T10:00:01+00:00",
                        "model": "muse-spark-1.3",
                        "estimated_usd": 1.0,
                        "actual_usd": 0.8,
                        "coverage_ratio": 1.25,
                        "request_id": "r-a",
                        "call_id": "a",
                        "status": "complete",
                    }
                ),
                json.dumps(
                    {
                        "ts": "2026-10-29T10:00:02+00:00",
                        "model": "muse-spark-1.3",
                        "estimated_usd": 0.3,
                        "actual_usd": None,
                        "request_id": None,
                        "call_id": "b",
                        "status": "reserved",
                    }
                ),
            ]
        )
        + "\n"
    )
    baseline, unit = rf._unit_spend_usd(None, ledger)
    assert baseline == rf.UNIT2_SPEND_BASELINE_USD
    assert unit == round(0.8 + 0.3 - baseline, 6)


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
            "windows_pulled": 0,
            "windows_kept_from_merge": 1,
            "clip_before_n": 10,
            "clip_after_n": 1,
            "window_pixels": 1000,
            "clip_before_pct": 1.0,
            "clip_after_pct": 0.1,
            "unit_spend_usd": 0.0,
            "worst_reserve_ratio": 2.0,
            "code_commit": "abc123",
        },
        "sets": [
            {
                "index": 1,
                "name": "001",
                "frames_used": ["a.NEF"],
                "frames_reason": "full",
                "pull_frame": "a.NEF",
                "distortion_strength": {},
                "lens": "Nikon AF-P DX 10-20mm (vendored lensfun profile)",
                "verticals": "level already",
                "vignetting": "skipped: x",
                "ghosting": 0.0,
                "clip_before": 0.01,
                "clip_after": 0.001,
                "window_pixels": 1000,
                "windows": [
                    {
                        "id": 0,
                        "reason": "shows sky",
                        "pull": "kept from merge",
                        "pull_reason": "rim darkened",
                    }
                ],
                "rejections": [{"id": 1, "reason": "a mirror"}],
                "checks": {
                    "highlights": (True, "clipped 0.0100 -> 0.0010 of window pixels"),
                    "verticals": (False, "not measured: no agreeing lines"),
                },
                "look": {"look_ok": True, "look_reason": "brightness 190 vs 192 (1.0%)"},
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
    assert "window mask over the merge" in html
    assert "NOT MEASURED" in html
    assert "skipped: x" in html
    assert "PASS look" in html, "every look row shows pass or fail"
    assert "window kept from merge" in html
    assert "rim darkened" in html
    assert "fitted on these same 16 photos" in html, (
        "the page must say plainly the shared look was fitted on these photos"
    )
    assert "abc123" in html, "the run's commit stamp shows on the page"


def test_review_marks_a_failed_look(tmp_path):
    from listing_partner import run_finish as rf

    manifest = {
        "summary": {
            "photos_finished": 1,
            "photos_failed": 0,
            "run_seconds": 1.0,
            "noise_before": 3.0,
            "noise_after": 1.5,
            "windows_found": 0,
            "windows_confirmed": 0,
            "windows_rejected": 0,
            "photos_with_windows": 0,
            "windows_pulled": 0,
            "windows_kept_from_merge": 0,
            "clip_before_n": 0,
            "clip_after_n": 0,
            "window_pixels": 0,
            "clip_before_pct": 0.0,
            "clip_after_pct": 0.0,
            "unit_spend_usd": 0.0,
        },
        "sets": [
            {
                "index": 13,
                "name": "013",
                "frames_used": ["a.NEF"],
                "frames_reason": "full",
                "pull_frame": None,
                "distortion_strength": {},
                "lens": "skipped: no lens profile matches",
                "verticals": "level already",
                "vignetting": "skipped: x",
                "ghosting": 0.0,
                "clip_before": 0.0,
                "clip_after": 0.0,
                "window_pixels": 0,
                "windows": [],
                "rejections": [],
                "checks": {},
                "look": {"look_ok": False, "look_reason": "b* gap 5.9 over 5"},
            }
        ],
    }
    html = rf.build_finish_review(tmp_path, manifest, {}).read_text()
    assert "FAIL look" in html, "a missed look row must show FAIL, never bare numbers"
    assert "skipped: no lens profile matches" in html


def test_review_names_zero_strength_photos_plainly(tmp_path):
    from listing_partner import run_finish as rf

    def entry(name, strengths):
        return {
            "index": 1,
            "name": name,
            "frames_used": ["a.NEF"],
            "frames_reason": "full",
            "pull_frame": "a.NEF",
            "distortion_strength": strengths,
            "verticals": "level already",
            "vignetting": "skipped: x",
            "ghosting": 0.0,
            "clip_before": 0.0,
            "clip_after": 0.0,
            "window_pixels": 0,
            "windows": [],
            "rejections": [],
            "checks": {},
            "look": None,
        }

    manifest = {
        "summary": {
            "photos_finished": 2,
            "photos_failed": 0,
            "run_seconds": 3.0,
            "noise_before": 3.0,
            "noise_after": 1.5,
            "windows_found": 0,
            "windows_confirmed": 0,
            "windows_rejected": 0,
            "photos_with_windows": 0,
            "clip_before_n": 0,
            "clip_after_n": 0,
            "window_pixels": 0,
            "clip_before_pct": 0.0,
            "clip_after_pct": 0.0,
            "unit_spend_usd": 0.0,
        },
        "sets": [entry("001", {"10.0": 0.0}), entry("002", {"10.0": 0.25})],
    }
    html = rf.build_finish_review(tmp_path, manifest, {}).read_text()
    assert "line sweep on a center crop did not improve" in html, (
        "strength-0 photos like 001/009/012 must say the sweep voted the step down"
    )
    corrected = html.split("Shot 002")[1]
    assert "line sweep on a center crop did not improve" not in corrected, (
        "photos with real correction must not carry the zero-strength note"
    )
