"""Tests for exposure balance and denoising. No network, no key."""

import cv2
import numpy as np

from listing_partner import checks, finish


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


def test_tone_changes_no_hue_anywhere():
    """Every tone step is one scale shared by all channels.

    No pixel's chromaticity may move: white balance runs at raw decode,
    so input chromaticity matches the output on every unclipped, unrolled
    pixel, in dim corners and mid walls alike. Per-channel gamma
    and shoulder, the blue cap and the spill guard all moved
    chromaticity by brightness or region and fail this; clipping is
    excluded because a clipped channel carries no hue.
    """
    img = np.full((200, 200, 3), (140, 118, 100), np.uint8)  # warm room, under the roll-off
    img[:40, :] = (60, 50, 42)  # dim corners
    img[120:180, 60:140] = (205, 205, 205)  # bright neutral spill on the floor
    before = img.astype(float)
    out, _ = finish.balance_exposure(img)
    after = out.astype(float)
    pred = before
    # Every pixel here is under both roll-off triggers: warm or neutral,
    # and far from clipping in the merge. Only channel clipping is excluded.
    keep = after.max(axis=2) < 250
    assert keep.mean() > 0.99, "the comparison needs unclipped pixels"
    assert (after.max(axis=2) > finish.SHOULDER_KNEE).sum() > 1000, "the shoulder must act"
    for channel in (0, 2):
        actual = after[:, :, channel][keep] / np.maximum(after[:, :, 1][keep], 1.0)
        expected = pred[:, :, channel][keep] / np.maximum(pred[:, :, 1][keep], 1.0)
        gap = float(np.abs(actual - expected).mean())
        assert gap <= 0.02, f"channel {channel} chromaticity moves {gap:.3f}"


def _exterior_room():
    img = np.full((200, 200, 3), (150, 150, 220), np.uint8)  # blue sky up top
    img[120:, :] = (172, 150, 120)  # warm ground-floor band below
    img[150:190, 60:140] = (205, 205, 205)  # bright neutral patch
    return img


def test_no_brightness_or_region_color_step():
    """The final-round regional and positional color steps stay gone
    (contract 02, final round): no blue cap, no daylight-spill guard,
    nothing like them, on interiors or exteriors. Part two allows one
    brightness-dependent color step, the smooth highlight roll-off,
    covered by the patch test above."""
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
    # Highlights hold and read neutral: the roll-off blends pixels near
    # clipping in the merge toward neutral gray of the same luminance,
    # then the shoulder compresses the peak channel. The old code clipped the blue channel at
    # 255 instead, which hid luminance (it read 239) while painting
    # the hot patch cyan (it read 216, 247, 255, spread 39): that
    # tint fails the spread bound below. No per-channel clamp hides
    # (or invents) clipping anymore.
    lum = 0.299 * out[:, :, 0] + 0.587 * out[:, :, 1] + 0.114 * out[:, :, 2]
    assert lum.max() <= 245, f"luminance holds at {lum.max():.0f}, not blown open"
    hot = out[160:, 100:].astype(float)
    spread = float((hot.max(axis=2) - hot.min(axis=2)).mean())
    assert spread <= 15.0, f"hot patch reads tinted, mean channel spread {spread:.0f}"
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


