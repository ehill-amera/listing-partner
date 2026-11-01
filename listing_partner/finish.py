"""Exposure balance and denoising (unit 2, steps C and D). Local only.

White balance is not here: it runs at raw decode, in linear light, one
set of multipliers per set (hdr.estimate_set_wb, contract 02, final round
part three). Balance is one global exposure gain per photo and one shared
tone pipeline applied to luminance only: every tone step multiplies all
three channels by the same per-pixel factor derived from luminance, so
hue and saturation never change with brightness. The one color step allowed
(final round part two) is a smooth highlight roll-off toward neutral, with
two triggers: pixels clipped in the merge, anywhere; and, in interiors only,
cool bright window views, inside confirmed window masks and nowhere else.
That second trigger is the one regional color step: it fades to zero at the
mask edge, and its color step across that edge is measured per photo
(contract 02, criterion 14). Outside the masks it never fires.
Denoise is edge-preserving bilateral on full-res luminance plus light
chroma smoothing, applied last.
"""

from __future__ import annotations

import cv2
import numpy as np

#: The one shared look. These constants were refitted in the final
#: round, part three (Oct 31), on these same 16 unit-a photos against
#: their MLS twins, and the report says so plainly: one set of raw-decode
#: white-balance multipliers per set, one global exposure gain per photo,
#: one luminance-only shared tone curve. They are frozen from this round
#: on, and unit 5 measures the same settings, unchanged, on Erik's home
#: set as the honest held-out test. Every photo gets the same constants;
#: per-set white balance and per-photo exposure adapt to that set's own
#: pixels only. Processing never reads the photo's MLS twin: a new listing
#: has no MLS photo to copy.
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
#: the class target is the final anchor. The highlight shoulder acts on
#: each pixel's peak channel and scales all three channels by one factor,
#: so no channel clips alone and a wall keeps its chromaticity: linear up
#: to the knee, then a smooth approach to the ceiling (rebuilt after the
#: review of 970ce8f, whose near-flat luminance shoulder wiped wall detail).
#: A gain-scaled blown window still reads at or above 250.
SHADOW_LIFT = 0.4
LOOK_GAMMA = 0.9
SHOULDER_KNEE = 190.0
SHOULDER_CEILING = 265.0
AUTO_GAIN_LO = 0.4
AUTO_GAIN_HI = 3.5
#: White balance at raw decode (contract 02, final round part three).
#: Interiors take the room's whole-frame linear average as neutral, then
#: this one shared tint keeps the slight warmth of Erik's finishes (R up
#: and B down, multiplying the neutral estimate). Exteriors sit between
#: the camera's as-shot daylight (0) and that neutral estimate (1): grass
#: and sky are not neutral surfaces, so they only lean toward it.
WB_INTERIOR_TINT_R = 1.08
WB_INTERIOR_TINT_B = 0.94
WB_EXTERIOR_STRENGTH = 0.5
#: Highlight roll-off toward neutral (contract 02, final round part two;
#: rebuilt after the reviews of 970ce8f and 7ee0217). Two triggers:
#: - Clipped in the merge: any hue, read from the merge's own peak channel,
#:   before tone and gain.
#: - Cool and bright, interiors only, inside confirmed window masks only:
#:   window views under indoor white balance read cyan. Coolness is
#:   (B - R) / peak and brightness is the peak after gain. The per-pixel
#:   version of this gate reached floors and baseboards, because merge floors
#:   and trim sit right at its threshold (7ee0217: up to 7.30% of the frame
#:   outside windows), and it flipped between neighboring pixels. So the
#:   per-pixel gate now only votes: its mean over the photo's masks picks one
#:   strength for every view in the photo, and every view pixel gets it,
#:   whatever its own color. That leaves no gray-white patch inside a view,
#:   only a paler view. The strength fades in from zero at the mask edge.
#:   Cool floors and trim outside the masks keep their cast. Exterior sky is
#:   real and keeps its blue.
ROLL_CLIP_START = 235.0
ROLL_CLIP_FULL = 252.0
ROLL_COOL_PEAK_START = 200.0
ROLL_COOL_PEAK_FULL = 280.0
ROLL_COOL_START = 0.05
ROLL_COOL_FULL = 0.15
ROLL_COOL_VIEW_START = 0.02
ROLL_COOL_VIEW_FULL = 0.10
ROLL_COOL_STRENGTH = 0.8
#: Feather width inside the mask, as a fraction of the frame's long side:
#: about 60 px on these photos.
ROLL_COOL_FEATHER_FRAC = 0.01


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


