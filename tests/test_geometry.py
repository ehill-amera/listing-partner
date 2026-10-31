"""Tests for lens/geometry correction. No raw files, no network."""

import cv2
import numpy as np
import pytest

from listing_partner import geometry


def _grid(size=400, step=40):
    img = np.zeros((size, size), np.uint8)
    for x in range(0, size, step):
        img[:, x : x + 2] = 255
    for y in range(0, size, step):
        img[y : y + 2, :] = 255
    return img


def test_ptlens_forward_model_fixes_corners():
    a, b, c = 0.01265, -0.08749, 0.1144  # vendored 10mm row
    assert geometry.ptlens_forward(1.0, a, b, c) == pytest.approx(1.0)
    assert geometry.ptlens_forward(0.0, a, b, c) == pytest.approx(0.0)
    # Barrel: mid-radius distorted points sit closer to the center.
    assert geometry.ptlens_forward(0.5, a, b, c) < 0.5


def _big_grid(size=1200, step=120, width=6):
    img = np.zeros((size, size), np.uint8)
    for x in range(0, size, step):
        img[:, x : x + width] = 255
    for y in range(0, size, step):
        img[y : y + width, :] = 255
    return img


def test_undistort_straightens_synthetic_barrel_grid():
    clean = _big_grid()
    a, b, c = 0.01265, -0.08749, 0.1144
    distorted = geometry.apply_forward_distortion(clean, a, b, c)
    bent = geometry.line_residual(distorted)
    assert bent > geometry.line_residual(clean), "the warp must bend lines first"
    fixed = geometry.undistort_image(distorted, a, b, c)
    assert geometry.line_residual(fixed) < bent, "undistort must lower the residual"


def _real_merge_gray(name="001"):
    import cv2

    img = cv2.imread(f"output/unit-a/merged/{name}.jpg")
    assert img is not None, "unit 1's merged photo must exist"
    return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)


def test_fit_strength_votes_a_grid_value_on_real_photo():
    profile = geometry.load_profile()
    gray = _real_merge_gray()
    strength = geometry.fit_strength(gray, profile, 10.0)
    assert strength in geometry.STRENGTH_GRID
    assert strength > 0.0, "unit-a's 10mm shots carry real barrel to remove"


def test_correct_distortion_improves_real_photo():
    import cv2

    profile = geometry.load_profile()
    gray = _real_merge_gray()
    before = geometry.top_line_length(gray)
    fixed, strength = geometry.correct_distortion(
        cv2.cvtColor(gray, cv2.COLOR_GRAY2RGB), profile, 10.0
    )
    assert strength > 0.0
    assert geometry.top_line_length(cv2.cvtColor(fixed, cv2.COLOR_RGB2GRAY)) >= before, (
        "fitted correction must not worsen the photo"
    )


def test_distortion_params_interpolate_between_calibrated_focals():
    profile = geometry.load_profile()
    at10 = geometry.distortion_params(profile, 10.0)
    at12 = geometry.distortion_params(profile, 12.0)
    at11 = geometry.distortion_params(profile, 11.0)
    assert at10 == pytest.approx((0.01265, -0.08749, 0.1144))
    for got, lo, hi in zip(at11, at10, at12):
        assert min(lo, hi) - 1e-9 <= got <= max(lo, hi) + 1e-9


def test_vignetting_lookup_reports_missing_data():
    profile = geometry.load_profile()
    assert geometry.vignetting_params(profile, 10.0) is None, (
        "the vendored profile carries no vignetting model, so the step "
        "must skip with a stated reason instead of pretending"
    )


def test_unknown_lens_has_no_match():
    assert geometry.match_profile({"maker": "Canon", "lens": "nobody"}) is None
    profile = geometry.match_profile(geometry.UNIT_A_LENS)
    assert profile is not None, "unit-a's measured lens identity must match"


def test_unit_a_lens_identity_matches_all_raw_frames():
    import glob

    paths = sorted(glob.glob("inputs/unit-a/raw/*.NEF"))
    assert len(paths) == 86
    for p in paths:
        assert geometry.match_profile(geometry.read_lens_identity(p)) is not None


def test_correct_verticals_uprights_tilted_bar():
    img = np.zeros((400, 400), np.uint8)
    img[50:350, 195:205] = 255
    tilted, true_angle = geometry.rotate_image(img, 3.0)
    fixed, found_angle = geometry.correct_verticals(tilted)
    assert found_angle == pytest.approx(-true_angle, abs=0.25)
    assert abs(geometry.dominant_vertical_angle(fixed)) < 0.5


def test_weighted_median_follows_length_not_mode():
    found = [(-2.0, 100.0), (-2.0, 100.0), (0.0, 100.0), (2.0, 100.0), (2.0, 100.0)]
    assert geometry.weighted_median_angle(found) == 0.0, (
        "the middle of the length sits at zero even though the longest "
        "leaning pile would win a squared vote"
    )
    assert geometry.agreement_share(found, 0.0) < geometry.VERT_MIN_AGREE_SHARE


def test_scattered_segments_vote_unknown():
    found = [(float(a), 50.0) for a in range(-9, 10)]
    median = geometry.weighted_median_angle(found)
    assert geometry.agreement_share(found, median) < geometry.VERT_MIN_AGREE_SHARE


def test_no_vertical_lines_means_unknown_not_level():
    assert geometry.dominant_vertical_angle(np.zeros((200, 200), np.uint8)) is None
    img, rotation = geometry.correct_verticals(np.zeros((200, 200), np.uint8))
    assert rotation is None and img.shape == (200, 200)


