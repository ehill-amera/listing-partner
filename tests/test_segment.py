"""Tests for window finding, verification, and pulling. No network, no key."""

import json

import cv2
import numpy as np

from listing_partner import segment


def _lane():
    from pathlib import Path

    return (Path(__file__).resolve().parent / "fixtures" / "sam_window_lane.txt").read_text()


def test_parse_live_lane_finds_three_candidates():
    candidates = segment.parse_lane(_lane(), frame_w=1024, frame_h=684)
    assert [c["object_id"] for c in candidates] == [0, 1, 2]
    boxes = [c["box"] for c in candidates]
    assert boxes[0] == (0, 74, 77, 680), "half-open bounds from the inclusive wire box"
    for c in candidates:
        assert c["mask"].shape == (684, 1024), "masks are frame-size"
        left, top, right, bottom = c["box"]
        inner = c["mask"][top:bottom, left:right]
        assert inner.mean() > 0.5, "glass fills its box"
        outer = c["mask"].copy()
        outer[top:bottom, left:right] = False
        assert not outer.any(), "nothing leaks outside the box"


def test_find_candidates_goes_through_the_capped_client(tmp_path, monkeypatch):
    monkeypatch.setenv("META_API_KEY", "test-key-never-a-real-secret")

    def _window_lane(url, headers, body):
        return {
            "id": "r-lane",
            "output": [{"type": "message", "content": [{"type": "output_text", "text": _lane()}]}],
            "usage": {"images_processed": 1},
        }

    ledger = tmp_path / "ledger.jsonl"
    tiny = cv2.imencode(".jpg", np.zeros((684, 1024, 3), np.uint8))[1].tobytes()
    candidates = segment.find_candidates(tiny, "window", transport=_window_lane, ledger_path=ledger)
    assert len(candidates) == 3
    lines = [json.loads(line) for line in ledger.read_text().splitlines()]
    assert len(lines) == 2 and lines[1]["status"] == "complete"


def test_verify_parses_spark_verdicts(tmp_path, monkeypatch):
    monkeypatch.setenv("META_API_KEY", "test-key-never-a-real-secret")
    ledger = tmp_path / "ledger.jsonl"
    replies = iter(
        [
            "0: not a window - mirrored closet door, no outdoor view\n"
            "1: window - clear view of trees and sky\n"
            "2: window - street view with houses\n"
        ]
    )

    def _spark(url, headers, body):
        return {
            "id": "r-v",
            "text": next(replies),
            "usage": {"input_tokens": 900, "output_tokens": 40},
        }

    boxes = [
        {"object_id": 0, "box": (0, 0, 30, 30)},
        {"object_id": 1, "box": (30, 30, 60, 60)},
        {"object_id": 2, "box": (60, 60, 90, 90)},
    ]
    verdicts = segment.verify_candidates(
        np.zeros((100, 100, 3), np.uint8),
        boxes,
        transport=_spark,
        ledger_path=ledger,
    )
    assert verdicts[0] == (False, "mirrored closet door, no outdoor view")
    assert verdicts[1][0] is True and "trees" in verdicts[1][1]
    assert verdicts[2][0] is True


def test_verify_prompt_sends_the_facade_rule(tmp_path, monkeypatch):
    monkeypatch.setenv("META_API_KEY", "test-key-never-a-real-secret")
    ledger = tmp_path / "ledger.jsonl"
    seen = []

    def _spark(url, headers, body):
        seen.append(body)
        return {
            "id": "r-f",
            "text": "0: not a window - facade glass seen from outside\n",
            "usage": {"input_tokens": 900, "output_tokens": 20},
        }

    photo = np.zeros((100, 100, 3), np.uint8)
    verdicts = segment.verify_candidates(
        photo,
        [{"object_id": 0, "box": (10, 10, 50, 50)}],
        transport=_spark,
        ledger_path=ledger,
    )
    assert verdicts[0] == (False, "facade glass seen from outside")
    assert "facade" in seen[0].decode("utf-8"), "Spark must get the facade rule"