def target_median(img: np.ndarray, scene: str | None = None, sky: float | None = None) -> float:
    """The shared brightness target for this photo's scene class.

    scene and sky come from the set's as-shot merge when the caller has
    them: a white-balanced interior's window reads blue, and reading the
    sky test off that photo would aim the room at the exterior target.
    """
    scene = scene if scene is not None else classify_scene(img)
    if scene == "exterior":
        sky = sky if sky is not None else sky_fraction(img)
        return min(
            EXTERIOR_MAX_MEDIAN,
            max(EXTERIOR_MIN_MEDIAN, EXTERIOR_BASE_MEDIAN + EXTERIOR_SKY_SLOPE * sky),
        )
    return INTERIOR_TARGET_MEDIAN


def _smoothstep(value: np.ndarray, start: float, full: float) -> np.ndarray:
    ramp = np.clip((value - start) / (full - start), 0.0, 1.0)
    return ramp * ramp * (3.0 - 2.0 * ramp)


def _mask_feather(window_mask: np.ndarray) -> np.ndarray:
    """1 well inside the mask, a smooth fade to 0 at its edge, exactly 0 outside."""
    distance = cv2.distanceTransform(window_mask.astype(np.uint8), cv2.DIST_L2, 5)
    return _smoothstep(distance, 0.0, ROLL_COOL_FEATHER_FRAC * max(window_mask.shape))


def _cool_view_gate(work: np.ndarray, gain: float, window_mask: np.ndarray) -> np.ndarray:
    """The cool trigger: one strength for the photo's views, feathered, zero outside."""
    out = work[window_mask] * gain
    peak = np.maximum(out.max(axis=1), 1e-3)
    votes = _smoothstep((out[:, 2] - out[:, 0]) / peak, ROLL_COOL_START, ROLL_COOL_FULL)
    votes = votes * _smoothstep(peak, ROLL_COOL_PEAK_START, ROLL_COOL_PEAK_FULL)
    view = _smoothstep(np.array(votes.mean()), ROLL_COOL_VIEW_START, ROLL_COOL_VIEW_FULL)
    return ROLL_COOL_STRENGTH * float(view) * _mask_feather(window_mask)


def feather_color_step(delta_lab: np.ndarray, gate: np.ndarray) -> tuple[float, float]:
    """Largest a* and b* step the regional correction makes across its edge.

    delta_lab is the photo with the correction minus the photo without it. Its
    mean is read in rings of equal gate strength from outside the mask to its
    core, so the scene's own detail averages out and only the correction's step
    remains. A hard edge shows as one big step between the outermost rings.
    """
    if not (gate > 0).any():
        return 0.0, 0.0
    # Ring zero is every pixel the gate never reaches.
    rings = np.ceil(gate / max(float(gate.max()), 1e-6) * 40.0).astype(np.int32).ravel()
    counts = np.bincount(rings, minlength=41).astype(np.float64)
    present = counts > 0
    steps = []
    for channel in (1, 2):
        total = np.bincount(rings, delta_lab[:, :, channel].ravel(), minlength=41)
        means = total[present] / counts[present]
        steps.append(float(np.abs(np.diff(means)).max()))
    return steps[0], steps[1]


def _highlight_tail(
    work: np.ndarray, clip_gate: np.ndarray, gain: float, cool_gate: np.ndarray | None = None
) -> np.ndarray:
    """Gain, the roll-off toward neutral, then the shoulder. Returns float RGB."""
    out = work * gain
    blend = clip_gate if cool_gate is None else 1.0 - (1.0 - clip_gate) * (1.0 - cool_gate)
    lum = 0.299 * out[:, :, 0] + 0.587 * out[:, :, 1] + 0.114 * out[:, :, 2]
    out = out + blend[:, :, None] * (lum[:, :, None] - out)
    # One factor per pixel from its peak channel: below the knee nothing
    # moves, above it the curve meets the knee with slope 1 and flattens
    # gradually, so no edge and no channel clipping alone.
    peak = np.maximum(out.max(axis=2), 1e-3)
    span = SHOULDER_CEILING - SHOULDER_KNEE
    excess = np.maximum(peak - SHOULDER_KNEE, 0.0) / span
    mapped = SHOULDER_KNEE + span * excess / (1.0 + excess)
    return out * (np.where(peak > SHOULDER_KNEE, mapped, peak) / peak)[:, :, None]


