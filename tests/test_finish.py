"""Tests for exposure balance and denoising. No network, no key."""

import cv2
import numpy as np

from listing_partner import finish


def _room_cast():
    """Gray room with a warm cast, dark corners, a true-black patch, and a
    hot floor patch."""
    img = np.full((200, 200, 3), 128, np.uint8)
    img = img.astype(np.float32)
    img[:, :, 0] *= 1.15
    img[:, :, 2] *= 0.85
    img[:40, :] *= 0.45
    img[160:, 100:] = 250
    img[:20, :20] = 5
    return np.clip(img, 0, 255).astype(np.uint8)


def test_white_balance_neutralizes_cast():
    out, _ = finish.balance_exposure(_room_cast())
    gray = out[60:140, 20:80].astype(float)
    assert abs(gray[:, :, 0].mean() - gray[:, :, 2].mean()) < 8, "walls read neutral"


def test_daylight_spill_keeps_neutral_color():
    img = np.full((200, 200, 3), (150, 100, 60), np.uint8)  # tungsten-lit room
    img[120:180, 60:140] = (205, 205, 205)  # neutral daylight spill on the floor
    out, _ = finish.balance_exposure(img)
    walls = out[20:60, 20:180].astype(float)
    assert abs(walls[:, :, 0].mean() - walls[:, :, 2].mean()) < 12, "walls still neutralize"
    spill = out[130:170, 70:130].astype(float)
    assert abs(spill[:, :, 2].mean() - spill[:, :, 0].mean()) < 8, (
        "daylight spill stays neutral instead of taking the tungsten room's blue"
    )


def _warm_room_big_wood_floor():
    """Warm-cast walls plus a wood floor that dominates the room pixels.

    Unit-a 006's floor voted itself gray: the all-room vote let saturated
    wood set the illuminant and the correction lavendered the floor. The
    bright lamp band holds the vote ceiling above walls and floor alike,
    the way bright fixtures do in real rooms. Walls read brighter than
    the floor, the way lit walls do.
    """
    img = np.full((200, 200, 3), (200, 160, 115), np.uint8)  # warm-cast neutral walls
    img[60:, :] = (190, 130, 80)  # saturated wood floor, most room pixels
    img[:20, :] = (230, 230, 230)  # bright lamp band, above the vote
    return img


def test_white_balance_votes_gray_not_wood():
    before = _warm_room_big_wood_floor().astype(float)
    wall_gap_before = before[25:55, 20:180, 0].mean() - before[25:55, 20:180, 2].mean()
    out, _ = finish.balance_exposure(_warm_room_big_wood_floor())
    walls = out[25:55, 20:180].astype(float)
    wall_gap = walls[:, :, 0].mean() - walls[:, :, 2].mean()
    assert 0 < wall_gap < wall_gap_before, (
        f"walls cool toward neutral without flipping blue, got R-B {wall_gap:.1f}"
    )
    floor = out[100:180, 20:180].astype(float)
    gap = floor[:, :, 0].mean() - floor[:, :, 2].mean()
    assert gap > 45, f"wood keeps its warm R-B spread instead of going gray, got {gap:.1f}"


def _exterior_room():
    img = np.full((200, 200, 3), (150, 150, 220), np.uint8)  # blue sky up top
    img[120:, :] = (172, 150, 120)  # warm ground-floor band below
    img[150:190, 60:140] = (205, 205, 205)  # bright neutral patch
    return img


def test_spill_guard_skips_exteriors():
    assert finish.classify_scene(_exterior_room()) == "exterior"
    spill = np.full((200, 200, 3), (150, 100, 60), np.uint8)
    spill[120:180, 60:140] = (205, 205, 205)
    _, interior_report = finish.balance_exposure(spill)
    assert interior_report.get("spill_guard", 0.0) > 0, "interiors keep the guard"
    _, exterior_report = finish.balance_exposure(_exterior_room())
    assert exterior_report.get("spill_guard", 0.0) == 0.0, (
        "exteriors skip the guard: unit-a 013's daylight needs no tungsten vote"
    )


def test_shadow_lift_opens_corners_without_haze():
    out, report = finish.balance_exposure(_room_cast())
    dark_before = np.sort(_room_cast().reshape(-1, 3).mean(axis=1))[:4000].mean()
    dark_after = np.sort(out.reshape(-1, 3).mean(axis=1))[:4000].mean()
    assert dark_after > dark_before + 5, "dark corners lift"
    assert report["shadow_gain"] > 0
    blacks = out[:20, :20].astype(float).mean()
    assert blacks < 25, "true blacks stay black, no haze veil"


def test_highlights_held_and_mls_matched():
    out, report = finish.balance_exposure(_room_cast())
    assert (out.astype(float).max(axis=2) >= 250).mean() < 0.02, "hot patch held"
    assert abs(out.astype(float).mean() - finish.INTERIOR_TARGET_MEDIAN) < 25, (
        "overall brightness near the shared interior target, with no twin read"
    )


