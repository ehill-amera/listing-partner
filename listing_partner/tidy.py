"""Honest tidy: remove carry-out clutter only, inside a saved mask, and prove it.

Order per kept photo: damage list first (every box is a protected zone), SAM
finds candidates from a fixed list, Muse Spark confirms each, Muse Image fills,
then only masked pixels are copied back. Tidied photos are PNG because a JPEG
re-encode would change pixels outside the mask.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
from datetime import datetime, timezone
from functools import partial
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from listing_partner import curate, fill_check, meta_client, segment, tidy_page
from listing_partner.run_listing import ledger_by_model

SPARK_MODEL = "muse-spark-1.3"
UNIT_BUDGET_USD = 5.00
SPARK_MAX_TOKENS = 4096
#: Listing objects and naming a kind ran past 4096 tokens on 4 of 9 home-a candidates.
CONFIRM_MAX_TOKENS = 16384
#: Reasons that mean no one judged the item. It stays, and the next run asks again.
_NO_VERDICT = ("Muse Spark's verdict failed", "Muse Spark's verdict could not be read")

#: The only things a tidy may ever target (contract 04, section B).
CLUTTER_LIST = (
    "trash bin",
    "cardboard box",
    "plastic bag",
    "packing material",
    "loose cable or cord",
    "laundry basket",
    "cleaning supplies",
    "shoes",
    "bucket",
    "ladder",
    "paint can",
    "tools",
)
#: The list before the navigator took hoses off it. Findings saved under it stay
#: good, less any hose, because the current list is the same list minus that item.
_LIST_WITH_HOSE = (*CLUTTER_LIST[:5], "hose", *CLUTTER_LIST[5:])

#: What the self-check can come back as. Only a reply Spark actually gave can
#: be a disagreement.
CHECK_PASS = "pass"
CHECK_DISAGREE = "disagree"
CHECK_INCOMPLETE = "did not complete"
SELFCHECK_INCOMPLETE_REASON = "self-check did not complete"
#: Why a photo ships untidied when the measured fill check fails twice.
FILL_REASON = "fill did not match the surrounding surface"

#: Mask growth for shadows, as a fixed share of the photo's long side. SAM
#: masks arrive at 1024 px and scale up by nearest neighbour, so at 5900 px
#: this is 24 px, about four mask pixels.
GROW_SHARE = 0.004
#: Nothing a person carries out in a day fills a tenth of a frame.
MAX_MASK_SHARE = 0.10
#: Fill blends over this many pixels, inward from the mask's edge only.
FEATHER_PX = 6
#: Long side of what Muse Image is sent. Its reply is refit to the crop.
EDIT_LONG_SIDE = 1536
#: Mean gray difference allowed in the ring around the mask, between the
#: generated picture and the finished photo. Over this, the picture moved.
ALIGN_MAX_GRAY = 12.0
RING_PX = 12
#: Share of the fill still holding the paint colour that fails the fill.
PAINT_LEFT_MAX = 0.01
PAINT = (255, 0, 255)

DAMAGE_PROMPT = (
    "You are listing visible damage for a maintenance coordinator. Look at this "
    "photo of a rental property and list every visible stain, crack, hole, scuff, "
    "peeling paint, water mark, broken item or missing item. Reply with JSON only: "
    '{"damage": [{"box": [left, top, right, bottom], "note": "plain words"}]}. Box '
    "numbers run 0 to 1000 across and down this image. Reply with an empty list if "
    "you see none. Normal wear of a clean surface, shadows and reflections are not "
    "damage."
)
#: What Spark was asked before review 4658909. Findings saved under it keep their
#: damage list and masks, and only their confirmation is asked again.
_CONFIRM_PROMPT_BEFORE = (
    "A red box marks a candidate for removal from a rental listing photo. It may be "
    "removed only if a person could carry it out in a day and it is not part of the "
    "property. Reject anything that is a fixture, part of the building, wired or "
    "plumbed in, furniture or an appliance that conveys with the unit, or damage. "
    "Say whether it truly is the kind of item the finder named. Say whether it is "
    "attached at either end: a cord plugged into an outlet or a device, a blind's "
    "pull cord, a hose on a spigot. Attached things stay. Reply with JSON only: "
    '{"confirm": true or false, "is_that_item": true or false, '
    '"attached": true or false, "reason": "plain words"}.'
)
#: Spark is not told what the finder called the candidate: asked "is it that",
#: it agreed about a red cup on home-a 003. It names the kind itself instead, and
#: lists what the outline covers, so one mask over two objects shows.
CONFIRM_PROMPT = (
    "A red outline marks exactly what would be removed from this rental listing photo. "
    "The first image is the whole room and the second is a zoom on the outline. "
    "List every separate object the outline covers, however small or partly covered, "
    "in plain words: a pair of shoes or a stack of the same boxes is one object. "
    "Then name the kind of thing it is, using only one of these kinds or the word none: "
    + ", ".join(CLUTTER_LIST)
    + ". Cups, dishes, food, decor and personal things are none. Cleaning supplies means "
    "products for cleaning, such as spray bottles or soap. It may be removed only if a person "
    "could carry it out in a day and it is not part of the property. Reject anything that is "
    "a fixture, part of the building, wired or plumbed in, furniture or an appliance that "
    "conveys with the unit, or damage. Say whether it is attached at either end: a cord "
    "plugged into an outlet or a device, a blind's pull cord, a hose on a spigot. Attached "
    "things stay. Reply with JSON only: "
    '{"objects": ["plain words"], "kind": "one kind or none", "confirm": true or false, '
    '"attached": true or false, "reason": "plain words"}.'
)
SELFCHECK_PROMPT = (
    "These two images show the same area of a rental listing photo, before and then "
    "after an edit meant to remove only carry-out clutter. Judge three things: is the "
    "listed item gone, did anything that is part of the property change, was any "
    "damage softened or hidden, was any object or detail added that the first image "
    "does not show (an outlet, a pipe, a mark), does any part of the listed item "
    "remain, and is the filled area smeared. Be strict. A smear counts as the property "
    "changing. Reply with JSON only: "
    '{"item_gone": true or false, "property_changed": true or false, '
    '"damage_softened": true or false, "object_added": true or false, '
    '"item_remains": true or false, "reason": "plain words"}.'
)
EDIT_PROMPT = (
    "The flat magenta area marks where a loose object was removed from this photo. "
    "Paint only that area, continuing the surfaces around it naturally: same floor, "
    "wall or ground, same light. Do not add any object, outlet, pipe, mark or detail. "
    "Change nothing else, and do not move, crop or reframe the picture. No magenta may remain."
)


class BudgetExceeded(Exception):
    """A call's reservation would pass this unit's budget."""


class PhotoFailed(Exception):
    """This photo ships untidied, for the reason in the message."""


def is_paint(rgb: np.ndarray) -> np.ndarray:
    return (rgb[..., 0] > 200) & (rgb[..., 1] < 70) & (rgb[..., 2] > 200)


def grow_px(shape: tuple) -> int:
    return max(1, int(round(max(shape[:2]) * GROW_SHARE)))


def _sha(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _load(path: Path) -> np.ndarray:
    with Image.open(path) as handle:
        return np.asarray(handle.convert("RGB"))


def _json_reply(text: str) -> dict:
    return curate._json_object(text)


def parse_damage(text: str, view: tuple) -> list[dict]:
    """Damage items from one look, in photo pixels. Raises on anything it
    cannot trust: a wrong empty list would leave real damage unprotected."""
    data = _json_reply(text)
    items = data.get("damage")
    if not isinstance(items, list):
        raise ValueError("damage reply has no list")
    left, top, right, bottom = view
    width, height = right - left, bottom - top
    out = []
    for item in items:
        box = item.get("box") if isinstance(item, dict) else None
        note = item.get("note") if isinstance(item, dict) else None
        if not isinstance(box, list) or len(box) != 4:
            raise ValueError(f"damage box unusable: {box!r}")
        if not all(isinstance(v, (int, float)) and 0 <= v <= 1000 for v in box):
            raise ValueError(f"damage box out of range: {box!r}")
        if box[0] >= box[2] or box[1] >= box[3]:
            raise ValueError(f"damage box inverted: {box!r}")
        if not isinstance(note, str) or not note.strip():
            raise ValueError("damage item has no note")
        out.append(
            {
                "box": (
                    left + int(np.floor(box[0] * width / 1000)),
                    top + int(np.floor(box[1] * height / 1000)),
                    left + int(np.ceil(box[2] * width / 1000)),
                    top + int(np.ceil(box[3] * height / 1000)),
                ),
                "note": note.strip(),
            }
        )
    return out


def parse_confirm(text: str, label: str) -> tuple[bool, str]:
    """(confirmed, reason). Every answer must be explicit and good: a confirmation
    with no reason, no list of objects or no blind name for the item never removes."""
    try:
        data = _json_reply(text)
    except ValueError:
        return False, "Muse Spark's verdict could not be read"
    reason = data.get("reason")
    if not isinstance(reason, str) or not reason.strip():
        return False, "Muse Spark gave no reason, so it stays"
    reason = reason.strip()
    objects = data.get("objects")
    if not isinstance(objects, list) or not objects:
        return False, f"Muse Spark did not list what the outline covers: {reason}"
    if len(objects) > 1:
        names = ", ".join(str(item) for item in objects)
        return False, f"the outline covers more than one object: {names}"
    if data.get("kind") != label:
        return False, f"Muse Spark did not name it {label}: {reason}"
    return data.get("confirm") is True and data.get("attached") is False, reason


def _no_verdict(detail: str) -> dict:
    return {
        "pass": False,
        "completed": False,
        "reason": SELFCHECK_INCOMPLETE_REASON,
        "detail": detail,
    }


def parse_selfcheck(text: str) -> dict:
    """The verdict. Only explicit good answers pass. A reply holding no answer
    at all is not a verdict, so it cannot count as Spark disagreeing."""
    try:
        data = _json_reply(text)
    except ValueError:
        return _no_verdict("reply could not be read")
    answers = ("item_gone", "property_changed", "damage_softened", "object_added", "item_remains")
    if not any(isinstance(data.get(name), bool) for name in answers):
        return _no_verdict("reply held no answers")
    good = (
        data.get("item_gone") is True
        and data.get("property_changed") is False
        and data.get("damage_softened") is False
        and data.get("object_added") is False
        and data.get("item_remains") is False
    )
    return {
        "pass": good,
        "completed": True,
        "item_gone": data.get("item_gone"),
        "property_changed": data.get("property_changed"),
        "damage_softened": data.get("damage_softened"),
        "object_added": data.get("object_added"),
        "item_remains": data.get("item_remains"),
        "reason": str(data.get("reason") or "no reason given"),
    }


def _damage_mask(damage: list[dict], shape: tuple) -> np.ndarray:
    zone = np.zeros(shape[:2], bool)
    for item in damage:
        left, top, right, bottom = item["box"]
        zone[max(0, top) : max(0, bottom), max(0, left) : max(0, right)] = True
    return zone


def build_final_mask(items: list[dict], damage: list[dict], shape: tuple) -> tuple:
    """(final mask, removed, left in place) from the confirmed candidates.

    A candidate whose own mask touches damage stays whole. When only its grown
    margin touches damage, those margin pixels go and the item is still removed.
    """
    shape = shape[:2]
    zone = _damage_mask(damage, shape)
    size = 2 * grow_px(shape) + 1
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (size, size))
    final = np.zeros(shape, bool)
    removed, left = [], []
    for item in items:
        if item["label"] not in CLUTTER_LIST:
            raise ValueError(f"{item['label']!r} is not on the clutter list")
        mask = item["mask"]
        if (mask & zone).any():
            left.append({"label": item["label"], "reason": "left in place: overlaps damage"})
        elif mask.sum() > MAX_MASK_SHARE * mask.size:
            left.append(
                {
                    "label": item["label"],
                    "reason": "left in place: too large to be something carried out",
                }
            )
        else:
            final |= cv2.dilate(mask.astype(np.uint8), kernel).astype(bool)
            removed.append({"label": item["label"], "reason": item["reason"]})
    return final & ~zone, removed, left


def composite(finished: np.ndarray, generated: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """Generated pixels inside the mask, blended inward from its edge. Every
    pixel outside the mask is copied from the finished photo."""
    distance = cv2.distanceTransform(mask.astype(np.uint8), cv2.DIST_L2, 3)
    alpha = np.clip(distance / FEATHER_PX, 0.0, 1.0)[..., None]
    blended = np.rint(finished * (1.0 - alpha) + generated * alpha).astype(np.uint8)
    out = finished.copy()
    out[mask] = blended[mask]
    return out


def measure(finished_path, tidied_path, mask_path, damage: list[dict]) -> dict:
    """Pixel proof, always read back from the saved files."""
    finished, tidied = _load(finished_path), _load(tidied_path)
    with Image.open(mask_path) as handle:
        mask = np.asarray(handle.convert("L")) > 0
    if finished.shape != tidied.shape or finished.shape[:2] != mask.shape:
        raise ValueError(f"sizes differ: {finished.shape}, {tidied.shape}, {mask.shape}")
    changed = (finished != tidied).any(axis=2)
    return {
        "mask_pixels": int(mask.sum()),
        "outside_changed_pixels": int((changed & ~mask).sum()),
        "inside_changed_pixels": int((changed & mask).sum()),
        "damage_overlap_pixels": int((mask & _damage_mask(damage, mask.shape)).sum()),
    }


def pixels_pass(numbers: dict) -> bool:
    return (
        numbers["outside_changed_pixels"] == 0
        and numbers["damage_overlap_pixels"] == 0
        and numbers["inside_changed_pixels"] > 0
    )


def ship_decision(pixels_ok: bool, spark: str, recheck: dict) -> tuple[str, str]:
    """All three must pass. The re-check's reason comes first when it fails."""
    if not recheck["pass"]:
        return "untidied", recheck["reason"]
    if pixels_ok and spark == CHECK_PASS:
        return "tidied", ""
    if spark == CHECK_INCOMPLETE:
        if pixels_ok:
            return "untidied", SELFCHECK_INCOMPLETE_REASON
        return "untidied", f"the pixel measurement failed and {SELFCHECK_INCOMPLETE_REASON}"
    if pixels_ok:
        return "untidied", "pixels passed but Muse Spark's self-check disagrees"
    if spark == CHECK_PASS:
        return "untidied", "Muse Spark's self-check passed but the pixel measurement disagrees"
    return "untidied", "both the pixel measurement and Muse Spark's self-check failed"


