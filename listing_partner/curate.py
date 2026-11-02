"""Muse Spark labels and rates each finished photo, then orders the keepers."""

from __future__ import annotations

import io
import json
import re
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from listing_partner.segment import jpeg_bytes

ROOMS = (
    "front exterior",
    "rear exterior",
    "living room",
    "dining area",
    "kitchen",
    "bedroom",
    "bathroom",
    "laundry",
    "hallway",
    "stairs",
    "basement",
    "garage",
    "yard",
    "other",
)
#: A 1 means unusable on the 1 to 5 scale; such a shot is dropped.
WEAK_AT = 1
#: A live ordering call spent 4096 output tokens on reasoning with no answer.
SET_MAX_TOKENS = 16000
_CROP = re.compile(r"CROP\s+(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)")

RATE_PROMPT = (
    "This is one photo from a rental listing shoot. Reply with JSON only: "
    '{"room": R, "sharpness": S, "framing": F, "note": "one short plain reason"}. '
    f"R is exactly one of: {', '.join(ROOMS)}. S and F are whole numbers 1 to 5, where 5 "
    "is excellent and 1 is unusable for a listing. If you need a closer look first, reply "
    "only: CROP x,y,w,h in these photo pixels."
)
SET_PROMPT = (
    "Numbered tiles show every usable photo from one rental listing. Their labels: {labels}. "
    "Reply with JSON only: "
    '{{"duplicates": [{{"keep": "ID", "drop": "ID", "reason": "plain reason"}}], '
    '"order": ["ID", ...]}}. List a duplicate only when two shots show the same view; keep '
    "the better one. Order is every kept ID once in the path a renter would walk: front "
    "exterior first, then through the home, then rear exterior and yard last."
)


def _json_object(text: str) -> dict:
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < start:
        raise ValueError("reply holds no JSON object")
    data = json.loads(text[start : end + 1])
    if not isinstance(data, dict):
        raise ValueError("reply is not a JSON object")
    return data


def parse_rating(text: str) -> dict:
    data = _json_object(text)
    if data.get("room") not in ROOMS:
        raise ValueError(f"room not on the list: {data.get('room')!r}")
    for key in ("sharpness", "framing"):
        value = data.get(key)
        if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 5:
            raise ValueError(f"{key} not 1 to 5: {value!r}")
    return {
        "room": data["room"],
        "sharpness": data["sharpness"],
        "framing": data["framing"],
        "note": str(data.get("note", "")),
    }


def enforce_walkthrough(order: list[str], labels: dict[str, str]) -> list[str]:
    """Front exterior first, rear exterior and yard last, otherwise as given."""
    front = [p for p in order if labels[p] == "front exterior"]
    tail = [p for p in order if labels[p] in ("rear exterior", "yard")]
    return front + [p for p in order if p not in front and p not in tail] + tail


def decide(ratings: list[dict], set_reply: str) -> dict:
    """Keep or drop every photo. Raises on any reply that does not add up."""
    by_id = {r["id"]: r for r in ratings}
    data = _json_object(set_reply)
    dropped: dict[str, str] = {}
    for r in ratings:
        if r["sharpness"] <= WEAK_AT or r["framing"] <= WEAK_AT:
            dropped[r["id"]] = (
                f"weak: sharpness {r['sharpness']}, framing {r['framing']}. {r.get('note', '')}"
            ).strip()
    pairs = data.get("duplicates", [])
    if not isinstance(pairs, list):
        raise ValueError("duplicates is not a list")
    for pair in pairs:
        keep, drop = str(pair.get("keep")), str(pair.get("drop"))
        reason = str(pair.get("reason", "")).strip()
        if keep not in by_id or drop not in by_id or keep == drop or not reason:
            raise ValueError(f"bad duplicate entry: {pair!r}")
        dropped.setdefault(drop, f"duplicate of {keep}: {reason}")
    for pair in pairs:
        if str(pair.get("keep")) in dropped:
            raise ValueError(f"duplicate keeps a dropped shot: {pair!r}")
    order = [str(x) for x in data.get("order", [])]
    expected = set(by_id) - set(dropped)
    if len(order) != len(set(order)) or set(order) != expected:
        raise ValueError(
            f"order is not exactly the kept shots: {sorted(order)} vs {sorted(expected)}"
        )
    labels = {i: by_id[i]["room"] for i in order}
    kept = [by_id[i] for i in enforce_walkthrough(order, labels)]
    return {
        "kept": kept,
        "dropped": [{**by_id[i], "reason": dropped[i]} for i in by_id if i in dropped],
    }


