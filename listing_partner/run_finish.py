"""Unit 2 pipeline: bracket sets in, finished listing photos out.

Per set: undistort each frame (vendored lens profile, per-photo fitted
strength) and correct TCA, align, fuse the chosen subset, straighten
verticals, balance exposure, SAM windows plus Spark verdicts, pull views
from the darkest frame, denoise last, crop to valid pixels, save. Every
Meta call goes through the spend-capped client; failures land in plain
words and still count.
"""

from __future__ import annotations

import argparse
import json
import time
import traceback
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from listing_partner import checks, finish, geometry, hdr, run_merge, segment
from listing_partner.hdr import save_clean_jpeg
from listing_partner.meta_client import SPEND_CAP_USD, MetaRefused, read_spend_total

SAM_PROMPTS = ("window", "glass door")
SEND_LONG_SIDE = 1024


def build_inputs(
    members: list[Path],
    record: dict,
) -> dict:
    """Local prep for one set: geometry, merge choice, balance, send size.

    No Meta calls, and no MLS twin: every decision reads the set's own
    frames through the frozen shared look. Fills record in place (partial
    on failure, like before) and returns the state the Meta step and the
    tail need.
    """
    focals = [geometry.read_focal(p) for p in members]
    identity = geometry.read_lens_identity(members[len(members) // 2])
    profile = geometry.match_profile(identity)
    record["focal"] = sorted({f for f in focals if f})
    if profile is None:
        raise ValueError("no lens profile matches this lens, geometry skipped")
    record["lens"] = "Nikon AF-P DX 10-20mm (vendored lensfun profile)"
    mid_focal = focals[len(focals) // 2] or 10.0
    if geometry.vignetting_params(profile, mid_focal) is None:
        record["vignetting"] = (
            "skipped: the vendored lensfun profile carries no vignetting model for this lens"
        )
    else:
        record["vignetting"] = "applied from the lens profile"

    decoded = [hdr.decode_frame(p) for p in members]
    strengths: dict[float, float] = {}
    corrected = []
    for frame, path, frame_focal in zip(decoded, members, focals):
        frame_focal = frame_focal or 10.0
        if frame_focal not in strengths:
            gray = cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY)
            strengths[frame_focal] = geometry.fit_strength(gray, profile, frame_focal)
        fixed, applied_strength = geometry.correct_distortion(
            frame, profile, frame_focal, strength=strengths[frame_focal]
        )
        strengths[frame_focal] = applied_strength
        tca = geometry.tca_params(profile, frame_focal)
        if tca is not None:
            fixed = geometry.correct_tca(fixed, tca)
        corrected.append(fixed)
    record["distortion_strength"] = strengths
    record["ghosting"] = round(geometry.ghosting_score(corrected), 4)
    h0, w0 = corrected[0].shape[:2]
    valid = np.ones((h0, w0), bool)
    for frame_focal, strength in strengths.items():
        if strength > 0:
            dx, dy = geometry._displacement_field(profile, frame_focal, w0, h0)
            valid &= geometry.undistort_valid_mask(h0, w0, strength * dx, strength * dy)

    aligned = hdr.align_to_first(corrected)
    options = hdr.merge_options(members)
    order = {p: i for i, p in enumerate(members)}
    merges = {}
    for key, subset in options.items():
        idx = [order[p] for p in subset]
        merges[key] = hdr.fuse_exposures([aligned[i] for i in idx])
    best_key, best_score, _ = hdr.choose_from_merges(merges)
    merged = merges[best_key]
    record["frames_used"] = [p.name for p in sorted(options[best_key], key=lambda p: order[p])]
    record["frames_reason"] = f"{best_key}: {best_score}"
    record["darkest_available"] = hdr.darkest_for_windows(members).name

    gray = cv2.cvtColor(merged, cv2.COLOR_RGB2GRAY)
    # Before and after on the same image: the merged room photo going
    # into vertical correction, so the improvement is that step's own.
    straight_before = geometry.line_measure(gray)
    tilt = geometry.dominant_vertical_angle(gray)
    # Keep the undistort validity above: rotations blacken more borders,
    # they never repair undistort's. Resetting here kept ~20px black bands.
    if geometry.needs_rotation(tilt):
        merged, applied = geometry.correct_verticals(merged)
        valid &= geometry.rotation_valid_mask(*gray.shape, applied)
        record["verticals"] = f"rotated {applied:.2f} deg to upright"
    elif tilt is not None:
        applied = 0.0
        record["verticals"] = f"level already (tilt {tilt:.2f} deg from verticals)"
    else:
        applied = 0.0
        record["verticals"] = "no agreeing verticals found (not measured)"
    residual = geometry.dominant_vertical_angle(cv2.cvtColor(merged, cv2.COLOR_RGB2GRAY))
    record["vertical_residual"] = residual
    record["straight_before"] = straight_before
    record["straight_after"] = geometry.line_measure(cv2.cvtColor(merged, cv2.COLOR_RGB2GRAY))

    balanced, balance_report = finish.balance_exposure(merged)
    record["balance"] = balance_report

    h, w = balanced.shape[:2]
    scale = SEND_LONG_SIDE / max(h, w)
    small = cv2.resize(
        balanced,
        (int(round(w * scale)), int(round(h * scale))),
        interpolation=cv2.INTER_AREA,
    )
    sent_jpeg = segment.jpeg_bytes(small)
    sent_h, sent_w = small.shape[:2]
    return {
        "balanced": balanced,
        "aligned": aligned,
        "members": list(members),
        "order": order,
        "small": small,
        "sent_jpeg": sent_jpeg,
        "sent_h": sent_h,
        "sent_w": sent_w,
        "valid": valid,
        "h": h,
        "w": w,
    }


def tint_overlay(finished: np.ndarray, union: np.ndarray) -> np.ndarray:
    """The finished photo with confirmed window glass tinted red.

    Tint touches masked pixels only: overlay equals finished everywhere
    outside the union, which is what proves the outline sits over the
    finished photo and not some other image.
    """
    overlay = finished.copy()
    if union.any():
        overlay[union] = (overlay[union] * 0.5 + np.array([255, 0, 0]) * 0.5).astype(np.uint8)
    return overlay


def finish_tail(record: dict, state: dict, dirs: dict, union: np.ndarray) -> None:
    """Local tail after verdicts: pull, denoise, crop, checks, saves.

    No Meta calls, no MLS twin. Fills the measured fields of record in
    place. Clip numbers are fractions of window pixels; the after number
    is read back from the saved JPEG file, the actual final output.
    """
    from listing_partner.checks import CLIP_LEVEL

    name = record["name"]
    balanced = state["balanced"]
    valid = state["valid"]
    pulled = balanced
    changed_outside = 0
    if union.any():
        pull_idx = segment.choose_pull_frame(state["aligned"], union, ref=balanced)
        view = state["aligned"][pull_idx]
        record["pull_frame"] = state["members"][pull_idx].name
        record["pull_frame_index"] = pull_idx
        pulled, changed_outside = segment.pull_window(balanced, view, union)
    else:
        record["pull_frame"] = None

    # Same patches both sides: the patch set is picked on the pulled
    # photo, so the drop is the denoiser's work on the same pixels, not
    # two different populations.
    patches = finish.flat_patch_mask(pulled)
    noise_before = finish.flat_noise(pulled, patches)
    edge_before = finish.edge_strength(pulled)
    finished = finish.denoise(pulled)
    record["noise_before"] = round(noise_before, 2)
    record["noise_after"] = round(finish.flat_noise(finished, patches), 2)
    record["edge_before"] = round(edge_before, 1)
    record["edge_after"] = round(finish.edge_strength(finished), 1)
    # One shared crop for every measurement: before and after count the
    # same window pixels, and the file holds exactly those pixels.
    finished = geometry.crop_valid(finished, valid)
    union = geometry.crop_valid(union, valid)
    balanced_cropped = geometry.crop_valid(balanced, valid)
    window_pixels = int(union.sum())
    if window_pixels:
        gray_before = cv2.cvtColor(balanced_cropped, cv2.COLOR_RGB2GRAY)
        clip_before_n = int(((gray_before >= CLIP_LEVEL) & union).sum())
    else:
        clip_before_n = 0
    record["window_pixels"] = window_pixels
    record["clip_before_n"] = clip_before_n
    clip_before_raw = clip_before_n / max(1, window_pixels)
    record["clip_before"] = round(clip_before_raw, 4)
    record["changed_outside"] = changed_outside

    record["finished_size"] = list(finished.shape[:2])
    finished_path = dirs["finished"] / f"{name}.jpg"
    save_clean_jpeg(finished, finished_path)
    reread = cv2.imread(str(finished_path))
    reread_rgb = cv2.cvtColor(reread, cv2.COLOR_BGR2RGB)
    if window_pixels:
        gray_after = cv2.cvtColor(reread_rgb, cv2.COLOR_RGB2GRAY)
        clip_after_n = int(((gray_after >= CLIP_LEVEL) & union).sum())
    else:
        clip_after_n = 0
    record["clip_after_n"] = clip_after_n
    clip_after_raw = clip_after_n / max(1, window_pixels)
    record["clip_after"] = round(clip_after_raw, 4)

    record["checks"] = {
        "highlights": checks.check_highlights(clip_before_raw, clip_after_raw),
        "outside": checks.check_outside_unchanged(changed_outside),
        "noise": checks.check_noise(noise_before, record["noise_after"]),
        "edges": checks.check_edges(edge_before, record["edge_after"]),
        "straightness": checks.check_straightness(
            record["straight_before"], record["straight_after"]
        ),
        "verticals": checks.check_verticals(record["vertical_residual"]),
    }
    # NOTE: finished and union stay cropped from here on (overlay below).
    thumb = cv2.resize(
        finished,
        (1024, int(round(finished.shape[0] * 1024 / finished.shape[1]))),
        interpolation=cv2.INTER_AREA,
    )
    save_clean_jpeg(thumb, dirs["review"] / f"finished_{name}.jpg")
    overlay_thumb = cv2.resize(
        tint_overlay(finished, union),
        (1024, int(round(finished.shape[0] * 1024 / finished.shape[1]))),
        interpolation=cv2.INTER_AREA,
    )
    save_clean_jpeg(overlay_thumb, dirs["review"] / f"overlay_{name}.jpg")


def replay_set(prior: dict, members: list[Path], dirs: dict) -> dict:
    """Re-run one set's local tail with its saved Meta results.

    Makes no Meta calls: verdicts, masks and transcripts come from the
    prior record and the saved mask files. Raises with a plain reason.
    """
    record: dict = {
        "index": prior["index"],
        "name": prior["name"],
        "notes": list(prior.get("notes", [])),
    }
    state = build_inputs(members, record)
    union = np.zeros((state["h"], state["w"]), bool)
    for window in prior.get("windows", []):
        path = dirs["masks"] / f"{record['name']}_window{window['id']}.png"
        mask = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
        if mask is None:
            raise ValueError(f"saved mask missing for window {window['id']}: {path.name}")
        if mask.shape != (state["h"], state["w"]):
            raise ValueError(
                f"saved mask {path.name} is {mask.shape}, expected {(state['h'], state['w'])}"
            )
        union |= mask > 127
    finish_tail(record, state, dirs, union)
    for key in ("candidates_found", "transcript", "windows", "rejections"):
        record[key] = prior[key]
    # Collapse exact duplicate rejection rows: both text prompts can return
    # the same region under one id, and one verdict then prints twice. Same
    # id plus same reason carries no new information either way.
    seen_rows = set()
    unique_rejections = []
    for rejection in record["rejections"]:
        key = (rejection["id"], rejection["reason"])
        if key in seen_rows:
            continue
        seen_rows.add(key)
        unique_rejections.append(rejection)
    record["rejections"] = unique_rejections
    record["candidates_found"] = len(record["windows"]) + len(unique_rejections)
    record["error"] = None
    return record


def process_set(
    members: list[Path],
    dirs: dict,
    index: int,
) -> dict:
    """Finish one bracket set. Raises with a plain reason on failure."""
    name = f"{index:03d}"
    record: dict = {"index": index, "name": name, "notes": []}
    transcript: list = []
    try:
        state = build_inputs(members, record)
        h, w = state["h"], state["w"]
        candidates = []
        for prompt in SAM_PROMPTS:
            candidates.extend(segment.find_candidates(state["sent_jpeg"], prompt))
        candidates = segment.dedupe_candidates(candidates)
        record["candidates_found"] = len(candidates)
        if candidates:
            verdicts = segment.verify_candidates(state["small"], candidates, transcript=transcript)
        else:
            verdicts = {}
        record["transcript"] = transcript
        confirmed = [
            c
            for c in segment.scale_candidates(candidates, state["sent_w"], state["sent_h"], h, w)
            if verdicts.get(c["object_id"], (False, ""))[0]
        ]
        record["windows"] = [
            {
                "id": c["object_id"],
                "box": c["box"],
                "reason": verdicts[c["object_id"]][1],
            }
            for c in confirmed
        ]
        record["rejections"] = [
            {
                "id": c["object_id"],
                "reason": verdicts[c["object_id"]][1],
            }
            for c in segment.scale_candidates(candidates, state["sent_w"], state["sent_h"], h, w)
            if c["object_id"] in verdicts and not verdicts[c["object_id"]][0]
        ]
        union = np.zeros((h, w), bool)
        for c in confirmed:
            union |= c["mask"]
            segment.save_mask_png(
                c["mask"],
                dirs["masks"] / f"{name}_window{c['object_id']}.png",
            )
        finish_tail(record, state, dirs, union)
        record["error"] = None
    except Exception as exc:  # noqa: BLE001 - every failure lands in plain words
        record["transcript"] = transcript
        record["error"] = f"{type(exc).__name__}: {exc}"
        record["traceback"] = traceback.format_exc(limit=3)
    return record


def _check_line(label: str, result) -> str:
    """One check as HTML: PASS, FAIL, or NOT MEASURED, never a silent pass."""
    ok, reason = result
    if ok:
        verdict = "PASS"
    elif "not measured" in reason:
        verdict = "NOT MEASURED"
    else:
        verdict = "FAIL"
    return f"<p>{verdict} {label}: {reason}</p>"


def build_finish_review(output_dir: Path, manifest: dict, mls_matches: dict) -> Path:
    """review-finish.html: one row per shot plus the measured top line.

    One row per shot: our unit 1 merge, our finished photo, the window
    outline over the finished photo, and Erik's MLS photo. Every skipped
    step shows with its reason; every check with nothing to measure shows
    NOT MEASURED.
    """
    rows = []
    for entry in manifest["sets"]:
        name = entry["name"]
        if entry.get("error"):
            rows.append(f"<section><h2>Shot {name}</h2><p>FAILED: {entry['error']}</p></section>")
            continue
        windows = entry.get("windows", [])
        if windows:
            win_cell = "".join(f"<p>window {w['id']}: {w['reason']}</p>" for w in windows)
        else:
            win_cell = "<p>no windows confirmed</p>"
        rejected = entry.get("rejections", [])
        rej_cell = "".join(f"<p>rejected {r['id']}: {r['reason']}</p>" for r in rejected)
        check_cell = "".join(
            _check_line(label, result) for label, result in entry.get("checks", {}).items()
        )
        mls_here = [
            photo for photo, info in mls_matches.items() if info["set"] == entry["index"] - 1
        ]
        mls_cell = (
            "".join(
                f'<img src="review/mls_{photo}" loading="lazy"><p>{photo}</p>' for photo in mls_here
            )
            or "<p>not published</p>"
        )
        look = entry.get("look")
        look_cell = f"<p>look: {look['look_reason']}</p>" if look else "<p>look: no MLS photo</p>"
        clip_cell = (
            f"<p>window clip {entry.get('clip_before', 0.0):.4f} -&gt; "
            f"{entry.get('clip_after', 0.0):.4f} of window pixels "
            f"({entry.get('window_pixels', 0)} px, after read from the file)</p>"
        )
        rows.append(
            f"<section><h2>Shot {name}</h2>"
            f"<p>{', '.join(entry.get('frames_used', []))}</p>"
            f"<p>merge: {entry.get('frames_reason', '')}</p>"
            f"<p>window view from: {entry.get('pull_frame', 'no windows')}</p>"
            f"<p>lens strength {entry.get('distortion_strength', '')}, "
            f"{entry.get('verticals', '')}, {entry.get('vignetting', '')}, "
            f"ghosting {entry.get('ghosting', '')}</p>"
            f"{clip_cell}{look_cell}"
            f'<div class="row">'
            f'<div><img src="review/merged_{name}.jpg" loading="lazy">'
            f"<p>unit 1 merge</p></div>"
            f'<div><img src="review/finished_{name}.jpg" loading="lazy">'
            f"<p>finished</p></div>"
            f'<div><img src="review/overlay_{name}.jpg" loading="lazy">'
            f"<p>window outline over the finished photo</p>{win_cell}{rej_cell}</div>"
            f"<div>{mls_cell}</div>"
            f"<div>{check_cell}</div>"
            "</div></section>"
        )
    top = manifest["summary"]
    try:
        spend_total = read_spend_total()
        spend_line = f"Meta spend to date: ${spend_total:.4f} of ${SPEND_CAP_USD:.2f} cap."
    except MetaRefused:
        spend_line = "Meta spend unknown, ledger unreadable"
    html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<title>Finished review: {top["photos_finished"]} finished, {top["photos_failed"]} failed</title>
<style>body{{font-family:sans-serif;max-width:1600px;margin:auto;padding:16px}}
.row{{display:grid;grid-template-columns:repeat(5,1fr);gap:8px}}
img{{width:100%;height:auto}}.row p{{font-size:12px}}</style></head><body>
<h1>Finished review</h1>
<p>{top["photos_finished"]} finished, {top["photos_failed"]} failed,
run time {top["run_seconds"]:.0f} s.</p>
<p>Median shadow noise {top["noise_before"]:.2f} -&gt; {top["noise_after"]:.2f}.
Windows found {top["windows_found"]}, confirmed {top["windows_confirmed"]},
rejected {top["windows_rejected"]}, photos with windows {top["photos_with_windows"]}.</p>
<p>Near-white window pixels {top["clip_before_n"]} -&gt; {top["clip_after_n"]}
of {top["window_pixels"]} window pixels
({top["clip_before_pct"]:.2f}% -&gt; {top["clip_after_pct"]:.2f}%).</p>
<p>Unit Meta spend ${top["unit_spend_usd"]:.4f} of $2.00.</p>
{"".join(rows)}
<footer><p>{spend_line}</p></footer>
</body></html>"""
    page = output_dir / "review-finish.html"
    page.write_text(html)
    return page


def _median(values: list[float]) -> float:
    ordered = sorted(values)
    n = len(ordered)
    if n == 0:
        return 0.0
    mid = n // 2
    return ordered[mid] if n % 2 else (ordered[mid - 1] + ordered[mid]) / 2.0


def _summarize(records: list[dict], elapsed: float, unit_spend_usd: float) -> dict:
    """Top-line numbers from finished records. Pure, no Meta calls.

    Noise is the median across photos; clip is pooled over every
    confirmed window pixel in the run, so one big window cannot hide
    behind per-photo means.
    """
    finished_records = [r for r in records if not r.get("error")]
    noises = [
        (r["noise_before"], r["noise_after"]) for r in finished_records if "noise_before" in r
    ]
    clip_before_n = sum(r.get("clip_before_n", 0) for r in finished_records)
    clip_after_n = sum(r.get("clip_after_n", 0) for r in finished_records)
    window_pixels = sum(r.get("window_pixels", 0) for r in finished_records)
    return {
        "photos_finished": len(finished_records),
        "photos_failed": len(records) - len(finished_records),
        "run_seconds": elapsed,
        "noise_before": _median([n[0] for n in noises]),
        "noise_after": _median([n[1] for n in noises]),
        "windows_found": sum(r.get("candidates_found", 0) for r in finished_records),
        "windows_confirmed": sum(len(r.get("windows", [])) for r in finished_records),
        "windows_rejected": sum(len(r.get("rejections", [])) for r in finished_records),
        "photos_with_windows": sum(1 for r in finished_records if r.get("windows")),
        "clip_before_n": clip_before_n,
        "clip_after_n": clip_after_n,
        "window_pixels": window_pixels,
        "clip_before_pct": 100 * clip_before_n / max(1, window_pixels),
        "clip_after_pct": 100 * clip_after_n / max(1, window_pixels),
        "unit_spend_usd": unit_spend_usd,
    }


def ensure_merge_thumbs(output_dir: Path, manifest: dict) -> None:
    """Review-size copies of unit 1's merges for the finish page column."""
    review_dir = output_dir / "review"
    merged_dir = output_dir / "merged"
    for entry in manifest["sets"]:
        if entry.get("error"):
            continue
        name = entry["name"]
        src = merged_dir / f"{name}.jpg"
        if not src.exists():
            continue
        img = cv2.imread(str(src))
        thumb = cv2.resize(
            img,
            (1024, int(round(img.shape[0] * 1024 / img.shape[1]))),
            interpolation=cv2.INTER_AREA,
        )
        save_clean_jpeg(cv2.cvtColor(thumb, cv2.COLOR_BGR2RGB), review_dir / f"merged_{name}.jpg")


def attach_look(records: list[dict], mls_matches: dict, mls_dir: Path, output_dir: Path) -> None:
    """Post-hoc criterion-11 numbers per shot, measured from shipped files.

    Runs after processing, never during: the MLS twin is read here only
    to verify the result, exactly as the contract allows.
    """
    from listing_partner import measure

    for record in records:
        if record.get("error"):
            continue
        number = record["index"]
        mls_here = [p for p, i in mls_matches.items() if i["set"] == number - 1]
        if not mls_here:
            record["look"] = None
            continue
        try:
            record["look"] = measure.look_stats(
                output_dir / "finished" / f"{record['name']}.jpg",
                mls_dir / mls_here[0],
            )
        except ValueError as exc:
            record["look"] = {"look_ok": False, "look_reason": str(exc)}


def run_replay(sets: list, mls_matches: dict, mls_dir: Path, output_dir: Path, dirs: dict) -> dict:
    """Re-run every set's local tail with its saved Meta results.

    Makes no Meta calls. Rewrites finished photos, review thumbs and the
    manifest; priors with errors are kept as-is. The unit spend stays the
    prior run's: replaying cost nothing.
    """
    manifest_path = output_dir / "finish_manifest.json"
    prior_manifest = json.loads(manifest_path.read_text())
    prior = {r["index"]: r for r in prior_manifest["sets"]}
    prior_spend = prior_manifest.get("summary", {}).get("unit_spend_usd", 0.0)
    records = []
    started = time.perf_counter()
    for number, members in enumerate(sets, 1):
        old = prior.get(number)
        if old is None or old.get("error"):
            records.append(old if old is not None else {"index": number})
            print(f"set {number}/{len(sets)}: kept prior record", flush=True)
            continue
        try:
            record = replay_set(old, members, dirs)
            print(f"set {number}/{len(sets)}: replayed", flush=True)
        except Exception as exc:  # noqa: BLE001 - every failure lands in plain words
            record = dict(old)
            record["error"] = f"{type(exc).__name__}: {exc}"
            record["traceback"] = traceback.format_exc(limit=3)
            print(f"set {number}/{len(sets)}: REPLAY FAILED {record['error']}", flush=True)
        records.append(record)
    elapsed = time.perf_counter() - started
    attach_look(records, mls_matches, mls_dir, output_dir)
    summary = _summarize(records, elapsed, prior_spend)
    manifest = {"summary": summary, "sets": records}
    manifest_path.write_text(json.dumps(manifest, indent=2, default=str))
    ensure_merge_thumbs(output_dir, manifest)
    build_finish_review(output_dir, manifest, mls_matches)
    return manifest


def run_finish(
    raw_dir: Path,
    mls_dir: Path,
    output_dir: Path,
    only: set[int] | None = None,
    replay: bool = False,
) -> dict:
    """Finish one unit's bracket sets. Returns the manifest.

    With only={...}, processes just those set numbers and merges fresh
    records into the existing manifest instead of starting over.
    With replay=True, re-runs every set's local tail with saved Meta
    results instead of calling Meta (see run_replay).
    """
    frames = sorted(raw_dir.glob("*.NEF")) + sorted(raw_dir.glob("*.nef"))
    if not frames:
        raise ValueError(f"no bracket frames in {raw_dir}")
    sets = hdr.group_frames(frames)
    finished_dir = output_dir / "finished"
    masks_dir = output_dir / "windows" / "masks"
    review_dir = output_dir / "review"
    for directory in (finished_dir, masks_dir, review_dir):
        directory.mkdir(parents=True, exist_ok=True)
    merged_dir = output_dir / "merged"
    mls_matches = run_merge.match_mls(sets, mls_dir, merged_dir)
    for photo in mls_dir.glob("*.jpg"):
        with Image.open(photo) as img:
            save_clean_jpeg(np.asarray(img.convert("RGB")), review_dir / f"mls_{photo.name}")
    try:
        spend_start = read_spend_total()
    except MetaRefused:
        spend_start = 0.0
    dirs = {"finished": finished_dir, "masks": masks_dir, "review": review_dir}
    if replay:
        if only is not None:
            raise ValueError("--replay processes every set, it cannot combine with --only")
        return run_replay(sets, mls_matches, mls_dir, output_dir, dirs)
    records = []
    started = time.perf_counter()
    for number, members in enumerate(sets, 1):
        if only is not None and number not in only:
            continue
        record = process_set(members, dirs, number)
        records.append(record)
        status = f"FAILED {record['error']}" if record.get("error") else "finished"
        print(f"set {number}/{len(sets)}: {status}", flush=True)
    elapsed = time.perf_counter() - started
    try:
        spend_end = read_spend_total()
    except MetaRefused:
        spend_end = spend_start
    summary = _summarize(records, elapsed, round(spend_end - spend_start, 6))
    manifest_path = output_dir / "finish_manifest.json"
    if only is not None and manifest_path.exists():
        prior_manifest = json.loads(manifest_path.read_text())
        prior = {r["index"]: r for r in prior_manifest["sets"]}
        prior_spend = prior_manifest.get("summary", {}).get("unit_spend_usd", 0.0)
        merged_records = []
        for number in range(1, len(sets) + 1):
            fresh = next((r for r in records if r["index"] == number), None)
            merged_records.append(
                fresh if fresh is not None else prior.get(number, {"index": number})
            )
        records = merged_records
        summary = _summarize(records, elapsed, round(prior_spend + (spend_end - spend_start), 6))
    attach_look(records, mls_matches, mls_dir, output_dir)
    manifest = {"summary": summary, "sets": records}
    manifest_path.write_text(json.dumps(manifest, indent=2, default=str))
    ensure_merge_thumbs(output_dir, manifest)
    build_finish_review(output_dir, manifest, mls_matches)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="Finish one unit's bracket sets.")
    parser.add_argument("unit_dir", type=Path, help="e.g. inputs/unit-a")
    parser.add_argument("--output", type=Path, required=True, help="e.g. output/unit-a")
    parser.add_argument("--only", default=None, help="e.g. 12,13 to retry just those sets")
    parser.add_argument(
        "--replay",
        action="store_true",
        help="re-run every set's local tail with saved Meta results, no Meta calls",
    )
    args = parser.parse_args()
    only = {int(n) for n in args.only.split(",")} if args.only else None
    manifest = run_finish(
        args.unit_dir / "raw", args.unit_dir / "mls", args.output, only=only, replay=args.replay
    )
    print(json.dumps(manifest["summary"], indent=2))


if __name__ == "__main__":
    main()