def regions(mask: np.ndarray) -> list[dict]:
    """Crops around the mask, with context. Crops that would overlap merge."""
    h, w = mask.shape
    floor = max(32, int(round(max(h, w) * 0.04)))
    count, _, stats, _ = cv2.connectedComponentsWithStats(mask.astype(np.uint8), connectivity=8)
    boxes = []
    for index in range(1, count):
        x, y, bw, bh = (int(v) for v in stats[index][:4])
        pad = max(floor, max(bw, bh))
        boxes.append((max(0, x - pad), max(0, y - pad), min(w, x + bw + pad), min(h, y + bh + pad)))
    merged = True
    while merged:
        merged = False
        for i in range(len(boxes)):
            for j in range(i + 1, len(boxes)):
                a, b = boxes[i], boxes[j]
                if a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]:
                    boxes[i] = (min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3]))
                    del boxes[j]
                    merged = True
                    break
            if merged:
                break
    return [{"box": box} for box in boxes]


def _save_jpeg(rgb: np.ndarray, path: Path, long_side: int, quality: int = 90) -> None:
    Path(path).write_bytes(segment.jpeg_bytes(rgb, long_side=long_side, quality=quality))


class _Meta:
    """Capped client calls behind this unit's budget."""

    def __init__(self, transport, ledger_path, baseline, budget):
        self.transport, self.ledger, self.baseline, self.budget = (
            transport,
            ledger_path,
            baseline,
            budget,
        )

    def spent(self) -> float:
        return meta_client.read_spend_total(self.ledger) - self.baseline

    def _guard(self, estimate: float) -> None:
        if self.spent() + estimate > self.budget:
            raise BudgetExceeded(
                f"${self.spent():.4f} + ${estimate:.4f} over the ${self.budget:.2f} unit budget"
            )

    def spark(self, prompt: str, images: list[bytes], max_tokens: int = SPARK_MAX_TOKENS) -> str:
        self._guard(meta_client.reserve_text_usd(SPARK_MODEL, prompt, max_tokens, len(images)))
        return meta_client.call_meta_text(
            SPARK_MODEL,
            prompt,
            max_tokens,
            images=images,
            transport=self.transport,
            ledger_path=self.ledger,
        )["text"]

    def sam(self, prompt: str, jpeg: bytes) -> list[dict]:
        self._guard(meta_client.reserve_segment_usd())
        return segment.find_candidates(
            jpeg, prompt, transport=self.transport, ledger_path=self.ledger
        )

    def edit(self, jpeg: bytes, size: str) -> bytes:
        self._guard(meta_client.reserve_image_usd())
        return meta_client.call_meta_image_edit(
            meta_client.IMAGE_MODEL,
            EDIT_PROMPT,
            jpeg,
            size=size,
            transport=self.transport,
            ledger_path=self.ledger,
        )["image"]


