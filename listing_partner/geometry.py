"""Lens and geometry correction (unit 2, step A0). Local only, no network.

Distortion and TCA come from the vendored lensfun profile in
``lens_data/`` (CC BY-SA 3.0, see ATTRIBUTION.md there). The correction
math reimplements the published lensfun formulas: the ptlens forward model
maps undistorted radius to distorted radius, so undistortion samples the
input at the forwarded position directly. Coordinates are normalized by the
half-diagonal (r = 1 at the image corners). The lensfun focal-length
rescale is skipped on purpose: calibration and unit-a bodies are both DX,
so it is within 3 percent, and line straightness is measured on the real
photos instead of assumed.
"""

from __future__ import annotations

from pathlib import Path
from xml.etree import ElementTree

import cv2
import exifread
import numpy as np

DATA_DIR = Path(__file__).resolve().parent / "lens_data"
PROFILE_PATH = DATA_DIR / "nikon-af-p-dx-10-20mm.xml"

# Unit-a's measured lens identity (from the NEFs' own MakerNote data):
# 10-20mm, f/4.5-5.6, G/D/VR type bits, on a NIKON D5500.
UNIT_A_LENS = {
    "maker": "NIKON CORPORATION",
    "model": "NIKON D5500",
    "focal_min": 10.0,
    "focal_max": 20.0,
    "aperture_min": 4.5,
    "aperture_max": 5.6,
}


def ptlens_forward(r, a: float, b: float, c: float):
    """Distorted radius for an undistorted radius (ptlens forward model)."""
    d = 1.0 - a - b - c
    r = np.asarray(r, dtype=np.float64)
    return r * (a * r**3 + b * r**2 + c * r + d)


def _newton_undistort(rd: np.ndarray, a: float, b: float, c: float) -> np.ndarray:
    """Undistorted radius for a distorted radius (Newton, like lensfun)."""
    d = 1.0 - a - b - c
    ru = rd.copy()
    for _ in range(6):
        f = ru * (a * ru**3 + b * ru**2 + c * ru + d) - rd
        fp = 4 * a * ru**3 + 3 * b * ru**2 + 2 * c * ru + d
        ru = ru - f / np.where(fp == 0, 1.0, fp)
    return ru


def _norm_grids(h: int, w: int):
    half_diag = float(np.hypot(h, w)) / 2.0
    ys, xs = np.mgrid[0:h, 0:w].astype(np.float64)
    return (xs - (w - 1) / 2.0) / half_diag, (ys - (h - 1) / 2.0) / half_diag


def _remap(img: np.ndarray, map_x: np.ndarray, map_y: np.ndarray) -> np.ndarray:
    return cv2.remap(img, map_x.astype(np.float32), map_y.astype(np.float32), cv2.INTER_LINEAR)


def calibration_math(
    profile: ElementTree.Element, focal: float, w: int, h: int, crop: float = 1.5
) -> tuple[tuple[float, float, float], float]:
    """Rescaled ptlens coefficients plus pixels-per-unit, lensfun's way.

    Coefficient rescale (focal-length preserving) and pixel normalization
    follow lensfun's mod-coord.cpp and modifier.cpp: the hugin scale comes
    from the calibration body's crop factor, and NormScale from this
    image's crop, size and focal length. Same DX crop both sides, so the
    rescale is small, but the units (not half-diagonal) are what make the
    calibrated curve land on the right pixels.
    """
    import math

    a, b, c = distortion_params(profile, focal)
    calib_crop = float(profile.findtext("cropfactor"))
    aspect = 1.5  # calibration body shoots 3:2 stills; the profile names none
    hugin_mm = math.hypot(36.0, 24.0) / calib_crop / math.hypot(aspect, 1) / 2.0
    s = focal / hugin_mm
    d = 1.0 - a - b - c
    rescaled = (a * s**3 / d**4, b * s**2 / d**3, c * s / d**2)
    norm_px = crop * math.hypot(w + 1.0, h + 1.0) * focal / math.hypot(36.0, 24.0)
    return rescaled, norm_px


