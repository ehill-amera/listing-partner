"""White balance at raw decode (contract 02, final round part three).

The far side is a fake sensor standing in for rawpy: it clips each channel
at sensor saturation, applies whatever multipliers it is asked for, clips
again, and returns display or linear pixels. Everything on our side runs
for real: the set estimate, the merge, the balance, the fallback.
"""

from pathlib import Path

import cv2
import numpy as np
import pytest

from listing_partner import checks, finish, geometry, hdr, run_finish

AS_SHOT = [2.285, 1.0, 1.227, 1.0]
#: Tungsten light as the sensor sees a neutral wall: the channel ratios
#: a daylight as-shot setting leaves far too yellow.
TUNGSTEN = np.array([0.62, 1.0, 0.30], np.float32)


class _FakeRaw:
    camera_whitebalance = AS_SHOT

    def __init__(self, linear, log):
        self.linear = linear
        self.log = log

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def postprocess(self, **kw):
        self.log.append(kw)
        if kw.get("use_camera_wb"):
            mult = np.array(AS_SHOT[:3], np.float32)
        else:
            mult = np.array(kw["user_wb"][:3], np.float32)
        # LibRaw's clip mode: multipliers normalize to the smallest, so
        # saturated pixels reach white on every channel.
        mult = mult / mult.min()
        out = np.clip(np.clip(self.linear, 0, 1) * mult, 0, 1)
        if kw.get("half_size"):
            out = out[::2, ::2]
        if kw.get("gamma") == (1, 1):
            return (out * 65535.0 + 0.5).astype(np.uint16)
        return (np.power(out, 1 / 2.2) * 255.0 + 0.5).astype(np.uint8)


def _room(light=TUNGSTEN):
    """A wall of neutral paint plus darker wood, lit by one light (camera linear)."""
    h, w = 240, 360
    paint = np.ones((h, w, 3), np.float32) * 0.5
    paint[160:] = np.array([0.30, 0.22, 0.14], np.float32)  # wood floor
    paint[40:70, 40:120] = 0.15  # dark picture frame, so frames align
    return paint * light


def _install(monkeypatch, scene):
    """Five bracket frames of one scene through the fake sensor."""
    log: list[dict] = []
    exposures = {f"frame{i}.NEF": 2.0 ** (i - 2) for i in range(5)}
    monkeypatch.setattr(
        hdr.rawpy, "imread", lambda p: _FakeRaw(scene * exposures[Path(p).name], log)
    )
    monkeypatch.setattr(hdr, "read_exposure_seconds", lambda p: exposures[Path(p).name])
    monkeypatch.setattr(geometry, "read_focal", lambda p: 10.0)
    monkeypatch.setattr(geometry, "read_lens_identity", lambda p: {})
    monkeypatch.setattr(geometry, "match_profile", lambda identity: None)
    return [Path(name) for name in exposures], log


def _full_decodes(log):
    """The display decodes that feed the merge: full size, not the quick reads."""
    return [kw for kw in log if not kw.get("half_size")]


def _lab_ab(rgb):
    lab = cv2.cvtColor(rgb.astype(np.uint8), cv2.COLOR_RGB2LAB).astype(float)
    return float(lab[:, :, 1].mean() - 128), float(lab[:, :, 2].mean() - 128)


def test_every_frame_decodes_with_one_set_of_multipliers(monkeypatch):
    """One set of channel multipliers per set, handed to the raw decoder."""
    members, log = _install(monkeypatch, _room())
    run_finish.build_inputs(members, {"index": 1, "name": "001", "notes": []})
    full = _full_decodes(log)
    assert len(full) == len(members), f"{len(full)} merge decodes for {len(members)} frames"
    used = {tuple(kw.get("user_wb") or ()) for kw in full}
    assert () not in used, "frames decoded with the camera's as-shot balance, not the set's"
    assert len(used) == 1, f"frames of one set got different multipliers: {used}"


def test_warm_room_wall_lands_near_neutral(monkeypatch):
    """A tungsten-lit neutral wall comes out near neutral, with no cap in the way.

    The part-two path decoded at the camera's daylight setting and could
    only move blue 1.25x on the 8-bit merge, so this wall stayed yellow.
    """
    members, _ = _install(monkeypatch, _room())
    state = run_finish.build_inputs(members, {"index": 1, "name": "001", "notes": []})
    _, b = _lab_ab(state["balanced"][80:150, 150:350])
    assert abs(b) <= 12.0, f"wall b* {b:+.1f}, limit 12 either way"


