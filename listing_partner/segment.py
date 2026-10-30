"""Windows: SAM finds them, Muse Spark confirms them, brackets fill them.

Local geometry plus capped Meta calls only. Masks cover glass; frames,
sills and trim stay from the merge. Step B changes nothing outside the
confirmed window masks.
"""

from __future__ import annotations

import io
import re
from pathlib import Path

import cv2
import numpy as np
from meta_sam_parser import (
    CompletedOutcome,
    decode_mask_to_raster,
    image_segmentation_format,
)
from PIL import Image, ImageDraw

from listing_partner import meta_client

SAM_MODEL = "sam-3.1"
SPARK_MODEL = "muse-spark-1.3"
#: View-frame gray below this holds no outdoor detail: the pixel is an
#: interior surface (frame, trim, blind) and stays from the merge.
VIEW_DETAIL_FLOOR = 50
#: A kept pixel inpaints from neighboring view pixels only when its
#: merge pixel reads blown at or above this gray: darker kept regions
#: the merge already holds stay from the merge.
HOLE_MERGE_FLOOR = 200
#: A blown keep region this thick (distance to non-keep) is glass, not
#: frame: trim rings, slats and mullions peak at 62 px thick on unit-a
#: 009, glass bays run into the hundreds. Measured both sides.
HOLE_THICK_PX = 80.0

# Follow-up rounds after the first annotated photo. Each round is one
# capped call; the bound keeps a confused photo from eating the budget.
# Spark drives at most once (its crop request); after that we drive,
# zooming each undecided candidate in turn, so chatter can never stall
# the loop.
MAX_CROP_ROUNDS = 6


def parse_lane(text: str, frame_w: int, frame_h: int) -> list[dict]:
    """SAM output-text lane to candidates with frame-size glass masks."""
    parser = image_segmentation_format().create_parser()
    parser.push(text)
    result = parser.finish(CompletedOutcome()).result
    boxes = {}
    masks = {}
    for record in result.records:
        name = type(record).__name__
        if name == "SegmentationBoxRecord":
            boxes[record.object_id] = record
        elif name == "SegmentationMaskRecord":
            masks[record.object_id] = record
    candidates = []
    for key in sorted(set(boxes) & set(masks), key=int):
        object_id = int(key)
        box = boxes[key]
        left, top, right, bottom = box.left, box.top, box.right, box.bottom
        raster = decode_mask_to_raster(masks[key].mask)
        small = np.frombuffer(raster, dtype=np.uint8).reshape(
            masks[key].mask.height, masks[key].mask.width
        )
        grown = cv2.resize(small, (right - left, bottom - top), interpolation=cv2.INTER_NEAREST)
        full = np.zeros((frame_h, frame_w), bool)
        full[top:bottom, left:right] = grown.astype(bool)
        candidates.append({"object_id": object_id, "box": (left, top, right, bottom), "mask": full})
    return candidates


def dedupe_candidates(candidates: list[dict]) -> list[dict]:
    """One entry per detected region, with sequential ids.

    Both text prompts run on the same photo, so the same glass can come
    back twice, and each lane numbers from zero, so two regions can share
    an id. Same box twice keeps the first; then ids are reassigned 0..n-1
    in first-seen order so every verdict names exactly one region.
    """
    unique = []
    seen = set()
    for candidate in candidates:
        if candidate["box"] in seen:
            continue
        seen.add(candidate["box"])
        unique.append(candidate)
    for new_id, candidate in enumerate(unique):
        candidate["object_id"] = new_id
    return unique


def find_candidates(
    image_jpeg: bytes, prompt: str, *, transport=None, ledger_path=None
) -> list[dict]:
    """One SAM call per prompt; returns candidates with frame-size masks."""
    out = meta_client.call_meta_segment(
        SAM_MODEL, prompt, image_jpeg, transport=transport, ledger_path=ledger_path
    )
    with Image.open(io.BytesIO(image_jpeg)) as handle:
        frame_w, frame_h = handle.size
    return parse_lane(out["text"], frame_w, frame_h)


def scale_candidates(
    candidates: list[dict], old_w: int, old_h: int, new_w: int, new_h: int
) -> list[dict]:
    """Scale boxes and masks from the sent size to full resolution."""
    sx, sy = new_w / old_w, new_h / old_h
    scaled = []
    for candidate in candidates:
        left, top, right, bottom = candidate["box"]
        box = (
            int(round(left * sx)),
            int(round(top * sy)),
            int(round(right * sx)),
            int(round(bottom * sy)),
        )
        mask = cv2.resize(
            candidate["mask"].astype(np.uint8),
            (new_w, new_h),
            interpolation=cv2.INTER_NEAREST,
        ).astype(bool)
        scaled.append({"object_id": candidate["object_id"], "box": box, "mask": mask})
    return scaled