def _pixel_grids_norm(h: int, w: int, norm_px: float):
    ys, xs = np.mgrid[0:h, 0:w].astype(np.float64)
    return (xs - (w - 1) / 2.0) / norm_px, (ys - (h - 1) / 2.0) / norm_px


def apply_forward_distortion(img: np.ndarray, a: float, b: float, c: float) -> np.ndarray:
    """Synthesize distortion: distorted(p_d) = clean(p_u), p_d = F(p_u)."""
    h, w = img.shape[:2]
    xn, yn = _norm_grids(h, w)
    rd = np.sqrt(xn**2 + yn**2)
    ru = _newton_undistort(rd, a, b, c)
    scale = np.divide(ru, rd, out=np.ones_like(ru), where=rd > 1e-9)
    half_diag = float(np.hypot(h, w)) / 2.0
    map_x = (xn * scale) * half_diag + (w - 1) / 2.0
    map_y = (yn * scale) * half_diag + (h - 1) / 2.0
    return _remap(img, map_x, map_y)


def undistort_image(img: np.ndarray, a: float, b: float, c: float) -> np.ndarray:
    """Remove barrel/pincushion distortion by direct inverse mapping.

    Coordinates normalized by the half-diagonal; used with raw calibrated
    coefficients in tests. Production uses correct_distortion below.
    """
    h, w = img.shape[:2]
    xn, yn = _norm_grids(h, w)
    ru = np.sqrt(xn**2 + yn**2)
    rd = ptlens_forward(ru, a, b, c)
    scale = np.divide(rd, ru, out=np.ones_like(rd), where=ru > 1e-9)
    half_diag = float(np.hypot(h, w)) / 2.0
    map_x = (xn * scale) * half_diag + (w - 1) / 2.0
    map_y = (yn * scale) * half_diag + (h - 1) / 2.0
    return _remap(img, map_x, map_y)


def _displacement_field(
    profile: ElementTree.Element, focal: float, w: int, h: int, crop: float = 1.5
):
    """Faithful-chain sample offsets (dx, dy) in pixels at full strength."""
    (a, b, c), norm_px = calibration_math(profile, focal, w, h, crop)
    xn, yn = _pixel_grids_norm(h, w, norm_px)
    ru = np.sqrt(xn**2 + yn**2)
    rd = ru * (a * ru**3 + b * ru**2 + c * ru + 1.0)
    scale = np.divide(rd, ru, out=np.ones_like(rd), where=ru > 1e-9)
    return (xn * scale - xn) * norm_px, (yn * scale - yn) * norm_px


def _apply_field(img: np.ndarray, dx, dy, strength: float) -> np.ndarray:
    h, w = img.shape[:2]
    ys, xs = np.mgrid[0:h, 0:w].astype(np.float32)
    return cv2.remap(
        img,
        (xs + strength * dx).astype(np.float32),
        (ys + strength * dy).astype(np.float32),
        cv2.INTER_LINEAR,
    )


def top_line_length(gray: np.ndarray, width: int = 1500) -> float:
    """Mean length of the 20 longest LSD segments at review size.

    Downsampling both sides equally washes out resampling-softness
    differences, so this compares geometry, not sharpness. Higher is
    straighter.
    """
    h, w = gray.shape
    small = cv2.resize(gray, (width, int(round(h * width / w))), interpolation=cv2.INTER_AREA)
    segs = cv2.createLineSegmentDetector().detect(small)[0]
    if segs is None or len(segs) < 20:
        return 0.0
    lengths = np.hypot(segs[:, 2] - segs[:, 0], segs[:, 3] - segs[:, 1])
    return float(np.sort(lengths)[-20:].mean())


STRENGTH_GRID = (0.0, 0.25, 0.5, 0.75, 1.0)


