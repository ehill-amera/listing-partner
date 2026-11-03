"""Unit 2 pipeline: bracket sets in, finished listing photos out.

Per set: estimate one set of white-balance multipliers and decode every
frame with them (linear light, before anything clips), undistort each
frame (vendored lens profile, per-photo fitted strength) and correct TCA,
align, fuse the chosen subset, straighten verticals, balance exposure, SAM
windows plus Spark verdicts (found, not
edited: window pulls are off for this unit), denoise last, crop to valid
pixels plus the dark edge fringe, save. Every Meta call goes through the
spend-capped client; failures land in plain words and still count.
"""

from __future__ import annotations

import argparse
import gc
import json
import resource
import sys
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
    window_mask: np.ndarray | None = None,
) -> dict:
    """Local prep for one set: white balance, geometry, merge, balance, send size.

    No Meta calls, and no MLS twin: every decision reads the set's own
    frames through the frozen shared look. Fills record in place (partial
    on failure, like before) and returns the state the Meta step and the
    tail need.

    window_mask is the union of the set's confirmed window masks: the only
    place the cool trigger can act. A fresh set has none yet, so it builds without
    one, asks Meta, then calls apply_window_mask.
    """
    wb = hdr.estimate_set_wb(members)
    record["wb_estimate"] = wb["multipliers"]
    if wb["multipliers"] is None:
        record["wb_as_shot"] = wb["as_shot_reason"]
    state = _prepare(members, record, wb, window_mask)
    state["wb"] = wb
    _read_bright_surfaces(record, state, window_mask)
    return state


def apply_window_mask(record: dict, state: dict, window_mask: np.ndarray) -> dict:
    """Rebalance a fresh set once its windows are known, then read its bright surfaces."""
    wb = state["wb"]
    state["balanced"], record["balance"] = finish.balance_exposure(
        state["merged"],
        anchor_mask=state["anchor"],
        scene=wb["scene"],
        sky=wb["sky"],
        window_mask=window_mask,
    )
    _read_bright_surfaces(record, state, window_mask)
    return state


def _read_bright_surfaces(record: dict, state: dict, window_mask: np.ndarray | None) -> None:
    """Bright cyan/blue share before the tail, whole frame and outside the windows.

    Measured only. The share never changes the white balance (contract 02,
    navigator decision of Nov 1): a photo over the limit is a known limit.
    """
    excluded = None if window_mask is None else finish.grown_window_mask(window_mask)
    record["bright_share"] = round(checks.bright_surface_share(state["balanced"]), 2)
    record["bright_share_outside"] = round(
        checks.bright_surface_share(state["balanced"], exclude=excluded), 2
    )