def test_verify_zooms_to_skipped_candidates(tmp_path, monkeypatch):
    monkeypatch.setenv("META_API_KEY", "test-key-never-a-real-secret")
    ledger = tmp_path / "ledger.jsonl"
    replies = iter(["1: window - trees outside\n", "0: not a window - mirror\n"])

    def _spark(url, headers, body):
        return {
            "id": "r-z",
            "text": next(replies),
            "usage": {"input_tokens": 900, "output_tokens": 20},
        }

    photo = np.zeros((100, 100, 3), np.uint8)
    boxes = [
        {"object_id": 0, "box": (0, 0, 30, 30)},
        {"object_id": 1, "box": (30, 30, 60, 60)},
    ]
    verdicts = segment.verify_candidates(photo, boxes, transport=_spark, ledger_path=ledger)
    assert verdicts[0] == (False, "mirror")
    assert verdicts[1][0] is True


def test_dedupe_candidates_collapses_same_box_and_reids():
    mask = np.zeros((10, 10), bool)
    candidates = [
        {"object_id": 0, "box": (0, 0, 5, 5), "mask": mask},
        {"object_id": 0, "box": (5, 5, 9, 9), "mask": mask},
        {"object_id": 1, "box": (0, 0, 5, 5), "mask": mask},
    ]
    unique = segment.dedupe_candidates(candidates)
    assert [(c["object_id"], c["box"]) for c in unique] == [
        (0, (0, 0, 5, 5)),
        (1, (5, 5, 9, 9)),
    ]


def test_scale_candidates_to_full_resolution():
    mask = np.zeros((684, 1024), bool)
    mask[74:680, 0:77] = True
    scaled = segment.scale_candidates(
        [{"object_id": 0, "box": (0, 74, 77, 680), "mask": mask}],
        1024,
        684,
        2048,
        1368,
    )
    assert scaled[0]["box"] == (0, 148, 154, 1360)
    assert scaled[0]["mask"].shape == (1368, 2048)
    assert scaled[0]["mask"][148:1360, 0:154].mean() > 0.9


def test_verify_clarifies_a_bare_crop_ask(tmp_path, monkeypatch):
    monkeypatch.setenv("META_API_KEY", "test-key-never-a-real-secret")
    ledger = tmp_path / "ledger.jsonl"
    replies = iter(["CROP", "CROP 10,10,40,40", "0: window - sky and trees\n"])
    prompts = []

    def _spark(url, headers, body):
        prompts.append(json.loads(body.decode("utf-8"))["input"])
        return {
            "id": "r-b",
            "text": next(replies),
            "usage": {"input_tokens": 900, "output_tokens": 20},
        }

    photo = np.zeros((100, 100, 3), np.uint8)
    verdicts = segment.verify_candidates(
        photo,
        [{"object_id": 0, "box": (10, 10, 50, 50)}],
        transport=_spark,
        ledger_path=ledger,
    )
    assert verdicts[0][0] is True
    assert "CROP x,y,w,h" in json.dumps(prompts[1]), "the follow-up asks for coords"


def test_verify_reads_chatter_embedded_crop_and_verdicts(tmp_path, monkeypatch):
    monkeypatch.setenv("META_API_KEY", "test-key-never-a-real-secret")
    ledger = tmp_path / "ledger.jsonl"
    replies = iter(
        [
            "This yard view needs a closer look. CROP 10,10,40,40\n",
            "0: window - sky and trees\n",
        ]
    )

    def _spark(url, headers, body):
        return {
            "id": "r-e",
            "text": next(replies),
            "usage": {"input_tokens": 900, "output_tokens": 20},
        }

    photo = np.zeros((100, 100, 3), np.uint8)
    verdicts = segment.verify_candidates(
        photo,
        [{"object_id": 0, "box": (10, 10, 50, 50)}],
        transport=_spark,
        ledger_path=ledger,
    )
    assert verdicts[0][0] is True


def test_verify_collects_partial_verdicts_across_rounds(tmp_path, monkeypatch):
    monkeypatch.setenv("META_API_KEY", "test-key-never-a-real-secret")
    ledger = tmp_path / "ledger.jsonl"
    replies = iter(["Some chatter here.\n1: window - trees\n", "0: not a window - mirror\n"])

    def _spark(url, headers, body):
        return {
            "id": "r-p",
            "text": next(replies),
            "usage": {"input_tokens": 900, "output_tokens": 20},
        }

    photo = np.zeros((100, 100, 3), np.uint8)
    boxes = [
        {"object_id": 0, "box": (0, 0, 30, 30)},
        {"object_id": 1, "box": (30, 30, 60, 60)},
    ]
    verdicts = segment.verify_candidates(photo, boxes, transport=_spark, ledger_path=ledger)
    assert verdicts[1] == (True, "trees")
    assert verdicts[0] == (False, "mirror")