def fit_strength(
    gray: np.ndarray, profile: ElementTree.Element, focal: float, crop: float = 1.5
) -> float:
    """Correction strength the photos themselves want, 0 to 1.

    The profile fixes the bend shape; focus distance and sample variation
    move its strength, so the strength is fitted per photo on a small copy
    by sweeping the faithful displacement field. Returns the argmax; the
    grid includes 0, so fitting can only decline the step, never worsen it.
    """
    h, w = gray.shape
    # Native-resolution center crop: no resampling anywhere in the fit, so
    # the fitted strength applies at full frame without a scale shift.
    cw, ch = min(2000, w), min(1333, h)
    x0, y0 = (w - cw) // 2, (h - ch) // 2
    small = gray[y0 : y0 + ch, x0 : x0 + cw]
    dx_full, dy_full = _displacement_field(profile, focal, w, h, crop)
    dx = dx_full[y0 : y0 + ch, x0 : x0 + cw]
    dy = dy_full[y0 : y0 + ch, x0 : x0 + cw]
    small_rgb = cv2.cvtColor(small, cv2.COLOR_GRAY2RGB)
    best_k, best_score = 0.0, top_line_length(small)
    for k in STRENGTH_GRID[1:]:
        score = top_line_length(
            cv2.cvtColor(_apply_field(small_rgb, dx, dy, k), cv2.COLOR_RGB2GRAY)
        )
        if score > best_score:
            best_k, best_score = k, score
    return best_k


def correct_distortion(
    img: np.ndarray,
    profile: ElementTree.Element,
    focal: float,
    crop: float = 1.5,
    strength: float | None = None,
) -> tuple[np.ndarray, float]:
    """Undistort, fitting strength from the photo unless given.

    Returns the corrected image and the applied strength (0 means the
    photos voted the step down: returned uncorrected, and the caller says
    so on the review page).
    """
    h, w = img.shape[:2]
    gray = img if img.ndim == 2 else cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
    if strength is None:
        strength = fit_strength(gray, profile, focal, crop)
    if strength <= 0.0:
        return img, 0.0
    dx, dy = _displacement_field(profile, focal, w, h, crop)
    return _apply_field(img, dx, dy, strength), strength


def line_residual(gray: np.ndarray) -> float:
    """Mean RMS distance of edge pixels from their global straight lines.

    Standard-Hough peaks give one infinite line per dominant edge; edge
    pixels near each line are scored by RMS perpendicular distance. Bent
    lines smear across the peak line and score higher; straight lines score
    near the pixel floor. Lower is straighter: correction must lower this.
    """
    edges = cv2.Canny(gray, 50, 150)
    lines = cv2.HoughLines(edges, 1, np.pi / 180, int(0.08 * max(gray.shape)))
    if lines is None:
        return 0.0
    ys, xs = np.nonzero(edges)
    xs = xs.astype(np.float64)
    ys = ys.astype(np.float64)
    residuals = []
    for rho, theta in lines[:30].reshape(-1, 2):
        dist = np.abs(xs * np.cos(theta) + ys * np.sin(theta) - rho)
        near = dist < 3.0
        if near.sum() > 50:
            residuals.append(float(np.sqrt((dist[near] ** 2).mean())))
    if not residuals:
        return 0.0
    return float(sum(residuals) / len(residuals))


def load_profile(path: Path = PROFILE_PATH) -> ElementTree.Element:
    """Parse the vendored lensfun lens node."""
    return ElementTree.parse(path).getroot().find("lens")


def match_profile(identity: dict) -> ElementTree.Element | None:
    """The vendored profile, or None when the lens does not match it.

    Match is by measured EXIF identity (Nikon body, 10-20mm f/4.5-5.6):
    anything else means no profile, and the caller skips the step.
    """
    if (
        identity.get("maker") == UNIT_A_LENS["maker"]
        and identity.get("focal_min") == UNIT_A_LENS["focal_min"]
        and identity.get("focal_max") == UNIT_A_LENS["focal_max"]
        and identity.get("aperture_min") == UNIT_A_LENS["aperture_min"]
        and identity.get("aperture_max") == UNIT_A_LENS["aperture_max"]
    ):
        return load_profile()
    return None


