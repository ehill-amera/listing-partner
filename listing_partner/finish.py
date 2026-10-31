"""Exposure balance and denoising (unit 2, steps C and D). Local only.

Balance is one global white balance plus one global exposure gain per
photo and one shared tone pipeline applied to luminance only: every
tone step multiplies all three channels by the same per-pixel factor
derived from luminance, so hue and saturation never change with
brightness. No regional, positional or brightness-dependent color step
exists anywhere (contract 02, final round Oct 31). Denoise is
edge-preserving bilateral on full-res luminance plus light chroma
smoothing, applied last.
"""

from __future__ import annotations

import cv2
import numpy as np

#: The one shared look. These constants were fitted on these same 16
#: unit-a photos against their MLS twins, and the report says so
#: plainly: they are frozen from this round on, and unit 5 measures the
#: same settings, unchanged, on Erik's home set as the honest held-out
#: test. Every photo gets the same constants; per-photo automatic
#: exposure and white balance adapt to the photo's own pixels only.
#: Processing never reads the photo's MLS twin: a new listing has no
#: MLS photo to copy.
#: Interior rooms finish bright and airy; exterior shots finish at their
#: own lower level, told apart by visible sky (a camera scene mode, not a
#: twin read).
#: 194, not the MLS center 187: large-window rooms meter bright glass
#: with the room, so they land ~15 levels under the anchor. 194 doubles
#: set 004's margin (176 at 193 left 0.4 points); set 008 keeps over two
#: points the other way.
INTERIOR_TARGET_MEDIAN = 194.0
SKY_FRACTION_CUT = 0.001
#: Exterior target scales with open sky, clipped to the range Erik's own
#: exterior finishes span: open sunny shots finish brighter, shaded ones
#: lower. Tuned once; the formula only reads the photo's own sky.
EXTERIOR_SKY_SLOPE = 240.0
EXTERIOR_BASE_MEDIAN = 111.0
EXTERIOR_MIN_MEDIAN = 108.0
EXTERIOR_MAX_MEDIAN = 144.0
#: Shadow lift through a blurred luminance mask, plus a gentle gamma for
#: the low-contrast HDR look. The automatic gain runs after the lift so
#: the class target is the final anchor. The highlight shoulder
#: compresses but never hides real clipping: a gain-scaled blown window
#: still reads at or above 250.
SHADOW_LIFT = 0.4
LOOK_GAMMA = 0.9
SHOULDER_SLOPE = 0.07
AUTO_GAIN_LO = 0.4
AUTO_GAIN_HI = 3.5
#: White balance reads the room without its brightest pixels (windows,
#: lamps), so daylight glass never votes on tungsten walls. Interiors
#: under artificial light correct hard; daylight exteriors keep their
#: scene palette with a light touch.
WB_BRIGHT_PERCENTILE = 90.0
WB_INTERIOR_STRENGTH = 0.95
WB_EXTERIOR_STRENGTH = 0.4
#: White-balance voters are room pixels below this saturation
#: (max-min)/max. Warm-lit whites read ~0.17-0.25, gray floors ~0.07,
#: wood 0.3 and up: the vote reads ceilings and trim, never wood.
WB_NEUTRAL_SAT = 0.25


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
        return min(
            EXTERIOR_MAX_MEDIAN,
            max(EXTERIOR_MIN_MEDIAN, EXTERIOR_BASE_MEDIAN + EXTERIOR_SKY_SLOPE * sky_fraction(img)),
        )
    return INTERIOR_TARGET_MEDIAN


def _apply_luminance_scale(work: np.ndarray, scale: np.ndarray) -> None:
    """Multiply every channel by one per-pixel factor, in place.

    The single rule every tone step obeys: the factor comes from
    luminance, and all three channels share it, so hue and saturation
    cannot change with brightness.
    """
    work *= scale[:, :, None]