def test_verify_crops_keep_the_red_annotation(tmp_path, monkeypatch):
    import base64
    import io
    import json

    from PIL import Image

    monkeypatch.setenv("META_API_KEY", "test-key-never-a-real-secret")
    ledger = tmp_path / "ledger.jsonl"
    bodies = []
    replies = iter(["CROP 0,0,60,60\n", "0: window - trees\n"])

    def _spark(url, headers, body):
        bodies.append(body)
        return {
            "id": "r-a",
            "text": next(replies),
            "usage": {"input_tokens": 900, "output_tokens": 20},
        }

    photo = np.zeros((100, 100, 3), np.uint8)
    verdicts = segment.verify_candidates(
        photo,
        [{"object_id": 0, "box": (10, 10, 50, 50)}],
        transport=_spark,
        ledger_path=ledger,
    )
    assert verdicts[0][0] is True
    assert len(bodies) == 2
    for body in bodies:
        payload = json.loads(body.decode("utf-8"))
        content = payload["input"][0]["content"]
        url = next(p["image_url"] for p in content if p["type"] == "input_image")
        raw = base64.b64decode(url.split(",", 1)[1])
        pixels = np.asarray(Image.open(io.BytesIO(raw)).convert("RGB"))
        red = (pixels[..., 0].astype(int) - pixels[..., 1].astype(int)) > 60
        assert red.any(), "follow-up crop lost the red numbered boxes"


def test_verify_zooms_after_one_spark_crop(tmp_path, monkeypatch):
    import json

    monkeypatch.setenv("META_API_KEY", "test-key-never-a-real-secret")
    ledger = tmp_path / "ledger.jsonl"
    bodies = []
    replies = iter(
        [
            "Need a closer look. CROP 0,0,60,60\n",
            "Still looking. CROP 0,0,50,50\n",
            "0: window - trees\n",
            "1: not a window - mirror\n",
        ]
    )

    def _spark(url, headers, body):
        bodies.append(body)
        return {
            "id": "r-s",
            "text": next(replies),
            "usage": {"input_tokens": 900, "output_tokens": 20},
        }

    photo = np.zeros((100, 100, 3), np.uint8)
    boxes = [
        {"object_id": 0, "box": (10, 10, 50, 50)},
        {"object_id": 1, "box": (60, 60, 90, 90)},
    ]
    verdicts = segment.verify_candidates(photo, boxes, transport=_spark, ledger_path=ledger)
    assert verdicts[0][0] is True
    assert verdicts[1] == (False, "mirror")
    prompts = [json.loads(b.decode("utf-8"))["input"] for b in bodies]
    assert "Visible candidate ids" in str(prompts[1])
    assert "Close-up of candidate box" in str(prompts[2])


def test_verify_grants_one_crop_round_on_request(tmp_path, monkeypatch):
    monkeypatch.setenv("META_API_KEY", "test-key-never-a-real-secret")
    ledger = tmp_path / "ledger.jsonl"
    seen_bodies = []
    replies = iter(["CROP 10,10,40,40", "0: window - awning outside, confirmed up close\n"])

    def _spark(url, headers, body):
        seen_bodies.append(json.loads(body.decode("utf-8")))
        return {
            "id": "r-c",
            "text": next(replies),
            "usage": {"input_tokens": 900, "output_tokens": 20},
        }

    photo = np.zeros((100, 100, 3), np.uint8)
    verdicts = segment.verify_candidates(
        photo,
        [{"object_id": 0, "box": (10, 10, 50, 50)}],
        transport=_spark,
        ledger_path=ledger,
    )
    assert verdicts[0][0] is True
    assert len(seen_bodies) == 2, "one annotated photo, then the requested crop"
    assert len(seen_bodies[1]["input"][0]["content"]) == 2, "crop rides as the image"


def _synthetic_brackets():
    """Room 200x200: dark walls, one bright window rect. Dark frame holds a
    gradient view in the window; bright frame blows it to white."""
    room = np.full((200, 200, 3), 40, np.uint8)
    dark = room.copy()
    bright = np.full((200, 200, 3), 180, np.uint8)
    view = np.tile(np.linspace(60, 200, 80, dtype=np.uint8), (120, 1))
    dark[40:160, 60:140] = view[:, :, None]
    bright[40:160, 60:140] = 255
    merge = room.copy()
    merge[40:160, 60:140] = 255
    mask = np.zeros((200, 200), bool)
    mask[40:160, 60:140] = True
    return merge, dark, mask