def _bracket(rows: list, focal: float):
    focals = [float(r.get("focal")) for r in rows]
    if focal < min(focals) or focal > max(focals):
        return None
    lo = max(f for f in focals if f <= focal)
    hi = min(f for f in focals if f >= focal)
    if lo == hi:
        return 0.0, rows[focals.index(lo)], rows[focals.index(lo)]
    t = (focal - lo) / (hi - lo)
    return t, rows[focals.index(lo)], rows[focals.index(hi)]


def distortion_params(profile: ElementTree.Element, focal: float) -> tuple | None:
    """Interpolated (a, b, c) at this focal length, or None outside range."""
    rows = [r for r in profile.find("calibration").findall("distortion")]
    found = _bracket(rows, focal)
    if found is None:
        return None
    t, lo, hi = found
    return tuple((1 - t) * float(lo.get(k)) + t * float(hi.get(k)) for k in ("a", "b", "c"))


def vignetting_params(profile: ElementTree.Element, focal: float) -> dict | None:
    """Vignetting model at this focal length, or None when the profile
    carries none. The vendored 10-20mm node ships distortion and TCA
    only, so unit-a skips this step and says so on the review page."""
    rows = profile.find("calibration").findall("vignetting")
    if not rows:
        return None
    found = _bracket([{"focal": r.get("focal"), **r.attrib} for r in rows], focal)
    return found


def tca_params(profile: ElementTree.Element, focal: float) -> dict | None:
    """Interpolated TCA scales at this focal length, or None outside range."""
    rows = [r for r in profile.find("calibration").findall("tca")]
    found = _bracket(rows, focal)
    if found is None:
        return None
    t, lo, hi = found

    def _mix(key: str) -> float:
        return (1 - t) * float(lo.get(key, 1.0)) + t * float(hi.get(key, 1.0))

    return {"br": _mix("br"), "vr": _mix("vr"), "bb": _mix("bb"), "vb": _mix("vb")}


def correct_tca(img: np.ndarray, tca: dict) -> np.ndarray:
    """Scale red and blue channels about the center (lateral CA only)."""
    h, w = img.shape[:2]
    xn, yn = _norm_grids(h, w)
    ru = np.sqrt(xn**2 + yn**2)
    half_diag = float(np.hypot(h, w)) / 2.0
    out = img.copy()
    for channel, b_, v_ in ((0, tca["bb"], tca["vb"]), (2, tca["br"], tca["vr"])):
        rd = ru * (b_ * ru**2 + v_)
        scale = np.divide(rd, ru, out=np.ones_like(rd), where=ru > 1e-9)
        map_x = (xn * scale) * half_diag + (w - 1) / 2.0
        map_y = (yn * scale) * half_diag + (h - 1) / 2.0
        out[:, :, channel] = _remap(img[:, :, channel], map_x, map_y)
    return out


def read_focal(path) -> float | None:
    """Focal length in mm from EXIF, fast path without MakerNote decoding."""
    with open(path, "rb") as handle:
        tags = exifread.process_file(handle, details=False)
    tag = tags.get("EXIF FocalLength")
    if tag is None:
        return None
    try:
        return float(tag.values[0])
    except (TypeError, ValueError, ZeroDivisionError, IndexError):
        return None


def read_lens_identity(path) -> dict:
    """Measured lens identity from a raw file's own metadata."""
    with open(path, "rb") as handle:
        tags = exifread.process_file(handle, details=True)
    focal = tags.get("EXIF FocalLength")

    def _num(tag, default=None):
        if tag is None:
            return default
        try:
            return float(tag.values[0]) if len(tag.values) == 1 else float(tag.values[0])
        except (TypeError, ValueError, ZeroDivisionError):
            return default

    mm = tags.get("MakerNote LensMinMaxFocalMaxAperture")
    identity = {
        "maker": str(tags.get("Image Make", "")),
        "model": str(tags.get("Image Model", "")),
        "focal": _num(focal),
    }
    if mm is not None and len(mm.values) == 4:
        try:
            identity["focal_min"] = float(mm.values[0])
            identity["focal_max"] = float(mm.values[1])
            identity["aperture_min"] = float(mm.values[2])
            identity["aperture_max"] = float(mm.values[3])
        except (TypeError, ValueError, ZeroDivisionError):
            pass
    return identity