_RECOVERABLE = (meta_client.TransportFailed, meta_client.ResponseUnreadable)


def _views(w: int, h: int) -> list[tuple]:
    """The whole photo, then four quarters overlapping by a tenth."""
    mx, my = int(w * 0.55), int(h * 0.55)
    return [
        (0, 0, w, h),
        (0, 0, mx, my),
        (w - mx, 0, w, my),
        (0, h - my, mx, h),
        (w - mx, h - my, w, h),
    ]


def _iou(a: tuple, b: tuple) -> float:
    ix = max(0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union else 0.0


def list_damage(rgb: np.ndarray, meta: _Meta) -> list[dict]:
    h, w = rgb.shape[:2]
    found: list[dict] = []
    for view in _views(w, h):
        jpeg = segment.jpeg_bytes(rgb[view[1] : view[3], view[0] : view[2]])
        for attempt in (1, 2):
            try:
                items = parse_damage(meta.spark(DAMAGE_PROMPT, [jpeg]), view)
                break
            except (*_RECOVERABLE, ValueError) as exc:
                if attempt == 2:
                    raise PhotoFailed(f"damage list unreadable, so no tidy: {exc}") from exc
        for item in items:
            if all(_iou(item["box"], other["box"]) < 0.5 for other in found):
                found.append(item)
    return found


def _save_damage_crops(rgb: np.ndarray, damage: list[dict], folder: Path) -> None:
    h, w = rgb.shape[:2]
    for number, item in enumerate(damage, 1):
        left, top, right, bottom = item["box"]
        pad = max(right - left, bottom - top) // 2
        crop = rgb[
            max(0, top - pad) : min(h, bottom + pad), max(0, left - pad) : min(w, right + pad)
        ]
        name = f"damage_{number}.jpg"
        _save_jpeg(crop, folder / name, 640)
        item["crop"] = name


def find_clutter(jpeg: bytes, meta: _Meta) -> list[dict]:
    """SAM, one fixed prompt at a time. The same region found twice is one."""
    found: list[dict] = []
    for label in CLUTTER_LIST:
        for attempt in (1, 2):
            try:
                candidates = meta.sam(label, jpeg)
                break
            except _RECOVERABLE as exc:
                if attempt == 2:
                    raise PhotoFailed(f"SAM 3.1 failed on {label}: {exc}") from exc
        for candidate in candidates:
            if all(_iou(candidate["box"], other["box"]) < 0.5 for other in found):
                found.append({**candidate, "label": label})
    return found


def _outlined(small: np.ndarray, candidate: dict) -> np.ndarray:
    """The photo with the mask's own outline on it: a box hides what the mask
    actually takes, which is how a second object went unseen."""
    canvas = small.copy()
    mask = cv2.resize(
        candidate["mask"].astype(np.uint8),
        (small.shape[1], small.shape[0]),
        interpolation=cv2.INTER_NEAREST,
    )
    contours, _ = cv2.findContours(mask, cv2.RETR_LIST, cv2.CHAIN_APPROX_NONE)
    cv2.drawContours(canvas, contours, -1, (255, 0, 0), 2)
    return canvas


def confirm_clutter(small: np.ndarray, found: list[dict], meta: _Meta) -> list[dict]:
    for candidate in found:
        marked = _outlined(small, candidate)
        crop = segment._zoom_crop(marked, candidate["box"])
        # A zoom alone loses the room, so Spark sees both.
        images = [segment.jpeg_bytes(marked), segment.jpeg_bytes(crop)]
        for attempt in (1, 2):
            try:
                reply = meta.spark(CONFIRM_PROMPT, images, CONFIRM_MAX_TOKENS)
                candidate["confirmed"], candidate["reason"] = parse_confirm(
                    reply, candidate["label"]
                )
                break
            except _RECOVERABLE as exc:
                candidate["confirmed"] = False
                candidate["reason"] = f"Muse Spark's verdict failed, so it stays: {exc}"
    return found


def _stage_key(digest: str, clutter_list: tuple = (), confirm_prompt: str = "") -> str:
    return hashlib.sha256(
        "\n".join(
            [
                digest,
                DAMAGE_PROMPT,
                confirm_prompt or CONFIRM_PROMPT,
                *(clutter_list or CLUTTER_LIST),
            ]
        ).encode()
    ).hexdigest()


def _save_findings(stage, masks_path, key, sent, damage, found) -> None:
    np.savez_compressed(masks_path, **{f"m{i}": c["mask"] for i, c in enumerate(found)})
    stage.write_text(
        json.dumps(
            {
                "key": key,
                "sent": sent,
                "damage": damage,
                "found": [{k: v for k, v in c.items() if k != "mask"} for c in found],
            }
        )
    )


def _findings(rgb: np.ndarray, digest: str, folder: Path, meta: _Meta) -> tuple:
    """Damage and confirmed candidates. Saved, so a rerun does not pay twice
    for findings made on these exact pixels with these exact prompts. Findings
    from the earlier confirm prompt keep their damage and masks, and are only
    confirmed again."""
    stage, masks_path = folder / "findings.json", folder / "findings_masks.npz"
    key = _stage_key(digest)
    jpeg = segment.jpeg_bytes(rgb)
    with Image.open(io.BytesIO(jpeg)) as handle:
        sent_w, sent_h = handle.size
        small = np.asarray(handle.convert("RGB"))
    if stage.exists() and masks_path.exists():
        saved = json.loads(stage.read_text())
        current = (key, _stage_key(digest, _LIST_WITH_HOSE))
        earlier = tuple(
            _stage_key(digest, listed, _CONFIRM_PROMPT_BEFORE)
            for listed in (CLUTTER_LIST, _LIST_WITH_HOSE)
        )
        if saved["key"] in current + earlier:
            with np.load(masks_path) as masks:
                found = [
                    {**c, "box": tuple(c["box"]), "mask": masks[f"m{i}"]}
                    for i, c in enumerate(saved["found"])
                    if c["label"] in CLUTTER_LIST
                ]
            damage = [{**d, "box": tuple(d["box"])} for d in saved["damage"]]
            ask = (
                found
                if saved["key"] in earlier
                else [c for c in found if c["reason"].startswith(_NO_VERDICT)]
            )
            if ask:
                confirm_clutter(small, ask, meta)
                _save_findings(stage, masks_path, key, saved["sent"], damage, found)
            return damage, found
    damage = list_damage(rgb, meta)
    found = confirm_clutter(small, find_clutter(jpeg, meta), meta)
    _save_findings(stage, masks_path, key, [sent_w, sent_h], damage, found)
    return damage, found


def blend_fill(crop: np.ndarray, fill: np.ndarray, inside: np.ndarray) -> np.ndarray:
    """Fit the fill to the photo at the mask's edge, so a brightness slope
    between the generated picture and the photo leaves no visible patch. The
    composite still takes only masked pixels from this result."""
    if not inside.any():
        return fill
    pad = 4
    wrap = partial(cv2.copyMakeBorder, top=pad, bottom=pad, left=pad, right=pad)
    source = wrap(fill, borderType=cv2.BORDER_REPLICATE)
    target = wrap(crop, borderType=cv2.BORDER_REPLICATE)
    area = wrap((inside * 255).astype(np.uint8), borderType=cv2.BORDER_CONSTANT, value=0)
    x, y, w, h = cv2.boundingRect(area)
    out = cv2.seamlessClone(source, target, area, (x + w // 2, y + h // 2), cv2.NORMAL_CLONE)
    return out[pad:-pad, pad:-pad]


def _fill_region(finished: np.ndarray, mask: np.ndarray, box: tuple, meta: _Meta) -> np.ndarray:
    """Generated pixels for one crop, refit, toned to the ring, and checked."""
    left, top, right, bottom = box
    crop, inside = finished[top:bottom, left:right], mask[top:bottom, left:right]
    painted = crop.copy()
    painted[inside] = PAINT
    jpeg = segment.jpeg_bytes(painted, long_side=EDIT_LONG_SIDE, quality=95)
    with Image.open(io.BytesIO(jpeg)) as handle:
        size = f"{handle.size[0]}x{handle.size[1]}"
    raw = None
    for attempt in (1, 2):
        try:
            raw = meta.edit(jpeg, size)
            break
        except _RECOVERABLE as exc:
            if attempt == 2:
                raise PhotoFailed(f"Muse Image failed: {exc}") from exc
    with Image.open(io.BytesIO(raw)) as handle:
        reply = np.asarray(handle.convert("RGB"))
    height, width = crop.shape[:2]
    interp = cv2.INTER_CUBIC if reply.shape[1] < width else cv2.INTER_AREA
    fill = cv2.resize(reply, (width, height), interpolation=interp)

    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * RING_PX + 1, 2 * RING_PX + 1))
    ring = cv2.dilate(inside.astype(np.uint8), kernel).astype(bool) & ~inside
    if ring.any():
        offset = crop[ring].astype(float).mean(axis=0) - fill[ring].astype(float).mean(axis=0)
        fill = np.clip(fill.astype(float) + offset, 0, 255).astype(np.uint8)
        gray_a = cv2.cvtColor(crop, cv2.COLOR_RGB2GRAY).astype(float)
        gray_b = cv2.cvtColor(fill, cv2.COLOR_RGB2GRAY).astype(float)
        drift = float(np.abs(gray_a[ring] - gray_b[ring]).mean())
        if drift > ALIGN_MAX_GRAY:
            raise PhotoFailed(
                f"Muse Image's picture does not line up with the photo: "
                f"ring difference {drift:.1f}, limit {ALIGN_MAX_GRAY:.1f}"
            )
    left_over = float(is_paint(fill)[inside].mean()) if inside.any() else 0.0
    if left_over > PAINT_LEFT_MAX:
        raise PhotoFailed(f"Muse Image left {left_over:.1%} of the mask unpainted")
    return blend_fill(crop, fill, inside)


def _self_check(
    before: np.ndarray, after: np.ndarray, spots: list[dict], meta: _Meta, labels
) -> dict:
    prompt = f"{SELFCHECK_PROMPT} The listed items are: {', '.join(labels)}."
    verdicts = []
    for spot in spots:
        left, top, right, bottom = spot["box"]
        images = [
            segment.jpeg_bytes(before[top:bottom, left:right]),
            segment.jpeg_bytes(after[top:bottom, left:right]),
        ]
        try:
            verdicts.append(parse_selfcheck(meta.spark(prompt, images)))
        except _RECOVERABLE as exc:
            verdicts.append(_no_verdict(str(exc)))
    reasons = list(dict.fromkeys(v["reason"] for v in verdicts))
    if any(v["completed"] and not v["pass"] for v in verdicts):
        state = CHECK_DISAGREE
    elif verdicts and all(v["pass"] for v in verdicts):
        state = CHECK_PASS
    else:
        state = CHECK_INCOMPLETE
    return {
        "pass": state == CHECK_PASS,
        "state": state,
        "reason": "; ".join(reasons) or SELFCHECK_INCOMPLETE_REASON,
        "areas": verdicts,
    }


def recheck_fill(tidied: np.ndarray, mask: np.ndarray, removed: list[dict], meta: _Meta) -> dict:
    """SAM again on the tidied pixels, with the prompt that found each item.

    The view is built the way the finding's was, so only the fill differs from
    what SAM saw then. Any overlap with the mask, one pixel included, fails: a
    fill is only proven by SAM no longer finding the item there. A prompt that
    cannot be asked also fails, because an unasked question proves nothing.
    """
    jpeg = segment.jpeg_bytes(tidied)
    h, w = mask.shape
    found_by_label: dict[str, int] = {}
    errors = []
    for label in dict.fromkeys(item["label"] for item in removed):
        for attempt in (1, 2):
            try:
                candidates = meta.sam(label, jpeg)
            except (*_RECOVERABLE, ValueError) as exc:
                if attempt == 2:
                    errors.append(f"{label}: {exc}")
                continue
            hit = np.zeros((h, w), bool)
            for candidate in candidates:
                hit |= cv2.resize(
                    candidate["mask"].astype(np.uint8), (w, h), interpolation=cv2.INTER_NEAREST
                ).astype(bool)
            found_by_label[label] = int((hit & mask).sum())
            break
    items = [
        {"label": item["label"], "found_pixels": found_by_label.get(item["label"])}
        for item in removed
    ]
    still = [label for label, pixels in found_by_label.items() if pixels]
    reasons = [f"SAM 3.1 still finds {label} in the filled area" for label in still]
    reasons += [f"SAM 3.1 re-check could not run on {error}" for error in errors]
    return {"pass": not reasons, "items": items, "reason": "; ".join(reasons)}


def _measured_fill(finished: np.ndarray, final: np.ndarray, spots: list[dict], meta) -> tuple:
    """(composite, readings). A spot whose fill fails the measured check gets one
    more Muse Image call; what comes back is measured again and stands."""
    generated = finished.copy()
    for spot in spots:
        left, top, right, bottom = spot["box"]
        generated[top:bottom, left:right] = _fill_region(finished, final, spot["box"], meta)
    tidied = composite(finished, generated, final)
    reading = fill_check.check_fill(finished, tidied, final)
    if reading["pass"]:
        return tidied, reading
    failed = [area["box"] for area in reading["areas"] if not area["pass"]]
    for spot in spots:
        left, top, right, bottom = spot["box"]
        if any(b[0] >= left and b[1] >= top and b[2] <= right and b[3] <= bottom for b in failed):
            generated[top:bottom, left:right] = _fill_region(finished, final, spot["box"], meta)
    tidied = composite(finished, generated, final)
    return tidied, {**fill_check.check_fill(finished, tidied, final), "retried": True}


def _save_page_images(
    before: np.ndarray, after: np.ndarray, mask: np.ndarray, folder: Path
) -> None:
    long_side = 2048
    _save_jpeg(before, folder / "before.jpg", long_side)
    _save_jpeg(after, folder / "after.jpg", long_side)
    h, w = mask.shape
    scale = min(1.0, long_side / max(h, w))
    size = (int(round(w * scale)), int(round(h * scale)))
    small = cv2.resize(mask.astype(np.uint8), size, interpolation=cv2.INTER_NEAREST) > 0
    overlay = np.zeros((*small.shape, 4), np.uint8)
    overlay[small] = (255, 0, 0, 200)
    Image.fromarray(overlay, mode="RGBA").save(folder / "mask_overlay.png")


def _clear_old_outputs(folder: Path) -> None:
    for name in (
        "tidied.png",
        "rejected.png",
        "mask.png",
        "before.jpg",
        "after.jpg",
        "mask_overlay.png",
    ):
        (folder / name).unlink(missing_ok=True)


def tidy_photo(kept: dict, output_dir: Path, meta: _Meta) -> dict:
    pid = kept["id"]
    source = output_dir / "finished" / f"{pid}.jpg"
    folder = output_dir / "tidy" / pid
    folder.mkdir(parents=True, exist_ok=True)
    _clear_old_outputs(folder)
    digest = _sha(source)
    record = {
        "id": pid,
        "room": kept.get("room", ""),
        "sha256": digest,
        "status": "nothing to tidy",
        "reason": "",
        "damage": [],
        "removed": [],
        "not_removed": [],
        "rejected": [],
        "left_in_place": [],
        "selfcheck": None,
        "recheck": None,
        "measure": None,
        "fill_check": None,
    }
    finished = _load(source)
    h, w = finished.shape[:2]
    removed: list[dict] = []
    try:
        damage, found = _findings(finished, digest, folder, meta)
        _save_damage_crops(finished, damage, folder)
        record["damage"] = damage
        record["rejected"] = [
            {"label": c["label"], "reason": c["reason"]} for c in found if not c["confirmed"]
        ]
        confirmed = []
        for candidate in found:
            if candidate["confirmed"]:
                mask = cv2.resize(
                    candidate["mask"].astype(np.uint8), (w, h), interpolation=cv2.INTER_NEAREST
                ).astype(bool)
                confirmed.append(
                    {"label": candidate["label"], "reason": candidate["reason"], "mask": mask}
                )
        final, removed, left = build_final_mask(confirmed, damage, finished.shape)
        record["left_in_place"] = left
        if not final.any():
            return record
        spots = regions(final)
        tidied, record["fill_check"] = _measured_fill(finished, final, spots, meta)
    except PhotoFailed as exc:
        record["status"], record["reason"] = "untidied", str(exc)
        record["not_removed"] = [{"label": item["label"], "reason": str(exc)} for item in removed]
        return record

    with Image.open(source) as handle:
        icc = handle.info.get("icc_profile")
    segment.save_mask_png(final, folder / "mask.png")
    Image.fromarray(tidied).save(folder / "tidied.png", icc_profile=icc)
    record["measure"] = measure(source, folder / "tidied.png", folder / "mask.png", damage)
    if not record["fill_check"]["pass"]:
        # Measured failure: no reason to pay Spark or SAM to look at this fill.
        record["status"], record["reason"] = "untidied", FILL_REASON
        record["not_removed"] = [{"label": i["label"], "reason": FILL_REASON} for i in removed]
        (folder / "tidied.png").rename(folder / "rejected.png")
        return record
    record["selfcheck"] = _self_check(
        finished, tidied, spots, meta, [item["label"] for item in removed]
    )
    record["recheck"] = recheck_fill(_load(folder / "tidied.png"), final, removed, meta)
    status, reason = ship_decision(
        pixels_pass(record["measure"]), record["selfcheck"]["state"], record["recheck"]
    )
    record["status"], record["reason"] = status, reason
    if status == "tidied":
        # The only place an item becomes removed: every check on the fill passed.
        record["removed"] = removed
        _save_page_images(finished, tidied, final, folder)
    else:
        record["not_removed"] = [{"label": i["label"], "reason": reason} for i in removed]
        (folder / "tidied.png").rename(folder / "rejected.png")
    return record


def _baseline(path: Path, ledger) -> float:
    """Ledger total when this unit first ran, so reruns count against its budget."""
    if path.exists():
        return float(json.loads(path.read_text())["meta"])
    total = meta_client.read_spend_total(ledger)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"meta": total}))
    return total


