"""Run command: one unit folder in, merged photos and a review page out.

Usage: python -m listing_partner.run_merge inputs/unit-a --output output/unit-a
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import datetime
from pathlib import Path

import numpy as np
from PIL import Image

from listing_partner import hdr
from listing_partner.meta_client import SPEND_CAP_USD, MetaRefused, read_spend_total


def dhash(gray: np.ndarray) -> int:
    """Difference hash of a grayscale image (robust to scaling, mild edits)."""
    small = np.asarray(Image.fromarray(gray).resize((33, 32), Image.BILINEAR))
    bits = (small[:, 1:] > small[:, :-1]).flatten()
    value = 0
    for bit in bits:
        value = (value << 1) | int(bit)
    return value


def hamming(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


def gray_thumb(path: Path, size: int = 256) -> np.ndarray:
    img = Image.open(path).convert("L")
    img.thumbnail((size, size))
    canvas = Image.new("L", (size, size), 128)
    canvas.paste(img, ((size - img.width) // 2, (size - img.height) // 2))
    return np.asarray(canvas)


def render_lightroom(dng: Path, out: Path) -> str:
    """Show the largest preview Lightroom embedded in a DNG.

    That is what Lightroom itself shows, so the comparison is fair; our own
    color processing stays out of the review page entirely. Returns
    "Lightroom's own preview", or "preview unavailable" when the DNG holds
    no embedded preview. Never raises: the review page must survive one
    bad DNG.
    """
    try:
        hdr.save_clean_jpeg(hdr.extract_preview(dng), out)
        return "Lightroom's own preview"
    except Exception:
        placeholder = np.zeros((256, 256, 3), dtype=np.uint8) + 114
        hdr.save_clean_jpeg(placeholder, out)
        return "preview unavailable"


def match_mls(sets: list[list[Path]], mls_dir: Path, merged_dir: Path) -> dict:
    """Match each MLS photo to a set index.

    By capture time inside the set window; the photo with no capture time by
    visual similarity (dHash, tolerant of crop and edits). Every MLS photo
    appears exactly once.
    """
    mls_files = sorted(mls_dir.glob("*.jpg"))
    windows = []
    for members in sets:
        stamps = [hdr.read_capture_time(p) for p in members]
        windows.append((min(stamps), max(stamps)))
    matches: dict[str, dict] = {}
    taken: set[int] = set()
    pending: list[Path] = []
    for photo in mls_files:
        try:
            stamp = hdr.read_capture_time(photo)
        except ValueError:
            pending.append(photo)
            continue
        hits = [
            i for i, (start, end) in enumerate(windows) if start <= stamp <= end and i not in taken
        ]
        if len(hits) == 1:
            matches[photo.name] = {"set": hits[0], "how": "capture time"}
            taken.add(hits[0])
        else:
            pending.append(photo)
    # Visual matching for the rest (usually just the timeless photo). Keyed
    # by set number from the file name, so a failed set (no merged file)
    # cannot shift later sets' numbers.
    merged = sorted(merged_dir.glob("*.jpg"))
    hashes = {int(m.stem) - 1: dhash(gray_thumb(m)) for m in merged}
    for photo in pending:
        target = dhash(gray_thumb(photo))
        ranked = sorted(hashes.items(), key=lambda kv: hamming(target, kv[1]))
        chosen = next((i for i, _ in ranked if i not in taken), ranked[0][0])
        matches[photo.name] = {
            "set": chosen,
            "how": "matched by look",
            "distance": hamming(target, hashes[chosen]),
        }
        taken.add(chosen)
    return matches


def build_review(
    output_dir: Path,
    manifest: dict,
    mls_matches: dict,
    lightroom_labels: dict,
    spend_total: float | None,
) -> Path:
    rows = []
    for entry in manifest["sets"]:
        idx = entry["index"]
        name = f"{idx:03d}"
        mls_here = [(photo, info) for photo, info in mls_matches.items() if info["set"] == idx - 1]
        if mls_here:
            mls_cell = "".join(
                f'<img src="review/mls_{photo}" loading="lazy"><p>{photo} ({info["how"]})</p>'
                for photo, info in mls_here
            )
        else:
            mls_cell = "<p>not published</p>"
        flag = " <b>FLAG: odd set size</b>" if entry["flagged"] else ""
        fail = f"<p>FAILED: {entry['error']}</p>" if entry["error"] else ""
        frames = ", ".join(entry["frames"])
        rows.append(
            f"<section><h2>Set {name}{flag}</h2>{fail}"
            f"<p>{entry['size']} frames: {frames}</p>"
            f'<div class="row"><div><img src="review/frame_{name}_dark.jpg" loading="lazy">'
            f"<p>darkest: {entry['darkest']}</p></div>"
            f'<div><img src="review/frame_{name}_bright.jpg" loading="lazy">'
            f"<p>brightest: {entry['brightest']}</p></div>"
            f'<div><img src="merged/{name}.jpg" loading="lazy"><p>our merge</p></div>'
            f'<div><img src="review/lightroom_{name}.jpg" loading="lazy">'
            f"<p>{lightroom_labels[name]}</p></div>"
            f"<div>{mls_cell}</div></div></section>"
        )
    top = manifest["summary"]
    if spend_total is None:
        spend_line = "Meta spend unknown, ledger unreadable"
    else:
        spend_line = f"Meta spend to date: ${spend_total:.4f} of ${SPEND_CAP_USD:.2f} cap."
    html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<title>Unit review: {top["frames_found"]} frames, {top["sets_found"]} sets</title>
<style>body{{font-family:sans-serif;max-width:1400px;margin:auto;padding:16px}}
.row{{display:grid;grid-template-columns:repeat(5,1fr);gap:8px}}
img{{width:100%;height:auto}}.row p{{font-size:12px}}</style></head><body>
<h1>Bracket review</h1>
<p>{top["frames_found"]} frames, {top["sets_found"]} sets, {top["sets_merged"]} merged, \
{top["sets_failed"]} failed, {top["sets_flagged"]} flagged, \
merge run time {top["merge_run_seconds"]:.1f} s (copy from Drive not counted).</p>
{"".join(rows)}
<footer><p>{spend_line}</p></footer>
</body></html>"""
    page = output_dir / "review.html"
    page.write_text(html)
    return page