def test_balance_takes_no_mls_twin():
    import inspect

    assert "mls" not in inspect.signature(finish.balance_exposure).parameters, (
        "processing a photo must never read its MLS twin"
    )


def test_pipeline_takes_no_mls_twin():
    import inspect

    from listing_partner import hdr, run_finish

    for func in (
        run_finish.build_inputs,
        run_finish.process_set,
        run_finish.replay_set,
        run_finish.finish_tail,
        hdr.score_merge,
        hdr.choose_from_merges,
        hdr.choose_frames,
    ):
        params = inspect.signature(func).parameters
        assert not [p for p in params if "mls" in p], func.__name__


def test_balance_does_not_hide_real_clipping():
    dark = np.full((200, 200, 3), 60, np.uint8)
    dark[40:160, 60:140] = 255
    out, _ = finish.balance_exposure(dark)
    hot = cv2.cvtColor(out, cv2.COLOR_RGB2GRAY)[40:160, 60:140]
    assert (hot >= 250).mean() > 0.9, "a blown window still reads blown"


def test_gain_anchors_on_masked_pixels_only():
    img = np.full((200, 200, 3), 100, np.uint8)
    img[0:20, :] = 0
    img[-20:, :] = 0
    mask = np.ones((200, 200), bool)
    mask[0:20, :] = False
    mask[-20:, :] = False
    out, _ = finish.balance_exposure(img, anchor_mask=mask)
    room = cv2.cvtColor(out, cv2.COLOR_RGB2GRAY)[20:180, :]
    assert (
        abs(float(np.median(room)) - finish.INTERIOR_TARGET_MEDIAN) / finish.INTERIOR_TARGET_MEDIAN
        < 0.1
    )


def test_exterior_class_targets_lower_brightness():
    assert finish.classify_scene(_room_cast()) == "interior"
    sky = np.full((200, 200, 3), 150, np.uint8)
    sky[:120, :, 2] = 220
    assert finish.classify_scene(sky) == "exterior"
    assert finish.target_median(sky) < finish.INTERIOR_TARGET_MEDIAN
    assert 108.0 <= finish.target_median(sky) <= 144.0


def test_balance_leaves_protected_windows_alone():
    photo = _room_cast()
    mask = np.zeros((200, 200), bool)
    mask[150:190, 110:190] = True
    out, _ = finish.balance_exposure(photo, protect=mask)
    assert (out[mask] == photo[mask]).all(), "pulled windows wait for step B"


def _noisy_edge():
    clean = np.zeros((120, 120, 3), np.uint8)
    clean[:, 60:] = 180
    rng = np.random.default_rng(3)
    noisy = clean.astype(int) + rng.integers(-25, 26, clean.shape)
    return np.clip(noisy, 0, 255).astype(np.uint8), clean


def test_denoise_compared_on_shared_patches():
    noisy, _ = _noisy_edge()
    out = finish.denoise(noisy)
    patches = finish.flat_patch_mask(noisy)
    assert finish.flat_noise(out, patches) < finish.flat_noise(noisy, patches), (
        "before and after share the before image's patches, so the drop "
        "is the denoiser's, not two populations'"
    )


def test_shared_look_constants_stay_frozen():
    assert finish.INTERIOR_TARGET_MEDIAN == 194.0
    assert finish.SKY_FRACTION_CUT == 0.001
    assert finish.EXTERIOR_SKY_SLOPE == 240.0
    assert finish.EXTERIOR_BASE_MEDIAN == 111.0
    assert finish.EXTERIOR_MIN_MEDIAN == 108.0
    assert finish.EXTERIOR_MAX_MEDIAN == 144.0
    assert finish.SHADOW_LIFT == 0.4
    assert finish.LOOK_GAMMA == 0.9
    assert finish.SHOULDER_SLOPE == 0.07
    assert (finish.AUTO_GAIN_LO, finish.AUTO_GAIN_HI) == (0.4, 3.5)
    assert finish.WB_BRIGHT_PERCENTILE == 90.0
    assert finish.WB_INTERIOR_STRENGTH == 0.95
    assert finish.WB_EXTERIOR_STRENGTH == 0.4


def test_flat_patches_cover_a_uniform_image():
    uniform = np.full((100, 100, 3), 150, np.uint8)
    patches = finish.flat_patch_mask(uniform)
    assert patches.sum() == 100 * 100, "a flat image is all patch"
    assert finish.flat_noise(uniform, patches) == 0.0


def test_denoise_drops_noise_keeps_edges():
    noisy, clean = _noisy_edge()
    before_n = finish.flat_noise(noisy)
    out = finish.denoise(noisy)
    after_n = finish.flat_noise(out)
    assert after_n < before_n * 0.7, "flat noise must drop"
    ratio = finish.edge_strength(out) / finish.edge_strength(noisy)
    assert 0.9 <= ratio <= 1.1, "same-scene edges stay within 10 percent"
