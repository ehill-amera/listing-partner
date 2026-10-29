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

#: The one shared look, tuned once against Erik's MLS photos (see the unit
#: 02 report for the tuning), then frozen. Every photo gets the same
#: constants; per-photo automatic exposure and white balance adapt to the
#: photo's own pixels only. Processing never reads the photo's MLS twin:
#: a new listing has no MLS photo to copy.
#: Interior rooms finish bright and airy; exterior shots finish at their
#: own lower level, told apart by visible sky (a camera scene mode, not a
#: twin read).
INTERIOR_TARGET_MEDIAN = 187.0
EXTERIOR_TARGET_MEDIAN = 123.0
SKY_FRACTION_CUT = 0.001
#: Shadow lift through a blurred luminance mask, plus a gentle gamma for
#: the low-contrast HDR look. Bounded auto gain toward the class target.
#: The highlight shoulder compresses but never hides real clipping: a
#: gain-scaled blown window still reads at or above 250.
SHADOW_LIFT = 0.6
LOOK_GAMMA = 1.0
SHOULDER_SLOPE = 0.07
AUTO_GAIN_LO = 0.4
AUTO_GAIN_HI = 3.5
#: White balance reads the room without its brightest pixels (windows,
#: lamps), so daylight glass never votes on tungsten walls. Strength 1.0
#: is full gray-world; lower keeps more of the room's own palette.
WB_BRIGHT_PERCENTILE = 90.0
WB_STRENGTH = 1.0


def _luminance(img: np.ndarray) -> np.ndarray:
    return cv2.cvtColor(img, cv2.COLOR_RGB2GRAY).astype(np.float32)


def sky_fraction(img: np.ndarray) -> float:
    """Share of bright blue pixels across the top three-fifths of frame."""
    h = img.shape[0]
    top = img[: int(h * 0.6)].astype(float)
    gray = top.mean(axis=2)
    sky = (top[:, :, 2] > top[:, :, 0] + 12) & (top[:, :, 2] > top[:, :, 1] + 5) & (gray > 110)
    return float(sky.mean())


def classify_scene(img: np.ndarray) -> str:
    """Interior or exterior, from the photo's own sky content."""
    return "exterior" if sky_fraction(img) > SKY_FRACTION_CUT else "interior"


def target_median(img: np.ndarray) -> float:
    """The shared brightness target for this photo's scene class."""
    if classify_scene(img) == "exterior":
        return EXTERIOR_TARGET_MEDIAN
    return INTERIOR_TARGET_MEDIAN


def balance_exposure(img: np.ndarray, protect: np.ndarray | None = None) -> tuple[np.ndarray, dict]:
    """Balance a merged room photo. Returns (photo, report).

    White balance from the room's own below-bright pixels, shadow lift
    through a blurred luminance mask, automatic gain toward the shared
    class target (bounded), then a soft highlight shoulder. Pixels under
    protect keep their exact values. No MLS twin is read.
    """
    work = img.astype(np.float32)
    gray = _luminance(img)
    ceiling = float(np.percentile(gray, WB_BRIGHT_PERCENTILE))
    room = gray < ceiling
    report: dict = {"white_balanced": False}
    if room.sum() > 1000:
        means = np.array([work[:, :, c][room].mean() for c in range(3)])
        target = float(means.mean())
        factors = target / np.maximum(means, 1e-6)
        factors = 1.0 + WB_STRENGTH * (factors - 1.0)
        work *= factors[None, None, :]
        report["white_balanced"] = True
    blur = cv2.GaussianBlur(gray, (0, 0), max(img.shape) / 40.0)
    darkness = np.clip((120.0 - blur) / 120.0, 0.0, 1.0)
    shadow_gain = 1.0 + SHADOW_LIFT * darkness
    work *= shadow_gain[:, :, None]
    report["shadow_gain"] = round(float(shadow_gain.mean() - 1.0), 4)
    target = target_median(img)
    gain = min(AUTO_GAIN_HI, max(AUTO_GAIN_LO, target / max(1.0, float(np.median(gray)))))
    work *= gain
    report["auto_gain"] = round(gain, 4)
    report["scene"] = classify_scene(img)
    if LOOK_GAMMA != 1.0:
        work = 255.0 * np.power(np.clip(work / 255.0, 0.0, 1.0), LOOK_GAMMA)
    # Highlight shoulder runs last so no earlier gain can re-blow whites.
    over = work > 235.0
    work[over] = 235.0 + (work[over] - 235.0) * SHOULDER_SLOPE
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
    """Edge-preserving bilateral denoise on luminance, light chroma pass.

    Kept gentle on purpose: real texture may only soften a little while
    flat-patch noise must still fall clearly.
    """
    ycrcb = cv2.cvtColor(img, cv2.COLOR_RGB2YCrCb)
    y, cr, cb = cv2.split(ycrcb)
    soft_y = cv2.bilateralFilter(y, 5, 15, 15)
    soft_cr = cv2.GaussianBlur(cr, (0, 0), 1.0)
    soft_cb = cv2.GaussianBlur(cb, (0, 0), 1.0)
    return cv2.cvtColor(cv2.merge([soft_y, soft_cr, soft_cb]), cv2.COLOR_YCrCb2RGB)
