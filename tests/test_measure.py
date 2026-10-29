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


def test_overlay_tint_touches_mask_only():
    from listing_partner import run_finish

    rng = np.random.default_rng(11)
    finished = rng.integers(0, 255, (100, 120, 3)).astype(np.uint8)
    union = np.zeros((100, 120), bool)
    union[30:70, 40:90] = True
    overlay = run_finish.tint_overlay(finished, union)
    assert (overlay[~union] == finished[~union]).all(), "outside the mask nothing changes"
    assert (overlay[union] != finished[union]).any(), "the outline shows over the glass"