def rotate_image(img: np.ndarray, angle_deg: float) -> tuple[np.ndarray, float]:
    """Rotate by angle_deg (positive tips the top to the right)."""
    h, w = img.shape[:2]
    matrix = cv2.getRotationMatrix2D(((w - 1) / 2.0, (h - 1) / 2.0), -angle_deg, 1.0)
    return cv2.warpAffine(img, matrix, (w, h), flags=cv2.INTER_LINEAR), angle_deg


#: Detection runs at this width: full-res interiors carry long structural
#: lines, but the old full-res minimum (a fifth of the long side) missed
#: every door frame in unit-a. Review size keeps them whole.
VERT_REVIEW_WIDTH = 1200
#: Near-vertical window, histogram bin, minimum peak share and minimum
#: total near-vertical length (as a fraction of the long side). Below any
#: of them the photo votes unknown, never level.
VERT_ANGLE_WINDOW = 10.0
VERT_BIN_DEG = 0.5
#: A real plurality of the length-squared evidence agrees on the peak:
#: unit-a interiors put 32-100% there (runner-up half that or less),
#: wooded lots scatter 19-25% across leaning trunks.
VERT_MIN_PEAK_SHARE = 0.30
VERT_MIN_TOTAL_FRAC = 0.3


def _near_vertical_segments(gray: np.ndarray) -> list[tuple[float, float]]:
    """(angle_deg, length) of near-vertical segments at review size."""
    h, w = gray.shape
    scale = VERT_REVIEW_WIDTH / max(h, w)
    if scale < 1.0:
        small = cv2.resize(
            gray,
            (int(round(w * scale)), int(round(h * scale))),
            interpolation=cv2.INTER_AREA,
        )
    else:
        small = gray
    edges = cv2.Canny(small, 50, 150)
    segs = cv2.HoughLinesP(
        edges,
        1,
        np.pi / 180,
        30,
        minLineLength=0.05 * max(small.shape),
        maxLineGap=10,
    )
    found = []
    if segs is None:
        return found
    for x1, y1, x2, y2 in segs.reshape(-1, 4):
        dx, dy = float(x2 - x1), float(y2 - y1)
        angle = float(np.degrees(np.arctan2(dx, -dy)))
        if abs(angle) <= VERT_ANGLE_WINDOW:
            found.append((angle, float(np.hypot(dx, dy))))
    return found


def dominant_vertical_angle(gray: np.ndarray) -> float | None:
    """Tilt of near-vertical lines in degrees (positive tips right).

    Length-squared voting over a histogram peak, so one long door frame
    outvotes scattered short edges (and leaning trees lose to agreeing
    walls). None when too little agrees: not level, unknown.
    """
    gray = gray if gray.ndim == 2 else cv2.cvtColor(gray, cv2.COLOR_RGB2GRAY)
    found = _near_vertical_segments(gray)
    if not found:
        return None
    # Segments are measured at review size, so the support bar is too:
    # a third of the review long side of near-vertical edge in total.
    h, w = gray.shape
    review_long = min(VERT_REVIEW_WIDTH, float(max(h, w)))
    if sum(L for _, L in found) < VERT_MIN_TOTAL_FRAC * review_long:
        return None
    bins: dict[float, float] = {}
    for angle, length in found:
        center = round(angle / VERT_BIN_DEG) * VERT_BIN_DEG
        bins[center] = bins.get(center, 0.0) + length * length
    total = sum(bins.values())
    peak = max(bins, key=lambda c: bins[c])
    if bins[peak] / total < VERT_MIN_PEAK_SHARE:
        return None
    near = [a for a, _ in found if abs(a - peak) <= 1.5 * VERT_BIN_DEG]
    weights = [L * L for a, L in found if abs(a - peak) <= 1.5 * VERT_BIN_DEG]
    return float(sum(a * w for a, w in zip(near, weights)) / sum(weights))