def test_balance_keeps_chromaticity_on_a_warm_room():
    """No white balance survives after the merge: a warm room stays warm."""
    img = np.full((200, 200, 3), (140, 118, 100), np.uint8)
    img[:40, :] = (60, 50, 42)
    out, _ = finish.balance_exposure(img)
    for row in (100, 20):
        pix = out[row, 100].astype(float)
        src = img[row, 100].astype(float)
        assert pix[0] / pix[1] == pytest.approx(src[0] / src[1], abs=0.03)
        assert pix[2] / pix[1] == pytest.approx(src[2] / src[1], abs=0.03)


def test_post_merge_white_balance_and_cap_are_gone():
    for gone in ("WB_CAP_LO", "WB_CAP_HI", "WB_BRIGHT_PERCENTILE", "WB_INTERIOR_STRENGTH"):
        assert not hasattr(finish, gone), f"post-merge white-balance constant still here: {gone}"


def _cyan_trap():
    """A warm room with a big panel, as bright as the wall, that the room's balance turns cold."""
    scene = _room()
    scene[60:130, 60:300] = np.array([0.18, 0.50, 0.22], np.float32)
    return scene


def test_fallback_ships_camera_as_shot_and_says_so(monkeypatch):
    """Over the bright-surface limit: every frame re-decodes as-shot, labeled."""
    members, log = _install(monkeypatch, _cyan_trap())
    record: dict = {"index": 1, "name": "001", "notes": []}
    state = run_finish.build_inputs(members, record)
    assert record["bright_share"] > checks.BRIGHT_SURFACE_LIMIT_PCT, (
        f"the set's balance must trip the limit, read {record['bright_share']}"
    )
    assert record.get("wb_as_shot"), "the record must carry the fallback reason"
    assert "bright cyan/blue" in record["wb_as_shot"]
    final = _full_decodes(log)[-len(members) :]
    assert all(kw.get("use_camera_wb") and not kw.get("user_wb") for kw in final)
    assert record["bright_share_final"] == pytest.approx(
        checks.bright_surface_share(state["balanced"]), abs=0.01
    )


def test_page_labels_camera_as_shot():
    html = run_finish._wb_cell({"wb_as_shot": "bright cyan/blue 3.00%"})
    assert "camera as-shot" in html and "bright cyan/blue 3.00%" in html


def test_blown_sensor_patch_stays_neutral(monkeypatch):
    """Fully saturated sensor pixels reach white at any multipliers (guard)."""
    scene = _room()
    scene[90:130, 200:260] = 40.0  # past saturation even in the darkest frame
    members, _ = _install(monkeypatch, scene)
    state = run_finish.build_inputs(members, {"index": 1, "name": "001", "notes": []})
    blown = state["balanced"][95:125, 205:255].astype(float)
    spread = float((blown.max(axis=2) - blown.min(axis=2)).mean())
    assert spread <= 15.0, f"blown patch reads tinted, mean channel spread {spread:.0f}"


def test_scene_reads_from_the_as_shot_merge(monkeypatch):
    """A neutralized interior whose window turns blue stays an interior (guard).

    The sky test runs on color: reading it after white balance would make
    any cooled window look like sky and aim the room at the exterior target.
    """
    scene = _room()
    scene[20:60, 200:300] = np.array([0.50, 0.75, 0.85], np.float32)  # window view
    members, _ = _install(monkeypatch, scene)
    record: dict = {"index": 1, "name": "001", "notes": []}
    state = run_finish.build_inputs(members, record)
    assert record["balance"]["scene"] == "interior"
    gray = cv2.cvtColor(state["balanced"], cv2.COLOR_RGB2GRAY)
    assert float(np.median(gray)) > 170.0, "the room aimed at the exterior target"


def test_jpeg_set_stays_as_shot_with_its_reason(tmp_path):
    """JPEG brackets hold no raw data: real files, as-shot, and it says why."""
    from PIL import Image

    paths = []
    for i, shade in enumerate((60, 120, 200)):
        path = tmp_path / f"frame_{i}.jpg"
        Image.new("RGB", (64, 48), (shade, shade, shade)).save(path, format="JPEG")
        paths.append(path)
    info = hdr.estimate_set_wb(paths)
    assert info["multipliers"] is None
    assert "JPEG" in info["as_shot_reason"]


def test_too_few_readable_pixels_stays_as_shot_with_its_reason(monkeypatch):
    """A middle frame with almost nothing unclipped never guesses a balance."""
    members, _ = _install(monkeypatch, np.full((240, 360, 3), 50.0, np.float32))
    info = hdr.estimate_set_wb(members)
    assert info["multipliers"] is None
    assert "unclipped pixels" in info["as_shot_reason"]