def spearman(a: list[int], b: list[int]) -> float:
    n = len(a)
    if n < 2:
        raise ValueError("rank correlation needs at least 2 shots")
    return 1 - 6 * sum((x - y) ** 2 for x, y in zip(a, b)) / (n * (n * n - 1))


def benchmark(kept_order: list[str], dropped: list[str], mls_positions: dict[str, int]) -> dict:
    """Ours against the photographer's published selection and order. Positions
    compare within the shots both kept."""
    both = [p for p in kept_order if p in mls_positions]
    his = sorted(both, key=lambda p: mls_positions[p])
    ours_rank = [both.index(p) + 1 for p in both]
    his_rank = [his.index(p) + 1 for p in both]
    return {
        "kept_both": sorted(both),
        "we_kept_he_dropped": sorted(p for p in kept_order if p not in mls_positions),
        "we_dropped_he_kept": sorted(p for p in dropped if p in mls_positions),
        "we_dropped_he_dropped": sorted(p for p in dropped if p not in mls_positions),
        "different_position": sum(1 for x, y in zip(ours_rank, his_rank) if x != y),
        "rank_correlation": round(spearman(ours_rank, his_rank), 4),
    }


def contact_sheet(photos: list[tuple[str, np.ndarray]], tile: int = 200, cols: int = 5) -> bytes:
    """Numbered tiles, about 0.6 MP for 17 shots, under the client's per-image
    token bound."""
    high = tile * 2 // 3 + 16
    rows = (len(photos) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * tile, rows * high), "white")
    draw = ImageDraw.Draw(sheet)
    for i, (pid, rgb) in enumerate(photos):
        thumb = Image.fromarray(rgb)
        thumb.thumbnail((tile - 2, high - 16))
        x, y = (i % cols) * tile, (i // cols) * high
        sheet.paste(thumb, (x, y + 14))
        draw.text((x + 2, y + 1), pid, fill="black")
    handle = io.BytesIO()
    sheet.save(handle, format="JPEG", quality=88)
    return handle.getvalue()


def _load(path: Path) -> np.ndarray:
    with Image.open(path) as img:
        return np.asarray(img.convert("RGB"))


def rate_photo(pid: str, rgb: np.ndarray, spark) -> dict:
    """At most one crop round and one retry on an unreadable reply. `spark` is
    (prompt, images) -> text, through the capped client."""
    small = np.asarray(Image.open(io.BytesIO(jpeg_bytes(rgb))))
    current, cropped, retried = jpeg_bytes(small), False, False
    prompt = RATE_PROMPT
    while True:
        text = spark(prompt, [current])
        match = _CROP.search(text)
        if match and not cropped:
            x, y, w, h = (int(v) for v in match.groups())
            crop = small[y : y + h, x : x + w]
            if crop.size == 0:
                raise ValueError(f"{pid}: empty crop request")
            current, cropped = jpeg_bytes(crop), True
            prompt = RATE_PROMPT.replace(
                "If you need a closer look first, reply only: CROP x,y,w,h in these photo pixels.",
                "This is a closer crop of the photo.",
            )
            continue
        try:
            return {"id": pid, "cropped": cropped, **parse_rating(text)}
        except ValueError:
            if retried:
                raise
            retried = True


def run_curation(finished_dir: Path, spark) -> dict:
    """Every finished photo ends kept with a position or dropped with a reason."""
    paths = sorted(Path(finished_dir).glob("*.jpg"))
    if not paths:
        raise ValueError(f"no finished photos in {finished_dir}")
    photos = [(p.stem, _load(p)) for p in paths]
    ratings = [rate_photo(pid, rgb, spark) for pid, rgb in photos]
    labels = json.dumps({r["id"]: r["room"] for r in ratings})
    sheet = contact_sheet(
        [(i, np.asarray(Image.fromarray(a).resize((400, 267)))) for i, a in photos]
    )
    prompt = SET_PROMPT.format(labels=labels)
    try:
        result = decide(ratings, spark(prompt, [sheet], SET_MAX_TOKENS))
    except ValueError as exc:
        result = decide(
            ratings, spark(f"{prompt} Your last reply was refused: {exc}", [sheet], SET_MAX_TOKENS)
        )
    if len(result["kept"]) + len(result["dropped"]) != len(paths):
        raise ValueError("kept plus dropped does not equal the finished photos")
    return result