def test_one_paint_keeps_one_color_across_brightness():
    """One paint keeps one color across its brightness range (contract 02,
    final round: one global exposure gain per photo; part two adds the
    highlight roll-off; part three moves white balance to raw decode).

    A single warm paint color under a smooth brightness ramp goes
    through the finish; its chromaticity (R/G and B/G) stays constant
    across the ramp. The pre-final-round steps (blue cap,
    daylight-spill guard) moved chromaticity by brightness and fail
    this (measured on bb5df2b: R/G drift 0.062, B/G drift 0.072).
    Lab a*/b* are not asserted: at constant chromaticity Lab chroma still
    grows with luminance, so a warm paint's b* drifts with no hue shift.
    """
    paint = np.array([200.0, 160.0, 115.0])  # one warm wall paint
    ramp = np.linspace(0.35, 1.0, 200)[:, None, None]
    img = np.clip(paint * ramp, 0, 255).astype(np.uint8)
    img = np.repeat(img, 20, axis=1)  # 200 rows of ramp x 20 cols
    # A bright neutral majority anchors the gain, so the whole ramp stays
    # under the roll-off, the one color step allowed to depend on brightness.
    img = np.hstack([img, np.full((200, 40, 3), 195, np.uint8)])
    out, _ = finish.balance_exposure(img)
    f = out[:, :20].astype(float)
    assert f.max() < 250, "the ramp must stay under the roll-off to measure the tone steps"
    # Band means, not single rows: 8-bit rounding chatters single rows
    # by ~1 level, while a real hue shift moves whole bands.
    rg = f[:, :, 0] / np.maximum(f[:, :, 1], 1.0)
    bg = f[:, :, 2] / np.maximum(f[:, :, 1], 1.0)
    bands_rg = rg[20:180].reshape(8, 20, 20).mean(axis=(1, 2))
    bands_bg = bg[20:180].reshape(8, 20, 20).mean(axis=(1, 2))
    drift_rg = float(bands_rg.max() - bands_rg.min())
    drift_bg = float(bands_bg.max() - bands_bg.min())
    assert drift_rg <= 0.02, f"R/G drifts {drift_rg:.3f} across one paint's ramp (limit 0.02)"
    assert drift_bg <= 0.02, f"B/G drifts {drift_bg:.3f} across one paint's ramp (limit 0.02)"


def _wall_ramp_far_from_clipping():
    """One wall paint under a smooth brightness ramp, far from merge clipping.

    Reviewer's unit-a 005 reading: the merge held RGB 89, 76, 65 where the
    finished wall read flat white. A dim majority anchors the gain high, so
    the wall's brightest rows pass the old roll-off's float trigger with
    every merge channel still far under clipping.
    """
    paint = np.array([89.0, 76.0, 65.0])  # the 005 wall, read from the merge
    ramp = np.linspace(0.55, 1.6, 400)[:, None, None]
    wall = np.repeat(np.clip(paint * ramp, 0, 255).astype(np.uint8), 20, axis=1)
    room = np.full((400, 60, 3), (58, 50, 43), np.uint8)
    return np.hstack([wall, room])


def test_one_wall_keeps_one_color_through_the_highlight_range():
    """A wall far from merge clipping keeps its color however bright it lands.

    Reviewer finding 2 on 970ce8f: the old ramp test stopped under the
    roll-off, and this one crosses it. Chromaticity must stay bounded from
    one row to the next, so the finish paints no edge on the wall, and across
    the whole ramp, so the wall reads one color.
    """
    img = _wall_ramp_far_from_clipping()
    assert img[:, :20].max() < 150, "the wall must be far from clipping in the merge"
    out, report = finish.balance_exposure(img)
    # 270 is where 970ce8f's float trigger went fully neutral.
    assert img[:, :20].max() * report["auto_gain"] > 270.0, (
        "the gain must carry the wall past where the old trigger went fully neutral"
    )
    f = out[:, :20].astype(float).mean(axis=1)
    rg = f[:, 0] / np.maximum(f[:, 1], 1.0)
    bg = f[:, 2] / np.maximum(f[:, 1], 1.0)
    # Eight-row bands: 8-bit rounding chatters single rows by a level, while
    # a real color step moves whole bands.
    bands_rg = rg[:400].reshape(50, 8).mean(axis=1)
    bands_bg = bg[:400].reshape(50, 8).mean(axis=1)
    step = max(np.abs(np.diff(bands_rg)).max(), np.abs(np.diff(bands_bg)).max())
    assert step <= 0.01, f"wall color steps {step:.3f} between neighboring bands (limit 0.01)"
    drift_rg = float(bands_rg.max() - bands_rg.min())
    drift_bg = float(bands_bg.max() - bands_bg.min())
    assert drift_rg <= 0.03, f"wall R/G drifts {drift_rg:.3f} across its ramp (limit 0.03)"
    assert drift_bg <= 0.03, f"wall B/G drifts {drift_bg:.3f} across its ramp (limit 0.03)"


