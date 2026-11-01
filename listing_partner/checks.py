"""Pass/fail checks with thresholds, for the unit 7 agent and the page.

Each check takes measured numbers and returns (passed, one-line reason).
Thresholds live here, in one place, so unit 7 reads this file, not prose.
"""

from __future__ import annotations

UNIT_SPEND_BUDGET_USD = 2.00
EDGE_TOLERANCE = 0.10
#: Near-white level for the window highlights check. Shared with the
#: pull-frame choice: the frame is picked on what this check measures.
CLIP_LEVEL = 250
#: Largest a* or b* step across a regional correction's edge (criterion 14).
REGION_EDGE_STEP_LIMIT = 2.0


def flat_white_share(rgb) -> float:
    """Percent of the frame reading flat neutral white.

    Channel spread 4 or less and mean 225 or more. Real white trim and blown
    windows count too, so this shows scale, it does not isolate a defect.
    """
    import numpy as np

    values = np.asarray(rgb).astype(np.int16)
    spread = values.max(axis=-1) - values.min(axis=-1)
    return 100.0 * float(((spread <= 4) & (values.mean(axis=-1) >= 225)).mean())


def check_region_edge(step_a: float | None, step_b: float | None) -> tuple[bool, str]:
    """Criterion 14: the a* and b* step across a regional correction's edge."""
    if step_a is None or step_b is None:
        return False, "not measured: no cool correction ran on this photo"
    ok = step_a <= REGION_EDGE_STEP_LIMIT and step_b <= REGION_EDGE_STEP_LIMIT
    return ok, f"a* step {step_a:.2f}, b* step {step_b:.2f} (limit {REGION_EDGE_STEP_LIMIT:.0f})"


def clipped_fraction(rgb) -> float:
    """Fraction of pixels near-white on any channel at the clipped level.

    Takes an RGB array: a pixel counts when its brightest channel reaches
    CLIP_LEVEL, exactly what criterion 4 measures. Grayscale understates
    blowout (a blown blue sky reads gray 160), so gray must never come in.
    """
    import numpy as np

    return float((np.asarray(rgb).max(axis=-1) >= CLIP_LEVEL).mean())


def check_highlights(
    clip_before: float, clip_after: float, window_pixels: int | None = None
) -> tuple[bool, str]:
    """Window highlights held, measured on the final output with no clamp.

    Near-white window pixels must drop when the window had any, and a
    window with none must gain none. With no window pixels at all there
    is nothing to measure: never a pass.
    """
    if window_pixels == 0:
        return False, "not measured: no confirmed window pixels"
    if clip_before > 0:
        ok = clip_after < clip_before
    else:
        ok = clip_after == 0
    return ok, f"clipped {clip_before:.4f} -> {clip_after:.4f} of window pixels"


def check_outside_unchanged(
    changed_outside: int, window_pixels: int | None = None
) -> tuple[bool, str]:
    """Step B changes nothing outside the window masks.

    With no mask the step had nothing to change: not measured, never
    a pass.
    """
    if window_pixels == 0:
        return False, "not measured: no window mask, step B had nothing to change"
    ok = changed_outside == 0
    return ok, f"{changed_outside} pixels changed outside masks"


def check_noise(noise_before: float, noise_after: float) -> tuple[bool, str]:
    """Shadow noise must drop."""
    ok = noise_after < noise_before
    return ok, f"shadow noise {noise_before:.2f} -> {noise_after:.2f}"


def check_edges(edge_before: float, edge_after: float) -> tuple[bool, str]:
    """Edge strength stays within tolerance."""
    if edge_before <= 0:
        return False, "not measured: no edge strength before"
    ratio = edge_after / edge_before
    ok = 1.0 - EDGE_TOLERANCE <= ratio <= 1.0 + EDGE_TOLERANCE
    return ok, f"edge strength ratio {ratio:.3f} (tolerance {EDGE_TOLERANCE})"


def check_straightness(
    topmean_before: float | None, topmean_after: float | None, corrected: bool = True
) -> tuple[bool, str]:
    """Line straightness improves after correction.

    corrected=False means no correction ran, so before and after are the
    same image: not measured, never a pass.
    """
    if not corrected:
        return False, "not measured: no lens correction applied, same image both sides"
    if topmean_before is None or topmean_after is None:
        return False, "not measured: too few line segments to compare"
    ok = topmean_after >= topmean_before
    return ok, f"line measure {topmean_before:.0f} -> {topmean_after:.0f}"


