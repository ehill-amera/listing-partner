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
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from listing_partner import curate, meta_client, segment, tidy_page
from listing_partner.run_listing import ledger_by_model

SPARK_MODEL = "muse-spark-1.3"
UNIT_BUDGET_USD = 5.00
SPARK_MAX_TOKENS = 4096

#: The only things a tidy may ever target (contract 04, section B).
CLUTTER_LIST = (
    "trash bin",
    "cardboard box",
    "plastic bag",
    "packing material",
    "loose cable or cord",
    "hose",
    "laundry basket",
    "cleaning supplies",
    "shoes",
    "bucket",
    "ladder",
    "paint can",
    "tools",
)

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
CONFIRM_PROMPT = (
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
    "wall or ground, same light. Do not add any object, outlet, pipe, mark or detail. Change nothing else, and do "
    "not move, crop or reframe the picture. No magenta may remain."
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


def parse_confirm(text: str) -> tuple[bool, str]:
    """(confirmed, reason). A confirmation with no reason never removes."""
    try:
        data = _json_reply(text)
    except ValueError:
        return False, "Muse Spark's verdict could not be read"
    reason = data.get("reason")
    if not isinstance(reason, str) or not reason.strip():
        return False, "Muse Spark gave no reason, so it stays"
    good = (
        data.get("confirm") is True
        and data.get("is_that_item") is True
        and data.get("attached") is False
    )
    return good, reason.strip()


def parse_selfcheck(text: str) -> dict:
    """The verdict. Only explicit good answers pass."""
    try:
        data = _json_reply(text)
    except ValueError:
        return {"pass": False, "reason": "Muse Spark's self-check could not be read"}
    good = (
        data.get("item_gone") is True
        and data.get("property_changed") is False
        and data.get("damage_softened") is False
        and data.get("object_added") is False
        and data.get("item_remains") is False
    )
    return {
        "pass": good,
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


def ship_decision(pixels_ok: bool, spark_ok: bool) -> tuple[str, str]:
    if pixels_ok and spark_ok:
        return "tidied", ""
    if pixels_ok:
        return "untidied", "pixels passed but Muse Spark's self-check disagrees"
    if spark_ok:
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

    def spark(self, prompt: str, images: list[bytes]) -> str:
        self._guard(
            meta_client.reserve_text_usd(SPARK_MODEL, prompt, SPARK_MAX_TOKENS, len(images))
        )
        return meta_client.call_meta_text(
            SPARK_MODEL,
            prompt,
            SPARK_MAX_TOKENS,
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


def confirm_clutter(small: np.ndarray, found: list[dict], meta: _Meta) -> list[dict]:
    for candidate in found:
        marked = segment.annotate(small, [{**candidate, "object_id": ""}])
        crop = segment._zoom_crop(marked, candidate["box"])
        # A zoom alone loses the room, so Spark sees both.
        prompt = f'{CONFIRM_PROMPT} The finder called this candidate "{candidate["label"]}".'
        try:
            reply = meta.spark(prompt, [segment.jpeg_bytes(marked), segment.jpeg_bytes(crop)])
            candidate["confirmed"], candidate["reason"] = parse_confirm(reply)
        except _RECOVERABLE as exc:
            candidate["confirmed"] = False
            candidate["reason"] = f"Muse Spark's verdict failed, so it stays: {exc}"
    return found


def _stage_key(digest: str) -> str:
    return hashlib.sha256(
        "\n".join([digest, DAMAGE_PROMPT, CONFIRM_PROMPT, *CLUTTER_LIST]).encode()
    ).hexdigest()


def _findings(rgb: np.ndarray, digest: str, folder: Path, meta: _Meta) -> tuple:
    """Damage and confirmed candidates. Saved, so a rerun does not pay twice
    for findings made on these exact pixels with these exact prompts."""
    stage, masks_path = folder / "findings.json", folder / "findings_masks.npz"
    key = _stage_key(digest)
    if stage.exists() and masks_path.exists():
        saved = json.loads(stage.read_text())
        if saved["key"] == key:
            with np.load(masks_path) as masks:
                found = [
                    {**c, "box": tuple(c["box"]), "mask": masks[f"m{i}"]}
                    for i, c in enumerate(saved["found"])
                ]
            damage = [{**d, "box": tuple(d["box"])} for d in saved["damage"]]
            return damage, found
    damage = list_damage(rgb, meta)
    jpeg = segment.jpeg_bytes(rgb)
    with Image.open(io.BytesIO(jpeg)) as handle:
        sent_w, sent_h = handle.size
    with Image.open(io.BytesIO(jpeg)) as handle:
        small = np.asarray(handle.convert("RGB"))
    found = confirm_clutter(small, find_clutter(jpeg, meta), meta)
    np.savez_compressed(masks_path, **{f"m{i}": c["mask"] for i, c in enumerate(found)})
    stage.write_text(
        json.dumps(
            {
                "key": key,
                "sent": [sent_w, sent_h],
                "damage": damage,
                "found": [{k: v for k, v in c.items() if k != "mask"} for c in found],
            }
        )
    )
    return damage, found


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
    return fill


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
            verdicts.append({"pass": False, "reason": f"self-check failed to run: {exc}"})
    reasons = list(dict.fromkeys(v["reason"] for v in verdicts))
    return {
        "pass": bool(verdicts) and all(v["pass"] for v in verdicts),
        "reason": "; ".join(reasons),
        "areas": verdicts,
    }


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
        "rejected": [],
        "left_in_place": [],
        "selfcheck": None,
        "measure": None,
    }
    finished = _load(source)
    h, w = finished.shape[:2]
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
        record["removed"], record["left_in_place"] = removed, left
        if not final.any():
            return record
        spots = regions(final)
        generated = finished.copy()
        for spot in spots:
            top, bottom, x0, x1 = spot["box"][1], spot["box"][3], spot["box"][0], spot["box"][2]
            generated[top:bottom, x0:x1] = _fill_region(finished, final, spot["box"], meta)
    except PhotoFailed as exc:
        record["status"], record["reason"] = "untidied", str(exc)
        return record

    tidied = composite(finished, generated, final)
    with Image.open(source) as handle:
        icc = handle.info.get("icc_profile")
    segment.save_mask_png(final, folder / "mask.png")
    Image.fromarray(tidied).save(folder / "tidied.png", icc_profile=icc)
    record["measure"] = measure(source, folder / "tidied.png", folder / "mask.png", damage)
    record["selfcheck"] = _self_check(
        finished, tidied, spots, meta, [item["label"] for item in removed]
    )
    status, reason = ship_decision(pixels_pass(record["measure"]), record["selfcheck"]["pass"])
    record["status"], record["reason"] = status, reason
    if status == "tidied":
        _save_page_images(finished, tidied, final, folder)
    else:
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
        f"{summary['nothing_to_tidy']} nothing to tidy, ${summary['unit_meta_usd']:.4f}"
    )


if __name__ == "__main__":
    main()