def _prepare(
    members: list[Path], record: dict, wb: dict, window_mask: np.ndarray | None = None
) -> dict:
    """Decode every frame with one white balance, then everything downstream."""
    focals = [geometry.read_focal(p) for p in members]
    identity = geometry.read_lens_identity(members[len(members) // 2])
    profile = geometry.match_profile(identity)
    record["focal"] = sorted({f for f in focals if f})
    decoded = [hdr.decode_frame(p, wb=wb["multipliers"]) for p in members]
    if profile is None:
        # Contract A0: with no profile the step is skipped for this photo
        # and the page says so. Frames go through uncorrected; every later
        # step still runs, so one odd lens never fails a photo.
        record["lens"] = "skipped: no lens profile matches this lens"
        record["vignetting"] = "skipped: no lens profile to correct from"
        record["tca"] = "skipped: no lens profile"
        record["distortion_strength"] = {}
        corrected = [frame.copy() for frame in decoded]
        record["distortion_applied"] = False
        record["straight_before"] = geometry.line_measure(decoded[len(decoded) // 2])
        record["straight_after"] = None
        ghost = geometry.ghosting_score(corrected)
        record["ghosting"] = round(ghost, 4)
        record["deghost"] = geometry.deghost_decision(ghost)
        h0, w0 = corrected[0].shape[:2]
        valid = np.ones((h0, w0), bool)
    else:
        record["lens"] = "Nikon AF-P DX 10-20mm (vendored lensfun profile)"
        mid_focal = focals[len(focals) // 2] or 10.0
        if geometry.vignetting_params(profile, mid_focal) is None:
            record["vignetting"] = (
                "skipped: the vendored lensfun profile carries no vignetting model for this lens"
            )
        else:
            record["vignetting"] = "applied from the lens profile"

        strengths: dict[float, float] = {}
        corrected = []
        tca_ran = False
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
                tca_ran = True
            corrected.append(fixed)
        record["distortion_strength"] = strengths
        record["tca"] = (
            "applied lateral-CA channel rescale"
            if tca_ran
            else "skipped: the profile carries no TCA row at these focals"
        )
        ghost = geometry.ghosting_score(corrected)
        record["ghosting"] = round(ghost, 4)
        record["deghost"] = geometry.deghost_decision(ghost)
        h0, w0 = corrected[0].shape[:2]
        valid = np.ones((h0, w0), bool)
        for frame_focal, strength in strengths.items():
            if strength > 0:
                dx, dy = geometry._displacement_field(profile, frame_focal, w0, h0)
                valid &= geometry.undistort_valid_mask(h0, w0, strength * dx, strength * dy)

        # Lens straightness on the same frame before and after: the middle
        # frame raw from the decoder, then that frame lens-corrected. When
        # the correction left the frame untouched the two are the same image
        # and the check reports not measured instead of a hollow pass.
        mid = len(decoded) // 2
        straight_before = geometry.line_measure(decoded[mid])
        if np.array_equal(decoded[mid], corrected[mid]):
            record["distortion_applied"] = False
            straight_after = None
        else:
            record["distortion_applied"] = True
            straight_after = geometry.line_measure(corrected[mid])
        record["straight_before"] = straight_before
        record["straight_after"] = straight_after

    aligned = hdr.align_to_first(corrected)
    options = hdr.merge_options(members)
    order = {p: i for i, p in enumerate(members)}
    merges = {}
    for key, subset in options.items():
        idx = [order[p] for p in subset]
        merges[key] = hdr.fuse_exposures([aligned[i] for i in idx])
    best_key, best_score, _ = hdr.choose_from_merges(merges, scene=wb["scene"], sky=wb["sky"])
    merged = merges[best_key]
    record["frames_used"] = [p.name for p in sorted(options[best_key], key=lambda p: order[p])]
    record["frames_reason"] = f"{best_key}: {best_score}"
    record["darkest_available"] = hdr.darkest_for_windows(members).name

    gray = cv2.cvtColor(merged, cv2.COLOR_RGB2GRAY)
    # Verticals before and after on the merged room photo going into and
    # out of rotation, by the length-weighted median of near-vertical
    # segments. Rotation repeats until the residual is within half a
    # degree; perspective correction is out of scope for this unit.
    tilt = geometry.dominant_vertical_angle(gray)
    record["vertical_before"] = tilt
    # Keep the undistort validity above: rotations blacken more borders,
    # they never repair undistort's. Resetting here kept ~20px black bands.
    if geometry.needs_rotation(tilt):
        merged, applied = geometry.correct_verticals(merged)
        valid &= geometry.rotation_valid_mask(*gray.shape, applied)
        residual = geometry.dominant_vertical_angle(cv2.cvtColor(merged, cv2.COLOR_RGB2GRAY))
        record["verticals"] = (
            f"rotated {applied:.2f} deg to upright "
            f"(tilt {tilt:.2f} -> {residual if residual is None else f'{residual:.2f}'} deg)"
        )
    elif tilt is not None:
        applied = 0.0
        residual = tilt
        record["verticals"] = f"level already (tilt {tilt:.2f} deg from verticals)"
    else:
        applied = 0.0
        residual = None
        record["verticals"] = "no agreeing verticals found (not measured)"
    record["vertical_residual"] = residual

    # The gain anchors on the exact pixels the final crop keeps: the
    # centered crop can cut valid-but-dark edges past the validity mask,
    # which would otherwise land the shipped file off target.
    y0, y1, x0, x1 = geometry.crop_valid_rect(valid)
    anchor = np.zeros_like(valid)
    anchor[y0:y1, x0:x1] = True
    balanced, balance_report = finish.balance_exposure(
        merged, anchor_mask=anchor, scene=wb["scene"], sky=wb["sky"], window_mask=window_mask
    )
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
        "merged": merged,
        "anchor": anchor,
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


def tint_overlay(base: np.ndarray, union: np.ndarray) -> np.ndarray:
    """The base photo with confirmed window glass tinted red.

    Tint touches masked pixels only: overlay equals base everywhere
    outside the union, which is what proves the outline sits over that
    photo and not some other image.
    """
    overlay = base.copy()
    if union.any():
        overlay[union] = (overlay[union] * 0.5 + np.array([255, 0, 0]) * 0.5).astype(np.uint8)
    return overlay


#: The floor zone as fractions of the shipped frame: the whole
#: visible floor (the lower half), never a window band. Window-adjacent
#: bands boxed lavender floors out of the measurement (finding 6).
FLOOR_ZONE_FRAC = (0.5, 1.0, 0.0, 1.0)


def finish_tail(
    record: dict,
    state: dict,
    dirs: dict,
    masks: dict[int, np.ndarray],
    union: np.ndarray,
    rej_masks: dict[int, np.ndarray] | None = None,
) -> None:
    """Local tail after verdicts: denoise, crop, checks, saves.

    No Meta calls, no MLS twin. Fills the measured fields of record in
    place. Window pulls are off for this unit (contract 02, Erik's
    decision Oct 30): every confirmed window keeps the balanced merge's
    pixels, labeled "found, not edited". Clip numbers are fractions of
    window pixels read on one scale both sides: before from the
    balanced crop, after back from the saved JPEG file, the actual
    final output (contract 02, final round). Both sides read the
    balanced merge this unit; no pull changes either.
    """
    from listing_partner.checks import CLIP_LEVEL

    name = record["name"]
    balanced = state["balanced"]
    valid = state["valid"]
    # One shared crop for measurement and file. The valid-pixel crop
    # drops undistort/rotation borders; the edge trim then drops the
    # darker resampling fringe inside them, so the file holds exactly
    # the measured pixels.
    y0, y1, x0, x1 = geometry.crop_valid_rect(valid)
    trim = geometry.trim_dark_edges(balanced[y0:y1, x0:x1])
    record["edge_trim"] = trim
    y0 += trim["top"]
    y1 -= trim["bottom"]
    x0 += trim["left"]
    x1 -= trim["right"]

    def _crop(arr: np.ndarray) -> np.ndarray:
        return arr[y0:y1, x0:x1]

    balanced_c = _crop(balanced)
    union_c = _crop(union)
    composed = balanced_c.copy()
    for window in record.get("windows", []):
        window["pull"] = "found, not edited"
        window["pull_reason"] = (
            "window pulls are off for this unit: kept the balanced merge's pixels"
        )
    record["pull_frame"] = None
    record["pull_frames"] = []
    record["windows_not_edited"] = len(record.get("windows", []))
    changed_outside = int((np.any(composed != balanced_c, axis=2) & ~union_c).sum())

    # Same patches both sides: the patch set is picked on the pulled
    # photo, so the drop is the denoiser's work on the same pixels, not
    # two different populations.
    patches = finish.flat_patch_mask(composed)
    noise_before = finish.flat_noise(composed, patches)
    edge_before = finish.edge_strength(composed)
    finished = finish.denoise(composed)
    record["noise_before"] = round(noise_before, 2)
    record["noise_after"] = round(finish.flat_noise(finished, patches), 2)
    record["edge_before"] = round(edge_before, 1)
    record["edge_after"] = round(finish.edge_strength(finished), 1)
    window_pixels = int(union_c.sum())
    if window_pixels:
        # Any channel at 250, as the contract says: grayscale understates
        # blowout, and a result shaped by clamping would not count. Both
        # sides read the same uint8 scale: before from the balanced crop,
        # after back from the saved file below.
        clip_before_n = int(((balanced_c.max(axis=2) >= CLIP_LEVEL) & union_c).sum())
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
        clip_after_n = int(((reread_rgb.max(axis=2) >= CLIP_LEVEL) & union_c).sum())
    else:
        clip_after_n = 0
    record["clip_after_n"] = clip_after_n
    clip_after_raw = clip_after_n / max(1, window_pixels)
    record["clip_after"] = round(clip_after_raw, 4)
    record["bright_outside_file"] = checks.bright_surface_share(
        reread_rgb, exclude=_crop(finish.grown_window_mask(union))
    )
    # Verticals on the finished file itself: the merge-time residual
    # below is the before story, this is what shipped.
    vertical_final = geometry.dominant_vertical_angle(cv2.cvtColor(reread_rgb, cv2.COLOR_RGB2GRAY))
    record["vertical_final"] = vertical_final

    # Criteria 4, 5 and 6 are paused with the pulls: the clip numbers
    # above are reported, never gated, and step B is off, so its checks
    # have nothing to measure.
    highlights: tuple[bool, str] = (
        False,
        "not measured: window pulls are off for this unit (criterion 4 paused)",
    )
    outside: tuple[bool, str] = (
        False,
        "not measured: window pulls are off for this unit (criterion 5 paused)",
    )
    record["checks"] = {
        "highlights": highlights,
        "outside": outside,
        "noise": checks.check_noise(noise_before, record["noise_after"]),
        "edges": checks.check_edges(edge_before, record["edge_after"]),
        "straightness": checks.check_straightness(
            record["straight_before"],
            record["straight_after"],
            record.get("distortion_applied", True),
        ),
        "verticals": checks.check_verticals(vertical_final),
    }
    gate = (record.get("balance") or {}).get("cool_gate") or {}
    record["checks"]["cool edge"] = checks.check_region_edge(
        gate.get("edge_step_a"), gate.get("edge_step_b")
    )
    # Floor zone as fractions of the shipped frame, so the post-hoc
    # measure maps it onto the MLS twin too: the whole visible floor.
    record["floor_zone"] = FLOOR_ZONE_FRAC
    # The third image is the window mask over the balanced merge (tinted
    # balance output), not over the finished photo.
    thumb = cv2.resize(
        finished,
        (1024, int(round(finished.shape[0] * 1024 / finished.shape[1]))),
        interpolation=cv2.INTER_AREA,
    )
    save_clean_jpeg(thumb, dirs["review"] / f"finished_{name}.jpg")
    overlay_thumb = cv2.resize(
        tint_overlay(balanced_c, union_c),
        (1024, int(round(finished.shape[0] * 1024 / finished.shape[1]))),
        interpolation=cv2.INTER_AREA,
    )
    save_clean_jpeg(overlay_thumb, dirs["review"] / f"overlay_{name}.jpg")
    # Rejected candidates get their own overlay thumbs, so every
    # rejection on the page shows its mask, not just its reason.
    for rej_id, rej_mask in (rej_masks or {}).items():
        rej_c = _crop(rej_mask)
        rej_thumb = cv2.resize(
            tint_overlay(balanced_c, rej_c),
            (1024, int(round(finished.shape[0] * 1024 / finished.shape[1]))),
            interpolation=cv2.INTER_AREA,
        )
        save_clean_jpeg(rej_thumb, dirs["review"] / f"rejected_{name}_{rej_id}.jpg")


def replay_set(prior: dict, members: list[Path], dirs: dict) -> dict:
    """Re-run one set's local tail with its saved Meta results.

    Makes no Meta calls: verdicts, masks and transcripts come from the
    prior record and the saved mask files. Raises with a plain reason.
    """
    record: dict = {
        "index": prior["index"],
        "name": prior["name"],
        "notes": list(prior.get("notes", [])),
        "windows": [
            {"id": w["id"], "box": w.get("box"), "reason": w.get("reason", "")}
            for w in prior.get("windows", [])
        ],
    }
    # The cool trigger reads the window masks, so they load before the balance.
    masks: dict[int, np.ndarray] = {}
    for window in prior.get("windows", []):
        path = dirs["masks"] / f"{record['name']}_window{window['id']}.png"
        mask = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
        if mask is None:
            raise ValueError(f"saved mask missing for window {window['id']}: {path.name}")
        masks[window["id"]] = mask > 127
    window_mask = None
    if masks:
        shapes = {mask.shape for mask in masks.values()}
        if len(shapes) != 1:
            raise ValueError(f"saved masks for {record['name']} disagree on size: {shapes}")
        window_mask = np.logical_or.reduce(list(masks.values()))
    state = build_inputs(members, record, window_mask=window_mask)
    union = np.zeros((state["h"], state["w"]), bool)
    if window_mask is not None:
        union = window_mask
    rej_masks: dict[int, np.ndarray] = {}
    for rejection in prior.get("rejections", []):
        mask_file = rejection.get("mask_file")
        if not mask_file:
            continue  # saved before rejected masks existed: reason only
        path = dirs["masks"] / mask_file
        mask = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
        if mask is None:
            raise ValueError(f"saved mask missing for rejection {rejection['id']}: {path.name}")
        if mask.shape != (state["h"], state["w"]):
            raise ValueError(
                f"saved mask {path.name} is {mask.shape}, expected {(state['h'], state['w'])}"
            )
        rej_masks[rejection["id"]] = mask > 127
    finish_tail(record, state, dirs, masks, union, rej_masks=rej_masks)
    # The set's images die here, before the next set starts: nothing in
    # the record references them (records are numbers, and the manifest
    # must stay JSON-serializable), so refcounting plus the caller's
    # gc.collect() returns the memory instead of growing across 17 sets.
    del state, union, masks
    # The saved verdicts stand; the found-not-edited labels are this
    # run's: carry them onto the prior window rows by id.
    labeled = {w["id"]: w for w in record.get("windows", [])}
    for window in prior.get("windows", []):
        fresh = labeled.get(window["id"], {})
        for key in ("pull", "pull_reason"):
            if key in fresh:
                window[key] = fresh[key]
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
        # No cool trigger on what Meta sees: the masks do not exist yet.
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
        # Width first, height second: the full-res frame is w columns by
        # h rows, and a transposed call scales boxes and masks onto a
        # swapped frame (dormant since the pulls-off replay bypasses this
        # line; fresh sets failed on it in the final round).
        scaled = segment.scale_candidates(candidates, state["sent_w"], state["sent_h"], w, h)
        confirmed = [c for c in scaled if verdicts.get(c["object_id"], (False, ""))[0]]
        record["windows"] = [
            {
                "id": c["object_id"],
                "box": c["box"],
                "reason": verdicts[c["object_id"]][1],
            }
            for c in confirmed
        ]
        rejected = [
            c for c in scaled if c["object_id"] in verdicts and not verdicts[c["object_id"]][0]
        ]
        record["rejections"] = [
            {
                "id": c["object_id"],
                "box": list(c["box"]),
                "reason": verdicts[c["object_id"]][1],
                "mask_file": f"{name}_rejected{c['object_id']}.png",
            }
            for c in rejected
        ]
        union = np.zeros((h, w), bool)
        masks: dict[int, np.ndarray] = {}
        for c in confirmed:
            union |= c["mask"]
            masks[c["object_id"]] = c["mask"]
            segment.save_mask_png(
                c["mask"],
                dirs["masks"] / f"{name}_window{c['object_id']}.png",
            )
        rej_masks: dict[int, np.ndarray] = {}
        for c in rejected:
            rej_masks[c["object_id"]] = c["mask"]
            segment.save_mask_png(
                c["mask"],
                dirs["masks"] / f"{name}_rejected{c['object_id']}.png",
            )
        state = apply_window_mask(record, state, union)
        finish_tail(record, state, dirs, masks, union, rej_masks=rej_masks)
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


def _lens_note(entry: dict) -> str:
    """Plain reason when the distortion fit voted the step down.

    A fitted strength of 0 on every focal length means the line sweep
    on a center crop did not improve, so no distortion correction ran
    on that photo. Anything else (including a missing strength record)
    carries no note.
    """
    strengths = entry.get("distortion_strength")
    if not isinstance(strengths, dict) or not strengths:
        return ""
    try:
        if all(float(value) == 0.0 for value in strengths.values()):
            note = (
                " (fitted strength 0: the line sweep on a center crop"
                " did not improve, so no distortion correction ran"
            )
            if entry.get("tca", "").startswith("applied"):
                note += (
                    "; any small straightness change is TCA resampling,"
                    " the only other step that touches the frame"
                )
            return note + ")"
    except (TypeError, ValueError):
        return ""
    return ""


def _window_lines(windows: list[dict]) -> str:
    """One page line per confirmed window: found, not edited."""
    lines = []
    for w in windows:
        lines.append(
            f"<p>window {w['id']}: {w.get('reason', '')} — "
            "found, not edited (window pulls are off for this unit)</p>"
        )
    return "".join(lines)


def _look_cell(look: dict | None) -> str:
    """Look numbers with their verdict: every row shows pass or fail."""
    if not look:
        return "<p>look: not measured, no MLS photo</p>"
    verdict = "PASS" if look.get("look_ok") else "FAIL"
    return f"<p>{verdict} look: {look.get('look_reason', '')}</p>"


def _wb_cell(entry: dict) -> str:
    """White-balance state: the set's multipliers, or as-shot and why no estimate exists."""
    as_shot = entry.get("wb_as_shot")
    if as_shot:
        return f"<p>camera as-shot white balance: {as_shot}</p>"
    wb = entry.get("wb_estimate")
    if wb:
        return f"<p>white balance at raw decode (R {wb[0]}, G {wb[1]}, B {wb[2]}), one per set</p>"
    return "<p>white balance: not recorded</p>"


def _bright_cell(bright: dict | None) -> str:
    """Bright-surface numbers with their verdict, or why there is none."""
    if not bright or bright.get("bright_share") is None:
        return "<p>bright surfaces: not measured</p>"
    verdict = "PASS" if bright.get("bright_ok") else "FAIL"
    limit = (
        "; known limit: over the limit outside windows, not changed"
        if bright.get("known_limit")
        else ""
    )
    return f"<p>{verdict} {bright.get('bright_reason', '')}{limit}</p>"


def _known_limits_line(limits: list[dict] | None) -> str:
    """Photos over the bright-surface limit outside their windows, for the page top."""
    if limits is None:
        listed = "not recorded"
    elif limits:
        listed = ", ".join(f"{item['name']} ({item['outside']:.2f}%)" for item in limits)
    else:
        listed = "none"
    return (
        f"<p>Known limit, bright cyan/blue over {checks.BRIGHT_SURFACE_LIMIT_PCT:.0f}% "
        f"of the frame outside the windows on the saved file: {listed}. "
        "Listed, not changed.</p>"
    )


def _bright_known_limits(records: list[dict]) -> list[dict]:
    """Every measured photo whose saved file reads over the limit outside its windows."""
    return [
        {"name": r.get("name"), "outside": r["bright"]["bright_share_outside"]}
        for r in records
        if (r.get("bright") or {}).get("known_limit")
    ]


def _flat_white_cell(flat: dict | None) -> str:
    """Flat white share next to the MLS twin's, or why there is none."""
    if not flat or flat.get("flat_white") is None:
        return "<p>flat white share: not measured</p>"
    twin = flat.get("mls_flat_white")
    twin_text = "no MLS twin" if twin is None else f"MLS twin {twin:.1f}%"
    return (
        f"<p>flat white share {flat['flat_white']:.1f}% of the frame, {twin_text} "
        "(channel spread 4 or less, mean 225 or more)</p>"
    )


def _gate_cell(entry: dict) -> str:
    """How far the cool trigger reached on this photo, from the gate it used."""
    gate = (entry.get("balance") or {}).get("cool_gate")
    if gate is None:
        return "<p>cool trigger gate share: not measured</p>"
    if not gate.get("strength"):
        return "<p>cool trigger gate share: 0.00% of the frame (did not fire)</p>"
    return (
        f"<p>cool trigger gate share {gate['frame_pct']:.2f}% of the frame, "
        f"{gate['window_pct']:.1f}% of window pixels, {gate['outside_pct']:.2f}% outside "
        f"the masks, strength {gate['strength']:.2f}</p>"
    )


def _floor_cell(floor: dict | None) -> str:
    """Floor-cast numbers with their verdict, or why there is none."""
    if not floor:
        return "<p>floor near windows: not measured</p>"
    if floor.get("floor_ok"):
        verdict = "PASS"
    elif "not measured" in floor.get("floor_reason", ""):
        verdict = "NOT MEASURED"
    else:
        verdict = "FAIL"
    return f"<p>{verdict} {floor.get('floor_reason', '')}</p>"


def build_finish_review(
    output_dir: Path, manifest: dict, mls_matches: dict, strips: dict | None = None
) -> Path:
    """review-finish.html: one row per shot plus the measured top line.

    One row per shot: our unit 1 merge, our finished photo, the window
    mask over the merge, and Erik's MLS photo. Every skipped step shows
    with its reason; every check with nothing to measure shows NOT
    MEASURED; every look row shows PASS or FAIL.
    """
    rows = []
    for entry in manifest["sets"]:
        name = entry["name"]
        if entry.get("error"):
            rows.append(f"<section><h2>Shot {name}</h2><p>FAILED: {entry['error']}</p></section>")
            continue
        windows = entry.get("windows", [])
        if windows:
            win_cell = _window_lines(windows)
        else:
            win_cell = "<p>no windows confirmed</p>"
        rejected = entry.get("rejections", [])
        rej_rows = []
        for r in rejected:
            if r.get("mask_file"):
                rej_rows.append(
                    f"<p>rejected {r['id']}: {r['reason']}</p>"
                    f'<img src="review/rejected_{name}_{r["id"]}.jpg" loading="lazy">'
                )
            else:
                rej_rows.append(
                    f"<p>rejected {r['id']}: {r['reason']} (mask not saved by that run)</p>"
                )
        rej_cell = "".join(rej_rows)
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
        look_cell = _look_cell(entry.get("look"))
        floor_cell = _floor_cell(entry.get("floor"))
        wb_cell = _wb_cell(entry)
        bright_cell = _bright_cell(entry.get("bright"))
        flat_cell = _flat_white_cell(entry.get("flat_white"))
        gate_cell = _gate_cell(entry)
        trim = entry.get("edge_trim") or {}
        trim_cell = (
            f"<p>edge trim (px): top {trim.get('top', 0)}, bottom {trim.get('bottom', 0)}, "
            f"left {trim.get('left', 0)}, right {trim.get('right', 0)}</p>"
            if trim
            else ""
        )
        clip_cell = (
            f"<p>window clip {entry.get('clip_before', 0.0):.4f} -&gt; "
            f"{entry.get('clip_after', 0.0):.4f} of window pixels "
            f"({entry.get('window_pixels', 0)} px, one scale both sides: "
            "before from the balanced crop, after from the file; window "
            "pulls are off, so both sides read the balanced merge)</p>"
        )
        rows.append(
            f"<section><h2>Shot {name}</h2>"
            f"<p>{', '.join(entry.get('frames_used', []))}</p>"
            f"<p>merge: {entry.get('frames_reason', '')}</p>"
            f"<p>windows: found, not edited (window pulls are off for this unit)</p>"
            f"<p>{entry.get('lens', '')}, "
            f"strength {entry.get('distortion_strength', '')}, "
            f"{entry.get('verticals', '')}, {entry.get('vignetting', '')}, "
            f"ghosting {entry.get('ghosting', '')} "
            f"({entry.get('deghost', '')}){_lens_note(entry)}</p>"
            f"{clip_cell}{look_cell}{floor_cell}{wb_cell}{bright_cell}{flat_cell}{gate_cell}{trim_cell}"
            f'<div class="row">'
            f'<div><img src="review/merged_{name}.jpg" loading="lazy">'
            f"<p>unit 1 merge</p></div>"
            f"<div>{_strip_cell((strips or {}).get(name), strips is not None)}"
            f'<img src="review/finished_{name}.jpg" loading="lazy">'
            f"<p>finished</p></div>"
            f'<div><img src="review/overlay_{name}.jpg" loading="lazy">'
            f"<p>window mask over the merge</p>{win_cell}{rej_cell}</div>"
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
    pulled_line = (
        f"<p>Windows found, not edited: {top.get('windows_not_edited', '?')} "
        f"(confirmed {top.get('windows_confirmed', '?')} of "
        f"{top.get('windows_found', '?')} candidates, "
        f"{top.get('windows_rejected', '?')} rejected). "
        "Window pulls are off for this unit.</p>"
    )
    ratio = top.get("worst_reserve_ratio")
    ratio_n = top.get("reserve_ratio_calls")
    prior_under = top.get("prior_under_one", 0)
    if ratio is not None:
        ratio_line = (
            f"<p>Lowest reservation-to-bill ratio {ratio:.2f} "
            f"across {ratio_n} settled unit calls (the worst-covered call). "
            f"{prior_under} earlier unit-1 call(s) under 1, reported separately.</p>"
        )
    else:
        ratio_line = "<p>Lowest reservation-to-bill ratio unknown.</p>"
    commit = top.get("code_commit")
    commit_line = f"<p>Run from commit {commit}.</p>" if commit else "<p>Run commit unknown.</p>"
    html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<title>Finished review: {top["photos_finished"]} finished, {top["photos_failed"]} failed</title>
<style>body{{font-family:sans-serif;max-width:1600px;margin:auto;padding:16px}}
.row{{display:grid;grid-template-columns:repeat(5,1fr);gap:8px}}
img{{width:100%;height:auto}}.row p{{font-size:12px}}
.strip{{display:flex;gap:2px;margin-bottom:4px}}.strip figure{{flex:1;margin:0;min-width:0}}
.strip img{{display:block}}.strip .unused img{{opacity:.45}}
.strip figcaption{{font-size:10px;text-align:center}}</style></head><body>
<h1>Finished review</h1>
<p>{top["photos_finished"]} finished, {top["photos_failed"]} failed,
run time {top["run_seconds"]:.0f} s.</p>
<p>Median shadow noise {top["noise_before"]:.2f} -&gt; {top["noise_after"]:.2f}.
Windows found {top["windows_found"]}, confirmed {top["windows_confirmed"]},
rejected {top["windows_rejected"]}, photos with windows {top["photos_with_windows"]}.</p>
<p>Near-white window pixels {top["clip_before_n"]} -&gt; {top["clip_after_n"]}
of {top["window_pixels"]} window pixels
({top["clip_before_pct"]:.2f}% -&gt; {top["clip_after_pct"]:.2f}%.
One scale both sides (before from the balanced crop, after from the
saved file). Window pulls are off, so both sides read the balanced
merge and no pull changes either.</p>
<p>Unit Meta spend ${top["unit_spend_usd"]:.4f} of $2.00.</p>
<p>White balance is estimated from each set's own pixels at raw decode. The bright-surface
reading never changes it. Camera as-shot only where no estimate exists (JPEG frames, or too few
readable pixels): {top.get("wb_as_shot", "?")} photo(s).
The bright-surface share counts pixels outside the confirmed window masks, with the masks
grown by the cool trigger's feather width.</p>
{_known_limits_line(top.get("bright_known_limit"))}
{pulled_line}
{ratio_line}
{commit_line}
<p>The shared look settings behind these photos were refitted in the final round,
part three (Oct 31), on these same 16 photos against their MLS twins: one set of
raw-decode white-balance multipliers per set, one global exposure gain per photo,
and one luminance-only shared tone curve. The highlight roll-off and shoulder were
rebuilt after the review of commit 970ce8f, and the roll-off's cool trigger was
confined to the window masks after the review of commit 7ee0217; the other
settings did not change.
They are frozen from this round on:
unit 5 measures the same settings, unchanged, on a held-out set. Window verdicts
and masks are the saved results; replay makes no Meta calls.</p>
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


#: Ledger total before this unit's first Meta call: unit 1's 3 live calls
#: of Oct 26 ($0.000988; every later line is this unit's). Measured from
#: the ledger, 2026-10-30, not estimated.
UNIT2_SPEND_BASELINE_USD = 0.000988


def _starting_baseline(manifest_path: Path) -> float:
    """A set's first run counts from the ledger as it stands now, so a new set
    never reports what other sets spent. A rerun keeps the set's first baseline."""
    if manifest_path.exists():
        saved = json.loads(manifest_path.read_text())
        if "spend_baseline_usd" in saved:
            return saved["spend_baseline_usd"]
    return read_spend_total()


def _unit_spend_usd(prior: dict | None, ledger_path=None) -> tuple[float, float]:
    """(baseline, unit_spend) from the ledger.

    The unit spent what the ledger holds now minus what it held before
    the unit's first call. The live total counts settled calls at actual
    cost and open reservations at estimate, so two unsettled lines can
    never understate the spend. When the ledger cannot be read, the
    prior number stands instead of a fresh zero.
    """
    baseline = (prior or {}).get("spend_baseline_usd", UNIT2_SPEND_BASELINE_USD)
    fallback = (prior or {}).get("summary", {}).get("unit_spend_usd", 0.0)
    try:
        total = read_spend_total(ledger_path)
    except MetaRefused:
        return baseline, fallback
    if total < baseline:
        return baseline, fallback
    return baseline, round(total - baseline, 6)


def _code_stamp() -> str | None:
    """The commit this run's outputs come from, plus a dirty marker.

    Makes stale outputs visible: the page shows the stamp, so a photo
    older than the code says so. Unknown when git cannot answer.
    """
    import subprocess

    try:
        sha = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        dirty = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        return sha + ("-dirty" if dirty else "")
    except Exception:  # noqa: BLE001 - any git failure reads as unknown
        return None


#: Unit 2's Meta calls start here: unit 1's 3 live calls are all Oct 26
#: ($0.000988 total), and every later ledger line is this unit's. The
#: reservation ratio page line scopes to this timestamp, so the minimum
#: it reports is the unit's own thinnest coverage.
UNIT2_RATIOS_SINCE = "2026-10-29T00:00:00+00:00"


def _summarize(records: list[dict], elapsed: float, unit_spend_usd: float) -> dict:
    """Top-line numbers from finished records. Pure, no Meta calls.

    Noise is the median across photos; clip is pooled over every
    confirmed window pixel in the run, so one big window cannot hide
    behind per-photo means. The reservation ratio is the lowest
    (worst-covered) ratio across this unit's settled calls; earlier
    units' under-covered calls count separately.
    """
    from listing_partner.meta_client import reserve_ratio_stats

    finished_records = [r for r in records if not r.get("error")]
    noises = [
        (r["noise_before"], r["noise_after"]) for r in finished_records if "noise_before" in r
    ]
    clip_before_n = sum(r.get("clip_before_n", 0) for r in finished_records)
    clip_after_n = sum(r.get("clip_after_n", 0) for r in finished_records)
    window_pixels = sum(r.get("window_pixels", 0) for r in finished_records)
    try:
        scoped = reserve_ratio_stats(since=UNIT2_RATIOS_SINCE)
        unscoped = reserve_ratio_stats()
        worst_ratio = scoped["worst"]
        ratio_calls = scoped["settled"]
        prior_under = unscoped["under_one"] - scoped["under_one"]
    except MetaRefused:
        worst_ratio, ratio_calls, prior_under = None, None, 0
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
        "windows_not_edited": sum(r.get("windows_not_edited", 0) for r in finished_records),
        "clip_before_n": clip_before_n,
        "clip_after_n": clip_after_n,
        "window_pixels": window_pixels,
        "clip_before_pct": 100 * clip_before_n / max(1, window_pixels),
        "clip_after_pct": 100 * clip_after_n / max(1, window_pixels),
        "wb_as_shot": sum(1 for r in finished_records if r.get("wb_as_shot")),
        "bright_known_limit": _bright_known_limits(finished_records),
        "unit_spend_usd": unit_spend_usd,
        "worst_reserve_ratio": worst_ratio,
        "reserve_ratio_calls": ratio_calls,
        "prior_under_one": prior_under,
        "code_commit": _code_stamp(),
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


#: Width of each raw bracket frame in the strip above a finished photo.
STRIP_WIDTH = 320


def _exposure_label(seconds: float) -> str:
    if seconds >= 1:
        return f"{seconds:g} s"
    return f"1/{round(1 / seconds)} s"


def ensure_bracket_strips(output_dir: Path, sets: list[list[Path]], manifest: dict) -> dict:
    """Small copies of every raw bracket frame per shot, darkest first.

    Decoded locally at the camera's as-shot balance with no brightening, so
    each frame shows its own exposure. A shot whose saved frames are not the
    frames grouped from the raw folder raises: a strip from the wrong set
    never reaches the page.
    """
    review_dir = output_dir / "review"
    review_dir.mkdir(parents=True, exist_ok=True)
    strips = {}
    for entry in manifest["sets"]:
        if entry.get("error"):
            continue
        number, name = entry["index"], entry["name"]
        if not 1 <= number <= len(sets):
            raise ValueError(f"shot {name}: no bracket set {number} in the raw folder")
        members = sorted(sets[number - 1], key=hdr.read_exposure_seconds)
        used = set(entry.get("frames_used", []))
        missing = used - {p.name for p in members}
        if missing:
            raise ValueError(f"shot {name}: saved frames {sorted(missing)} are not in its set")
        frames = []
        for k, path in enumerate(members):
            out = review_dir / f"bracket_{name}_{k}.jpg"
            if not out.exists():
                rgb = hdr.decode_frame(path, half_size=True)
                height = int(round(rgb.shape[0] * STRIP_WIDTH / rgb.shape[1]))
                small = cv2.resize(rgb, (STRIP_WIDTH, height), interpolation=cv2.INTER_AREA)
                save_clean_jpeg(small, out)
            frames.append(
                {
                    "file": out.name,
                    "frame": path.name,
                    "exposure": _exposure_label(hdr.read_exposure_seconds(path)),
                    "used": path.name in used,
                }
            )
        strips[name] = frames
    return strips


def _strip_cell(frames: list[dict] | None, attempted: bool) -> str:
    """The raw brackets above the finished photo; says plainly when they are missing."""
    if not frames:
        why = "no raw frames found for this shot" if attempted else "not built for this page"
        return f"<p>raw brackets: {why}</p>"
    figures = "".join(
        f'<figure class="{"used" if f["used"] else "unused"}">'
        f'<img src="review/{f["file"]}" alt="{f["frame"]}" loading="lazy">'
        f"<figcaption>{f['exposure']}</figcaption></figure>"
        for f in frames
    )
    used = sum(f["used"] for f in frames)
    return (
        f'<div class="strip">{figures}</div>'
        f"<p>raw brackets, darkest first: {len(frames)} frames, {used} merged "
        "(the dimmed ones were left out)</p>"
    )


def render_finish_page(raw_dir: Path, mls_dir: Path, output_dir: Path) -> Path:
    """Rebuild review-finish.html from the saved manifest. No Meta call and no
    decode beyond the small bracket copies; the manifest is only read."""
    manifest = json.loads((output_dir / "finish_manifest.json").read_text())
    frames = sorted(raw_dir.glob("*.NEF")) + sorted(raw_dir.glob("*.nef"))
    if not frames:
        raise ValueError(f"no bracket frames in {raw_dir}")
    sets = hdr.group_frames(frames)
    mls_matches = run_merge.match_mls(sets, mls_dir, output_dir / "merged")
    # Runs before e642dd1 built the summary before the bright reading and saved an
    # empty list. The page lists it again from each photo's saved reading.
    manifest["summary"]["bright_known_limit"] = _bright_known_limits(
        [r for r in manifest["sets"] if not r.get("error")]
    )
    ensure_merge_thumbs(output_dir, manifest)
    strips = ensure_bracket_strips(output_dir, sets, manifest)
    return build_finish_review(output_dir, manifest, mls_matches, strips)


def attach_look(records: list[dict], mls_matches: dict, mls_dir: Path, output_dir: Path) -> None:
    """Post-hoc criterion-11 and floor numbers per shot, from shipped files.

    Runs after processing, never during: the MLS twin is read here only
    to verify the result, exactly as the contract allows.
    """
    from listing_partner import measure

    for record in records:
        if record.get("error"):
            continue
        number = record["index"]
        mls_here = [p for p, i in mls_matches.items() if i["set"] == number - 1]
        finished_path = output_dir / "finished" / f"{record['name']}.jpg"
        if not mls_here:
            record["look"] = None
            mls_path = None
        else:
            mls_path = mls_dir / mls_here[0]
            try:
                record["look"] = measure.look_stats(finished_path, mls_path)
            except ValueError as exc:
                record["look"] = {"look_ok": False, "look_reason": str(exc)}
        try:
            record["floor"] = measure.floor_cast_stats(
                finished_path, mls_path, record.get("floor_zone")
            )
        except ValueError as exc:
            record["floor"] = {
                "floor_cast": None,
                "mls_floor_cast": None,
                "floor_ok": False,
                "floor_reason": f"not measured: {exc}",
            }
        try:
            record["flat_white"] = measure.flat_white_stats(finished_path, mls_path)
        except ValueError as exc:
            record["flat_white"] = None
            record.setdefault("notes", []).append(f"flat white not measured: {exc}")
        # The bright-surface check runs per interior photo (contract 02,
        # final round part two): on exteriors real sky trips the measure,
        # so those rows report not measured, never pass or fail.
        if (record.get("balance") or {}).get("scene", "interior") != "interior":
            record["bright"] = {
                "bright_share": None,
                "mls_bright_share": None,
                "bright_ok": False,
                "bright_reason": "not measured: exterior scene, real sky trips the measure",
            }
        else:
            try:
                record["bright"] = measure.bright_surface_stats(
                    finished_path, mls_path, record.get("bright_outside_file")
                )
            except ValueError as exc:
                record["bright"] = {
                    "bright_share": None,
                    "mls_bright_share": None,
                    "bright_ok": False,
                    "bright_reason": f"not measured: {exc}",
                }


def peak_rss_mb() -> float:
    """Peak resident set size of this process in MiB, for the run log."""
    peak = float(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    if sys.platform == "darwin":
        return peak / (1024.0 * 1024.0)
    return peak / 1024.0


def run_replay(sets: list, mls_matches: dict, mls_dir: Path, output_dir: Path, dirs: dict) -> dict:
    """Re-run every set's local tail with its saved Meta results.

    Makes no Meta calls. Rewrites finished photos, review thumbs and the
    manifest; priors with errors are kept as-is. The unit spend stays the
    prior run's: replaying cost nothing. Sets run strictly one at a time
    in this process (no workers): each set's images are released before
    the next starts, and the run log carries one peak-memory line per set.
    """
    manifest_path = output_dir / "finish_manifest.json"
    prior_manifest = json.loads(manifest_path.read_text())
    prior = {r["index"]: r for r in prior_manifest["sets"]}
    records = []
    started = time.perf_counter()
    for number, members in enumerate(sets, 1):
        old = prior.get(number)
        if old is None or old.get("error"):
            records.append(old if old is not None else {"index": number})
            print(f"set {number}/{len(sets)}: kept prior record", flush=True)
        else:
            try:
                record = replay_set(old, members, dirs)
                print(f"set {number}/{len(sets)}: replayed", flush=True)
            except Exception as exc:  # noqa: BLE001 - every failure lands in plain words
                record = dict(old)
                record["error"] = f"{type(exc).__name__}: {exc}"
                record["traceback"] = traceback.format_exc(limit=3)
                print(f"set {number}/{len(sets)}: REPLAY FAILED {record['error']}", flush=True)
            records.append(record)
        gc.collect()
        print(
            f"set {number}/{len(sets)}: peak_rss_mb={peak_rss_mb():.0f}",
            flush=True,
        )
    elapsed = time.perf_counter() - started
    attach_look(records, mls_matches, mls_dir, output_dir)
    baseline, unit_spend = _unit_spend_usd(prior_manifest)
    summary = _summarize(records, elapsed, unit_spend)
    manifest = {"summary": summary, "sets": records, "spend_baseline_usd": baseline}
    manifest_path.write_text(json.dumps(manifest, indent=2, default=str))
    ensure_merge_thumbs(output_dir, manifest)
    strips = ensure_bracket_strips(output_dir, sets, manifest)
    build_finish_review(output_dir, manifest, mls_matches, strips)
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
    dirs = {"finished": finished_dir, "masks": masks_dir, "review": review_dir}
    if replay:
        if only is not None:
            raise ValueError("--replay processes every set, it cannot combine with --only")
        return run_replay(sets, mls_matches, mls_dir, output_dir, dirs)
    prior_manifest = None
    manifest_path = output_dir / "finish_manifest.json"
    if only is not None and manifest_path.exists():
        prior_manifest = json.loads(manifest_path.read_text())
    start_baseline = _starting_baseline(manifest_path)
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
    if prior_manifest is not None:
        prior = {r["index"]: r for r in prior_manifest["sets"]}
        merged_records = []
        for number in range(1, len(sets) + 1):
            fresh = next((r for r in records if r["index"] == number), None)
            merged_records.append(
                fresh if fresh is not None else prior.get(number, {"index": number})
            )
        records = merged_records
    baseline, unit_spend = _unit_spend_usd(prior_manifest or {"spend_baseline_usd": start_baseline})
    # The bright reading lands in attach_look; the summary lists it, so it comes after.
    attach_look(records, mls_matches, mls_dir, output_dir)
    summary = _summarize(records, elapsed, unit_spend)
    manifest = {"summary": summary, "sets": records, "spend_baseline_usd": baseline}
    manifest_path.write_text(json.dumps(manifest, indent=2, default=str))
    ensure_merge_thumbs(output_dir, manifest)
    strips = ensure_bracket_strips(output_dir, sets, manifest)
    build_finish_review(output_dir, manifest, mls_matches, strips)
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
    parser.add_argument(
        "--render-only",
        action="store_true",
        help="rebuild review-finish.html from the saved manifest, no Meta calls",
    )
    args = parser.parse_args()
    if args.render_only:
        page = render_finish_page(args.unit_dir / "raw", args.unit_dir / "mls", args.output)
        print(f"page: {page}")
        return
    only = {int(n) for n in args.only.split(",")} if args.only else None
    manifest = run_finish(
        args.unit_dir / "raw", args.unit_dir / "mls", args.output, only=only, replay=args.replay
    )
    print(json.dumps(manifest["summary"], indent=2))


if __name__ == "__main__":
    main()
