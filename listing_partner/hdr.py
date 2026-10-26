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


def read_capture_time(path: Path) -> datetime:
    """Capture time of a NEF or JPEG, from EXIF DateTimeOriginal."""
    with open(path, "rb") as handle:
        tags = exifread.process_file(handle, details=False)
    tag = (
        tags.get("EXIF DateTimeOriginal")
        or tags.get("Image DateTimeOriginal")
        or tags.get("EXIF DateTimeDigitized")
        or tags.get("Image DateTime")
    )
    if tag is None:
        raise ValueError(f"no capture time in {path.name}")
    return datetime.strptime(str(tag), "%Y:%m:%d %H:%M:%S")


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


def decode_raw(path: Path, half_size: bool = False) -> np.ndarray:
    """Decode a NEF/DNG to an sRGB uint8 RGB array."""
    with rawpy.imread(str(path)) as raw:
        rgb = raw.postprocess(
            use_camera_wb=True,
            half_size=half_size,
            no_auto_bright=False,
            output_bps=8,
            output_color=rawpy.ColorSpace.sRGB,
        )
    return np.asarray(rgb, dtype=np.uint8)


def extract_preview(path: Path) -> np.ndarray:
    """Largest embedded JPEG preview of a raw file (fallback only)."""
    with rawpy.imread(str(path)) as raw:
        thumb = raw.extract_thumb()
    if thumb.format == rawpy.ThumbFormat.JPEG:
        with Image.open(BytesIO(thumb.data)) as img:
            return np.asarray(img.convert("RGB"))
    data = np.frombuffer(thumb.data, dtype=np.uint8)
    return np.asarray(Image.fromarray(data).convert("RGB"))


def render_linear_dng(path: Path) -> np.ndarray:
    """Render a linear-DNG (e.g. Lightroom HDR merge) to display sRGB.

    Reads the largest floating-point series, normalizes scene-linear light
    by a highlight percentile, and applies a 2.2 gamma. This is a plain
    viewer render of Lightroom's merge, not a re-edit of it.
    """
    import tifffile

    with tifffile.TiffFile(path) as tif:
        candidates = [s for s in tif.series if s.dtype == np.float16 and len(s.shape) == 3]
        if not candidates:
            raise ValueError("no linear image series in DNG")
        series = max(candidates, key=lambda s: s.shape[0] * s.shape[1])
        linear = np.asarray(series.asarray(), dtype=np.float32)
        neutral = None
        for page in tif.pages:
            if "AsShotNeutral" in page.tags:
                neutral = [float(v) for v in page.tags["AsShotNeutral"].value[:3]]
                break
    if linear.shape[2] == 4:
        linear = linear[:, :, :3]
    if neutral and all(v > 0 for v in neutral):
        linear = linear / np.array(neutral[:3], dtype=np.float32).reshape(1, 1, 3)
    peak = float(np.percentile(linear, 99.5))
    if peak <= 0:
        raise ValueError("DNG linear data is black")
    display = np.clip(linear / peak, 0.0, 1.0) ** (1.0 / 2.2)
    return (display * 255.0 + 0.5).astype(np.uint8)


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
        shift = warp.copy()
        shift[:, 2] /= ECC_SCALE  # ECC ran at reduced resolution
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
        decoded = [decode_raw(p) for p in frame_paths]
    except Exception as exc:
        raise ValueError(f"could not decode raw frames: {exc}") from exc
    try:
        return fuse_exposures(align_to_first(decoded))
    except Exception as exc:
        raise ValueError(f"could not fuse exposures: {exc}") from exc
