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
#: 194, not the MLS center 187: the window pull swaps in darker real
#: view pixels after the gain anchors, so large-window rooms land ~15
#: levels under the anchor. 194 doubles set 004's margin (176 at 193
#: left 0.4 points); set 008 keeps over two points the other way.
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


def balance_exposure(
    img: np.ndarray,
    protect: np.ndarray | None = None,
    anchor_mask: np.ndarray | None = None,
    return_preshoulder: bool = False,
) -> tuple[np.ndarray, dict] | tuple[np.ndarray, dict, np.ndarray]:
    """Balance a merged room photo. Returns (photo, report).

    White balance from the room's own below-bright pixels, shadow lift
    through a blurred luminance mask, automatic gain toward the shared
    class target (bounded), then a soft highlight shoulder. Pixels under
    protect keep their exact values. No MLS twin is read. Every step is
    global and smooth: no spatial box or zone anywhere, so no regional
    correction can leave a visible boundary (contract 02 section C).

    anchor_mask limits the gain anchor to the pixels that survive the
    final crop (undistort borders are dark and would drag the median
    under the target the shipped file is measured against).

    With return_preshoulder, also returns the balanced photo from just
    before the shoulder: the shoulder parks blown glass under the
    near-white level, so honest highlight numbers are read there.
    """
    scene = classify_scene(img)
    work = img.astype(np.float32)
    gray = _luminance(img)
    ceiling = float(np.percentile(gray, WB_BRIGHT_PERCENTILE))
    room = gray < ceiling
    if anchor_mask is not None:
        room = room & anchor_mask
    report: dict = {"white_balanced": False}
    if room.sum() > 1000:
        strength = WB_INTERIOR_STRENGTH if scene == "interior" else WB_EXTERIOR_STRENGTH
        means = np.array([work[:, :, c][room].mean() for c in range(3)])
        target = float(means.mean())
        base = target / np.maximum(means, 1e-6)
        factors = 1.0 + strength * (base - 1.0)
        pre = work.copy()
        work *= factors
        # Daylight-spill guard, interiors only: the vote reads
        # tungsten-lit walls, and its cooling is right for them, but
        # daylight spilling across floors near windows is already
        # neutral, so full cooling turns it blue. Bright low-saturation
        # pixels keep their own chromaticity in proportion: tungsten
        # walls and ceilings are saturated or dim and keep the full vote.
        # Exterior daylight needs no tungsten vote, so the guard stays
        # off there. Anchors are the photo's own percentiles, and the
        # look targets below do not move.
        if scene == "interior":
            gray_pre = pre.mean(axis=2)
            mx = pre.max(axis=2)
            lowsat = 1.0 - (mx - pre.min(axis=2)) / np.maximum(mx, 1.0)
            room_gray = gray_pre[room]
            p50 = float(np.median(room_gray))
            p90 = float(np.percentile(room_gray, 90.0))
            bright = np.clip((gray_pre - p50) / max(1.0, p90 - p50), 0.0, 1.0)
            guard = (lowsat * lowsat * bright)[:, :, None].astype(np.float32)
            work = work * (1.0 - guard) + pre * guard
            report["spill_guard"] = round(float(guard.mean()), 4)
        else:
            report["spill_guard"] = 0.0
        report["white_balanced"] = True
    lifted_gray = cv2.cvtColor(np.clip(work, 0, 255).astype(np.uint8), cv2.COLOR_RGB2GRAY)
    blur = cv2.GaussianBlur(lifted_gray.astype(np.float32), (0, 0), max(img.shape) / 40.0)
    darkness = np.clip((120.0 - blur) / 120.0, 0.0, 1.0)
    shadow_gain = 1.0 + SHADOW_LIFT * darkness
    work *= shadow_gain[:, :, None]
    report["shadow_gain"] = round(float(shadow_gain.mean() - 1.0), 4)
    if LOOK_GAMMA != 1.0:
        work = 255.0 * np.power(np.clip(work / 255.0, 0.0, 1.0), LOOK_GAMMA)
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
    # It compresses but never hides real clipping from honest numbers:
    # moderately blown glass parks just under the near-white level, so
    # the pre-shoulder frame (unclipped float: real blowout reads in the
    # hundreds) is the one the highlights check reads.
    preshoulder = work.copy()
    over = work > 235.0
    work[over] = 235.0 + (work[over] - 235.0) * SHOULDER_SLOPE
    out = np.clip(work, 0, 255).astype(np.uint8)
    if protect is not None:
        out[protect] = img[protect]
    if return_preshoulder:
        if protect is not None:
            preshoulder[protect] = img[protect].astype(np.float32)
        return out, report, preshoulder
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