def test_real_nef_decoder_honors_the_set_multipliers():
    """The real decoder, on a real frame: more blue multiplier, more blue."""
    frames = sorted(Path("inputs/unit-a/raw").glob("*.NEF"))
    if not frames:
        pytest.skip("gitignored raw photos absent (fresh clone): real decoder not exercised")
    low = hdr.decode_raw(frames[0], half_size=True, wb=[2.0, 1.0, 1.2])
    high = hdr.decode_raw(frames[0], half_size=True, wb=[2.0, 1.0, 2.4])
    low_ratio = low[:, :, 2].mean() / max(low[:, :, 1].mean(), 1.0)
    high_ratio = high[:, :, 2].mean() / max(high[:, :, 1].mean(), 1.0)
    assert high_ratio > low_ratio * 1.1, f"B/G {low_ratio:.3f} -> {high_ratio:.3f}"


def _panel_mask():
    """The confirmed window: exactly the panel _cyan_trap paints."""
    mask = np.zeros((240, 360), bool)
    mask[60:130, 60:300] = True
    return mask


def _far_mask():
    """A confirmed window that sits nowhere near the panel."""
    mask = np.zeros((240, 360), bool)
    mask[180:230, 10:50] = True
    return mask


def _install_uncorrected_trap(monkeypatch):
    """The trap with the cool trigger off, so a panel in a mask stays cyan.

    The trigger pales a view enough to hide the panel from the fallback, and these
    tests are about what the fallback counts.
    """
    monkeypatch.setattr(finish, "ROLL_COOL_STRENGTH", 0.0)
    return _install(monkeypatch, _cyan_trap())


def test_excess_inside_the_windows_does_not_fall_back(monkeypatch):
    """The same cyan panel, called a window: the set's balance ships, not as-shot."""
    members, log = _install_uncorrected_trap(monkeypatch)
    record: dict = {"index": 1, "name": "001", "notes": []}
    run_finish.build_inputs(members, record, window_mask=_panel_mask())
    assert record["bright_share"] > checks.BRIGHT_SURFACE_LIMIT_PCT, "the frame must trip the rule"
    assert not record.get("wb_as_shot"), f"fell back: {record.get('wb_as_shot')}"
    final = _full_decodes(log)[-len(members) :]
    assert all(kw.get("user_wb") and not kw.get("use_camera_wb") for kw in final)


def test_excess_in_the_grown_ring_does_not_count(monkeypatch):
    """A mask one feather width short of the panel on each side still covers it."""
    width = int(finish.ROLL_COOL_FEATHER_FRAC * 360)
    mask = np.zeros((240, 360), bool)
    mask[60 + width : 130 - width, 60 + width : 300 - width] = True
    members, _ = _install_uncorrected_trap(monkeypatch)
    record: dict = {"index": 1, "name": "001", "notes": []}
    run_finish.build_inputs(members, record, window_mask=mask)
    assert record["bright_share_outside"] <= checks.BRIGHT_SURFACE_LIMIT_PCT
    assert not record.get("wb_as_shot"), f"fell back: {record.get('wb_as_shot')}"


def test_excess_outside_the_windows_still_falls_back(monkeypatch):
    """A window elsewhere excuses nothing: the panel still trips the rule."""
    members, log = _install_uncorrected_trap(monkeypatch)
    record: dict = {"index": 1, "name": "001", "notes": []}
    run_finish.build_inputs(members, record, window_mask=_far_mask())
    assert record.get("wb_as_shot"), "the excess outside the windows must fall back"
    final = _full_decodes(log)[-len(members) :]
    assert all(kw.get("use_camera_wb") and not kw.get("user_wb") for kw in final)


def test_fresh_set_settles_on_the_share_outside_its_windows(monkeypatch):
    """The Meta path: first balance has no masks, then the windows decide."""
    members, _ = _install_uncorrected_trap(monkeypatch)
    record: dict = {"index": 1, "name": "001", "notes": []}
    state = run_finish.build_inputs(members, record, settle_wb=False)
    assert not record.get("wb_as_shot"), "no decision before the windows are known"
    run_finish.apply_window_mask(members, record, state, _panel_mask())
    assert record["bright_share"] > checks.BRIGHT_SURFACE_LIMIT_PCT, "the frame must trip the rule"
    assert not record.get("wb_as_shot"), f"fell back: {record.get('wb_as_shot')}"
