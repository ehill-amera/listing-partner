"""HDR merge: each bracket set becomes one natural-looking photo.

Local only: this module never imports the Meta client and makes no network
calls. Grouping follows capture-time gaps (more than 8 seconds starts a new
set), never a fixed set size and never exposure bias. Fusion is exposure
fusion (Mertens), not tone-mapped HDR.
"""

from __future__ import annotations

from datetime import datetime
from io import BytesIO
from pathlib import Path

import cv2
import exifread
import numpy as np
import rawpy
from PIL import Image

# A new bracket set starts after a gap of more than this many seconds.
SET_GAP_SECONDS = 8.0


def _xmp_capture_time(path: Path) -> datetime | None:
    """Capture time from the file's XMP block, or None when absent.

    Some finished JPEGs (unit-a MLS 007.jpg) carry no EXIF dates at all;
    their capture time sits only in XMP as ``xmp:CreateDate`` (which matches
    EXIF DateTimeOriginal to the second on sibling files that carry both).
    Times compare against naive local capture stamps, so a zone offset is
    dropped after parsing: the wall time is what matters.
    """
    import re

    with open(path, "rb") as handle:
        raw = handle.read()
    start = raw.find(b"<x:xmpmeta")
    end = raw.find(b"</x:xmpmeta>")
    if start < 0 or end < 0:
        return None
    packet = raw[start : end + len(b"</x:xmpmeta>")].decode("utf-8", "replace")
    for field in ("xmp:CreateDate", "exif:DateTimeOriginal", "photoshop:DateCreated"):
        match = re.search(re.escape(field) + r'\s*=\s*"([^"]+)"', packet)
        if not match:
            continue
        text = match.group(1).strip()
        try:
            stamp = datetime.fromisoformat(text)
        except ValueError:
            continue
        if stamp.tzinfo is not None:
            stamp = stamp.replace(tzinfo=None)
        return stamp.replace(microsecond=0)
    return None


def read_capture_time(path: Path) -> datetime:
    """Capture time of a NEF or JPEG, from EXIF then XMP DateTimeOriginal."""
    with open(path, "rb") as handle:
        tags = exifread.process_file(handle, details=False)
    tag = (
        tags.get("EXIF DateTimeOriginal")
        or tags.get("Image DateTimeOriginal")
        or tags.get("EXIF DateTimeDigitized")
        or tags.get("Image DateTime")
    )
    if tag is not None:
        return datetime.strptime(str(tag), "%Y:%m:%d %H:%M:%S")
    stamp = _xmp_capture_time(path)
    if stamp is not None:
        return stamp
    raise ValueError(f"no capture time in {path.name}")


def read_exposure_seconds(path: Path) -> float:
    """Exposure time in seconds, from EXIF ExposureTime."""
    with open(path, "rb") as handle:
        tags = exifread.process_file(handle, details=False)
    tag = tags.get("EXIF ExposureTime") or tags.get("Image ExposureTime")
    if tag is None:
        raise ValueError(f"no exposure time in {path.name}")
    values = tag.values
    if isinstance(values, list) and len(values) == 1:
        try:
            return float(values[0])
        except (TypeError, ValueError, ZeroDivisionError):
            pass
    if isinstance(values, list) and len(values) == 2 and values[1]:
        return float(values[0]) / float(values[1])
    text = str(tag).split()[0].strip()
    if "/" in text:
        num, _, den = text.partition("/")
        if float(den):
            return float(num) / float(den)
    return float(text)


def group_frames(paths: list[Path], gap_seconds: float = SET_GAP_SECONDS) -> list[list[Path]]:
    """Group frames into bracket sets by capture-time gaps.

    Frames sorted by capture time; a gap of more than ``gap_seconds``
    starts a new set. Every frame lands in exactly one set.
    """
    stamped = sorted((read_capture_time(p), p) for p in paths)
    sets: list[list[Path]] = []
    last_stamp = None
    for stamp, path in stamped:
        if not sets or (
            last_stamp is not None and (stamp - last_stamp).total_seconds() > gap_seconds
        ):
            sets.append([path])
        else:
            sets[-1].append(path)
        last_stamp = stamp
    return sets


def most_common_size(sets: list[list[Path]]) -> int:
    sizes: dict[int, int] = {}
    for s in sets:
        sizes[len(s)] = sizes.get(len(s), 0) + 1
    return max(sorted(sizes), key=lambda n: (sizes[n], -n))


JPEG_SUFFIXES = (".jpg", ".jpeg")