def jpeg_bytes(photo_rgb: np.ndarray, long_side: int = 1024, quality: int = 88) -> bytes:
    """Downscale-and-encode a photo for a Meta image call."""
    h, w = photo_rgb.shape[:2]
    scale = min(1.0, long_side / max(h, w))
    if scale < 1.0:
        photo_rgb = cv2.resize(
            photo_rgb,
            (int(round(w * scale)), int(round(h * scale))),
            interpolation=cv2.INTER_AREA,
        )
    handle = io.BytesIO()
    Image.fromarray(photo_rgb).save(handle, format="JPEG", quality=quality)
    return handle.getvalue()


def annotate(photo_rgb: np.ndarray, candidates: list[dict]) -> np.ndarray:
    """Numbered boxes over a copy, so Spark can verdict by id."""
    canvas = Image.fromarray(photo_rgb)
    draw = ImageDraw.Draw(canvas)
    for candidate in candidates:
        left, top, right, bottom = candidate["box"]
        draw.rectangle([left, top, right, bottom], outline=(255, 0, 0), width=3)
        draw.text((left + 4, top + 4), str(candidate["object_id"]), fill=(255, 0, 0))
    return np.asarray(canvas)


_VERDICT = re.compile(r"^\s*(\d+)\s*:\s*(window|not a window)\s*[-–]\s*(.+?)\s*$")
_CROP = re.compile(r"CROP\s+(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)")


def _parse_verdicts(text: str) -> dict[int, tuple[bool, str]]:
    """Every verdict line anywhere in the reply (chatter ignored)."""
    verdicts = {}
    for line in text.strip().splitlines():
        match = _VERDICT.match(line)
        if match:
            object_id = int(match.group(1))
            verdicts[object_id] = (match.group(2) == "window", match.group(3))
    return verdicts


def _wants_closer_look(text: str) -> bool:
    lowered = text.lower()
    return "crop" in lowered or "zoom" in lowered or "closer look" in lowered


VERIFY_PROMPT = (
    "Numbered red boxes mark window candidates in this room photo. "
    "For EACH numbered box reply one line exactly like: "
    "ID: window - reason OR ID: not a window - reason. "
    "A real window is seen from INSIDE the room and shows the outdoors "
    "(sky, trees, buildings, street). Glass photographed from OUTSIDE "
    "(a house facade, a neighbor's windows, a garage or shed window) is "
    "not a view to the outdoors: reject it, naming what it actually is. "
    "Reject mirrors, screens, framed pictures, light fixtures and cabinet "
    "glass, naming what it actually is. If one box needs a closer look, "
    "reply only: CROP x,y,w,h in these photo pixels."
)


ZOOM_PROMPT = (
    "Close-up of candidate box {object_id} from the room photo. Reply one "
    "line exactly like: {object_id}: window - reason OR {object_id}: not a "
    "window - reason. A real window shows the outdoors (sky, trees, "
    "buildings, street). Reject mirrors, screens, pictures, fixtures and "
    "cabinet glass, naming what it actually is."
)

CROP_ASK = "Reply with only the crop rectangle as CROP x,y,w,h in photo pixels, nothing else."


def _zoom_crop(photo_rgb: np.ndarray, box: tuple) -> np.ndarray:
    left, top, right, bottom = box
    h, w = photo_rgb.shape[:2]
    pad_x = int(round((right - left) * 0.5))
    pad_y = int(round((bottom - top) * 0.5))
    x0, y0 = max(0, left - pad_x), max(0, top - pad_y)
    x1, y1 = min(w, right + pad_x), min(h, bottom + pad_y)
    return photo_rgb[y0:y1, x0:x1]