def balance_exposure(
    img: np.ndarray,
    protect: np.ndarray | None = None,
    anchor_mask: np.ndarray | None = None,
) -> tuple[np.ndarray, dict]:
    """Balance a merged room photo. Returns (photo, report).

    One global white balance from the room's own below-bright pixels,
    then one shared tone pipeline applied to luminance only (shadow
    lift through a blurred luminance mask, a gentle gamma, one global
    exposure gain toward the shared class target, then a soft highlight
    shoulder). Pixels under protect keep their exact values. No MLS
    twin is read. No regional, positional or brightness-dependent color
    step exists: the only per-pixel differences are luminance scales
    shared by all three channels (contract 02 section C and final
    round).

    anchor_mask limits the gain anchor to the pixels that survive the
    final crop (undistort borders are dark and would drag the median
    under the target the shipped file is measured against).
    """
    scene = classify_scene(img)
    work = img.astype(np.float32)
    gray = _luminance(img)
    ceiling = float(np.percentile(gray, WB_BRIGHT_PERCENTILE))
    room = gray < ceiling
    if anchor_mask is not None:
        room = room & anchor_mask
    report: dict = {"white_balanced": False}
    # The vote reads neutral surfaces (low-saturation room pixels: white
    # ceilings, trim, gray floors): saturated wood must never set the
    # illuminant, or its vote flips shadowed floors blue. Too few
    # neutral pixels, and every room pixel votes instead.
    mx = work.max(axis=2)
    sat = (mx - work.min(axis=2)) / np.maximum(mx, 1.0)
    neutral = room & (sat < WB_NEUTRAL_SAT)
    voters = neutral if neutral.sum() > 1000 else room
    report["wb_voters"] = "neutral" if voters is neutral else "all-room"
    if voters.sum() > 1000:
        strength = WB_INTERIOR_STRENGTH if scene == "interior" else WB_EXTERIOR_STRENGTH
        means = np.array([work[:, :, c][voters].mean() for c in range(3)])
        target = float(means.mean())
        base = target / np.maximum(means, 1e-6)
        factors = 1.0 + strength * (base - 1.0)
        work *= factors
        report["white_balanced"] = True
        report["wb_factors"] = [round(float(f), 4) for f in factors]
    lum = cv2.cvtColor(np.clip(work, 0, 255).astype(np.uint8), cv2.COLOR_RGB2GRAY)
    blur = cv2.GaussianBlur(lum.astype(np.float32), (0, 0), max(img.shape) / 40.0)
    darkness = np.clip((120.0 - blur) / 120.0, 0.0, 1.0)
    shadow_gain = 1.0 + SHADOW_LIFT * darkness
    _apply_luminance_scale(work, shadow_gain)
    report["shadow_gain"] = round(float(shadow_gain.mean() - 1.0), 4)
    if LOOK_GAMMA != 1.0:
        lum = np.maximum(_luminance(np.clip(work, 0, 255).astype(np.uint8)), 1.0)
        _apply_luminance_scale(work, np.power(np.clip(lum / 255.0, 0.0, 1.0), LOOK_GAMMA - 1.0))
    # The gain runs after the tone work so the class target is the final
    # anchor: per-photo automatic exposure, still with no twin read.
    post = cv2.cvtColor(np.clip(work, 0, 255).astype(np.uint8), cv2.COLOR_RGB2GRAY)
    target = target_median(img)
    anchor = post[anchor_mask] if anchor_mask is not None else post.ravel()
    gain = min(AUTO_GAIN_HI, max(AUTO_GAIN_LO, target / max(1.0, float(np.median(anchor)))))
    work *= gain
    report["auto_gain"] = round(gain, 4)
    report["scene"] = scene
    # Highlight shoulder runs last so no earlier gain can re-blow whites.
    # Luminance-only like every tone step: over-bright luminance
    # compresses toward 235 while every pixel keeps its chromaticity.
    # Luminance reads the unclipped float work: the uint8 frame hides
    # real blowout in the hundreds, and a scale built from it would
    # leave those pixels blown.
    lum = (0.299 * work[:, :, 0] + 0.587 * work[:, :, 1] + 0.114 * work[:, :, 2]).astype(np.float32)
    over = lum > 235.0
    if over.any():
        compressed = 235.0 + (lum - 235.0) * SHOULDER_SLOPE
        scale = np.ones_like(lum)
        scale[over] = compressed[over] / np.maximum(lum[over], 1.0)
        _apply_luminance_scale(work, scale)
    out = np.clip(work, 0, 255).astype(np.uint8)
    if protect is not None:
        out[protect] = img[protect]
    return out, report


def flat_patch_mask(img: np.ndarray) -> np.ndarray:
    """Dark flat pixels of one image: the patch set both noise readings share."""
    gray = _luminance(img)
    dark = gray < np.percentile(gray, 25)
    lap = cv2.Laplacian(gray, cv2.CV_32F)
    flat = dark & (cv2.GaussianBlur(np.abs(lap), (0, 0), 2) < 3.0)
    if flat.sum() < 100:
        flat = dark
    if flat.sum() == 0:
        # Uniform image: no pixel is below the percentile, and the noise
        # is zero everywhere, so every pixel is a fair patch.
        flat = np.ones(gray.shape, bool)
    return flat


def flat_noise(img: np.ndarray, mask: np.ndarray | None = None) -> float:
    """Noise level: std of the Laplacian over dark flat patches.

    With mask, the caller's patch set (picked on the before image), so
    before and after measure the same pixels. Without, the image picks
    its own patches, which must never compare across different images.
    """
    gray = _luminance(img)
    lap = cv2.Laplacian(gray, cv2.CV_32F)
    flat = mask if mask is not None else flat_patch_mask(img)
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