def line_measure(gray: np.ndarray, width: int = 1500) -> float | None:
    """Mean length of the 20 longest LSD segments, or None when fewer
    than 20 segments exist to measure. The None case is unmeasurable,
    never a zero to compare against."""
    gray = gray if gray.ndim == 2 else cv2.cvtColor(gray, cv2.COLOR_RGB2GRAY)
    h, w = gray.shape
    small = cv2.resize(gray, (width, int(round(h * width / w))), interpolation=cv2.INTER_AREA)
    segs = cv2.createLineSegmentDetector().detect(small)[0]
    if segs is None or len(segs) < 20:
        return None
    lengths = np.hypot(segs[:, 2] - segs[:, 0], segs[:, 3] - segs[:, 1])
    return float(np.sort(lengths)[-20:].mean())


def correct_verticals(img: np.ndarray) -> tuple[np.ndarray, float | None]:
    """Rotate so near-vertical lines come out vertical. Returns the image
    and the applied rotation in degrees (None, image untouched, when no
    near-vertical lines exist to read)."""
    gray = img if img.ndim == 2 else cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
    tilt = dominant_vertical_angle(gray)
    if tilt is None:
        return img, None
    fixed, _ = rotate_image(img, -tilt)
    return fixed, -tilt


def crop_valid(img: np.ndarray, valid: np.ndarray) -> np.ndarray:
    """Largest centered same-aspect rectangle holding only valid pixels.

    Rotations and undistortion leave black borders; finished photos must
    not show them. valid marks samplable pixels (True inside). Found by
    bisection on an integral image, so partial edge rows cannot fool it.
    """
    h, w = valid.shape
    integ = cv2.integral(valid.astype(np.uint8))

    def all_valid(y0: int, y1: int, x0: int, x1: int) -> bool:
        area = integ[y1, x1] - integ[y0, x1] - integ[y1, x0] + integ[y0, x0]
        return area == (y1 - y0) * (x1 - x0)

    lo, hi = 0.0, 1.0
    for _ in range(12):
        mid = (lo + hi) / 2.0
        hh, hw = mid * h / 2.0, mid * w / 2.0
        y0, y1 = int(round(h / 2.0 - hh)), int(round(h / 2.0 + hh))
        x0, x1 = int(round(w / 2.0 - hw)), int(round(w / 2.0 + hw))
        if all_valid(y0, y1, x0, x1):
            lo = mid
        else:
            hi = mid
    hh, hw = lo * h / 2.0 - 1.0, lo * w / 2.0 - 1.0
    y0, y1 = int(round(h / 2.0 - hh)), int(round(h / 2.0 + hh))
    x0, x1 = int(round(w / 2.0 - hw)), int(round(w / 2.0 + hw))
    if y1 <= y0 or x1 <= x0:
        raise ValueError("no valid centered crop")
    return img[y0:y1, x0:x1]


def undistort_valid_mask(h: int, w: int, dx, dy) -> np.ndarray:
    """Pixels the undistortion field samples from inside the frame."""
    ys, xs = np.mgrid[0:h, 0:w].astype(np.float32)
    return (xs + dx >= 0) & (xs + dx <= w - 1) & (ys + dy >= 0) & (ys + dy <= h - 1)


def rotation_valid_mask(h: int, w: int, angle_deg: float) -> np.ndarray:
    """Pixels a rotation by angle_deg fills from inside the frame."""
    matrix = cv2.getRotationMatrix2D(((w - 1) / 2.0, (h - 1) / 2.0), -angle_deg, 1.0)
    warped = cv2.warpAffine(
        np.ones((h, w), np.uint8) * 255, matrix, (w, h), flags=cv2.INTER_NEAREST
    )
    return warped > 0


def ghosting_score(frames: list[np.ndarray]) -> float:
    """Fraction of pixels that move between aligned bracket frames."""
    gray = [f if f.ndim == 2 else cv2.cvtColor(f, cv2.COLOR_RGB2GRAY) for f in frames]
    stack = np.stack([g.astype(np.float32) for g in gray])
    spread = stack.max(axis=0) - stack.min(axis=0)
    return float((spread > 15.0).mean())
