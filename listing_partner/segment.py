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
#: A frame darker than this across the window holds murk, not a view.
VIEW_DETAIL_FLOOR = 50
#: Merge pixels at or above this gray with no detail-frame hold are
#: near-white: the balance shoulder parks blown glass here. Below it the
#: merge holds its own detail.
SHOULDER_FLOOR = 240
#: Merge brighter than the view by more than this is the blowout
#: signature. Smaller differences are exposure wobble between bracket
#: frames of the same surface (trim reads near-merge in an
#: exposure-matched frame), so those pixels keep the merge.
AGREE_GAP = 25
#: View-frame local gray std below this holds no scene: flat paint, trim,
#: blinds and smooth sky read the same in every direction, so a flat view
#: pixel is an interior surface or unrecoverable sky and stays from the
#: merge. Sunlit trim reads 130-140 in a mid frame (unit-a 005) with std
#: ~3, while foliage glass reads 15+: the gate sits between them. Measured
#: in a 15 px box: wide enough that a smooth ramp still reads (a real
#: gradient holds detail), narrow enough that flat paint stays flat.
VIEW_TEXTURE_K = 15
VIEW_TEXTURE_MIN = 6.0
#: A take hole bright in BOTH frames on any channel is a foliage gap
#: onto sky, white whichever frame draws it: filling it with the view's
#: own white changes nothing visible and keeps the shipped view one
#: continuous region instead of solarized speckle. Blue sky reads dark in
#: gray (~170) so the test runs on channel max, not gray. Darker holes
#: are the merge's own detail (a leaf silhouette, a mullion shadow) and
#: stay exactly as the merge drew them.
HOLE_BRIGHT = 240
#: Take erosion in pixels: the texture window straddles every glass/trim
#: edge, so a band this wide around each boundary passes texture on the
#: glass's testimony and would drag dark trim paint into white rooms as
#: outlines on every mullion. Eroding past the straddle radius keeps the
#: insert on glass the window's own texture vouches for; narrow mullions
#: vanish whole, wide glass barely notices. The seam lands on white trim
#: beside white glass, where no line shows.
TAKE_ERODE_PX = 9

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


def _ring_gain(merge_rgb: np.ndarray, view_rgb: np.ndarray, mask: np.ndarray) -> float:
    """Median light ratio between merge and view on the mask's own ring.

    The ring is the same room surfaces in both frames, so the ratio
    reads exposure difference, not scene difference. A ratio near one
    means the view frame's light already matches the room; far from one
    means inserting it would scar trim either bright or dark.
    """
    ring = cv2.dilate(mask.astype(np.uint8), np.ones((7, 7), np.uint8)).astype(bool)
    ring &= ~mask
    if not ring.any():
        return 1.0
    merge_med = float(np.median(cv2.cvtColor(merge_rgb, cv2.COLOR_RGB2GRAY)[ring]))
    view_med = float(np.median(cv2.cvtColor(view_rgb, cv2.COLOR_RGB2GRAY)[ring]))
    return merge_med / max(1.0, view_med)


def _view_texture(view_gray: np.ndarray) -> np.ndarray:
    """Local gray std of the view frame: flat paint reads ~3, foliage 15+.

    A flat view pixel holds no scene to pull, so it never takes: that is
    what keeps sunlit trim (mid-tone and unblown in a mid frame, every
    other condition passing) from dragging dark paint into a white room.
    """
    gray = view_gray.astype(np.float32)
    mean = cv2.boxFilter(gray, -1, (VIEW_TEXTURE_K, VIEW_TEXTURE_K))
    sq = cv2.boxFilter(gray * gray, -1, (VIEW_TEXTURE_K, VIEW_TEXTURE_K))
    return np.sqrt(np.maximum(sq - mean * mean, 0.0))


def _take_mask(merge_rgb: np.ndarray, view_rgb: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """Mask pixels the view frame replaces: blown merge with real detail.

    Only pixels where the merge is near-white, the view holds outdoor
    detail, the view itself is not near-white on any channel, the view
    carries texture (flat paint holds no scene), and the merge reads
    clearly brighter (the blowout signature) change. Trim, mullions,
    blinds and sills fail one of these and keep the merge pixel-exact.
    Bright holes fully inside the take (foliage gaps onto sky, bright in
    both frames) fill so the shipped view is one continuous region;
    darker holes are the merge's own detail and stay. The take then
    erodes past the texture straddle radius so edge bands and narrow
    mullions never insert, and speckle dots too small to be a pane drop.
    Glass pixels taken never reach near-white (filled holes match the
    merge's own white), so the after count can only drop against an
    honest before count.
    """
    from listing_partner.checks import CLIP_LEVEL

    merge_gray = cv2.cvtColor(merge_rgb, cv2.COLOR_RGB2GRAY).astype(np.float32)
    view_gray = cv2.cvtColor(view_rgb, cv2.COLOR_RGB2GRAY).astype(np.float32)
    view_max = view_rgb.max(axis=2)
    raw = (
        mask
        & (merge_rgb.max(axis=2) >= SHOULDER_FLOOR)
        & (view_gray >= VIEW_DETAIL_FLOOR)
        & (view_max < CLIP_LEVEL)
        & ((merge_gray - view_gray) > AGREE_GAP)
        & (_view_texture(view_gray) >= VIEW_TEXTURE_MIN)
    )
    if not raw.any():
        return raw
    # Fill bright interior holes: invert, flood the outside from a dry
    # seed, what stays dry is a hole. Only bright holes fill; dark ones
    # are merge detail.
    inv = (~raw).astype(np.uint8) * 255
    dry = np.nonzero(inv)
    take = raw
    if dry[0].size:
        flooded = inv.copy()
        cv2.floodFill(flooded, None, (int(dry[1][0]), int(dry[0][0])), 128)
        holes = (
            (flooded == 255)
            & mask
            & (view_rgb.max(axis=2) >= HOLE_BRIGHT)
            & (merge_rgb.max(axis=2) >= HOLE_BRIGHT)
        )
        take = raw | holes
    # Past the straddle: edge bands and narrow mullions leave the take.
    erode_d = 2 * TAKE_ERODE_PX + 1
    take = cv2.erode(
        take.astype(np.uint8), cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (erode_d, erode_d))
    ).astype(bool)
    if not take.any():
        return take
    # Speckle dots: connected take smaller than a thousandth of the mask
    # cannot be a pane; they would ship as isolated view dots in white.
    n, labels, stats, _ = cv2.connectedComponentsWithStats(take.astype(np.uint8), 8)
    if n > 2:
        floor = max(1.0, float(mask.sum()) * 0.001)
        small = np.where(stats[1:, cv2.CC_STAT_AREA] < floor)[0] + 1
        take = take & ~np.isin(labels, small)
    return take