def decode_frame(path: Path, half_size: bool = False) -> np.ndarray:
    """Decode one bracket frame to an sRGB uint8 RGB array.

    JPEG for units shot that way (PIL), raw decode otherwise. This is the
    only decode path merge code may use.
    """
    if path.suffix.lower() in JPEG_SUFFIXES:
        with Image.open(path) as img:
            frame = np.asarray(img.convert("RGB"))
        if half_size:
            half = Image.fromarray(frame)
            frame = np.asarray(half.resize((half.width // 2, half.height // 2), Image.BILINEAR))
        return frame
    return decode_raw(path, half_size=half_size)


def decode_raw(path: Path, half_size: bool = False) -> np.ndarray:
    """Decode a NEF/DNG to an sRGB uint8 RGB array.

    Auto-brightening stays off: every frame reaches fusion at its true
    exposure, so the dark brackets keep their window highlights unclipped.
    """
    with rawpy.imread(str(path)) as raw:
        rgb = raw.postprocess(
            use_camera_wb=True,
            half_size=half_size,
            no_auto_bright=True,
            output_bps=8,
            output_color=rawpy.ColorSpace.sRGB,
        )
    return np.asarray(rgb, dtype=np.uint8)


def _largest_tiff_preview(path: Path) -> np.ndarray | None:
    """Largest decoded uint8 RGB preview series, or None when absent.

    A Lightroom HDR DNG embeds several previews (a 256-pixel thumbnail, a
    1024-pixel preview, and more). rawpy's thumbnail call only ever returns
    the smallest, so the review page reads the file's own preview list and
    takes the largest instead.
    """
    import tifffile

    # Decodes happen inside the open block: a series reads lazily from the
    # file, so decoding after close always fails. Largest first: one
    # undecodable preview must not veto the rest.
    try:
        with tifffile.TiffFile(path) as tif:
            candidates = [
                series
                for series in tif.series
                if series.dtype == np.uint8 and len(series.shape) == 3 and series.shape[2] in (3, 4)
            ]
            decoded = []
            for series in sorted(
                candidates,
                key=lambda s: int(s.shape[0]) * int(s.shape[1]),
                reverse=True,
            ):
                try:
                    decoded.append(
                        np.asarray(np.asarray(series.asarray())[:, :, :3], dtype=np.uint8)
                    )
                    break
                except Exception:
                    continue
    except Exception:
        return None
    return decoded[0] if decoded else None


def extract_preview(path: Path) -> np.ndarray:
    """Largest embedded preview of a raw file (fallback only)."""
    largest = _largest_tiff_preview(path)
    if largest is not None:
        return largest
    with rawpy.imread(str(path)) as raw:
        thumb = raw.extract_thumb()
    if thumb.format == rawpy.ThumbFormat.JPEG:
        with Image.open(BytesIO(thumb.data)) as img:
            return np.asarray(img.convert("RGB"))
    data = np.frombuffer(thumb.data, dtype=np.uint8)
    return np.asarray(Image.fromarray(data).convert("RGB"))


# XYZ (D65) to linear sRGB, exact sRGB specification values.
_XYZ_TO_LINEAR_SRGB = np.array(
    [
        [3.2404542, -1.5371385, -0.4985314],
        [-0.9692660, 1.8760108, 0.0415560],
        [0.0556434, -0.2040259, 1.0572252],
    ],
    dtype=np.float64,
)

# Bradford chromatic adaptation, DNG profile connection space (D50) to D65.
_D50_TO_D65 = np.array(
    [
        [1.0478112, 0.0228866, -0.0501270],
        [0.0295424, 0.9904844, -0.0170491],
        [-0.0092345, 0.0150436, 0.7521316],
    ],
    dtype=np.float64,
)


def _dng_floats(value, count: int) -> list[float] | None:
    """Parse DNG RATIONAL/SRATIONAL tag values to floats.

    tifffile hands these back either as (numerator, denominator) pairs or
    as one flat [num, den, ...] run; both shapes occur in the wild.
    """
    try:
        flat = list(np.asarray(value, dtype=object).ravel())
    except Exception:
        return None
    pairs: list[tuple[float, float]]
    if flat and isinstance(flat[0], (tuple, list)):
        pairs = [(float(n), float(d)) for n, d in flat]
    else:
        nums = [float(x) for x in flat]
        pairs = list(zip(nums[0::2], nums[1::2]))
    if len(pairs) < count:
        return None
    return [n / d if d else 0.0 for n, d in pairs[:count]]


def _srgb_eotf(linear: np.ndarray) -> np.ndarray:
    """The sRGB tone curve: piecewise transfer function to display light."""
    low = 12.92 * linear
    high = 1.055 * np.power(np.clip(linear, 0.0, None), 1.0 / 2.4) - 0.055
    return np.where(linear <= 0.0031308, low, high)


def render_linear_dng(path: Path) -> np.ndarray:
    """Render a linear-DNG (e.g. Lightroom HDR merge) to display sRGB.

    The DNG color chain, per the DNG specification: white balance from
    AsShotNeutral, camera-native linear light to XYZ via the daylight
    (D65) ForwardMatrix when present else the D65 ColorMatrix, Bradford
    adaptation to D65, the sRGB matrix, then the sRGB tone curve. Display
    exposure is set from a highlight percentile afterwards: the merge
    files store unnormalized scene-linear values, so this normalization
    stands in for the output-referred exposure every viewer must pick. It
    is a plain viewer render of Lightroom's merge, not a re-edit of it.
    """
    import tifffile

    with tifffile.TiffFile(path) as tif:
        candidates = [s for s in tif.series if s.dtype == np.float16 and len(s.shape) == 3]
        if not candidates:
            raise ValueError("no linear image series in DNG")
        series = max(candidates, key=lambda s: s.shape[0] * s.shape[1])
        linear = np.asarray(series.asarray(), dtype=np.float64)
        tags: dict = {}
        for page in tif.pages:
            for name in (
                "AsShotNeutral",
                "ForwardMatrix2",
                "ForwardMatrix1",
                "ColorMatrix2",
                "ColorMatrix1",
                "BlackLevel",
                "WhiteLevel",
            ):
                if name in page.tags and name not in tags:
                    tags[name] = page.tags[name].value
    if linear.shape[2] == 4:
        linear = linear[:, :, :3]
    black = _dng_floats(tags["BlackLevel"], 3) if "BlackLevel" in tags else None
    if black:
        linear = linear - np.array(black[:3], dtype=np.float64).reshape(1, 1, 3)
    white = _dng_floats(tags["WhiteLevel"], 1) if "WhiteLevel" in tags else None
    if white and white[0] > 0:
        linear = linear / white[0]
    neutral = _dng_floats(tags["AsShotNeutral"], 3) if "AsShotNeutral" in tags else None
    if neutral and all(v > 0 for v in neutral):
        linear = linear / np.array(neutral[:3], dtype=np.float64).reshape(1, 1, 3)
    profile = None
    for name in ("ForwardMatrix2", "ForwardMatrix1", "ColorMatrix2", "ColorMatrix1"):
        if name in tags:
            profile = _dng_floats(tags[name], 9)
            if profile:
                break
    if profile is None:
        raise ValueError("no color matrix (Forward/ColorMatrix) in DNG")
    camera_to_srgb = _XYZ_TO_LINEAR_SRGB @ _D50_TO_D65 @ np.array(profile).reshape(3, 3)
    rgb = linear @ camera_to_srgb.T
    peak = float(np.percentile(rgb, 99.5))
    if not np.isfinite(peak) or peak <= 0:
        raise ValueError("DNG linear data is black")
    display = _srgb_eotf(np.clip(rgb / peak, 0.0, None))
    return (np.clip(display, 0.0, 1.0) * 255.0 + 0.5).astype(np.uint8)


ECC_SCALE = 0.25


def _to_gray_small(img: np.ndarray, scale: float = ECC_SCALE) -> np.ndarray:
    gray = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
    small = cv2.resize(gray, (0, 0), fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    return small


def align_to_first(images: list[np.ndarray]) -> list[np.ndarray]:
    """Translate each frame onto the first (tripod brackets need no more)."""
    if len(images) <= 1:
        return list(images)
    ref = _to_gray_small(images[0])
    aligned = [images[0]]
    for img in images[1:]:
        gray = _to_gray_small(img)
        warp = np.eye(2, 3, dtype=np.float32)
        try:
            cv2.findTransformECC(ref, gray, warp, cv2.MOTION_TRANSLATION)
        except cv2.error:
            aligned.append(img)  # alignment failed: keep the frame as shot
            continue
        h, w = img.shape[:2]
        # findTransformECC returns the template-into-input map, but
        # warpAffine takes the source-into-destination map, so the
        # translation is negated (then scaled back up: ECC ran small).
        shift = warp.copy()
        shift[:, 2] = -warp[:, 2] / ECC_SCALE
        aligned.append(cv2.warpAffine(img, shift, (w, h), flags=cv2.INTER_LINEAR))
    return aligned


def fuse_exposures(images: list[np.ndarray]) -> np.ndarray:
    """Mertens exposure fusion of aligned uint8 RGB frames."""
    merger = cv2.createMergeMertens()
    fused = merger.process([img.astype(np.uint8) for img in images])
    out = np.clip(fused * 255.0, 0, 255).astype(np.uint8)
    return out


def darkest_and_brightest(frame_paths: list[Path]) -> tuple[Path, Path]:
    """Darkest (shortest exposure) and brightest (longest) frames of a set."""
    ranked = sorted(frame_paths, key=read_exposure_seconds)
    return ranked[0], ranked[-1]


def save_clean_jpeg(image: np.ndarray, path: Path, quality: int = 92) -> None:
    """Write an sRGB JPEG with no EXIF: no GPS, no serial, nothing."""
    Image.fromarray(image.astype(np.uint8), mode="RGB").save(
        path, format="JPEG", quality=quality, exif=b""
    )


def merge_set(frame_paths: list[Path]) -> np.ndarray:
    """Align then fuse one bracket set. Raises with a plain reason on failure."""
    if not frame_paths:
        raise ValueError("empty set")
    try:
        decoded = [decode_frame(p) for p in frame_paths]
    except Exception as exc:
        raise ValueError(f"could not decode frames: {exc}") from exc
    try:
        return fuse_exposures(align_to_first(decoded))
    except Exception as exc:
        raise ValueError(f"could not fuse exposures: {exc}") from exc
