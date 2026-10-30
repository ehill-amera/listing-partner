"""Tests for post-hoc measurement. No network, no key."""

import numpy as np

from listing_partner import checks, measure


def test_check_look_passes_near_match():
    ok, _ = checks.check_look(190, 185, 2.0, 2.5, 8.0, 9.0)
    assert ok is True


def test_check_look_fails_dark_or_orange():
    assert checks.check_look(100, 190, 2.0, 2.5, 8.0, 9.0)[0] is False
    assert checks.check_look(190, 185, 14.0, 2.5, 40.0, 9.0)[0] is False


def test_look_stats_reads_files_not_arrays(tmp_path):
    import cv2

    fin = np.full((60, 80, 3), 190, np.uint8)
    mls = np.full((60, 80, 3), 185, np.uint8)
    fin_path = tmp_path / "fin.jpg"
    mls_path = tmp_path / "mls.jpg"
    cv2.imwrite(str(fin_path), cv2.cvtColor(fin, cv2.COLOR_RGB2BGR))
    cv2.imwrite(str(mls_path), cv2.cvtColor(mls, cv2.COLOR_RGB2BGR))
    stats = measure.look_stats(fin_path, mls_path)
    assert stats["look_ok"] is True
    assert abs(stats["fin_median"] - 190) < 3


def test_floor_cast_ignores_white_sun_patches(tmp_path):
    """White reads R == G == B, never purple.

    Unit-a 001's floor zone holds blown sun patches through the
    windows: on uint8 the +2 wrapped past 255 and every white pixel
    counted, firing the wood guard at 30% on a 3% zone.
    """
    import cv2

    white = np.full((100, 120, 3), 255, np.uint8)
    white_path = tmp_path / "white.jpg"
    cv2.imwrite(str(white_path), cv2.cvtColor(white, cv2.COLOR_RGB2BGR))
    stats = measure.floor_cast_stats(white_path, None, (0.0, 1.0, 0.0, 1.0))
    assert stats["floor_cast"] == 0.0, stats
    assert stats["floor_ok"] is True


def test_floor_cast_flags_lavender_not_wood(tmp_path):
    import cv2

    wood = np.full((100, 120, 3), (191, 176, 166), np.uint8)  # warm wood, R above B
    lav = np.full((100, 120, 3), (186, 182, 193), np.uint8)  # lavender gray
    wood_path, lav_path = tmp_path / "wood.jpg", tmp_path / "lav.jpg"
    cv2.imwrite(str(wood_path), cv2.cvtColor(wood, cv2.COLOR_RGB2BGR))
    cv2.imwrite(str(lav_path), cv2.cvtColor(lav, cv2.COLOR_RGB2BGR))
    zone = (0.0, 1.0, 0.0, 1.0)
    wood_stats = measure.floor_cast_stats(wood_path, None, zone)
    assert wood_stats["floor_ok"] is True, wood_stats["floor_reason"]
    lav_stats = measure.floor_cast_stats(lav_path, wood_path, zone)
    assert lav_stats["floor_ok"] is False, "lavender floors must fail"
    assert lav_stats["mls_floor_cast"] is not None


def test_floor_cast_matches_gray_reference_floor(tmp_path):
    """A zone no more purple than Erik's own finish of it passes.

    Unit-a 007's rug reads purple in the MLS twin too; matching the
    reference within slack is correct there, while anything worse than
    the reference still fails.
    """
    import cv2

    gray = np.full((100, 120, 3), (200, 195, 210), np.uint8)
    gray_path = tmp_path / "gray.jpg"
    cv2.imwrite(str(gray_path), cv2.cvtColor(gray, cv2.COLOR_RGB2BGR))
    zone = (0.0, 1.0, 0.0, 1.0)
    same = measure.floor_cast_stats(gray_path, gray_path, zone)
    assert same["floor_ok"] is True, same["floor_reason"]
    wood = np.full((100, 120, 3), (191, 176, 166), np.uint8)
    wood_path = tmp_path / "wood.jpg"
    cv2.imwrite(str(wood_path), cv2.cvtColor(wood, cv2.COLOR_RGB2BGR))
    worse = measure.floor_cast_stats(gray_path, wood_path, zone)
    assert worse["floor_ok"] is False, "worse than the reference still fails"


def test_overlay_tint_touches_mask_only():
    from listing_partner import run_finish

    rng = np.random.default_rng(11)
    finished = rng.integers(0, 255, (100, 120, 3)).astype(np.uint8)
    union = np.zeros((100, 120), bool)
    union[30:70, 40:90] = True
    overlay = run_finish.tint_overlay(finished, union)
    assert (overlay[~union] == finished[~union]).all(), "outside the mask nothing changes"
    assert (overlay[union] != finished[union]).any(), "the outline shows over the glass"
