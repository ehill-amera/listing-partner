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