def choose_view_frame(
    frames: list[np.ndarray],
    mask: np.ndarray,
    merge_rgb: np.ndarray,
    union: np.ndarray | None = None,
) -> tuple[int | None, str]:
    """The one frame that pulls this window, plus the plain-words reason.

    One continuous source per window: mixing frames per pixel is what
    made views patchy. Scores each light-matched frame by blown glass it
    would fix, minus the blown glass it would leave unfixed (murk in the
    view where the merge blew out). No fix anywhere means a clean window:
    (None, reason), and the window keeps the merge pixel-exact.
    """
    from listing_partner.checks import PULL_GAIN_HI, PULL_GAIN_LO

    if not frames:
        raise ValueError("no bracket frames to pull the view from")
    if union is None:
        union = mask
    merge_max = merge_rgb.max(axis=2)
    best, best_score, best_fixed = None, 0.0, 0
    matched_any = False
    for i, frame in enumerate(frames):
        gain = _ring_gain(merge_rgb, frame, union)
        if not PULL_GAIN_LO <= gain <= PULL_GAIN_HI:
            continue
        matched_any = True
        take = _take_mask(merge_rgb, frame, mask)
        fixed = float(take.sum())
        if fixed <= 0:
            continue
        view_gray = cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY).astype(np.float32)
        murk = float(((merge_max >= SHOULDER_FLOOR) & (view_gray < VIEW_DETAIL_FLOOR)).sum())
        score = fixed - 0.5 * murk
        if best is None or score > best_score:
            best, best_score, best_fixed = i, score, int(take.sum())
    if best is None:
        if not matched_any:
            return None, "no bracket frame matches the room light here"
        if (merge_rgb.max(axis=2) >= SHOULDER_FLOOR)[mask].any():
            return None, "glass is blown but no frame holds a detailed view to pull"
        return None, "nothing blown to fix: the merge already holds the glass"
    return best, f"fixes {best_fixed} blown pixels"


def pull_window(
    merge_rgb: np.ndarray,
    view_rgb: np.ndarray,
    mask: np.ndarray,
    union: np.ndarray | None = None,
) -> tuple[np.ndarray, dict]:
    """Fill blown glass from one real view frame, glass only.

    The view lands at its native gain: no rescale ever shifts its hue.
    Taken glass pixels never reach near-white (see _take_mask), so no
    clamp or cap shapes the measurement; filled sky-gap holes match the
    merge's own white pixel for pixel. The feather ramps up inside the
    replaced glass and is exactly zero outside it, so the blend never
    reaches the frame: no dark outline, no smear, nothing changes
    outside the mask. When the view light does not match the room the
    pull refuses and reports why instead of scarring trim.
    Returns the pulled photo and info (take_px, rim_gain, refused).
    """
    from listing_partner.checks import PULL_GAIN_HI, PULL_GAIN_LO

    if union is None:
        union = mask
    rim_gain = _ring_gain(merge_rgb, view_rgb, union)
    info = {"take_px": 0, "rim_gain": round(rim_gain, 3), "refused": None}
    if not PULL_GAIN_LO <= rim_gain <= PULL_GAIN_HI:
        info["refused"] = (
            f"view light does not match the room (ratio {rim_gain:.2f}); "
            "matching the trim would blow the glass"
        )
        return merge_rgb.copy(), info
    take = _take_mask(merge_rgb, view_rgb, mask)
    info["take_px"] = int(take.sum())
    if not take.any():
        return merge_rgb.copy(), info
    feather = max(2, int(round(max(mask.shape) * 0.002)))
    dist = cv2.distanceTransform(take.astype(np.uint8), cv2.DIST_L2, 3)
    alpha = np.clip(dist / feather, 0.0, 1.0).astype(np.float32)
    pulled = (
        merge_rgb.astype(np.float32) * (1 - alpha[:, :, None])
        + view_rgb.astype(np.float32) * alpha[:, :, None]
    )
    return np.clip(pulled, 0, 255).astype(np.uint8), info


def save_mask_png(mask: np.ndarray, path: Path) -> None:
    """Glass-white mask PNG for the review page and the package record."""
    Image.fromarray((mask.astype(np.uint8)) * 255, mode="L").save(path)
