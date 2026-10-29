"""Exposure balance and denoising (unit 2, steps C and D). Local only.

Balance is global smooth curves plus a blurred luminance lift: no region
edges by construction. The white point comes from near-gray pixels so
walls read true; pulled-window interiors can be protected and wait for
step B. Denoise is edge-preserving bilateral on full-res luminance plus
light chroma smoothing, applied last.
"""

from __future__ import annotations

import cv2
import numpy as np


def _luminance(img: np.ndarray) -> np.ndarray:
    return cv2.cvtColor(img, cv2.COLOR_RGB2GRAY).astype(np.float32)


def balance_exposure(
    img: np.ndarray, mls_median: float | None = None, protect: np.ndarray | None = None
) -> tuple[np.ndarray, dict]:
    """Balance a merged room photo. Returns (photo, report).

    White balance from near-gray pixels, shadow lift through a blurred
    luminance mask, soft highlight shoulder, then an overall gain toward
    the MLS photo's median (bounded). Pixels under protect keep their
    exact values.
    """
    work = img.astype(np.float32)
    gray = _luminance(img)
    near_gray = (
        (np.abs(img[:, :, 0].astype(float) - img[:, :, 1].astype(float)) < 12)
        & (np.abs(img[:, :, 2].astype(float) - img[:, :, 1].astype(float)) < 12)
        & (gray > 40)
        & (gray < 220)
    )
    report: dict = {"white_balanced": False}
    if near_gray.sum() > 1000:
        means = [work[:, :, c][near_gray].mean() for c in range(3)]
        target = sum(means) / 3.0
        for c in range(3):
            if means[c] > 1e-6:
                work[:, :, c] *= target / means[c]
        report["white_balanced"] = True
    blur = cv2.GaussianBlur(gray, (0, 0), max(img.shape) / 40.0)
    darkness = np.clip((120.0 - blur) / 120.0, 0.0, 1.0)
    shadow_gain = 1.0 + 0.35 * darkness
    work *= shadow_gain[:, :, None]
    report["shadow_gain"] = round(float(shadow_gain.mean() - 1.0), 4)
    if mls_median is not None:
        gap = mls_median / max(1.0, float(gray.mean()))
        gain = min(1.25, max(0.8, gap))
        work *= gain
        report["mls_gain"] = round(gain, 4)
    # Highlight shoulder runs last so no earlier gain can re-blow whites.
    over = work > 235.0
    work[over] = 235.0 + (work[over] - 235.0) * 0.15
    out = np.clip(work, 0, 255).astype(np.uint8)
    if protect is not None:
        out[protect] = img[protect]
    return out, report


def flat_noise(img: np.ndarray) -> float:
    """Noise level: std of the Laplacian over dark flat patches."""
    gray = _luminance(img)
    dark = gray < np.percentile(gray, 25)
    lap = cv2.Laplacian(gray, cv2.CV_32F)
    flat = dark & (cv2.GaussianBlur(np.abs(lap), (0, 0), 2) < 3.0)
    if flat.sum() < 100:
        flat = dark
    return float(lap[flat].std())


def edge_strength(img: np.ndarray) -> float:
    """Texture energy: mean of the strongest 1 percent of gradients.

    Only the strongest edges count, so the noise bed never joins in and
    the same scene scores comparably before and after denoising.
    """
    gray = _luminance(img)
    grad = np.abs(cv2.Sobel(gray, cv2.CV_32F, 1, 0)) + np.abs(cv2.Sobel(gray, cv2.CV_32F, 0, 1))
    flat = np.sort(grad.ravel())
    top = flat[-max(10, flat.size // 100) :]
    return float(top.mean())


def denoise(img: np.ndarray) -> np.ndarray:
    """Edge-preserving bilateral denoise on luminance, light chroma pass."""
    ycrcb = cv2.cvtColor(img, cv2.COLOR_RGB2YCrCb)
    y, cr, cb = cv2.split(ycrcb)
    soft_y = cv2.bilateralFilter(y, 7, 25, 25)
    soft_cr = cv2.GaussianBlur(cr, (0, 0), 1.0)
    soft_cb = cv2.GaussianBlur(cb, (0, 0), 1.0)
    return cv2.cvtColor(cv2.merge([soft_y, soft_cr, soft_cb]), cv2.COLOR_YCrCb2RGB)