def _room_with_window_view():
    """Warm dim room with a cool window view at wall-level merge brightness."""
    img = np.full((200, 200, 3), (60, 52, 45), np.uint8)
    img[40:120, 40:120] = (100, 112, 130)  # view, far from clipping in the merge
    return img


def test_cool_window_view_does_not_read_cyan():
    """The roll-off's cool trigger, in isolation from the clip trigger."""
    img = _room_with_window_view()
    assert img.max() < finish.ROLL_CLIP_START, "this case must not reach the clip trigger"
    mask = np.zeros(img.shape[:2], bool)
    mask[40:120, 40:120] = True
    out, report = finish.balance_exposure(img, scene="interior", window_mask=mask)
    assert report["cool_gate"]["strength"] > 0.0, "the trigger must fire on this view"
    view = out[40:120, 40:120]
    assert view.mean() > 170, "the view must land bright enough for the check to apply"
    # The feather leaves the outermost pixels their color, on purpose: the view's
    # core is held at zero, the whole frame to the product's 1% bar.
    assert checks.bright_surface_share(out[50:110, 50:110]) == 0.0
    assert checks.bright_surface_share(out) <= checks.BRIGHT_SURFACE_LIMIT_PCT
    plain, _ = finish.balance_exposure(img, scene="interior")
    assert checks.bright_surface_share(plain) > 1.0, "without the trigger this view reads cyan"


def test_exterior_sky_keeps_its_blue():
    """The cool trigger is interior only: real sky is not a color error."""
    img = _room_with_window_view()
    mask = np.zeros(img.shape[:2], bool)
    mask[40:120, 40:120] = True
    out, report = finish.balance_exposure(img, scene="exterior", sky=0.1, window_mask=mask)
    assert report["cool_gate"]["strength"] == 0.0
    view = out[40:120, 40:120].astype(float)
    assert float((view[:, :, 2] - view[:, :, 0]).mean()) > 40.0


def test_clip_trigger_reads_the_merge_at_any_hue():
    """A warm pixel clipped in the merge rolls neutral; the same hue a little
    dimmer in the merge keeps its color under the same gain."""
    img = np.full((200, 300, 3), (70, 60, 52), np.uint8)
    img[20:80, 20:80] = (255, 215, 170)  # clipped in the merge
    img[120:180, 20:80] = (150, 126, 100)  # same hue family, far from clipping
    out, _ = finish.balance_exposure(img, scene="interior")
    clipped = out[20:80, 20:80].astype(float).mean(axis=(0, 1))
    assert clipped.max() - clipped.min() <= 3.0, f"clipped patch reads {clipped}"
    held = out[120:180, 20:80].astype(float).mean(axis=(0, 1))
    assert held[0] / held[2] > 1.3, f"unclipped warm patch lost its color: {held}"


def test_wall_detail_survives_the_shoulder():
    """A darker band on a bright wall keeps its contrast and the wall its color.

    Measured on this fixture: 970ce8f reads the wall neutral (242, 242, 242)
    with the band 4.0 levels under it; the rebuilt shoulder reads about
    (245, 210, 179) with the band 5.1 levels under.
    """
    img = np.full((200, 200, 3), (58, 50, 43), np.uint8)
    img[60:140, 60:140] = (130, 111, 95)
    img[95:105, 60:140] = (100, 85, 73)
    out, _ = finish.balance_exposure(img)
    wall = out[70:90, 70:130].astype(float).mean(axis=(0, 1))
    band = out[97:103, 70:130].astype(float).mean(axis=(0, 1))
    gap = float(wall.mean() - band.mean())
    assert gap >= 4.5, f"the band reads only {gap:.1f} levels under the wall"
    assert wall[0] - wall[2] >= 40.0, f"the bright wall lost its color: {wall}"


