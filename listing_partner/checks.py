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


def clipped_fraction(gray) -> float:
    """Fraction of pixels at or above the clipped level."""
    import numpy as np

    return float((np.asarray(gray) >= CLIP_LEVEL).mean())


def check_highlights(clip_before: float, clip_after: float) -> tuple[bool, str]:
    """Window highlights held, measured on the final output with no clamp.

    Near-white window pixels must drop when the window had any, and a
    window with none must gain none.
    """
    if clip_before > 0:
        ok = clip_after < clip_before
    else:
        ok = clip_after == 0
    return ok, f"clipped {clip_before:.4f} -> {clip_after:.4f} of window pixels"


def check_outside_unchanged(changed_outside: int) -> tuple[bool, str]:
    """Step B changes nothing outside the window masks."""
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
    topmean_before: float | None, topmean_after: float | None
) -> tuple[bool, str]:
    """Line straightness improves after correction."""
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


def check_spend(unit_spend_usd: float) -> tuple[bool, str]:
    """Unit spend stays under budget."""
    ok = unit_spend_usd < UNIT_SPEND_BUDGET_USD
    return ok, f"unit spend ${unit_spend_usd:.4f} of ${UNIT_SPEND_BUDGET_USD:.2f}"


def check_counts(processed: int, failed: int, total: int = 17) -> tuple[bool, str]:
    """Every set finished or failed in plain words."""
    ok = processed + failed == total
    return ok, f"{processed} processed + {failed} failed = {total} sets"