def test_pull_uses_real_dark_pixels_inside_leaves_rest():
    merge, dark, mask = _synthetic_brackets()
    pulled, _ = segment.pull_window(merge, dark, mask)
    assert (pulled[~mask] == merge[~mask]).all(), "outside the mask no pixel may change"
    # Deep interior, past erosion and feather: the take edge keeps the
    # merge by design, so only the middle testifies for the view.
    inside = np.zeros_like(mask)
    inside[60:140, 80:120] = True
    assert np.abs(pulled[inside].astype(int) - dark[inside].astype(int)).mean() < 12, (
        "the pulled view comes from the real darker frame"
    )


def _three_frames():
    """Same room, three views: black (no detail), clean gradient, blown white."""
    room = np.full((200, 200, 3), 40, np.uint8)
    black = room.copy()
    black[40:160, 60:140] = 8
    mid = room.copy()
    view = np.tile(np.linspace(60, 200, 80, dtype=np.uint8), (120, 1))
    mid[40:160, 60:140] = view[:, :, None]
    blown = room.copy()
    blown[40:160, 60:140] = 255
    merge = room.copy()
    merge[40:160, 60:140] = 255
    mask = np.zeros((200, 200), bool)
    mask[40:160, 60:140] = True
    return merge, [black, mid, blown], mask


def _bright_room_brackets():
    """Exposure-matched rooms: the view lands at its native gain, never
    rescaled past its own frame, so no hue shifts and no new clipping."""
    merge = np.full((200, 200, 3), 150, np.uint8)
    merge[40:160, 60:140] = 255
    dark = np.full((200, 200, 3), 150, np.uint8)
    view = np.tile(np.linspace(60, 200, 80, dtype=np.uint8), (120, 1))
    dark[40:160, 60:140] = view[:, :, None]
    mask = np.zeros((200, 200), bool)
    mask[40:160, 60:140] = True
    return merge, dark, mask


def test_pull_never_pushes_view_brighter_than_its_frame():
    merge, dark, mask = _bright_room_brackets()
    pulled, _ = segment.pull_window(merge, dark, mask)
    # Deep interior, past the feather band: where the view is in control
    # it keeps its own native pixels, never brighter than its frame.
    interior = np.zeros_like(mask)
    interior[55:145, 75:125] = True
    assert (pulled[interior].astype(int) <= dark[interior].astype(int) + 1).all(), (
        "the view lands at native gain, never brightened past its frame"
    )


def test_pull_reports_real_clip_when_every_frame_is_blown():
    merge, _, mask = _three_frames()
    blown = np.full((200, 200, 3), 255, np.uint8)
    blown[~mask] = 40
    pulled, _ = segment.pull_window(merge, blown, mask)
    gray = cv2.cvtColor(pulled, cv2.COLOR_RGB2GRAY)
    assert float((gray[mask] >= 250).mean()) > 0.9, (
        "a blown view must still measure blown: no clamp may fake the check"
    )


def _trimmed_window():
    """White trim ring plus a dark blind band inside the mask, blown glass
    between them. The mask covers trim, blinds and glass, the way SAM
    draws it: the pull must change glass only."""
    merge = np.full((200, 200, 3), 150, np.uint8)
    merge[40:160, 60:140] = 255  # blown glass
    merge[36:40, 56:144] = 242  # white trim, bright but not blown
    merge[160:164, 56:144] = 242
    merge[36:164, 56:60] = 242
    merge[36:164, 140:144] = 242
    merge[70:90, 60:140] = 180  # blind band across the glass, holds detail
    dark = np.full((200, 200, 3), 150, np.uint8)
    view = np.tile(np.linspace(60, 200, 80, dtype=np.uint8), (120, 1))
    dark[40:160, 60:140] = view[:, :, None]
    dark[36:40, 56:144] = 45  # trim reads dark in the dark frame
    dark[160:164, 56:144] = 45
    dark[36:164, 56:60] = 45
    dark[36:164, 140:144] = 45
    dark[70:90, 60:140] = 40  # blinds read dark in the dark frame
    mask = np.zeros((200, 200), bool)
    mask[36:164, 56:144] = True
    return merge, dark, mask


