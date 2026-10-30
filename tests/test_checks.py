"""Tests for the unit-7 check thresholds."""

import numpy as np

from listing_partner import checks


def test_highlights_must_drop_or_never_appear():
    assert checks.check_highlights(0.02, 0.01)[0] is True
    assert checks.check_highlights(0.02, 0.02)[0] is False
    assert checks.check_highlights(0.01, 0.02)[0] is False
    assert checks.check_highlights(0.0, 0.0)[0] is True
    assert checks.check_highlights(0.0, 0.0001)[0] is False
    assert checks.check_highlights(0.0, 0.0, window_pixels=500)[0] is True
    ok, reason = checks.check_highlights(0.0, 0.0, window_pixels=0)
    assert ok is False and "not measured" in reason


def test_clipped_fraction_counts_any_channel():
    from listing_partner import checks

    blue = np.zeros((10, 10, 3), np.uint8)
    blue[:, :] = (150, 150, 255)
    assert checks.clipped_fraction(blue) == 1.0, "a blown blue channel clips the pixel"
    gray = np.full((10, 10, 3), 245, np.uint8)
    assert checks.clipped_fraction(gray) == 0.0


def test_outside_unchanged_is_exact():
    assert checks.check_outside_unchanged(0)[0] is True
    assert checks.check_outside_unchanged(1)[0] is False
    assert checks.check_outside_unchanged(0, window_pixels=900)[0] is True
    ok, reason = checks.check_outside_unchanged(0, window_pixels=0)
    assert ok is False and "not measured" in reason


def test_noise_must_drop():
    assert checks.check_noise(5.0, 3.0)[0] is True
    assert checks.check_noise(3.0, 5.0)[0] is False


def test_edges_within_ten_percent():
    assert checks.check_edges(100.0, 95.0)[0] is True
    assert checks.check_edges(100.0, 105.0)[0] is True
    assert checks.check_edges(100.0, 80.0)[0] is False
    assert checks.check_edges(0.0, 5.0)[0] is False


def test_straightness_must_not_fall():
    assert checks.check_straightness(300.0, 320.0)[0] is True
    assert checks.check_straightness(300.0, 280.0)[0] is False


def test_verticals_half_degree_or_unknown():
    assert checks.check_verticals(0.3)[0] is True
    assert checks.check_verticals(0.8)[0] is False
    ok, reason = checks.check_verticals(None)
    assert ok is False and "not measured" in reason


def test_empty_checks_report_not_measured_never_pass():
    for check in (
        lambda: checks.check_verticals(None),
        lambda: checks.check_straightness(None, 300.0),
        lambda: checks.check_straightness(300.0, None),
        lambda: checks.check_straightness(289.0, 289.0, corrected=False),
        lambda: checks.check_edges(0.0, 0.0),
        lambda: checks.check_highlights(0.0, 0.0, window_pixels=0),
        lambda: checks.check_outside_unchanged(0, window_pixels=0),
    ):
        ok, reason = check()
        assert ok is False and "not measured" in reason


def test_spend_and_counts():
    assert checks.check_spend(1.99)[0] is True
    assert checks.check_spend(2.01)[0] is False
    assert checks.check_counts(16, 1)[0] is True
    assert checks.check_counts(15, 1)[0] is False