def _warm_room_with_hot_patches():
    """Warm tungsten room with a warm near-clipped patch and a blown patch.

    Unit-a 008: a post-merge vote pushed blue up 4.6x, so sunlit shades
    and blown bulbs came out saturated cyan (mean RGB 127, 220, 255 on
    fully blown pixels). The near-clipped patch is warm lamp-lit white;
    the blown patch is already clipped warm white in the input.
    """
    img = np.full((200, 200, 3), (150, 110, 70), np.uint8)  # warm room
    img[20:80, 20:80] = (252, 214, 160)  # warm near-clipped patch
    img[120:180, 120:180] = (255, 252, 244)  # blown patch
    img[:8, :] = (245, 245, 245)  # bright lamp band above the vote
    return img


def test_warm_bright_and_blown_patches_stay_neutral():
    """Warm near-clipped and blown patches never read cyan or blue.

    Contract 02, final round part two: the bright-surface share (mean
    above 170, B at least G, G minus R at least 15, B minus R at least
    30) stays at or below 1% of the frame, and the blown patch reads
    neutral white, not cyan.
    """
    out, _ = finish.balance_exposure(_warm_room_with_hot_patches())
    share = checks.bright_surface_share(out)
    assert share <= 1.0, f"bright cyan/blue covers {share:.1f}% of the frame (limit 1%)"
    blown = out[120:180, 120:180].astype(float)
    spread = float((blown.max(axis=2) - blown.min(axis=2)).mean())
    assert spread <= 15.0, f"blown patch reads tinted, mean channel spread {spread:.0f}"


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
    """The refitted final-round look, pinned: unit 5 measures these same
    settings unchanged on the held-out home set."""
    assert finish.INTERIOR_TARGET_MEDIAN == 194.0
    assert finish.SKY_FRACTION_CUT == 0.001
    assert finish.EXTERIOR_SKY_SLOPE == 240.0
    assert finish.EXTERIOR_BASE_MEDIAN == 111.0
    assert finish.EXTERIOR_MIN_MEDIAN == 108.0
    assert finish.EXTERIOR_MAX_MEDIAN == 144.0
    assert finish.SHADOW_LIFT == 0.4
    assert finish.LOOK_GAMMA == 0.9
    assert (finish.SHOULDER_KNEE, finish.SHOULDER_CEILING) == (190.0, 265.0)
    assert (finish.AUTO_GAIN_LO, finish.AUTO_GAIN_HI) == (0.4, 3.5)
    assert finish.WB_INTERIOR_TINT_R == 1.08
    assert finish.WB_INTERIOR_TINT_B == 0.94
    assert finish.WB_EXTERIOR_STRENGTH == 0.5
    assert (finish.ROLL_CLIP_START, finish.ROLL_CLIP_FULL) == (235.0, 252.0)
    assert (finish.ROLL_COOL_PEAK_START, finish.ROLL_COOL_PEAK_FULL) == (200.0, 280.0)
    assert (finish.ROLL_COOL_START, finish.ROLL_COOL_FULL) == (0.05, 0.15)
    assert (finish.ROLL_COOL_VIEW_START, finish.ROLL_COOL_VIEW_FULL) == (0.02, 0.10)
    assert finish.ROLL_COOL_STRENGTH == 0.8
    assert finish.ROLL_COOL_FEATHER_FRAC == 0.01
    # No WOOD_* constants: the zone wood guard and its tuning are removed
    # (finding 2, criterion 14: no spatial box in any color correction).
    # No WB_BLUE_CAP_* or WB_NEUTRAL_SAT constants: the blue cap, the
    # daylight-spill guard and the neutral-subset vote are gone with the
    # final round (one global room vote instead).
    for gone in ("WB_BLUE_CAP", "WB_BLUE_CAP_DIM_LO", "WB_NEUTRAL_SAT", "wood_max_for"):
        assert not hasattr(finish, gone), f"removed constant is back: {gone}"


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


def _implied_blend(img: np.ndarray, out: np.ndarray) -> np.ndarray:
    """How far each pixel moved toward neutral, read from input and output.

    Every other step scales the three channels by one factor, so (B - R) / peak
    only changes by the blend. Where the input is barely cool, 8-bit rounding
    swamps that ratio, so those pixels read NaN.
    """
    before = img.astype(np.float32)
    after = out.astype(np.float32)
    cool_in = (before[:, :, 2] - before[:, :, 0]) / np.maximum(before.max(axis=2), 1.0)
    cool_out = (after[:, :, 2] - after[:, :, 0]) / np.maximum(after.max(axis=2), 1.0)
    return 1.0 - cool_out / np.where(np.abs(cool_in) < 0.10, np.nan, cool_in)