def run_tidy(
    *,
    output_dir,
    transport=None,
    ledger_path=None,
    baseline_path=None,
    budget_usd: float = UNIT_BUDGET_USD,
) -> dict:
    output_dir = Path(output_dir)
    saved = curate.load_saved(output_dir / "curation.json", output_dir / "finished")
    ledger = Path(ledger_path) if ledger_path is not None else meta_client.default_ledger_path()
    baseline_file = (
        Path(baseline_path) if baseline_path is not None else ledger.parent / "unit04_baseline.json"
    )
    baseline = _baseline(baseline_file, ledger)
    started = datetime.now(timezone.utc).isoformat()
    meta = _Meta(transport, ledger, baseline, budget_usd)
    photos = [tidy_photo(kept, output_dir, meta) for kept in saved["kept"]]
    tidied = sum(p["status"] == "tidied" for p in photos)
    untidied = sum(p["status"] == "untidied" for p in photos)
    summary = {
        "generated_at": started,
        "result": "tidied" if tidied else ("untidied" if untidied else "nothing to tidy"),
        "tidied": tidied,
        "untidied": untidied,
        "nothing_to_tidy": sum(p["status"] == "nothing to tidy" for p in photos),
        "items_removed": sum(len(p["removed"]) for p in photos),
        "items_failed_recheck": sum(
            item["found_pixels"] != 0
            for p in photos
            if p["recheck"]
            for item in p["recheck"]["items"]
        ),
        "fill_check_failed": sum(p["reason"] == FILL_REASON for p in photos),
        "selfcheck_did_not_complete": sum(
            bool(p["selfcheck"]) and p["selfcheck"]["state"] == CHECK_INCOMPLETE for p in photos
        ),
        "unit_meta_usd": round(meta.spent(), 6),
        "budget_usd": budget_usd,
        "this_run": ledger_by_model(ledger, started),
        "photos": photos,
    }
    (output_dir / "tidy.json").write_text(json.dumps(summary, indent=1))
    (output_dir / "tidy.html").write_text(tidy_page.render(summary))
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--unit", default="unit-a", help="the set name under output/")
    args = parser.parse_args()
    root = Path(__file__).resolve().parent.parent
    summary = run_tidy(output_dir=root / "output" / args.unit)
    print(
        f"{summary['result']}: {summary['tidied']} tidied, {summary['untidied']} untidied, "
        f"{summary['nothing_to_tidy']} nothing to tidy, "
        f"{summary['items_removed']} items removed, "
        f"{summary['items_failed_recheck']} items failed the re-check, "
        f"{summary['fill_check_failed']} photos failed the fill check, "
        f"{summary['selfcheck_did_not_complete']} self-checks did not complete, "
        f"${summary['unit_meta_usd']:.4f}"
    )


if __name__ == "__main__":
    main()