def verify_candidates(
    photo_rgb: np.ndarray,
    candidates: list[dict],
    *,
    transport=None,
    ledger_path=None,
    max_output_tokens: int = 4096,
    transcript: list | None = None,
) -> dict[int, tuple[bool, str]]:
    """Spark verdicts per candidate id: (is_window, reason).

    One annotated photo first; up to MAX_CROP_ROUNDS follow-ups when Spark
    asks for a closer crop or skips a box. Every round goes through the
    capped client. Raw replies append to transcript when given.
    """
    wanted = {c["object_id"] for c in candidates}
    if not wanted:
        return {}
    boxes = {c["object_id"]: c["box"] for c in candidates}
    annotated = annotate(photo_rgb, candidates)
    current_jpeg = jpeg_bytes(annotated)
    prompt = VERIFY_PROMPT
    rounds = 0
    spark_drove = False
    zoomed: set[int] = set()
    found: dict[int, tuple[bool, str]] = {}
    while True:
        out = meta_client.call_meta_text(
            SPARK_MODEL,
            prompt,
            max_output_tokens,
            images=[current_jpeg],
            transport=transport,
            ledger_path=ledger_path,
        )
        if transcript is not None:
            transcript.append(out["text"])
        found.update(_parse_verdicts(out["text"]))
        missing = sorted(wanted - set(found))
        if not missing:
            return {k: found[k] for k in wanted}
        if rounds >= MAX_CROP_ROUNDS:
            raise ValueError(f"Spark left candidates {missing} undecided after {rounds + 1} rounds")
        match = None if spark_drove else _CROP.search(out["text"])
        if match:
            spark_drove = True
            x, y, w, h = (int(v) for v in match.groups())
            crop = annotated[y : y + h, x : x + w]
            if crop.size == 0:
                raise ValueError(f"empty crop {x},{y},{w},{h}")
            current_jpeg = jpeg_bytes(crop)
            prompt = VERIFY_PROMPT + _visible_note(boxes, (x, y, w, h))
            rounds += 1
            continue
        if _wants_closer_look(out["text"]) or not found:
            if spark_drove:
                need = next((m for m in missing if m not in zoomed), missing[0])
            else:
                prompt = CROP_ASK
                rounds += 1
                continue
        else:
            need = next((m for m in missing if m not in zoomed), missing[0])
        box = boxes[need]
        zoomed.add(need)
        prompt = ZOOM_PROMPT.format(object_id=need)
        current_jpeg = jpeg_bytes(_zoom_crop(annotated, box))
        rounds += 1


def _visible_note(boxes: dict[int, tuple], crop: tuple) -> str:
    """Name the candidate ids whose box centers land inside a crop."""
    x, y, w, h = crop
    inside = sorted(
        object_id
        for object_id, (left, top, right, bottom) in boxes.items()
        if x <= (left + right) / 2 <= x + w and y <= (top + bottom) / 2 <= y + h
    )
    if not inside:
        return ""
    ids = ", ".join(str(i) for i in inside)
    return f" Visible candidate ids in this view: {ids}. Reply one verdict line for each."


def choose_pull_frame(
    frames: list[np.ndarray], mask: np.ndarray, ref: np.ndarray | None = None
) -> int:
    """Index of the frame whose window region is best exposed.

    Fewest near-white pixels on any channel (threshold 250, the same
    level the highlights check measures) wins. Ties go to the frame
    closest to the merge: when the merge already holds the view, the
    pull changes it the least, so clean windows gain nothing. Never the
    darkest frame by default: an almost-black frame holds no view at
    all.
    """
    from listing_partner.checks import clipped_fraction

    ref_mean = None
    if ref is not None and mask.any():
        ref_mean = float(cv2.cvtColor(ref, cv2.COLOR_RGB2GRAY).astype(np.float32)[mask].mean())

    def score(frame: np.ndarray) -> tuple[float, float]:
        gray = cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY).astype(np.float32)
        clip = clipped_fraction(frame[mask]) if mask.any() else 0.0
        mean = float(gray[mask].mean()) if mask.any() else 0.0
        tie = abs(mean - ref_mean) if ref_mean is not None else -mean
        return (clip, tie)

    if not frames:
        raise ValueError("no bracket frames to pull the view from")
    return min(range(len(frames)), key=lambda i: score(frames[i]))