def _noisy_surface_across_the_cool_threshold():
    """One surface whose coolness walks across the trigger's range, with noise.

    Far from merge clipping, as on the 009 floor (merge peak 66 to 102). A dim
    majority outside the surface anchors the gain, so the surface lands bright.
    """
    rng = np.random.default_rng(9)
    h, w = 400, 900
    cool = np.linspace(0.03, 0.17, w)[None, :]
    surface = np.zeros((h, w, 3), np.float32)
    surface[:, :, 2] = 120.0
    surface[:, :, 1] = 120.0 * (1.0 - cool / 2.0)
    surface[:, :, 0] = 120.0 * (1.0 - cool)
    surface += rng.normal(0.0, 1.5, (h, w, 3)).astype(np.float32)
    room = np.full((h, 1400, 3), (58, 50, 43), np.float32)
    img = np.clip(np.hstack([surface, room]), 0, 255).astype(np.uint8)
    mask = np.zeros(img.shape[:2], bool)
    mask[:, :w] = True
    return img, mask


def test_noisy_surface_crossing_the_cool_threshold_changes_color_boundedly():
    """Reviewer finding 2 on 7ee0217: neighboring pixels of one surface must not
    flip between rolled and not rolled, however close it sits to the threshold."""
    img, mask = _noisy_surface_across_the_cool_threshold()
    out, report = finish.balance_exposure(img, scene="interior", window_mask=mask)
    assert report["auto_gain"] * 120.0 > finish.ROLL_COOL_PEAK_START, "the surface must land bright"
    blend = _implied_blend(img, out)[20:-20, 60:840]
    assert np.nanmax(blend) > 0.2, "the trigger must act on this surface for the bound to mean it"
    step = np.abs(np.diff(blend, axis=1))
    p99 = float(np.nanpercentile(step, 99))
    assert p99 <= 0.05, f"blend toward neutral jumps {p99:.3f} between neighbors (limit 0.05)"


def test_cool_trigger_is_zero_outside_the_window_mask():
    """A cool bright floor outside the mask keeps its exact coolness."""
    img = np.full((400, 900, 3), (58, 50, 43), np.uint8)
    img[250:, :] = (100, 112, 125)  # cool, bright after gain, far from merge clipping
    img[40:160, 300:600] = (100, 112, 125)  # the same color, seen through the window
    mask = np.zeros(img.shape[:2], bool)
    mask[40:160, 300:600] = True
    out, report = finish.balance_exposure(img, scene="interior", window_mask=mask)
    assert report["auto_gain"] * 125.0 > finish.ROLL_COOL_PEAK_FULL, "the gate must be fully open"
    floor = _implied_blend(img, out)[270:380, 20:880]
    worst = float(np.nanmax(np.abs(floor)))
    assert worst <= 0.03, f"the floor outside the mask moved {worst:.3f} toward neutral"


def _view_house_and_lawn():
    """A window view: a cool house beside a saturated green lawn, in a dim room."""
    img = np.full((400, 900, 3), (58, 50, 43), np.uint8)
    img[60:340, 200:450] = (100, 112, 130)  # cool house
    img[60:340, 450:700] = (70, 125, 60)  # saturated lawn
    mask = np.zeros(img.shape[:2], bool)
    mask[60:340, 200:700] = True
    return img, mask