def run_merge(raw_dir: Path, lightroom_dir: Path, mls_dir: Path, output_dir: Path) -> dict:
    frames = (
        sorted(raw_dir.glob("*.NEF"))
        + sorted(raw_dir.glob("*.nef"))
        + sorted(raw_dir.glob("*.jpg"))
        + sorted(raw_dir.glob("*.JPG"))
        + sorted(raw_dir.glob("*.jpeg"))
        + sorted(raw_dir.glob("*.JPEG"))
    )
    if not frames:
        raise ValueError(f"no bracket frames (NEF or JPEG) in {raw_dir}")
    sets = hdr.group_frames(frames)
    common = hdr.most_common_size(sets)
    merged_dir = output_dir / "merged"
    review_dir = output_dir / "review"
    merged_dir.mkdir(parents=True, exist_ok=True)
    review_dir.mkdir(parents=True, exist_ok=True)

    entries = []
    merged_count = 0
    failed_count = 0
    flagged_count = 0
    started = time.perf_counter()
    for number, members in enumerate(sets, 1):
        name = f"{number:03d}"
        flagged = len(members) != common
        flagged_count += flagged
        dark, bright = hdr.darkest_and_brightest(members)
        entry = {
            "index": number,
            "frames": [p.name for p in members],
            "size": len(members),
            "flagged": flagged,
            "darkest": dark.name,
            "brightest": bright.name,
            "error": None,
        }
        try:
            image = hdr.merge_set(members)
            hdr.save_clean_jpeg(image, merged_dir / f"{name}.jpg")
            merged_count += 1
        except ValueError as exc:
            entry["error"] = str(exc)
            failed_count += 1
        for label, frame in (("dark", dark), ("bright", bright)):
            thumb = hdr.decode_frame(frame, half_size=True)
            small = np.asarray(Image.fromarray(thumb).resize((640, 427), Image.BILINEAR))
            hdr.save_clean_jpeg(small, review_dir / f"frame_{name}_{label}.jpg", quality=80)
        entries.append(entry)
    elapsed = time.perf_counter() - started

    lightroom_labels = {}
    for entry in entries:
        name = f"{entry['index']:03d}"
        first_stem = Path(entry["frames"][0]).stem
        candidates = list(lightroom_dir.glob(f"{first_stem}-HDR.dng"))
        if candidates:
            lightroom_labels[name] = render_lightroom(
                candidates[0], review_dir / f"lightroom_{name}.jpg"
            )
        else:
            lightroom_labels[name] = "Lightroom merge missing"

    mls_matches = match_mls(sets, mls_dir, merged_dir)
    # Copy MLS photos beside the page so it opens anywhere, stripped of
    # metadata like every other output JPEG.
    for photo in mls_dir.glob("*.jpg"):
        with Image.open(photo) as img:
            hdr.save_clean_jpeg(np.asarray(img.convert("RGB")), review_dir / f"mls_{photo.name}")

    manifest = {
        "summary": {
            "frames_found": len(frames),
            "sets_found": len(sets),
            "sets_merged": merged_count,
            "sets_failed": failed_count,
            "sets_flagged": flagged_count,
            "merge_run_seconds": elapsed,
            "ran_at": datetime.now().isoformat(),
        },
        "sets": entries,
    }
    (output_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))
    try:
        spend_total: float | None = read_spend_total()
    except MetaRefused:
        spend_total = None
    build_review(output_dir, manifest, mls_matches, lightroom_labels, spend_total)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="Merge one unit's brackets.")
    parser.add_argument("unit_dir", type=Path, help="e.g. inputs/unit-a")
    parser.add_argument("--output", type=Path, required=True, help="e.g. output/unit-a")
    args = parser.parse_args()
    manifest = run_merge(
        args.unit_dir / "raw",
        args.unit_dir / "lightroom",
        args.unit_dir / "mls",
        args.output,
    )
    print(json.dumps(manifest["summary"], indent=2))


if __name__ == "__main__":
    main()