def pull_window(
    merge_rgb: np.ndarray, dark_rgb: np.ndarray, mask: np.ndarray
) -> tuple[np.ndarray, int]:
    """Fill blown glass from the best-exposed real bracket frame.

    A mask pixel takes the view only when the view frame holds outdoor
    detail there (at or above VIEW_DETAIL_FLOOR): frames, mullions,
    blinds, sills and trim read dark in the pull frame, so they stay
    from the merge pixel-exact. Kept glass the merge blows out but the
    view reads dark is sky the dark frame underexposes: enclosed specks
    and deep thick regions inpaint from neighboring real view pixels,
    while edge-hugging trim, thin slats and bars, and dark held regions
    stay. The feather ramps up inside the replaced glass, so the blend
    never reaches the frame: no dark outline, no smear.
    The view is matched to the room with a single uniform gain that can
    only darken: it is never pushed brighter than its own frame, so a
    held view stays held. No clamp, no cap: what the view holds is what
    gets measured. Returns the pulled photo and the count of changed
    pixels outside the mask (must be 0).
    """
    # A pixel takes the view only when the view frame holds something
    # there: frames, mullions, blinds, sills and trim read dark in the
    # (dark) pull frame, while glass carries the brighter outdoor view.
    # Measured unit-a: interior surfaces 18-36 gray, glass 60+ in the
    # darkest frames. Brightness in the merge cannot decide: the balance
    # shoulder compresses blown glass to just under 250, exactly where
    # white trim sits.
    view_gray = cv2.cvtColor(dark_rgb, cv2.COLOR_RGB2GRAY)
    merge_gray = cv2.cvtColor(merge_rgb, cv2.COLOR_RGB2GRAY)
    replaced = mask & (view_gray >= VIEW_DETAIL_FLOOR)
    # Enclosed sky holes: kept components fully inside the mask whose
    # merge pixels are blown are sky holes the dark pull frame renders
    # near-black (unit-a 009: 1,848 specks, median 5 px, merge 245+ where
    # the view reads 42). They take neighboring real view pixels through
    # classical diffusion inpainting, no generative model. Keep touching
    # the mask border is real frame, and dark kept regions the merge
    # already holds stay from the merge.
    keep = mask & ~replaced
    hole_mask = np.zeros_like(mask)
    if keep.any():
        # Glass the merge blows out but the view reads dark inpaints from
        # neighboring real view pixels when it is sky: enclosed specks, or
        # blown regions thicker than any frame member. Trim rings, blind
        # slats and mullion bars are thin (measured widths stay under
        # 40 px); dark woodwork reads below the merge floor. All stay.
        thick = cv2.distanceTransform(keep.astype(np.uint8), cv2.DIST_L2, 3)
        stout = thick >= HOLE_THICK_PX
        blown = merge_gray >= HOLE_MERGE_FLOOR
        count, labels, _, _ = cv2.connectedComponentsWithStats(keep.astype(np.uint8), 8)
        touching = np.zeros_like(mask)
        touching[1:, :] |= keep[1:, :] & ~mask[:-1, :]
        touching[:-1, :] |= keep[:-1, :] & ~mask[1:, :]
        touching[:, 1:] |= keep[:, 1:] & ~mask[:, :-1]
        touching[:, :-1] |= keep[:, :-1] & ~mask[:, 1:]
        touched_labels = set(np.unique(labels[touching]).tolist()) - {0}
        all_labels = set(np.unique(labels[keep]).tolist()) - {0}
        enclosed = np.isin(labels, list(all_labels - touched_labels))
        hole_mask = keep & blown & (enclosed | stout)
    if not replaced.any() and not hole_mask.any():
        return merge_rgb.copy(), 0
    room = ~mask
    matched = dark_rgb.astype(np.float32)
    if room.any():
        merge_lum = cv2.cvtColor(merge_rgb, cv2.COLOR_RGB2GRAY).astype(np.float32)[room].mean()
        view_lum = cv2.cvtColor(dark_rgb, cv2.COLOR_RGB2GRAY).astype(np.float32)[room].mean()
        gain = min(1.0, float(merge_lum) / max(1e-6, float(view_lum)))
        matched *= gain
    if hole_mask.any():
        # Blown keep conduits join the inpaint region so brightness from
        # replaced glass reaches the holes past the dark keep band; only
        # hole pixels are taken, conduits (trim included) stay from the
        # merge.
        paint = np.clip(matched, 0, 255).astype(np.uint8)
        region = hole_mask | (keep & blown)
        filled = cv2.inpaint(paint, region.astype(np.uint8), 3, cv2.INPAINT_TELEA).astype(
            np.float32
        )
        matched[hole_mask] = filled[hole_mask]
        replaced |= hole_mask
    feather = max(2, int(round(max(mask.shape) * 0.002)))
    dist = cv2.distanceTransform(replaced.astype(np.uint8), cv2.DIST_L2, 3)
    alpha = np.clip(dist / feather, 0.0, 1.0).astype(np.float32)
    base = merge_rgb.astype(np.float32)
    pulled = base * (1 - alpha[:, :, None]) + matched * alpha[:, :, None]
    pulled = np.clip(pulled, 0, 255).astype(np.uint8)
    changed_outside = int((np.any(pulled != merge_rgb, axis=2) & ~mask).sum())
    return pulled, changed_outside


def save_mask_png(mask: np.ndarray, path: Path) -> None:
    """Glass-white mask PNG for the review page and the package record."""
    Image.fromarray((mask.astype(np.uint8)) * 255, mode="L").save(path)