def test_verticals_found_on_real_interior():
    gray = _real_merge_gray("001")
    tilt = geometry.dominant_vertical_angle(gray)
    assert tilt is not None, "door frames and wall corners must read"
    assert abs(tilt) < 3.0, "a level tripod shot reads near zero"


def test_verticals_found_on_real_laundry_room():
    gray = _real_merge_gray("011")
    tilt = geometry.dominant_vertical_angle(gray)
    assert tilt is not None, "window and door frames must read"
    assert abs(tilt) < 3.0


def test_line_measure_needs_twenty_segments():
    assert geometry.line_measure(np.zeros((200, 200), np.uint8)) is None
    gray = _real_merge_gray("001")
    assert geometry.line_measure(gray) is not None
    assert geometry.line_measure(gray) > 0


def test_level_shots_do_not_rotate():
    assert geometry.needs_rotation(0.11) is False
    assert geometry.needs_rotation(None) is False
    assert geometry.needs_rotation(0.3) is True
    assert geometry.needs_rotation(-1.5) is True


def test_wooded_lot_has_no_agreeing_verticals():
    gray = _real_merge_gray("016")
    assert geometry.dominant_vertical_angle(gray) is None, (
        "leaning trunks must vote unknown, never a fake tilt"
    )


def test_crumb_verticals_vote_unknown():
    """Thirty short blind slats are one object's vote, not the room's.

    Unit-a 005's finished photo holds 30 near-vertical crumbs totalling
    857 px at review size: they agree with each other yet say nothing
    about the walls. A vote under one frame-height of edge, with no long
    architectural segment, is unknown.
    """
    img = np.full((600, 1200), 150, np.uint8)
    for i in range(30):
        x = 100 + (i * 31) % 1000
        cv2.line(img, (x, 200), (x + 1, 230), 40, 1)
    tilt = geometry.dominant_vertical_angle(img)
    assert tilt is None, f"30 short crumbs must not read as a room tilt, got {tilt}"


def test_vertical_correction_roundtrip_on_real_photo():
    gray = _real_merge_gray("001")
    tilted, _ = geometry.rotate_image(gray, 1.5)
    fixed, applied = geometry.correct_verticals(tilted)
    assert applied is not None
    residual = geometry.dominant_vertical_angle(fixed)
    assert residual is not None and abs(residual) <= 0.5


def test_crop_rect_matches_crop_valid():
    valid = np.ones((400, 500), bool)
    valid[0:10, :] = False
    y0, y1, x0, x1 = geometry.crop_valid_rect(valid)
    img = np.zeros((400, 500, 3), np.uint8)
    assert (geometry.crop_valid(img, valid) == img[y0:y1, x0:x1]).all()
    assert y0 >= 10, "the rect must exclude the invalid top rows"
    assert valid[y0:y1, x0:x1].all(), "the rect holds only valid pixels"


def test_crop_valid_removes_rotation_borders():
    img = np.full((400, 500, 3), 200, np.uint8)
    tilted, angle = geometry.rotate_image(img, 5.0)
    assert (tilted == 0).any(), "rotation leaves black corners first"
    valid = geometry.rotation_valid_mask(400, 500, angle)
    cropped = geometry.crop_valid(tilted, valid)
    assert not (cropped == 0).any(), "the crop holds only filled pixels"
    assert cropped.shape[0] > 350 and cropped.shape[1] > 400, "crop stays generous"


def test_ghosting_zero_on_identical_frames():
    frames = [np.zeros((64, 64, 3), np.uint8) for _ in range(3)]
    assert geometry.ghosting_score(frames) == pytest.approx(0.0)


def test_ghosting_detects_motion():
    frames = [np.zeros((64, 64, 3), np.uint8) for _ in range(3)]
    frames[1][20:30, 20:30] = 255
    assert geometry.ghosting_score(frames) > 0.0


def test_ghosting_ignores_exposure_steps():
    """Bracket-like exposure scaling is not motion.

    Three frames of one scene at 1x/2x/4x gain (the way brackets differ)
    must read near zero once the score normalizes exposure first. The
    old spread-without-normalization reads ~1.0 here ("99% of pixels
    moved"), which is what made the A0 number meaningless.
    """
    rng = np.random.default_rng(7)
    base = rng.integers(10, 60, size=(64, 64, 3)).astype(np.uint8)
    frames = [
        np.clip(base.astype(np.float32) * gain, 0, 255).astype(np.uint8) for gain in (1.0, 2.0, 4.0)
    ]
    assert geometry.ghosting_score(frames) < 0.05, "exposure steps are not motion"


def test_ghosting_detects_motion_after_normalization():
    """Real motion still reads once exposure is normalized away."""
    rng = np.random.default_rng(11)
    base = rng.integers(10, 60, size=(64, 64, 3)).astype(np.float32)
    frames = [np.clip(base * gain, 0, 255).astype(np.uint8) for gain in (1.0, 2.0, 4.0)]
    moved = frames[1].copy()
    moved[10:30, 10:30] = 200
    moved_frames = [frames[0], moved, frames[2]]
    assert geometry.ghosting_score(moved_frames) > 0.05, "moved pixels still count"


def test_deghost_decision_names_no_motion():
    assert "no deghost" in geometry.deghost_decision(0.01).lower()
    assert "deghost" in geometry.deghost_decision(0.99).lower()
