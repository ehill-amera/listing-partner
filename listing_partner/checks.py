"""Pass/fail checks with thresholds, for the unit 7 agent and the page.

Each check takes measured numbers and returns (passed, one-line reason).
Thresholds live here, in one place, so unit 7 reads this file, not prose.
"""

from __future__ import annotations

UNIT_SPEND_BUDGET_USD = 2.00
EDGE_TOLERANCE = 0.10
CLIP_LEVEL = 250


def clipped_fraction(gray) -> float:
    """Fraction of pixels at or above the clipped level."""
    import numpy as np

    return float((np.asarray(gray) >= CLIP_LEVEL).mean())


def check_highlights(clip_before: float, clip_after: float) -> tuple[bool, str]:
    """Window highlights held: clipped fraction must not grow."""
    ok = clip_after <= clip_before
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


def check_spend(unit_spend_usd: float) -> tuple[bool, str]:
    """Unit spend stays under budget."""
    ok = unit_spend_usd < UNIT_SPEND_BUDGET_USD
    return ok, f"unit spend ${unit_spend_usd:.4f} of ${UNIT_SPEND_BUDGET_USD:.2f}"


def check_counts(processed: int, failed: int, total: int = 17) -> tuple[bool, str]:
    """Every set finished or failed in plain words."""
    ok = processed + failed == total
    return ok, f"{processed} processed + {failed} failed = {total} sets"