def test_pull_keeps_trim_and_blinds_from_the_merge():
    merge, dark, mask = _trimmed_window()
    pulled, _ = segment.pull_window(merge, dark, mask)
    assert (pulled[~mask] == merge[~mask]).all()
    trim = np.zeros_like(mask)
    trim[36:40, 56:144] = True
    assert (pulled[trim] == merge[trim]).all(), "white trim keeps its real color"
    blinds = np.zeros_like(mask)
    blinds[74:86, 70:130] = True  # band middle, past the feather
    assert (pulled[blinds] == merge[blinds]).all(), "blinds stay from the merge"
    glass = np.zeros_like(mask)
    glass[100:150, 70:130] = True
    assert np.abs(pulled[glass].astype(int) - dark[glass].astype(int)).mean() < 12, (
        "blown glass still takes the real view"
    )


def test_pull_replaces_only_blown_glass_view_holds():
    """One source, native gain: blown glass takes the view, lit trim and
    detailed bars keep the merge pixel-exact.

    The view frame reads the trim bright (230, near the merge's 242), the
    way a same-exposure frame does. Per-pixel source mixing used to take
    that trim dark; the single native source must leave it alone.
    """
    merge = np.full((200, 200, 3), 150, np.uint8)
    merge[40:160, 60:140] = 255  # blown glass
    merge[8:40, 56:144] = 242  # lit trim band, same brightness as glass
    merge[90:110, 40:160] = 120  # dark mullion bar holding merge detail
    view = np.full((200, 200, 3), 150, np.uint8)
    # Real bracket views carry texture; a perfectly smooth ramp is sky,
    # which must keep the merge. Grain it the way foliage reads.
    rng = np.random.default_rng(13)
    glass = np.tile(np.linspace(100, 200, 80, dtype=np.float32), (120, 1))
    glass += rng.normal(0, 10, glass.shape)
    view[40:160, 60:140] = np.clip(glass, 0, 249).astype(np.uint8)[:, :, None]
    view[8:40, 56:144] = 230  # trim reads near-merge in the view frame
    view[90:110, 40:160] = 110
    mask = np.zeros((200, 200), bool)
    mask[8:164, 56:144] = True
    pulled, info = segment.pull_window(merge, view, mask)
    assert info["refused"] is None
    assert (pulled[~mask] == merge[~mask]).all(), "outside the mask nothing changes"
    # Band interior: both edges texture and blend their own neighbors.
    trim = np.zeros_like(mask)
    trim[18:28, 70:130] = True
    assert (pulled[trim] == merge[trim]).all(), "lit trim keeps its merged color"
    bar = np.zeros_like(mask)
    bar[94:106, 70:130] = True
    assert (pulled[bar] == merge[bar]).all(), "detailed bars keep the merge"
    # Deep interior past erosion and feather, where alpha is exactly one.
    inner = np.zeros_like(mask)
    inner[125:145, 75:125] = True
    assert (pulled[inner] == view[inner]).all(), "blown glass takes native view pixels"


def test_pull_inserts_view_at_native_gain():
    """The pull never rescales the view: no hue shift, no new clipping.

    View and merge rooms read different exposures here, the way brackets
    do. A room-matched rescale would darken the whole insert; the native
    insert keeps the view's own color instead.
    """
    merge = np.full((200, 200, 3), 150, np.uint8)
    merge[40:160, 60:140] = 255
    view = np.full((200, 200, 3), 200, np.uint8)
    # Textured the way a real view reads; a smooth ramp is sky and keeps
    # the merge, since the pull cannot tell it from flat trim.
    rng = np.random.default_rng(14)
    glass = np.tile(np.linspace(100, 200, 80, dtype=np.float32), (120, 1))
    glass += rng.normal(0, 10, glass.shape)
    glass = np.clip(glass, 0, 249).astype(np.uint8)
    view[40:160, 60:140] = glass[:, :, None]
    view[40:160, 60:140, 0] = np.clip(glass.astype(int) + 30, 0, 249)  # warm view tint
    mask = np.zeros((200, 200), bool)
    mask[40:160, 60:140] = True
    pulled, _ = segment.pull_window(merge, view, mask)
    inner = np.zeros_like(mask)
    inner[60:140, 80:120] = True
    assert (pulled[inner] == view[inner]).all(), "the view lands unscaled, hue intact"