def check_verticals(residual_deg: float | None) -> tuple[bool, str]:
    """Near-vertical lines stand within half a degree.

    None means no agreeing verticals were found: not measured, never a
    pass. A check that finds nothing to measure must say so.
    """
    if residual_deg is None:
        return False, "not measured: no agreeing near-vertical lines found"
    ok = abs(residual_deg) <= 0.5
    return ok, f"residual tilt {residual_deg:.2f} degrees"


LOOK_BRIGHTNESS_TOL = 0.15
LOOK_COLOR_TOL = 5.0


def check_look(
    fin_median: float,
    mls_median: float,
    fin_a: float,
    mls_a: float,
    fin_b: float,
    mls_b: float,
) -> tuple[bool, str]:
    """The finished look matches Erik's MLS photo of the same shot.

    Median brightness within 15%, mean Lab a* and b* within 5 units.
    Measured after the run from the shipped files; processing never
    reads the twin, so this check can only observe, never steer.
    """
    bright_gap = abs(fin_median - mls_median) / max(1.0, mls_median)
    ok = (
        bright_gap <= LOOK_BRIGHTNESS_TOL
        and abs(fin_a - mls_a) <= LOOK_COLOR_TOL
        and abs(fin_b - mls_b) <= LOOK_COLOR_TOL
    )
    return ok, (
        f"brightness {fin_median:.0f} vs {mls_median:.0f} "
        f"({bright_gap * 100:.1f}%), a* {fin_a:+.1f} vs {mls_a:+.1f}, "
        f"b* {fin_b:+.1f} vs {mls_b:+.1f}"
    )


#: Ship-gate bounds for one window pull (contract 02 section B). The rim
#: is the mask's own border band, mostly trim: the pull may correct its
#: light by up to RIM_TOL gray levels, but a whole frame going dark is
#: damage, never a correction. The pull inserts native view pixels, so
#: its light ratio against the room must already read near one: outside
#: PULL_GAIN_LO..PULL_GAIN_HI the view light does not match the room.
RIM_TOL = 25.0
PULL_GAIN_LO = 0.5
PULL_GAIN_HI = 2.0


def check_window_rim(rim_before: float, rim_after: float) -> tuple[bool, str]:
    """The window rim keeps its merged light within tolerance."""
    gap = abs(rim_after - rim_before)
    ok = gap <= RIM_TOL
    return ok, f"rim light {rim_before:.1f} -> {rim_after:.1f} (tolerance {RIM_TOL:.0f})"


def check_pull_gain(gain: float) -> tuple[bool, str]:
    """The view light matches the room light well enough to insert."""
    ok = PULL_GAIN_LO <= gain <= PULL_GAIN_HI
    return ok, f"view-to-room light ratio {gain:.2f} (bounds {PULL_GAIN_LO}-{PULL_GAIN_HI})"


#: Bright-surface limit for the finish (contract 02, final round part
#: two): at most this share of a finished interior frame may read cyan
#: or blue, unless the photo's MLS twin reads higher.
BRIGHT_SURFACE_LIMIT_PCT = 1.0


def bright_surface_share(rgb) -> float:
    """Share (%) of the frame reading bright cyan or blue.

    Bright means mean above 170; cyan or blue means B at least G, G
    minus R at least 15, B minus R at least 30. Takes an RGB array.
    """
    import numpy as np

    a = np.asarray(rgb).astype(float)
    mean = a.mean(axis=2)
    r, g, b = a[:, :, 0], a[:, :, 1], a[:, :, 2]
    bad = (mean > 170) & (b >= g) & (g - r >= 15) & (b - r >= 30)
    return float(bad.mean() * 100.0)


def check_bright_surfaces(share: float, twin_share: float | None = None) -> tuple[bool, str]:
    """Bright surfaces stay neutral: the cyan/blue share stays at or below
    1% of the frame, or at or below the MLS twin's share, whichever is
    higher."""
    limit = max(BRIGHT_SURFACE_LIMIT_PCT, twin_share or 0.0)
    ok = share <= limit
    twin = f", twin {twin_share:.2f}%" if twin_share is not None else ""
    return ok, f"bright cyan/blue {share:.2f}% of frame (limit {limit:.2f}%{twin})"


def check_spend(unit_spend_usd: float) -> tuple[bool, str]:
    """Unit spend stays under budget."""
    ok = unit_spend_usd < UNIT_SPEND_BUDGET_USD
    return ok, f"unit spend ${unit_spend_usd:.4f} of ${UNIT_SPEND_BUDGET_USD:.2f}"


def check_counts(processed: int, failed: int, total: int = 17) -> tuple[bool, str]:
    """Every set finished or failed in plain words."""
    ok = processed + failed == total
    return ok, f"{processed} processed + {failed} failed = {total} sets"
