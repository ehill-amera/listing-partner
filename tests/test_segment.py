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
    pulled, changed_outside = segment.pull_window(merge, dark, mask)
    assert changed_outside == 0, "outside the mask no pixel may change"
    inside = pulled[mask].astype(int)
    assert np.abs(inside - dark[mask].astype(int)).mean() < 12, (
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


def test_choose_pull_frame_skips_blown_and_empty_views():
    merge, frames, mask = _three_frames()
    assert segment.choose_pull_frame(frames, mask) == 1, (
        "the view comes from the best-exposed frame, not the darkest"
    )


def test_choose_pull_frame_prefers_more_detail_on_ties():
    room = np.full((100, 100, 3), 40, np.uint8)
    dim = room.copy()
    dim[20:80, 20:80] = 100
    bright = room.copy()
    bright[20:80, 20:80] = 180
    mask = np.zeros((100, 100), bool)
    mask[20:80, 20:80] = True
    assert segment.choose_pull_frame([dim, bright], mask) == 1, (
        "with no clipping anywhere, the brighter frame holds more view detail"
    )


def _bright_room_brackets():
    """Bright-room merge (150), dark-room view frame (40): the old room
    match scaled the view up 3.75x and blew it out; the view must stay."""
    merge = np.full((200, 200, 3), 150, np.uint8)
    merge[40:160, 60:140] = 255
    dark = np.full((200, 200, 3), 40, np.uint8)
    view = np.tile(np.linspace(60, 200, 80, dtype=np.uint8), (120, 1))
    dark[40:160, 60:140] = view[:, :, None]
    mask = np.zeros((200, 200), bool)
    mask[40:160, 60:140] = True
    return merge, dark, mask


def test_pull_never_pushes_view_brighter_than_its_frame():
    merge, dark, mask = _bright_room_brackets()
    pulled, _ = segment.pull_window(merge, dark, mask)
    # Deep interior, past the feather band: the seam band blends toward
    # the room by design, but where the view is in control it keeps its
    # own brightness or darker, never brighter than its frame.
    interior = np.zeros_like(mask)
    interior[55:145, 75:125] = True
    assert (pulled[interior].astype(int) <= dark[interior].astype(int) + 1).all(), (
        "room matching may only darken the view, never brighten it past its frame"
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