def test_pull_refuses_a_light_mismatched_view():
    """A view three stops darker than the room would scar the trim.

    The whole view frame sits a uniform 3x under the merge here, trim
    included. Matching the trim would need 3x and blow the glass; the
    pull refuses and the window keeps the merge.
    """
    merge = np.full((200, 200, 3), 150, np.uint8)
    merge[40:160, 60:140] = 255
    merge[36:40, 56:144] = 242
    view = np.full((200, 200, 3), 50, np.uint8)
    view[40:160, 60:140] = 140
    view[36:40, 56:144] = 80
    mask = np.zeros((200, 200), bool)
    mask[36:164, 56:144] = True
    pulled, info = segment.pull_window(merge, view, mask)
    assert info["refused"] is not None, "light mismatch must refuse, not scar"
    assert (pulled == merge).all(), "a refused pull changes nothing"


def test_pull_keeps_sun_glints_honest():
    """A glint blown in every frame keeps the merge: no clamp may fake it."""
    rng = np.random.default_rng(15)
    merge = np.full((200, 200, 3), 150, np.uint8)
    merge[40:160, 60:140] = 255
    view = np.full((200, 200, 3), 150, np.uint8)
    # Textured glass: a flat 140 models nothing a real frame holds, and
    # flat view pixels stay from the merge (they read as trim, not scene).
    view[40:160, 60:140] = np.clip(140 + rng.normal(0, 12, (120, 80, 1)), 0, 249).astype(np.uint8)
    view[95:100, 90:110] = 255  # sun glint, blown in the view too
    mask = np.zeros((200, 200), bool)
    mask[40:160, 60:140] = True
    pulled, _ = segment.pull_window(merge, view, mask)
    glint = np.zeros_like(mask)
    glint[95:100, 90:110] = True
    assert (pulled[glint] == merge[glint]).all(), "glints keep the merge, never a cap"
    # Deep interior past erosion and feather, where alpha is exactly one.
    inner = np.zeros_like(mask)
    inner[125:145, 75:125] = True
    assert (pulled[inner] == view[inner]).all(), "real glass beside it still fills"


def test_pull_keeps_single_channel_blowout_out():
    """A view pixel blown on one channel only never lands in the photo."""
    merge = np.full((100, 100, 3), 150, np.uint8)
    merge[20:80, 20:80] = 255
    view = np.full((100, 100, 3), 150, np.uint8)
    view[20:80, 20:80] = 140
    view[40:60, 40:60] = (140, 140, 255)  # blue blown, gray calm
    mask = np.zeros((100, 100), bool)
    mask[20:80, 20:80] = True
    pulled, _ = segment.pull_window(merge, view, mask)
    spot = np.zeros_like(mask)
    spot[40:60, 40:60] = True
    assert (pulled[spot] == merge[spot]).all(), "single-channel blowout stays out"


def test_choose_view_frame_skips_murk_picks_fix():
    room = np.full((100, 100, 3), 40, np.uint8)
    merge = room.copy()
    merge[20:80, 20:80] = 255
    murk = room.copy()
    murk[20:80, 20:80] = 30  # darkest: no clip, no detail
    fix = room.copy()
    # Textured midtone view: a flat 150 reads as paint, not a view, and
    # the frame would rightly lose to nobody. Grain it like foliage.
    rng = np.random.default_rng(18)
    fix[20:80, 20:80] = np.clip(150 + rng.normal(0, 12, (60, 60, 1)), 0, 249).astype(np.uint8)
    blown = room.copy()
    blown[20:80, 20:80] = 255
    mask = np.zeros((100, 100), bool)
    mask[20:80, 20:80] = True
    idx, reason = segment.choose_view_frame([murk, fix, blown], mask, merge)
    assert idx == 1, f"the frame that fixes blown glass wins over murk and white ({reason})"


def test_choose_view_frame_returns_none_when_nothing_to_fix():
    room = np.full((100, 100, 3), 150, np.uint8)
    merge = room.copy()
    merge[20:80, 20:80] = 180  # clean detailed glass, nothing blown
    view = room.copy()
    view[20:80, 20:80] = 120
    mask = np.zeros((100, 100), bool)
    mask[20:80, 20:80] = True
    idx, reason = segment.choose_view_frame([view], mask, merge)
    assert idx is None, (
        f"a clean window keeps the merge pixel-exact instead of gaining churn ({reason})"
    )