def _solve_gain(
    work: np.ndarray,
    clip_gate: np.ndarray,
    target: float,
    anchor_mask: np.ndarray | None,
) -> float:
    """The gain that lands the anchor pixels' median luminance on target.

    The shoulder moves bright medians, so the anchor reads after it. Solved
    on a regular sample of the frame; the gain limits still apply. The cool
    trigger stays out of this solve, so the window masks cannot move the gain
    and every pixel outside them comes out the same with or without them.
    """
    step = max(1, max(work.shape[:2]) // 1000)
    sample = work[::step, ::step]
    gate = clip_gate[::step, ::step]
    keep = None if anchor_mask is None else anchor_mask[::step, ::step]
    low, high = AUTO_GAIN_LO, AUTO_GAIN_HI
    for _ in range(14):
        gain = (low + high) / 2.0
        out = np.clip(_highlight_tail(sample, gate, gain), 0.0, 255.0)
        lum = 0.299 * out[:, :, 0] + 0.587 * out[:, :, 1] + 0.114 * out[:, :, 2]
        median = float(np.median(lum if keep is None else lum[keep]))
        if median < target:
            low = gain
        else:
            high = gain
    return (low + high) / 2.0


def _cool_gate_report(
    gate: np.ndarray | None, window_mask: np.ndarray | None, plain: np.ndarray, final: np.ndarray
) -> dict:
    """The cool trigger's reach, read from the gate this photo really used."""
    if gate is None:
        return {"frame_pct": 0.0, "window_pct": 0.0, "outside_pct": 0.0, "strength": 0.0}
    on = gate > 0.5
    delta = cv2.cvtColor(
        np.clip(final, 0, 255).astype(np.float32) / 255.0, cv2.COLOR_RGB2LAB
    ) - cv2.cvtColor(np.clip(plain, 0, 255).astype(np.float32) / 255.0, cv2.COLOR_RGB2LAB)
    step_a, step_b = feather_color_step(delta, gate)
    return {
        "frame_pct": round(100.0 * float(on.mean()), 2),
        "window_pct": round(100.0 * float(on[window_mask].mean()), 2),
        "outside_pct": round(100.0 * float((gate[~window_mask] > 0).mean()), 2),
        "strength": round(float(gate.max()), 3),
        "edge_step_a": round(step_a, 3),
        "edge_step_b": round(step_b, 3),
    }


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
    scene: str | None = None,
    sky: float | None = None,
    window_mask: np.ndarray | None = None,
) -> tuple[np.ndarray, dict]:
    """Balance a merged room photo. Returns (photo, report).

    One shared tone pipeline applied to luminance only (shadow lift
    through a blurred luminance mask, a gentle gamma, one global exposure
    gain toward the shared class target, then a soft highlight shoulder),
    plus the single allowed brightness-dependent color step: a smooth
    highlight roll-off toward neutral (see the ROLL constants). White balance already
    happened at raw decode. Pixels under protect keep their exact values. No MLS
    twin is read. The only regional color step is the cool trigger, confined to
    window_mask (the photo's confirmed window glass, all windows together). With
    no mask, or on an exterior, it does not exist.

    anchor_mask limits the gain anchor to the pixels that survive the
    final crop (undistort borders are dark and would drag the median
    under the target the shipped file is measured against).

    scene and sky are the set's own, read from its as-shot merge (see
    target_median); without them the photo itself is read.
    """
    scene = scene if scene is not None else classify_scene(img)
    work = img.astype(np.float32)
    report: dict = {}
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
    # The clip gate reads the merge itself, before any tone step or gain.
    target = target_median(img, scene=scene, sky=sky)
    clip_gate = _smoothstep(img.max(axis=2).astype(np.float32), ROLL_CLIP_START, ROLL_CLIP_FULL)
    gain = _solve_gain(work, clip_gate, target, anchor_mask)
    report["auto_gain"] = round(gain, 4)
    report["scene"] = scene
    if window_mask is not None and window_mask.shape != img.shape[:2]:
        raise ValueError(f"window mask is {window_mask.shape}, photo is {img.shape[:2]}")
    gate = None
    if scene == "interior" and window_mask is not None and window_mask.any():
        gate = _cool_view_gate(work, gain, window_mask)
    plain = _highlight_tail(work, clip_gate, gain)
    work = plain if gate is None else _highlight_tail(work, clip_gate, gain, gate)
    report["cool_gate"] = _cool_gate_report(gate, window_mask, plain, work)
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
    soft_y = cv2.bilateralFilter(y, 5, 12, 15)
    soft_cr = cv2.GaussianBlur(cr, (0, 0), 1.0)
    soft_cb = cv2.GaussianBlur(cb, (0, 0), 1.0)
    return cv2.cvtColor(cv2.merge([soft_y, soft_cr, soft_cb]), cv2.COLOR_YCrCb2RGB)
