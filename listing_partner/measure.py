"""Post-hoc measurement from shipped files. Never processing input.

Every number here is read off finished photos, MLS photos, masks and the
spend ledger after the run. The pipeline must never call this while
processing a photo: measuring against the MLS twin is how results are
verified, not how they are produced.
"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from listing_partner import checks


def lab_mean_ab(rgb: np.ndarray) -> tuple[float, float]:
    """Mean a* and b* of an RGB photo (Lab, centered)."""
    lab = cv2.cvtColor(np.clip(rgb, 0, 255).astype(np.uint8), cv2.COLOR_RGB2LAB).astype(float)
    return float(lab[:, :, 1].mean() - 128.0), float(lab[:, :, 2].mean() - 128.0)


#: Purple-cast tolerance for the floor zone near pulled windows, in
#: percentage points of lit zone pixels reading R and B above G.
#: Absolute bar 8; rooms whose own floor reads gray (unit-a 003, 004,
#: 007) are judged against Erik's finish of the same floor instead
#: (FLOOR_TWIN_SLACK): matching the reference within slack is correct
#: even past 8, and anything worse than the reference still fails.
FLOOR_CAST_TOL = 8.0
FLOOR_TWIN_SLACK = 3.0
#: A floor zone with fewer lit pixels than this is not a measurement.
FLOOR_MIN_LIT = 1000


def zone_mask(h: int, w: int, zone_frac: tuple | None) -> np.ndarray | None:
    """Boolean mask for a fractional (y0, y1, x0, x1) zone, or None."""
    if zone_frac is None:
        return None
    y0, y1, x0, x1 = zone_frac
    yy, xx = np.mgrid[0:h, 0:w]
    return (yy >= y0 * h) & (yy < y1 * h) & (xx >= x0 * w) & (xx < x1 * w)


def purple_share(rgb: np.ndarray, zone: np.ndarray) -> tuple[float, int]:
    """Share (%) of lit zone pixels reading purple, plus the lit count.

    Purple is R and B both above G by more than 2 on pixels brighter
    than mean 90: the lavender gray a wrong white balance paints on
    wood. Warm wood reads R above B and never counts. Arithmetic runs
    on int16: on uint8, G at 255 wraps the +2 and white sun patches
    would count as purple.
    """
    lit = zone & (rgb.mean(axis=2) > 90)
    lit_n = int(lit.sum())
    if lit_n == 0:
        return 0.0, 0
    r = rgb[:, :, 0].astype(np.int16)
    g = rgb[:, :, 1].astype(np.int16)
    b = rgb[:, :, 2].astype(np.int16)
    share = float((((r > g + 2) & (b > g + 2)) & lit).sum()) / lit_n * 100.0
    return share, lit_n


def floor_cast_stats(finished_path: Path, mls_path: Path | None, zone_frac: tuple | None) -> dict:
    """Criterion-13 floor numbers for one shot, from the shipped files."""
    fin_bgr = cv2.imread(str(finished_path))
    if fin_bgr is None:
        raise ValueError(f"cannot read finished photo {finished_path}")
    fin_rgb = cv2.cvtColor(fin_bgr, cv2.COLOR_BGR2RGB)
    zone = zone_mask(*fin_rgb.shape[:2], zone_frac)
    if zone is None or not zone.any():
        return {
            "floor_cast": None,
            "mls_floor_cast": None,
            "floor_ok": False,
            "floor_reason": "not measured: no floor zone near the windows",
        }
    cast, lit_n = purple_share(fin_rgb, zone)
    if lit_n < FLOOR_MIN_LIT:
        return {
            "floor_cast": round(cast, 1),
            "mls_floor_cast": None,
            "floor_ok": False,
            "floor_reason": "not measured: too little lit floor near the windows",
        }
    mls_cast = None
    if mls_path is not None:
        mls_bgr = cv2.imread(str(mls_path))
        if mls_bgr is None:
            raise ValueError(f"cannot read MLS photo {mls_path}")
        mls_rgb = cv2.cvtColor(mls_bgr, cv2.COLOR_BGR2RGB)
        mls_zone = zone_mask(*mls_rgb.shape[:2], zone_frac)
        mls_cast, _ = purple_share(mls_rgb, mls_zone)
    ok = cast <= FLOOR_CAST_TOL
    twin = f", MLS twin {mls_cast:.1f}%" if mls_cast is not None else ", no MLS twin"
    if not ok and mls_cast is not None and cast <= mls_cast + FLOOR_TWIN_SLACK:
        ok = True
        twin += " (matches the reference floor)"
    reason = f"floor near windows {cast:.1f}% purple (limit {FLOOR_CAST_TOL:.0f}%){twin}"
    return {
        "floor_cast": round(cast, 1),
        "mls_floor_cast": None if mls_cast is None else round(mls_cast, 1),
        "floor_ok": ok,
        "floor_reason": reason,
    }


def bright_surface_stats(finished_path: Path, mls_path: Path | None) -> dict:
    """Criterion bright-surface numbers for one shot, from shipped files.

    The finished photo's bright cyan/blue share against the 1% bar or
    the MLS twin's share, whichever is higher. Post-hoc only: the
    pipeline never reads the twin while processing.
    """
    fin_bgr = cv2.imread(str(finished_path))
    if fin_bgr is None:
        raise ValueError(f"cannot read finished photo {finished_path}")
    fin_rgb = cv2.cvtColor(fin_bgr, cv2.COLOR_BGR2RGB)
    share = checks.bright_surface_share(fin_rgb)
    twin_share = None
    if mls_path is not None:
        mls_bgr = cv2.imread(str(mls_path))
        if mls_bgr is None:
            raise ValueError(f"cannot read MLS photo {mls_path}")
        twin_share = checks.bright_surface_share(cv2.cvtColor(mls_bgr, cv2.COLOR_BGR2RGB))
    ok, reason = checks.check_bright_surfaces(share, twin_share)
    return {
        "bright_share": round(share, 2),
        "mls_bright_share": None if twin_share is None else round(twin_share, 2),
        "bright_ok": ok,
        "bright_reason": reason,
    }


def look_stats(finished_path: Path, mls_path: Path) -> dict:
    """Criterion-11 numbers for one shot, from the two shipped files."""
    fin_bgr = cv2.imread(str(finished_path))
    mls_bgr = cv2.imread(str(mls_path))
    if fin_bgr is None:
        raise ValueError(f"cannot read finished photo {finished_path}")
    if mls_bgr is None:
        raise ValueError(f"cannot read MLS photo {mls_path}")
    fin_rgb = cv2.cvtColor(fin_bgr, cv2.COLOR_BGR2RGB)
    mls_rgb = cv2.cvtColor(mls_bgr, cv2.COLOR_BGR2RGB)
    fin_med = float(np.median(cv2.cvtColor(fin_bgr, cv2.COLOR_BGR2GRAY)))
    mls_med = float(np.median(cv2.cvtColor(mls_bgr, cv2.COLOR_BGR2GRAY)))
    fin_a, fin_b = lab_mean_ab(fin_rgb)
    mls_a, mls_b = lab_mean_ab(mls_rgb)
    ok, reason = checks.check_look(fin_med, mls_med, fin_a, mls_a, fin_b, mls_b)
    return {
        "fin_median": round(fin_med, 1),
        "mls_median": round(mls_med, 1),
        "fin_a": round(fin_a, 2),
        "fin_b": round(fin_b, 2),
        "mls_a": round(mls_a, 2),
        "mls_b": round(mls_b, 2),
        "look_ok": ok,
        "look_reason": reason,
    }
