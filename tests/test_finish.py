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


def test_tone_changes_no_hue_anywhere():
    """Every tone step is a luminance scale shared by all channels.

    Past the reported global white-balance factors, no pixel's
    chromaticity may move: predicted chromaticity (input times the
    reported factors) matches the output on every unclipped pixel, in
    dim corners, mid walls and bright spill alike. Per-channel gamma
    and shoulder, the blue cap and the spill guard all moved
    chromaticity by brightness or region and fail this; clipping is
    excluded on both sides because a clipped channel carries no hue.
    """
    img = np.full((200, 200, 3), (150, 100, 60), np.uint8)  # tungsten-lit room
    img[:40, :] = (60, 45, 30)  # dim corners
    img[120:180, 60:140] = (205, 205, 205)  # bright neutral spill on the floor
    before = img.astype(float)
    out, report = finish.balance_exposure(img)
    after = out.astype(float)
    factors = np.array(report["wb_factors"], float)
    pred = before * factors
    keep = (before.max(axis=2) < 250) & (after.max(axis=2) < 250)
    assert keep.sum() > 1000, "the comparison needs unclipped pixels"
    for channel in (0, 2):
        actual = after[:, :, channel][keep] / np.maximum(after[:, :, 1][keep], 1.0)
        expected = pred[:, :, channel][keep] / np.maximum(pred[:, :, 1][keep], 1.0)
        gap = float(np.abs(actual - expected).mean())
        assert gap <= 0.02, f"channel {channel} chromaticity moves {gap:.3f} past the vote"


def _cast_room_with_wood_floor():
    """A realistic room (walls and ceiling dominate) under one warm cast.

    The global room vote reads the whole room below the bright cutoff:
    walls, ceiling and rug outvote the wood floor, so the cast lifts and
    the minority wood keeps its warm character. The bright lamp band
    holds the vote ceiling above walls and floor alike, the way bright
    fixtures do in real rooms.
    """
    img = np.full((200, 200, 3), (200, 160, 115), np.uint8)  # warm beige walls
    img[:25, :] = (220, 218, 216)  # near-white neutral ceiling
    img[:10, :] = (245, 245, 245)  # bright lamp band, above the vote
    img[30:55, 20:180] = (175, 172, 170)  # neutral gray rug on the wall band
    img[140:, :] = (190, 130, 80)  # saturated wood floor, lower third
    cast = np.array([1.08, 1.0, 0.92])  # one warm cast over the whole room
    return np.clip(img.astype(float) * cast, 0, 255).astype(np.uint8)


def test_neutral_vote_cools_cast_keeps_wood_warm():
    """The global room vote lifts the cast and keeps wood warm.

    The warm cast cools on ceiling and walls, while the wood floor keeps
    its warm character (red above blue, blue at or below green): warm
    wood must never read blue. One multiplier per channel for the whole
    photo, so there is no boundary to measure.
    """
    img = _cast_room_with_wood_floor()
    before = img.astype(float)
    out, report = finish.balance_exposure(img)
    assert report["white_balanced"] is True
    # The vote cools in the right direction: the wall band's red/blue gap
    # shrinks. How far it goes is fitted on real rooms (criterion 11),
    # not asserted here: a synthetic majority-warm room over-cools by
    # construction, and real rooms carry the verdict.
    wall_before = before[60:100, 20:180]
    wall_after = out[60:100, 20:180].astype(float)
    gap_before = wall_before[:, :, 0].mean() - wall_before[:, :, 2].mean()
    gap_after = wall_after[:, :, 0].mean() - wall_after[:, :, 2].mean()
    assert 0 < gap_after < gap_before, (
        f"vote cools walls, got R-B {gap_before:.1f} -> {gap_after:.1f}"
    )
    floor = out[150:190, 20:180].astype(float)
    assert (floor[:, :, 0] - floor[:, :, 2]).mean() > 0, "wood stays warm, never flips blue"


def _exterior_room():
    img = np.full((200, 200, 3), (150, 150, 220), np.uint8)  # blue sky up top
    img[120:, :] = (172, 150, 120)  # warm ground-floor band below
    img[150:190, 60:140] = (205, 205, 205)  # bright neutral patch
    return img