def test_pull_fills_wide_blown_bay_from_single_view():
    # A wide blown bay takes the one view frame everywhere, border or
    # not. Trim agrees with the merge and stays pixel-exact; the slat
    # holds merge detail and stays.
    rng = np.random.default_rng(16)
    merge = np.full((400, 400, 3), 150, np.uint8)
    merge[40:360, 60:340] = 255  # blown glass bay to the border
    merge[40:46, 60:340] = 242  # white trim along the top
    merge[190:200, 60:340] = 180  # thin blind slat across the pane
    view = np.full((400, 400, 3), 150, np.uint8)
    # Textured bay: flat 140 reads as paint, not a view, and stays out.
    view[40:360, 60:340] = np.clip(140 + rng.normal(0, 12, (320, 280, 1)), 0, 249).astype(np.uint8)
    view[40:46, 60:340] = 230  # trim reads near-merge in the view
    view[190:200, 60:340] = 175
    mask = np.zeros((400, 400), bool)
    mask[40:360, 60:340] = True
    pulled, _ = segment.pull_window(merge, view, mask)
    bay = np.zeros_like(mask)
    bay[110:180, 150:250] = True
    assert abs(pulled[bay].astype(int).mean() - 140) < 12, (
        "blown bays take the view, wherever they touch"
    )
    trim = np.zeros_like(mask)
    trim[42:45, 100:300] = True
    assert (pulled[trim] == merge[trim]).all(), "trim stays"
    slat = np.zeros_like(mask)
    slat[192:198, 100:300] = True
    assert (pulled[slat] == merge[slat]).all(), "thin slats stay"


def test_pull_fills_shoulder_glass_but_not_shadowed_trim():
    # Blown glass the shoulder parks just under near-white takes the
    # view when it holds detail there; trim the view reads dark stays
    # because no view pixel there holds a scene.
    rng = np.random.default_rng(7)
    merge = np.full((200, 200, 3), 150, np.uint8)
    merge[40:160, 60:140] = 240  # shoulder-parked blown glass
    merge[150:160, 60:140] = 242  # trim, same brightness
    view = np.full((200, 200, 3), 150, np.uint8)
    grain = rng.normal(0, 12, (110, 80, 1))
    view[40:150, 60:140] = np.clip(140 + grain, 0, 255).astype(np.uint8)
    view[150:160, 60:140] = 40  # trim: dark in the view frame
    mask = np.zeros((200, 200), bool)
    mask[40:160, 60:140] = True
    pulled, _ = segment.pull_window(merge, view, mask)
    glass = np.zeros_like(mask)
    glass[60:140, 70:130] = True
    assert abs(pulled[glass].astype(int).mean() - 140) < 30, (
        "shoulder glass takes the view that holds detail"
    )
    trim = np.zeros_like(mask)
    trim[154:158, 70:130] = True
    assert (pulled[trim] == merge[trim]).all(), "dark-reading trim stays"


def test_pull_keeps_room_bright_flat_trim_next_to_blown_core():
    # Sunlit trim reads room-bright in the merge and dark in the view
    # frame while the blown core beside it takes the view. The trim's
    # own view pixels hold no scene, so every trim pixel stays.
    rng = np.random.default_rng(17)
    merge = np.full((200, 200, 3), 150, np.uint8)
    merge[40:160, 60:140] = 255  # blown core
    merge[40:46, 60:140] = 242  # sunlit trim strip against the core
    view = np.full((200, 200, 3), 150, np.uint8)
    view[40:46, 60:140] = 40
    # Textured core: flat 140 reads as paint and stays out, like trim.
    view[46:160, 60:140] = np.clip(140 + rng.normal(0, 12, (114, 80, 1)), 0, 249).astype(np.uint8)
    mask = np.zeros((200, 200), bool)
    mask[40:160, 60:140] = True
    pulled, _ = segment.pull_window(merge, view, mask)
    trim = np.zeros_like(mask)
    trim[40:46, 70:130] = True
    assert (pulled[trim] == merge[trim]).all(), "sunlit trim stays"


def test_pull_keeps_dark_mullion_bar_from_the_merge():
    merge, dark, mask = _synthetic_brackets()
    merge[90:110, 40:160] = 120  # dark mullion bar across the blown glass
    dark[90:110, 40:160] = 30
    pulled, _ = segment.pull_window(merge, dark, mask)
    bar = np.zeros_like(mask)
    bar[94:106, 70:130] = True
    assert (pulled[bar] == merge[bar]).all(), "the frame bar keeps its color"


