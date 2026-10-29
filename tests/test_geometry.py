"""Tests for lens/geometry correction. No raw files, no network."""

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


def test_wooded_lot_has_no_agreeing_verticals():
    gray = _real_merge_gray("016")
    assert geometry.dominant_vertical_angle(gray) is None, (
        "leaning trunks must vote unknown, never a fake tilt"
    )


def test_vertical_correction_roundtrip_on_real_photo():
    gray = _real_merge_gray("001")
    tilted, _ = geometry.rotate_image(gray, 1.5)
    fixed, applied = geometry.correct_verticals(tilted)
    assert applied is not None
    residual = geometry.dominant_vertical_angle(fixed)
    assert residual is not None and abs(residual) <= 0.5


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