def test_no_brightness_or_region_color_step():
    """Every brightness-dependent, regional and positional color step is
    gone (contract 02, final round): no blue cap, no daylight-spill
    guard, nothing like them, on interiors or exteriors."""
    assert not hasattr(finish, "WB_BLUE_CAP"), "the blue cap constant is gone"
    assert not hasattr(finish, "WB_BLUE_CAP_DIM_LO"), "the cap's dim ramp is gone too"
    assert not hasattr(finish, "wood_max_for"), "the old zone guard stays gone"
    assert finish.classify_scene(_exterior_room()) == "exterior"
    spill = np.full((200, 200, 3), (150, 100, 60), np.uint8)
    spill[120:180, 60:140] = (205, 205, 205)
    for img in (spill, _exterior_room()):
        _, report = finish.balance_exposure(img)
        assert "blue_capped" not in report, "no blue-cap report key"
        assert "spill_guard" not in report, "no spill-guard report key"


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
    # Highlights hold in luminance: the shoulder compresses over-bright
    # luminance toward 235 while every pixel keeps its chromaticity, so
    # no per-channel clamp hides (or invents) clipping. A per-channel
    # clamp would be a brightness-dependent color step, which the final
    # round removes.
    lum = 0.299 * out[:, :, 0] + 0.587 * out[:, :, 1] + 0.114 * out[:, :, 2]
    assert lum.max() <= 240, f"luminance holds at {lum.max():.0f}, not blown open"
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


def _tungsten_room_wood_floor():
    """Dark warm room with a dim saturated wood floor.

    Unit-a 006: the all-room gray-world vote's blue gain (1.6x) flipped
    the shadowed wood floor from B-G -31 to +25. The floor is dim
    (shadowed) and strongly warm (wood), the population the blue-cap
    protects; the lamp band holds the vote ceiling up the way bright
    fixtures do in real rooms.
    """
    img = np.full((200, 200, 3), (95, 70, 40), np.uint8)  # dark warm room
    img[100:, :] = (120, 100, 72)  # dim saturated wood floor below
    img[:16, :] = (230, 230, 230)  # bright lamp band, above the vote
    return img


def test_vote_reports_its_factors():
    """The global vote states its per-channel multipliers in the report."""
    img = _tungsten_room_wood_floor()
    out, report = finish.balance_exposure(img)
    assert report["white_balanced"] is True
    assert len(report["wb_factors"]) == 3, "one multiplier per channel"


def test_one_paint_keeps_one_color_across_brightness():
    """One paint keeps one color across its brightness range (contract 02,
    final round: one global exposure gain and white balance per photo, one
    luminance-only shared tone curve, no brightness-dependent color step).

    A single paint color under a smooth brightness ramp goes through the
    finish; its a* and b* stay within 2 across the ramp. The old
    tone-dependent steps (blue cap, daylight-spill guard, per-channel
    gamma and shoulder) moved b* by ~8 across the same ramp.
    """
    import cv2

    paint = np.array([200.0, 160.0, 115.0])  # one warm wall paint
    ramp = np.linspace(0.35, 1.0, 200)[:, None, None]
    img = np.clip(paint * ramp, 0, 255).astype(np.uint8)
    img = np.repeat(img, 20, axis=1)  # 200 rows of ramp x 20 cols
    out, _ = finish.balance_exposure(img)
    lab = cv2.cvtColor(out, cv2.COLOR_RGB2LAB).astype(float)[:, :, 1:] - 128.0
    # Band means, not single rows: 8-bit rounding chatters single rows
    # by ~1 level, while a real hue shift moves whole bands (the old
    # code read b* 1.2, 1.3, 1.4, 1.8, 4.3, 7.6, 10.0, 7.4 by band).
    bands = lab[20:180].reshape(8, 20, 20, 2).mean(axis=(1, 2))
    drift_a = float(bands[:, 0].max() - bands[:, 0].min())
    drift_b = float(bands[:, 1].max() - bands[:, 1].min())
    assert drift_a <= 2.0, f"a* drifts {drift_a:.1f} across one paint's ramp (limit 2)"
    assert drift_b <= 2.0, f"b* drifts {drift_b:.1f} across one paint's ramp (limit 2)"


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
    assert (out[mask] == photo[mask]).all(), "protected pixels keep their exact values"


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
    # No WOOD_* constants: the zone wood guard and its tuning are removed
    # (finding 2, criterion 14: no spatial box in any color correction).


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