def test_pull_reaches_full_view_inside_without_overshoot():
    merge, dark, mask = _synthetic_brackets()
    pulled, _ = segment.pull_window(merge, dark, mask)
    # Deep interior: pure matched view, no merge bleeding through.
    interior = mask.copy()
    interior[40:160, 60:140] = False
    interior[50:150, 70:130] = True
    assert np.abs(pulled[interior].astype(int) - dark[interior].astype(int)).mean() < 12
    # Seam band: a linear blend never leaves the [view, room] interval, so
    # no bright halo or dark outline can appear.
    lo = np.minimum(dark.astype(int), merge.astype(int))
    hi = np.maximum(dark.astype(int), merge.astype(int))
    band = pulled.astype(int)
    assert ((band >= lo - 1) & (band <= hi + 1)).all(), "no overshoot past either input"


def _sunlit_flat_trim_textured_glass():
    """005 in miniature: flat sunlit trim at view 130-140 with the merge
    trim near-white, beside grain-textured glass blown in the merge.

    Every old take condition passes on that trim (bright in the merge,
    mid-tone and unblown in the view, big gap), so the pull used to drag
    dark flat trim into a white room and scar it brown. Flat view pixels
    hold no scene: only textured view pixels take."""
    rng = np.random.default_rng(11)
    merge = np.full((200, 200, 3), 150, np.uint8)
    merge[40:160, 60:140] = 255  # blown glass
    merge[10:40, 56:144] = 250  # sunlit trim band, near-white like the glass
    grain = rng.normal(0, 14, (120, 80, 1))
    view = np.full((200, 200, 3), 150, np.uint8)
    view[40:160, 60:140] = np.clip(150 + grain, 0, 249).astype(np.uint8)
    view[10:40, 56:144] = 135  # flat trim in the mid frame, 005's own read
    mask = np.zeros((200, 200), bool)
    mask[10:164, 56:144] = True
    return merge, view, mask


def test_pull_leaves_flat_sunlit_trim_takes_textured_glass():
    merge, view, mask = _sunlit_flat_trim_textured_glass()
    pulled, info = segment.pull_window(merge, view, mask)
    assert info["refused"] is None
    assert (pulled[~mask] == merge[~mask]).all()
    # Band interior, clear of both edges: each edge textures its own
    # neighbors through the texture window and blends through the feather,
    # by design. The band itself must keep the merge pixel-exact.
    trim = np.zeros_like(mask)
    trim[20:30, 70:130] = True
    assert (pulled[trim] == merge[trim]).all(), "flat sunlit trim keeps the merge"
    glass = np.zeros_like(mask)
    glass[60:140, 70:130] = True
    assert np.abs(pulled[glass].astype(int) - view[glass].astype(int)).mean() < 14, (
        "textured blown glass still takes the real view"
    )


def test_take_mask_erodes_past_the_edge_straddle():
    """The texture window testifies for glass up to half its width past
    every glass/trim edge, which used to outline each mullion in dark
    trim paint. The take gives back that band: edge-adjacent rows stay
    from the merge, deep glass still fills."""
    merge, view, mask = _sunlit_flat_trim_textured_glass()
    take = segment._take_mask(merge, view, mask)
    band = np.zeros_like(mask)
    band[33:42, 70:130] = True  # trim-side straddle rows at the glass edge
    assert not take[band].any(), "edge bands leave the take"
    deep = np.zeros_like(mask)
    deep[90:110, 70:130] = True
    assert take[deep].all(), "deep glass still takes"


def test_take_mask_closes_bright_dither_holes():
    """Foliage gaps read blown even in the view frame, dithering the take
    into speckle: white merge dots inside the pulled glass that read as
    solarized blobs. A bright hole fully inside the take fills, so the
    shipped view is one continuous region."""
    rng = np.random.default_rng(12)
    merge = np.full((200, 200, 3), 150, np.uint8)
    merge[40:160, 60:140] = 255
    grain = rng.normal(0, 14, (120, 80, 1))
    view = np.full((200, 200, 3), 150, np.uint8)
    view[40:160, 60:140] = np.clip(150 + grain, 0, 249).astype(np.uint8)
    view[95:105, 90:110] = 255  # sky gap, blown in the view too
    mask = np.zeros((200, 200), bool)
    mask[40:160, 60:140] = True
    take = segment._take_mask(merge, view, mask)
    hole = np.zeros_like(mask)
    hole[95:105, 90:110] = True
    assert take[hole].all(), "bright dither holes fill: one continuous view"