def test_view_moves_as_one_with_no_gray_patch_against_saturated_areas():
    """Reviewer finding 1: a house going gray-white beside a green lawn. Every
    view pixel gets one strength, so the lawn pales with the house."""
    img, mask = _view_house_and_lawn()
    out, report = finish.balance_exposure(img, scene="interior", window_mask=mask)
    plain, _ = finish.balance_exposure(img, scene="interior")
    strength = report["cool_gate"]["strength"]
    assert strength > 0.0, "the trigger must fire on this view"

    def _spread(photo, y, x):
        pixel = photo[y, x].astype(float)
        return pixel.max() - pixel.min()

    house = _spread(out, 200, 325) / _spread(plain, 200, 325)
    lawn = _spread(out, 200, 575) / _spread(plain, 200, 575)
    assert abs(house - lawn) <= 0.05, f"house keeps {house:.2f} of its color, lawn {lawn:.2f}"


def test_outside_the_mask_is_identical_with_or_without_it():
    """Exact zero, down to the byte: the mask cannot move the gain either."""
    img, mask = _view_house_and_lawn()
    with_mask, report = finish.balance_exposure(img, scene="interior", window_mask=mask)
    without, _ = finish.balance_exposure(img, scene="interior")
    assert report["cool_gate"]["strength"] > 0.0
    assert report["cool_gate"]["outside_pct"] == 0.0
    assert (with_mask[~mask] == without[~mask]).all()
    assert (with_mask[mask] != without[mask]).any()


def test_correction_fades_to_nothing_at_the_mask_edge():
    """Criterion 14 on the real path: the a* and b* step across the edge is 2 or less."""
    # At a real frame's scale: the feather is a share of the frame's long side.
    img, mask = _view_house_and_lawn()
    img = cv2.resize(img, None, fx=6, fy=6, interpolation=cv2.INTER_NEAREST)
    mask = cv2.resize(mask.astype(np.uint8), None, fx=6, fy=6, interpolation=cv2.INTER_NEAREST) > 0
    _, report = finish.balance_exposure(img, scene="interior", window_mask=mask)
    gate = report["cool_gate"]
    assert gate["strength"] > 0.0
    ok, reason = checks.check_region_edge(gate["edge_step_a"], gate["edge_step_b"])
    assert ok, reason


def test_edge_step_measure_fails_on_a_hard_edge():
    """The measure itself: a correction with no feather reads over the limit."""
    h, w = 300, 300
    gate = np.zeros((h, w), np.float32)
    gate[100:200, 100:200] = 0.8
    delta = np.zeros((h, w, 3), np.float32)
    delta[:, :, 2] = gate * 30.0  # b* moves 24 at the edge, all at once
    step_a, step_b = finish.feather_color_step(delta, gate)
    assert step_a == 0.0
    assert step_b > 20.0, f"a hard edge must read as a big step, read {step_b:.2f}"
    assert not checks.check_region_edge(step_a, step_b)[0]


def test_edge_step_measure_ignores_scene_detail_under_a_feather():
    """Scene detail is not a correction step. the first ring measure read
    10.96 b* on 003 by comparing different scene pixels; this fixture does the same:
    a rim and a core of different color under one smooth gate."""
    h, w = 400, 400
    inside = np.zeros((h, w), np.uint8)
    inside[50:350, 50:350] = 1
    distance = cv2.distanceTransform(inside, cv2.DIST_L2, 5)
    gate = 0.8 * np.clip(distance / 60.0, 0.0, 1.0).astype(np.float32)
    full = np.zeros((h, w, 3), np.float32)
    full[:, :, 2] = -10.0
    full[110:290, 110:290, 2] = 5.0  # the core is a different scene
    delta = full * gate[:, :, None]
    _, step_b = finish.feather_color_step(delta, gate)
    assert step_b <= 0.2, f"scene detail read as a correction step: {step_b:.2f}"


def test_masks_never_turn_on_the_trigger_for_a_dim_or_warm_view():
    """A window that is not cool and bright gets no correction at all."""
    img = np.full((400, 900, 3), (58, 50, 43), np.uint8)
    img[60:340, 200:700] = (120, 100, 80)
    mask = np.zeros(img.shape[:2], bool)
    mask[60:340, 200:700] = True
    _, report = finish.balance_exposure(img, scene="interior", window_mask=mask)
    assert report["cool_gate"]["strength"] == 0.0
    assert "edge_step_a" not in report["cool_gate"], "no edge exists, so none is measured"
