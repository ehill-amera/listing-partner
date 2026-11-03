"""Unit 4: the honest tidy. Model far side faked at the transport, no network."""

import base64
import hashlib
import io
import json
import re
from pathlib import Path

import cv2
import numpy as np
import pytest
from PIL import Image

from listing_partner import meta_client, segment, tidy

W, H = 600, 400
BG = (200, 180, 160)
ITEM = (10, 10, 10)
ITEM_BOX = (100, 100, 200, 200)
BIN_BOX = (400, 100, 480, 180)


def _photo():
    # A gentle pattern, so a whole-image regeneration cannot pass by accident.
    yy, xx = np.mgrid[0:H, 0:W]
    rgb = np.stack([BG[0] + xx % 7, BG[1] + yy % 5, BG[2] + (xx + yy) % 3], axis=2).astype(np.uint8)
    left, top, right, bottom = ITEM_BOX
    rgb[top:bottom, left:right] = ITEM
    return rgb


def _rect(box, shape=(H, W)):
    mask = np.zeros(shape, bool)
    left, top, right, bottom = box
    mask[top:bottom, left:right] = True
    return mask


GOOD_CONFIRM = {
    "confirm": True,
    "is_that_item": True,
    "objects": ["a loose item"],
    "attached": False,
    "reason": "loose item",
}


class World:
    """The far side of the capped client: Spark, SAM and Muse Image."""

    def __init__(self):
        self.sam = {"cardboard box": [ITEM_BOX]}
        # What SAM finds once a fill has been made: by default, nothing.
        self.recheck = {}
        self.recheck_error = None
        self.recheck_seen = []
        self.damage = []
        self.damage_reply = None
        self.confirm = {}
        self.selfcheck = {
            "item_gone": True,
            "property_changed": False,
            "damage_softened": False,
            "object_added": False,
            "item_remains": False,
            "reason": "the box is gone and the wall is the same",
        }
        self.selfcheck_error = None
        self.selfcheck_reply = None
        # Which self-check calls fail, counted from 1. None means all of them.
        self.selfcheck_error_on = None
        self.image_error = None
        self.edit_shift = 0
        self.edit_size = None
        # Changes the generated picture: (attempt from 1, picture, painted area).
        self.edit_paint = None
        self.confirm_texts = []
        self.confirm_tokens = []
        self.confirm_errors = 0
        self.confirm_images = []
        self.calls = {"damage": 0, "sam": 0, "confirm": 0, "selfcheck": 0, "edit": 0}
        self.edit_bodies = []
        self.sent_jpegs = 0

    def __call__(self, url, headers, body):
        data = json.loads(body)
        if url.endswith("/images/edits"):
            return self._edit(data)
        content = data["input"][0]["content"]
        text = content[0]["text"]
        self.sent_jpegs += 1
        if data["model"] == "sam-3.1":
            self.calls["sam"] += 1
            if self.calls["edit"]:
                self.recheck_seen.append((text, content[1]["image_url"]))
                if self.recheck_error:
                    raise OSError(self.recheck_error)
                reply = json.dumps(self.recheck.get(text, []))
            else:
                reply = json.dumps(self.sam.get(text, []))
        elif text.startswith(tidy.DAMAGE_PROMPT[:40]):
            self.calls["damage"] += 1
            first = self.calls["damage"] % 5 == 1
            reply = self.damage_reply
            if reply is None:
                reply = json.dumps({"damage": self.damage if first else []})
        elif text.startswith(tidy.CONFIRM_PROMPT[:40]):
            self.calls["confirm"] += 1
            # Spark is not told the finder's label, so candidates are matched by
            # order: the finder walks the list in order and so does the confirm.
            order = [x for x in tidy.CLUTTER_LIST for _ in self.sam.get(x, [])]
            label = order[(self.calls["confirm"] - 1) % len(order)]
            self.confirm_texts.append(text)
            self.confirm_tokens.append(data["max_output_tokens"])
            if self.confirm_errors:
                self.confirm_errors -= 1
                raise OSError("reply cut off")
            self.confirm_images.append(content[1:])
            verdict = {"kind": label, **GOOD_CONFIRM, **self.confirm.get(label, {})}
            if label in self.confirm and not self.confirm[label]:
                verdict = {}
            reply = json.dumps(verdict)
        elif text.startswith(tidy.SELFCHECK_PROMPT[:40]):
            self.calls["selfcheck"] += 1
            on = self.selfcheck_error_on
            if self.selfcheck_error and (on is None or self.calls["selfcheck"] in on):
                raise OSError(self.selfcheck_error)
            reply = self.selfcheck_reply or json.dumps(self.selfcheck)
        else:
            raise AssertionError(f"unexpected prompt {text[:60]!r}")
        return {"id": "r", "text": reply, "usage": {"input_tokens": 10, "output_tokens": 5}}

    def _edit(self, data):
        self.calls["edit"] += 1
        self.edit_bodies.append(data)
        if self.image_error:
            raise OSError(self.image_error)
        raw = base64.b64decode(data["images"][0]["image_url"].split(",", 1)[1])
        with Image.open(io.BytesIO(raw)) as handle:
            sent = np.asarray(handle.convert("RGB")).copy()
        # Fill the painted area with the wall colour, and touch nothing else,
        # the way a good edit would, but mark it as generated.
        painted = tidy.is_paint(sent)
        sent[painted] = (150, 140, 130)
        if self.edit_paint:
            sent = self.edit_paint(self.calls["edit"], sent, painted)
        if self.edit_shift:
            sent = np.roll(sent, self.edit_shift, axis=1)
        out = Image.fromarray(sent)
        if self.edit_size:
            out = out.resize(self.edit_size)
        handle = io.BytesIO()
        out.save(handle, format="PNG")
        return {"created": 1, "data": [{"b64_json": base64.b64encode(handle.getvalue()).decode()}]}


@pytest.fixture
def world(monkeypatch):
    monkeypatch.setenv(meta_client.KEY_ENV_VAR, "test-key")

    # SAM's wire format has its own tests; the fake lane here is a list of boxes.
    def lane(text, frame_w, frame_h):
        return [
            {"object_id": i, "box": tuple(b), "mask": _rect(b, (frame_h, frame_w))}
            for i, b in enumerate(json.loads(text))
        ]

    monkeypatch.setattr(segment, "parse_lane", lane)
    return World()


@pytest.fixture
def unit(tmp_path):
    out = tmp_path / "unit"
    (out / "finished").mkdir(parents=True)
    for pid in ("001", "002"):
        Image.fromarray(_photo()).save(out / "finished" / f"{pid}.jpg", quality=95)
    hashes = {
        p.stem: hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted((out / "finished").glob("*.jpg"))
    }
    (out / "curation.json").write_text(
        json.dumps(
            {
                "kept": [{"id": "001", "room": "bedroom"}],
                "dropped": [{"id": "002", "room": "bedroom", "reason": "duplicate"}],
                "photos": hashes,
                "cost": {"calls": 1, "usd": 0.01},
            }
        )
    )
    return out


def _run(unit, world, **kw):
    return tidy.run_tidy(
        output_dir=unit,
        transport=world,
        ledger_path=unit / "ledger.jsonl",
        baseline_path=unit / "baseline.json",
        **kw,
    )


def _finished(unit, pid="001"):
    with Image.open(unit / "finished" / f"{pid}.jpg") as handle:
        return np.asarray(handle.convert("RGB"))


def _tidied(unit, pid="001"):
    with Image.open(unit / "tidy" / pid / "tidied.png") as handle:
        return np.asarray(handle.convert("RGB"))


def _mask(unit, pid="001"):
    with Image.open(unit / "tidy" / pid / "mask.png") as handle:
        return np.asarray(handle.convert("L")) > 0


# --- the fixed clutter list


def test_clutter_list_is_exactly_the_contract_list():
    assert tidy.CLUTTER_LIST == (
        "trash bin",
        "cardboard box",
        "plastic bag",
        "packing material",
        "loose cable or cord",
        "laundry basket",
        "cleaning supplies",
        "shoes",
        "bucket",
        "ladder",
        "paint can",
        "tools",
    )


def test_sam_is_asked_only_for_the_fixed_list(unit, world):
    seen = []
    inner = world.__call__

    def spy(url, headers, body):
        data = json.loads(body)
        if data["model"] == "sam-3.1":
            seen.append(data["input"][0]["content"][0]["text"])
        return inner(url, headers, body)

    tidy.run_tidy(
        output_dir=unit,
        transport=spy,
        ledger_path=unit / "ledger.jsonl",
        baseline_path=unit / "baseline.json",
    )
    # The fixed list once to find, then only the removed item's prompt to re-check.
    count = len(tidy.CLUTTER_LIST)
    assert tuple(seen[:count]) == tidy.CLUTTER_LIST
    assert seen[count:] == ["cardboard box"]
    assert "hose" not in seen


@pytest.mark.parametrize("label", ["sofa", "hose"])
def test_build_mask_refuses_a_label_off_the_list(label):
    item = {"label": label, "mask": _rect(ITEM_BOX), "reason": "r"}
    with pytest.raises(ValueError, match="not on the clutter list"):
        tidy.build_final_mask([item], [], (H, W))


# --- damage list parsing


def test_parse_damage_maps_view_coordinates_to_photo_pixels():
    reply = json.dumps({"damage": [{"box": [0, 0, 500, 500], "note": "stain"}]})
    assert tidy.parse_damage(reply, (100, 50, 300, 250)) == [
        {"box": (100, 50, 200, 150), "note": "stain"}
    ]


@pytest.mark.parametrize(
    "reply",
    [
        "no json here",
        "{}",
        json.dumps({"damage": [{"box": [0, 0, 10], "note": "x"}]}),
        json.dumps({"damage": [{"box": [10, 10, 5, 20], "note": "x"}]}),
        json.dumps({"damage": [{"box": [0, 0, 1001, 10], "note": "x"}]}),
        json.dumps({"damage": [{"box": [0, 0, 10, 10], "note": ""}]}),
    ],
)
def test_parse_damage_raises_on_anything_it_cannot_trust(reply):
    with pytest.raises(ValueError):
        tidy.parse_damage(reply, (0, 0, 100, 100))


def test_unreadable_damage_list_means_no_tidy_on_that_photo(unit, world):
    world.damage_reply = "I see nothing wrong"
    summary = _run(unit, world)
    photo = summary["photos"][0]
    assert photo["status"] == "untidied"
    assert "damage list" in photo["reason"]
    assert world.calls["edit"] == 0
    assert not (unit / "tidy" / "001" / "tidied.png").exists()


# --- mask rules


def test_mask_is_grown_by_the_fixed_margin():
    item = {"label": "bucket", "mask": _rect(ITEM_BOX), "reason": "r"}
    final, removed, left = tidy.build_final_mask([item], [], (H, W))
    margin = tidy.grow_px((H, W))
    assert final[100, 100 - margin] and not final[100, 100 - margin - 2]
    assert [r["label"] for r in removed] == ["bucket"] and left == []


def test_candidate_whose_own_mask_touches_damage_is_left_in_place():
    item = {"label": "bucket", "mask": _rect(ITEM_BOX), "reason": "r"}
    damage = [{"box": (190, 190, 260, 260), "note": "crack"}]
    final, removed, left = tidy.build_final_mask([item], damage, (H, W))
    assert not final.any() and removed == []
    assert left == [{"label": "bucket", "reason": "left in place: overlaps damage"}]


def test_grown_margin_touching_damage_is_cut_and_the_item_still_goes():
    item = {"label": "bucket", "mask": _rect(ITEM_BOX), "reason": "r"}
    damage = [{"box": (201, 100, 260, 200), "note": "crack"}]
    final, removed, left = tidy.build_final_mask([item], damage, (H, W))
    assert [r["label"] for r in removed] == ["bucket"] and left == []
    assert final[150, 199] and not final[150, 201:260].any()


def test_oversized_candidate_is_left_in_place_with_a_reason():
    item = {"label": "bucket", "mask": _rect((0, 0, 400, 200)), "reason": "r"}
    final, removed, left = tidy.build_final_mask([item], [], (H, W))
    assert not final.any() and removed == []
    assert "too large" in left[0]["reason"]


# --- composite and measurement


def test_composite_copies_every_outside_pixel_from_the_finished_photo():
    finished, generated = _photo(), np.full((H, W, 3), 7, np.uint8)
    mask = _rect((100, 100, 200, 200))
    out = tidy.composite(finished, generated, mask)
    assert (out[~mask] == finished[~mask]).all()
    assert (out[150, 150] == 7).all()


def test_blend_fill_removes_a_brightness_slope_at_the_mask_edge():
    crop = np.full((200, 300, 3), 120, np.uint8)
    slope = np.linspace(-40, 40, 300)[None, :, None]
    fill = np.clip(crop + slope, 0, 255).astype(np.uint8)
    inside = _rect((100, 50, 200, 150), (200, 300))
    out = tidy.blend_fill(crop, fill, inside)
    edge = inside & ~cv2.erode(inside.astype(np.uint8), np.ones((5, 5), np.uint8)).astype(bool)
    assert np.abs(out[edge].astype(float) - 120).max() <= 4


def test_blend_fill_handles_a_mask_on_the_crop_edge():
    crop = np.full((100, 100, 3), 120, np.uint8)
    fill = np.full((100, 100, 3), 90, np.uint8)
    inside = _rect((0, 0, 40, 40), (100, 100))
    assert tidy.blend_fill(crop, fill, inside).shape == crop.shape


def test_measure_counts_one_changed_pixel_outside_the_mask(tmp_path):
    finished = _photo()
    mask = _rect((100, 100, 200, 200))
    after = finished.copy()
    after[10, 10, 0] ^= 1
    fin, tid, msk = tmp_path / "f.png", tmp_path / "t.png", tmp_path / "m.png"
    Image.fromarray(finished).save(fin)
    Image.fromarray(after).save(tid)
    segment.save_mask_png(mask, msk)
    out = tidy.measure(fin, tid, msk, [])
    assert out["outside_changed_pixels"] == 1


def test_measure_counts_damage_pixels_under_the_mask(tmp_path):
    finished = _photo()
    mask = _rect((100, 100, 200, 200))
    fin, msk = tmp_path / "f.png", tmp_path / "m.png"
    Image.fromarray(finished).save(fin)
    segment.save_mask_png(mask, msk)
    damage = [{"box": (190, 190, 210, 210), "note": "x"}]
    assert tidy.measure(fin, fin, msk, damage)["damage_overlap_pixels"] == 100


def test_measure_raises_on_a_size_mismatch(tmp_path):
    fin, tid, msk = tmp_path / "f.png", tmp_path / "t.png", tmp_path / "m.png"
    Image.fromarray(_photo()).save(fin)
    Image.fromarray(_photo()[:-1]).save(tid)
    segment.save_mask_png(_rect((0, 0, 5, 5)), msk)
    with pytest.raises(ValueError):
        tidy.measure(fin, tid, msk, [])


CLEAR = {"pass": True, "reason": ""}
FOUND = {"pass": False, "reason": "SAM 3.1 still finds bucket in the filled area"}


@pytest.mark.parametrize(
    ("pixels_ok", "spark", "recheck", "ships"),
    [
        (True, tidy.CHECK_PASS, CLEAR, "tidied"),
        (True, tidy.CHECK_DISAGREE, CLEAR, "untidied"),
        (True, tidy.CHECK_INCOMPLETE, CLEAR, "untidied"),
        (False, tidy.CHECK_PASS, CLEAR, "untidied"),
        (True, tidy.CHECK_PASS, FOUND, "untidied"),
    ],
)
def test_ship_decision_needs_all_three_to_pass(pixels_ok, spark, recheck, ships):
    assert tidy.ship_decision(pixels_ok, spark, recheck)[0] == ships


def test_ship_decision_names_a_disagreement():
    assert "disagree" in tidy.ship_decision(True, tidy.CHECK_DISAGREE, CLEAR)[1]
    assert "disagree" in tidy.ship_decision(False, tidy.CHECK_PASS, CLEAR)[1]


def test_ship_decision_says_a_check_with_no_verdict_did_not_complete():
    assert tidy.ship_decision(True, tidy.CHECK_INCOMPLETE, CLEAR)[1] == (
        "self-check did not complete"
    )
    both = tidy.ship_decision(False, tidy.CHECK_INCOMPLETE, CLEAR)[1]
    assert "self-check did not complete" in both
    assert "disagree" not in both and "self-check failed" not in both


def test_ship_decision_gives_the_recheck_reason_first():
    assert tidy.ship_decision(True, tidy.CHECK_DISAGREE, FOUND)[1].startswith(FOUND["reason"])


# --- the whole run, on the real ledger code and real files


def test_run_tidies_and_every_outside_pixel_matches_when_read_back(unit, world):
    summary = _run(unit, world)
    photo = summary["photos"][0]
    assert photo["status"] == "tidied"
    mask = _mask(unit)
    assert mask[150, 150]
    assert (_tidied(unit)[~mask] == _finished(unit)[~mask]).all()
    assert photo["measure"]["outside_changed_pixels"] == 0
    assert photo["measure"]["inside_changed_pixels"] > 0
    assert (_tidied(unit)[150, 150] != ITEM).any()


def test_only_kept_photos_are_tidied(unit, world):
    summary = _run(unit, world)
    assert [p["id"] for p in summary["photos"]] == ["001"]
    assert not (unit / "tidy" / "002").exists()


def test_finished_photo_is_left_untouched(unit, world):
    before = (unit / "finished" / "001.jpg").read_bytes()
    _run(unit, world)
    assert (unit / "finished" / "001.jpg").read_bytes() == before


def test_what_goes_to_muse_image_has_the_clutter_painted_out(unit, world):
    _run(unit, world)
    raw = base64.b64decode(world.edit_bodies[0]["images"][0]["image_url"].split(",", 1)[1])
    with Image.open(io.BytesIO(raw)) as handle:
        sent = np.asarray(handle.convert("RGB"))
    assert tidy.is_paint(sent).any()
    # The clutter's own colour is gone from what the model sees.
    assert not (sent.max(axis=2) < 40).any()


def test_generated_reply_of_another_size_is_refit_and_outside_still_exact(unit, world):
    world.edit_size = (321, 123)
    summary = _run(unit, world)
    mask = _mask(unit)
    assert summary["photos"][0]["measure"]["outside_changed_pixels"] == 0
    assert (_tidied(unit)[~mask] == _finished(unit)[~mask]).all()


def test_a_fill_that_does_not_line_up_ships_untidied(unit, world):
    # Stripes the shift would misplace: the ring around the mask stops matching.
    photo = _photo()
    photo[:, ::8] = (30, 30, 30)
    Image.fromarray(photo).save(unit / "finished" / "001.jpg", quality=95)
    data = json.loads((unit / "curation.json").read_text())
    data["photos"]["001"] = hashlib.sha256((unit / "finished" / "001.jpg").read_bytes()).hexdigest()
    (unit / "curation.json").write_text(json.dumps(data))
    world.edit_shift = 4
    photo_out = _run(unit, world)["photos"][0]
    assert photo_out["status"] == "untidied"
    assert "line up" in photo_out["reason"]


def test_rejection_keeps_the_item_and_carries_the_reason(unit, world):
    world.confirm["cardboard box"] = {"confirm": False, "reason": "built-in shelf"}
    summary = _run(unit, world)
    photo = summary["photos"][0]
    assert photo["status"] == "nothing to tidy"
    assert photo["rejected"] == [{"label": "cardboard box", "reason": "built-in shelf"}]
    assert world.calls["edit"] == 0


@pytest.mark.parametrize(
    "verdict",
    [{**GOOD_CONFIRM, "reason": ""}, {**GOOD_CONFIRM, "reason": " "}, {}],
)
def test_confirm_without_a_reason_never_removes(unit, world, verdict):
    world.confirm["cardboard box"] = verdict
    photo = _run(unit, world)["photos"][0]
    assert photo["status"] == "nothing to tidy"
    assert photo["removed"] == []
    assert photo["rejected"][0]["reason"]


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ({"attached": True}, "still plugged into the outlet"),
        ({"attached": None}, "no answer on attachment"),
    ],
)
def test_attached_item_or_one_with_no_answer_on_it_is_never_removed(unit, world, change, reason):
    world.confirm["cardboard box"] = {**GOOD_CONFIRM, **change, "reason": reason}
    photo = _run(unit, world)["photos"][0]
    assert photo["removed"] == []
    assert photo["rejected"] == [{"label": "cardboard box", "reason": reason}]
    assert world.calls["edit"] == 0


def test_damage_box_is_protected_through_the_whole_run(unit, world):
    # 700..800 of 1000 across, 500..600 down: clear of the box.
    world.damage = [{"box": [700, 500, 800, 600], "note": "water stain"}]
    photo = _run(unit, world)["photos"][0]
    assert photo["damage"][0]["note"] == "water stain"
    assert photo["measure"]["damage_overlap_pixels"] == 0
    assert (unit / "tidy" / "001" / "damage_1.jpg").exists()


def test_candidate_on_damage_is_listed_and_nothing_is_generated(unit, world):
    world.damage = [{"box": [300, 450, 400, 550], "note": "crack"}]
    photo = _run(unit, world)["photos"][0]
    assert photo["status"] == "nothing to tidy"
    assert photo["left_in_place"] == [
        {"label": "cardboard box", "reason": "left in place: overlaps damage"}
    ]
    assert world.calls["edit"] == 0


def test_muse_image_failure_ships_untidied_with_the_reason(unit, world):
    world.image_error = "backend down"
    photo = _run(unit, world)["photos"][0]
    assert photo["status"] == "untidied"
    assert "Muse Image" in photo["reason"]
    assert not (unit / "tidy" / "001" / "tidied.png").exists()


def test_self_check_failure_is_a_disagreement_and_ships_untidied(unit, world):
    world.selfcheck["property_changed"] = True
    world.selfcheck["reason"] = "the baseboard changed"
    photo = _run(unit, world)["photos"][0]
    assert photo["status"] == "untidied"
    assert "disagree" in photo["reason"]
    assert photo["selfcheck"]["reason"] == "the baseboard changed"
    assert photo["selfcheck"]["pass"] is False


@pytest.mark.parametrize(
    "change",
    [{"object_added": True}, {"item_remains": True}, {"object_added": None}],
)
def test_self_check_naming_an_added_object_or_a_remnant_ships_untidied(unit, world, change):
    world.selfcheck.update(change)
    photo = _run(unit, world)["photos"][0]
    assert photo["status"] == "untidied"
    assert "disagree" in photo["reason"]


NO_VERDICT = "self-check did not complete"


def _no_verdict_timeout(world):
    world.selfcheck_error = "timed out"


def _no_verdict_unreadable(world):
    world.selfcheck_reply = "I could not tell"


def _no_verdict_empty_json(world):
    world.selfcheck_reply = "{}"


@pytest.mark.parametrize(
    "make", [_no_verdict_timeout, _no_verdict_unreadable, _no_verdict_empty_json]
)
def test_self_check_with_no_verdict_says_so_and_never_says_spark_disagreed(unit, world, make):
    make(world)
    summary = _run(unit, world)
    photo = summary["photos"][0]
    html = (unit / "tidy.html").read_text()
    assert photo["status"] == "untidied"
    assert photo["reason"] == NO_VERDICT
    assert photo["selfcheck"]["state"] == tidy.CHECK_INCOMPLETE
    assert photo["not_removed"] == [{"label": "cardboard box", "reason": NO_VERDICT}]
    assert summary["selfcheck_did_not_complete"] == 1
    assert NO_VERDICT in html
    assert "disagree" not in html
    assert "timed out" not in html


def test_real_disagreement_is_not_counted_as_did_not_complete(unit, world):
    world.selfcheck["property_changed"] = True
    summary = _run(unit, world)
    assert summary["photos"][0]["selfcheck"]["state"] == tidy.CHECK_DISAGREE
    assert summary["selfcheck_did_not_complete"] == 0
    assert NO_VERDICT not in (unit / "tidy.html").read_text()


def test_one_area_disagreeing_and_one_timing_out_reports_both(unit, world):
    # Two items far apart make two self-check areas: the second call times out.
    world.sam = {"cardboard box": [(20, 20, 60, 60), (530, 330, 570, 370)]}
    world.selfcheck["property_changed"] = True
    world.selfcheck["reason"] = "the baseboard changed"
    world.selfcheck_error = "timed out"
    world.selfcheck_error_on = {2}
    photo = _run(unit, world)["photos"][0]
    assert world.calls["selfcheck"] == 2
    assert photo["selfcheck"]["state"] == tidy.CHECK_DISAGREE
    assert "disagree" in photo["reason"]
    assert "the baseboard changed" in photo["selfcheck"]["reason"]
    assert NO_VERDICT in photo["selfcheck"]["reason"]


def test_recheck_failure_with_no_verdict_still_shows_the_check_did_not_complete(unit, world):
    world.selfcheck_error = "timed out"
    world.recheck = {"cardboard box": [(120, 120, 180, 180)]}
    photo = _run(unit, world)["photos"][0]
    html = (unit / "tidy.html").read_text()
    assert photo["reason"].startswith("SAM 3.1 still finds")
    assert NO_VERDICT in html and "disagree" not in html


def test_tidied_photo_has_a_passing_self_check_verdict(unit, world):
    photo = _run(unit, world)["photos"][0]
    assert photo["selfcheck"]["pass"] is True and world.calls["selfcheck"] >= 1


def test_nothing_found_reports_nothing_to_tidy_not_a_failure(unit, world):
    world.sam = {}
    summary = _run(unit, world)
    assert summary["photos"][0]["status"] == "nothing to tidy"
    assert summary["result"] == "nothing to tidy"
    assert summary["tidied"] == 0


def test_budget_stops_the_run_before_the_next_call(unit, world):
    with pytest.raises(tidy.BudgetExceeded):
        _run(unit, world, budget_usd=0.001)
    assert meta_client.read_spend_total(unit / "ledger.jsonl") < 0.05


def test_cap_refusal_is_not_swallowed_as_a_photo_failure(unit, world):
    (unit / "ledger.jsonl").write_text(json.dumps({"estimated_usd": 20.0, "actual_usd": 20.0}))
    (unit / "baseline.json").write_text(json.dumps({"meta": 20.0}))
    with pytest.raises(meta_client.CapReached):
        _run(unit, world)


def test_missing_curation_raises(unit, world):
    (unit / "curation.json").unlink()
    with pytest.raises(Exception, match="curation"):
        _run(unit, world)


def test_summary_spend_comes_from_the_ledger(unit, world):
    summary = _run(unit, world)
    assert summary["unit_meta_usd"] == pytest.approx(
        meta_client.read_spend_total(unit / "ledger.jsonl")
    )
    assert summary["unit_meta_usd"] < 5.0


def test_second_run_reuses_the_saved_findings_without_paying_again(unit, world):
    _run(unit, world)
    first = dict(world.calls)
    _run(unit, world)
    assert world.calls["damage"] == first["damage"]
    # Findings are reused. The re-check looks at the new fill, so it is never reused.
    assert world.calls["sam"] == first["sam"] + 1
    assert world.calls["confirm"] == first["confirm"]
    assert world.calls["edit"] == first["edit"] + 1


#: The list before the navigator took hoses off it. Findings saved under it are
#: on disk, and each photo's cost well over this unit's remaining budget to redo.
LIST_WITH_HOSE = (
    "trash bin",
    "cardboard box",
    "plastic bag",
    "packing material",
    "loose cable or cord",
    "hose",
    "laundry basket",
    "cleaning supplies",
    "shoes",
    "bucket",
    "ladder",
    "paint can",
    "tools",
)


def test_findings_saved_with_hoses_are_reused_and_the_hose_is_never_removed(
    unit, world, monkeypatch
):
    world.sam = {"cardboard box": [ITEM_BOX], "hose": [BIN_BOX]}
    with monkeypatch.context() as patch:
        patch.setattr(tidy, "CLUTTER_LIST", LIST_WITH_HOSE)
        _run(unit, world)
    damage_calls, sam_calls, confirm_calls = (
        world.calls["damage"],
        world.calls["sam"],
        world.calls["confirm"],
    )
    summary = _run(unit, world)
    photo = summary["photos"][0]
    assert world.calls["damage"] == damage_calls and world.calls["confirm"] == confirm_calls
    # Only the re-check of the one item still removed.
    assert world.calls["sam"] == sam_calls + 1
    assert [item["label"] for item in photo["removed"]] == ["cardboard box"]
    assert photo["recheck"]["items"] == [{"label": "cardboard box", "found_pixels": 0}]
    left, top, right, bottom = BIN_BOX
    assert not _mask(unit)[top:bottom, left:right].any()
    assert (_tidied(unit)[top:bottom, left:right] == _finished(unit)[top:bottom, left:right]).all()
    assert "hose" not in (unit / "tidy.html").read_text()


def test_findings_saved_under_any_other_list_are_not_reused(unit, world, monkeypatch):
    with monkeypatch.context() as patch:
        patch.setattr(tidy, "CLUTTER_LIST", ("cardboard box", "sofa"))
        _run(unit, world)
    damage_calls = world.calls["damage"]
    _run(unit, world)
    assert world.calls["damage"] == damage_calls + 5


def test_tidy_works_for_any_set_name(tmp_path, world):
    out = tmp_path / "whatever-set"
    (out / "finished").mkdir(parents=True)
    Image.fromarray(_photo()).save(out / "finished" / "009.jpg", quality=95)
    digest = hashlib.sha256((out / "finished" / "009.jpg").read_bytes()).hexdigest()
    (out / "curation.json").write_text(
        json.dumps(
            {
                "kept": [{"id": "009", "room": "kitchen"}],
                "dropped": [],
                "photos": {"009": digest},
                "cost": {"calls": 1, "usd": 0.01},
            }
        )
    )
    summary = _run(out, world)
    assert summary["photos"][0]["id"] == "009"


# --- the SAM re-check on the tidied photo


def test_recheck_finding_the_item_in_the_mask_ships_untidied_with_the_reason(unit, world):
    world.recheck = {"cardboard box": [(120, 120, 180, 180)]}
    summary = _run(unit, world)
    photo = summary["photos"][0]
    assert photo["status"] == "untidied"
    assert "SAM 3.1" in photo["reason"] and "cardboard box" in photo["reason"]
    assert photo["removed"] == []
    assert photo["not_removed"] == [{"label": "cardboard box", "reason": photo["reason"]}]
    assert photo["recheck"]["items"][0]["found_pixels"] == 3600
    assert summary["items_removed"] == 0 and summary["items_failed_recheck"] == 1
    assert not (unit / "tidy" / "001" / "tidied.png").exists()
    assert (unit / "tidy" / "001" / "rejected.png").exists()


def test_recheck_one_pixel_of_overlap_with_the_mask_still_fails(unit, world):
    # The grown mask ends a fixed margin past the item: touch its last column.
    margin = tidy.grow_px((H, W))
    right = ITEM_BOX[2] + margin - 1
    world.recheck = {"cardboard box": [(right, 150, right + 40, 151)]}
    photo = _run(unit, world)["photos"][0]
    assert photo["status"] == "untidied"
    assert photo["recheck"]["items"][0]["found_pixels"] == 1


def test_recheck_finding_something_outside_the_mask_does_not_count(unit, world):
    world.recheck = {"cardboard box": [BIN_BOX]}
    summary = _run(unit, world)
    photo = summary["photos"][0]
    assert photo["status"] == "tidied"
    assert [item["label"] for item in photo["removed"]] == ["cardboard box"]
    assert photo["recheck"]["items"][0]["found_pixels"] == 0
    assert summary["items_removed"] == 1 and summary["items_failed_recheck"] == 0


def test_recheck_looks_at_the_saved_tidied_pixels_not_the_finished_photo(unit, world):
    _run(unit, world)
    prompt, sent = world.recheck_seen[0]
    assert prompt == "cardboard box"
    expected = segment.jpeg_bytes(_tidied(unit))
    assert sent == "data:image/jpeg;base64," + base64.b64encode(expected).decode()


def test_recheck_that_cannot_run_ships_untidied(unit, world):
    world.recheck_error = "backend down"
    summary = _run(unit, world)
    photo = summary["photos"][0]
    assert photo["status"] == "untidied"
    assert "re-check" in photo["reason"]
    assert photo["removed"] == []
    assert summary["items_failed_recheck"] == 1


def test_recheck_runs_once_per_label_and_covers_every_removed_item(unit, world):
    world.sam = {"cardboard box": [ITEM_BOX, BIN_BOX]}
    photo = _run(unit, world)["photos"][0]
    assert [text for text, _ in world.recheck_seen] == ["cardboard box"]
    assert [item["label"] for item in photo["recheck"]["items"]] == ["cardboard box"] * 2


def test_failed_fill_lists_nothing_as_removed(unit, world):
    world.image_error = "backend down"
    photo = _run(unit, world)["photos"][0]
    assert photo["status"] == "untidied"
    assert photo["removed"] == []
    assert photo["not_removed"][0]["label"] == "cardboard box"


def test_page_never_lists_an_item_as_removed_when_the_recheck_failed(unit, world):
    world.recheck = {"cardboard box": [(120, 120, 180, 180)]}
    summary = _run(unit, world)
    html = (unit / "tidy.html").read_text()
    removed_block = html.split("<h3>Removed</h3>")[1].split("</ul>")[0]
    assert "cardboard box" not in removed_block and "none" in removed_block
    assert "Edited: clutter removed" not in html
    assert "Tried, not removed" in html and summary["photos"][0]["reason"] in html


def test_page_shows_the_recheck_result_on_a_tidied_photo(unit, world):
    _run(unit, world)
    assert "SAM 3.1 re-check: pass" in (unit / "tidy.html").read_text()


# --- the page


def test_page_has_slider_flash_lists_and_label_for_a_tidied_photo(unit, world):
    world.damage = [{"box": [700, 500, 800, 600], "note": "<b>water</b> stain"}]
    summary = _run(unit, world)
    html = (unit / "tidy.html").read_text()
    assert summary["tidied"] == 1
    assert html.count("Edited: clutter removed") == 1
    assert 'type="range"' in html
    assert "flashMask" in html and "1000" in html
    assert "cardboard box" in html
    assert "tidy/001/before.jpg" in html and "tidy/001/after.jpg" in html
    assert "tidy/001/mask_overlay.png" in html
    assert "tidy/001/damage_1.jpg" in html
    assert "&lt;b&gt;water&lt;/b&gt; stain" in html and "<b>water</b>" not in html
    assert "the box is gone" in html
    assert "finished/001.jpg" in html
    for name in ("before.jpg", "after.jpg", "mask_overlay.png"):
        assert (unit / "tidy" / "001" / name).exists()


def test_page_shows_no_edit_label_when_a_photo_shipped_untidied(unit, world):
    world.image_error = "backend down"
    _run(unit, world)
    html = (unit / "tidy.html").read_text()
    assert "Edited: clutter removed" not in html
    assert "Muse Image" in html


def test_page_says_nothing_to_tidy(unit, world):
    world.sam = {}
    _run(unit, world)
    assert "nothing to tidy" in (unit / "tidy.html").read_text().lower()


def test_page_paths_stay_relative(unit, world):
    _run(unit, world)
    html = (unit / "tidy.html").read_text()
    assert str(unit) not in html


# --- review of 4658909, finding 1: home-a 003's candidate 0, a red cup and a black
# object at the dish rack under one mask, labeled "cleaning supplies"

CUP_MASK_BOX = (300, 200, 400, 320)


def _cup_world(world, verdict):
    world.sam = {"cleaning supplies": [CUP_MASK_BOX]}
    world.confirm["cleaning supplies"] = {**GOOD_CONFIRM, **verdict}
    return world


def test_item_spark_names_as_something_off_the_list_is_rejected(unit, world):
    # The old prompt told Spark the label and it agreed. "is_that_item" stays
    # true here, so only the blind answer can stop it.
    _cup_world(world, {"kind": "none", "objects": ["a red dotted cup"], "reason": "a drinking cup"})
    photo = _run(unit, world)["photos"][0]
    assert photo["removed"] == [] and world.calls["edit"] == 0
    assert photo["status"] == "nothing to tidy"
    assert photo["rejected"] == [
        {
            "label": "cleaning supplies",
            "reason": "Muse Spark did not name it cleaning supplies: a drinking cup",
        }
    ]


def test_item_spark_names_as_another_list_kind_is_rejected(unit, world):
    _cup_world(world, {"kind": "bucket", "reason": "a small bucket"})
    photo = _run(unit, world)["photos"][0]
    assert photo["removed"] == [] and world.calls["edit"] == 0
    assert "did not name it cleaning supplies" in photo["rejected"][0]["reason"]


def test_mask_spanning_a_second_object_is_rejected(unit, world):
    _cup_world(
        world,
        {
            "kind": "cleaning supplies",
            "objects": ["a red dotted bottle", "a black object at the dish rack"],
            "reason": "bottle by the sink",
        },
    )
    photo = _run(unit, world)["photos"][0]
    assert photo["removed"] == [] and world.calls["edit"] == 0
    assert photo["rejected"][0]["reason"] == (
        "the outline covers more than one object: "
        "a red dotted bottle, a black object at the dish rack"
    )


@pytest.mark.parametrize(
    "gap",
    [{"kind": None}, {"kind": "a sofa"}, {"objects": None}, {"objects": []}, {"objects": "one"}],
)
def test_confirm_with_no_usable_name_or_object_list_never_removes(unit, world, gap):
    _cup_world(world, gap)
    photo = _run(unit, world)["photos"][0]
    assert photo["removed"] == [] and world.calls["edit"] == 0
    assert photo["rejected"][0]["reason"]


def test_spark_is_not_told_the_finders_label(unit, world):
    _cup_world(world, {"kind": "cleaning supplies"})
    _run(unit, world)
    text = world.confirm_texts[0]
    assert '"cleaning supplies"' not in text and "finder" not in text.lower()
    for kind in tidy.CLUTTER_LIST:
        assert kind in text


def test_spark_sees_the_outline_of_the_mask_not_only_a_box(unit, world, monkeypatch):
    world.sam = {"cardboard box": [ITEM_BOX]}
    disc = np.zeros((H, W), np.uint8)
    cv2.circle(disc, (150, 150), 40, 1, -1)

    def lane(text, frame_w, frame_h):
        return [
            {"object_id": i, "box": tuple(b), "mask": disc.astype(bool)}
            for i, b in enumerate(json.loads(text))
        ]

    monkeypatch.setattr(segment, "parse_lane", lane)
    _run(unit, world)
    url = world.confirm_images[0][0]["image_url"]
    with Image.open(io.BytesIO(base64.b64decode(url.split(",", 1)[1]))) as handle:
        sent = np.asarray(handle.convert("RGB")).astype(int)
    # The disc's left edge, far from the box's own lines.
    r, g, b = sent[150, 110]
    assert r > 180 and g < 90 and b < 90


#: Word for word what findings on disk were confirmed with before this review.
OLD_CONFIRM_PROMPT = (
    "A red box marks a candidate for removal from a rental listing photo. It may be "
    "removed only if a person could carry it out in a day and it is not part of the "
    "property. Reject anything that is a fixture, part of the building, wired or "
    "plumbed in, furniture or an appliance that conveys with the unit, or damage. "
    "Say whether it truly is the kind of item the finder named. Say whether it is "
    "attached at either end: a cord plugged into an outlet or a device, a blind's "
    "pull cord, a hose on a spigot. Attached things stay. Reply with JSON only: "
    '{"confirm": true or false, "is_that_item": true or false, '
    '"attached": true or false, "reason": "plain words"}.'
)


def test_findings_saved_under_the_old_confirm_are_confirmed_again_without_a_new_scan(
    unit, world, monkeypatch
):
    with monkeypatch.context() as patch:
        patch.setattr(tidy, "CONFIRM_PROMPT", OLD_CONFIRM_PROMPT)
        _run(unit, world)
    before = dict(world.calls)
    world.confirm["cardboard box"] = {"kind": "none", "reason": "a drinking cup"}
    world.calls["confirm"] = 0
    photo = _run(unit, world)["photos"][0]
    assert world.calls["damage"] == before["damage"]
    # One scan's worth of SAM calls would be the whole list again.
    assert world.calls["sam"] == before["sam"]
    assert world.calls["confirm"] == 1
    assert photo["removed"] == []
    # Saved under the new prompt now, so a third run does not pay again.
    world.calls["confirm"] = 0
    _run(unit, world)
    assert world.calls["confirm"] == 0


def test_confirm_reply_cut_off_once_is_asked_again(unit, world):
    world.confirm_errors = 1
    photo = _run(unit, world)["photos"][0]
    assert world.calls["confirm"] == 2
    assert [item["label"] for item in photo["removed"]] == ["cardboard box"]


def test_confirm_with_no_verdict_stays_and_is_asked_again_on_the_next_run(unit, world):
    # Live on home-a, a cut-off reply was saved as a rejection: safe, but no one
    # had judged the item, and a rerun would have kept that answer forever.
    world.confirm_errors = 2
    photo = _run(unit, world)["photos"][0]
    assert photo["removed"] == [] and world.calls["edit"] == 0
    assert "verdict failed" in photo["rejected"][0]["reason"]
    sam_calls = world.calls["sam"]
    photo = _run(unit, world)["photos"][0]
    assert world.calls["confirm"] == 3
    assert world.calls["sam"] == sam_calls + 1  # the re-check of the fill, no new scan
    assert [item["label"] for item in photo["removed"]] == ["cardboard box"]


def test_confirm_has_room_to_answer(unit, world):
    _run(unit, world)
    assert world.confirm_tokens == [tidy.CONFIRM_MAX_TOKENS] and tidy.CONFIRM_MAX_TOKENS > 4096


# --- review of 4658909, findings 2 and 3: a measured check of the fill

WALL_W, WALL_H = 1000, 700
WALL_ITEM = (300, 200, 560, 430)
FILL_REASON = "fill did not match the surrounding surface"


def _wall():
    # A clean wall with a slow light falloff, and one dark item on it.
    yy, xx = np.mgrid[0:WALL_H, 0:WALL_W].astype(float)
    gray = 196 - xx * 0.006 - yy * 0.004
    rgb = np.clip(np.stack([gray, gray - 6, gray - 16], axis=2), 0, 255).round().astype(np.uint8)
    left, top, right, bottom = WALL_ITEM
    rgb[top:bottom, left:right] = (12, 12, 12)
    return rgb


@pytest.fixture
def wall_unit(tmp_path):
    out = tmp_path / "wall"
    (out / "finished").mkdir(parents=True)
    Image.fromarray(_wall()).save(out / "finished" / "001.jpg", quality=98)
    digest = hashlib.sha256((out / "finished" / "001.jpg").read_bytes()).hexdigest()
    (out / "curation.json").write_text(
        json.dumps(
            {
                "kept": [{"id": "001", "room": "bedroom"}],
                "dropped": [],
                "photos": {"001": digest},
                "cost": {"calls": 1, "usd": 0.01},
            }
        )
    )
    return out


def _wall_world(world):
    world.sam = {"laundry basket": [WALL_ITEM]}
    return world


def _flat_fill(sent, painted):
    # The ring's own colour, so the seamless clone has nothing to fix.
    ys, xs = np.nonzero(painted)
    out = sent.copy()
    edge = cv2.dilate(painted.astype(np.uint8), np.ones((15, 15), np.uint8)).astype(bool) & ~painted
    out[painted] = np.median(sent[edge], axis=0).round().astype(np.uint8)
    return out, ys, xs


def _soft_spot(sent, ys, xs, amount):
    """A soft patch over most of the fill, as on home-a 008's wall."""
    cy, cx = ys.mean(), xs.mean()
    yy, xx = np.mgrid[0 : sent.shape[0], 0 : sent.shape[1]].astype(float)
    return amount * np.exp(-(((yy - cy) / 90) ** 2 + ((xx - cx) / 110) ** 2) / 2)


def _cloud(levels):
    def paint(attempt, sent, painted):
        out, ys, xs = _flat_fill(sent, painted)
        dip = _soft_spot(sent, ys, xs, levels)[..., None]
        out = np.where(painted[..., None], np.clip(out.astype(float) - dip, 0, 255), out)
        return out.round().astype(np.uint8)

    return paint


def _good_fill(attempt, sent, painted):
    return _flat_fill(sent, painted)[0]


def _specks(attempt, sent, painted):
    out, ys, xs = _flat_fill(sent, painted)
    cy, cx = int(ys.mean()), int(xs.mean())
    for dy, dx in ((-60, -70), (40, -30), (10, 60), (-40, 90)):
        out[cy + dy - 2 : cy + dy + 3, cx + dx - 2 : cx + dx + 3] = (230, 120, 60)
    return out


@pytest.mark.parametrize("levels", [5, 8, 10])
def test_gray_cloud_on_a_clean_wall_ships_untidied_after_one_retry(wall_unit, world, levels):
    _wall_world(world).edit_paint = _cloud(levels)
    photo = _run(wall_unit, world)["photos"][0]
    assert world.calls["edit"] == 2
    assert photo["status"] == "untidied"
    assert photo["reason"] == FILL_REASON
    assert photo["removed"] == []
    assert photo["not_removed"] == [{"label": "laundry basket", "reason": FILL_REASON}]
    assert not (wall_unit / "tidy" / "001" / "tidied.png").exists()
    assert (wall_unit / "tidy" / "001" / "rejected.png").exists()
    # Nothing is paid for on a fill the measurement already failed.
    assert world.calls["selfcheck"] == 0


def test_cloud_on_the_first_try_and_a_clean_fill_on_the_retry_ships_tidied(wall_unit, world):
    cloud = _cloud(10)
    _wall_world(world).edit_paint = lambda a, s, p: (
        cloud(a, s, p) if a == 1 else _good_fill(a, s, p)
    )
    photo = _run(wall_unit, world)["photos"][0]
    assert world.calls["edit"] == 2
    assert photo["status"] == "tidied"
    assert [i["label"] for i in photo["removed"]] == ["laundry basket"]


def test_clean_fill_ships_tidied_on_the_first_try(wall_unit, world):
    _wall_world(world).edit_paint = _good_fill
    photo = _run(wall_unit, world)["photos"][0]
    assert world.calls["edit"] == 1
    assert photo["status"] == "tidied"


def test_colour_cast_on_a_clean_wall_ships_untidied(wall_unit, world):
    def cast(attempt, sent, painted):
        out, ys, xs = _flat_fill(sent, painted)
        tint = _soft_spot(sent, ys, xs, 16)
        shifted = out.astype(float)
        shifted[..., 2] = np.where(painted, shifted[..., 2] + tint, shifted[..., 2])
        return np.clip(shifted, 0, 255).round().astype(np.uint8)

    _wall_world(world).edit_paint = cast
    photo = _run(wall_unit, world)["photos"][0]
    assert photo["status"] == "untidied" and photo["reason"] == FILL_REASON


def test_orange_specks_the_wall_does_not_have_ship_untidied(wall_unit, world):
    _wall_world(world).edit_paint = _specks
    photo = _run(wall_unit, world)["photos"][0]
    assert world.calls["edit"] == 2
    assert photo["status"] == "untidied" and photo["reason"] == FILL_REASON
    assert photo["fill_check"]["specks"] >= 1


def test_every_measured_photo_records_its_fill_readings_and_the_page_shows_them(wall_unit, world):
    _wall_world(world).edit_paint = _good_fill
    summary = _run(wall_unit, world)
    check = summary["photos"][0]["fill_check"]
    assert check["pass"] is True and check["flat_surfaces"] >= 1
    assert check["worst_reading"] <= check["worst_limit"]
    page = (wall_unit / "tidy.html").read_text()
    assert "Fill check" in page and f"{check['worst_reading']:.1f}" in page


def test_page_gives_the_fill_reason_when_the_fill_check_fails(wall_unit, world):
    _wall_world(world).edit_paint = _cloud(10)
    _run(wall_unit, world)
    page = (wall_unit / "tidy.html").read_text()
    assert FILL_REASON in page and "Edited: clutter removed" not in page


EVIDENCE = Path(__file__).resolve().parent.parent / ".navigator/evidence/tidy-4658909/home-a/tidy"
FINISHED = Path(__file__).resolve().parent.parent / "output/home-a/finished"
needs_evidence = pytest.mark.skipif(
    not (EVIDENCE / "008" / "tidied.png").exists() or not FINISHED.exists(),
    reason="the reviewed home-a fills are local only",
)


def _saved(pid):
    def rgb(path):
        with Image.open(path) as handle:
            return np.asarray(handle.convert("RGB"))

    with Image.open(EVIDENCE / pid / "mask.png") as handle:
        mask = np.asarray(handle.convert("L")) > 0
    return rgb(FINISHED / f"{pid}.jpg"), rgb(EVIDENCE / pid / "tidied.png"), mask


@needs_evidence
def test_the_real_home_a_008_cloud_fails_the_fill_check():
    from listing_partner import fill_check

    reading = fill_check.check_fill(*_saved("008"))
    assert reading["pass"] is False and reading["worst_reading"] > reading["worst_limit"]


@needs_evidence
def test_the_real_home_a_003_speck_fails_the_fill_check():
    from listing_partner import fill_check

    reading = fill_check.check_fill(*_saved("003"))
    assert reading["pass"] is False and reading["specks"] >= 1


# --- review of 4658909, navigator note: hoses are off the public lists


@pytest.mark.parametrize("name", ["PRODUCT.md", "docs/build-plan.md"])
def test_public_docs_no_longer_list_hoses_as_a_tidy_target(name):
    root = Path(__file__).resolve().parent.parent
    assert not re.search(r"\bhoses?\b", (root / name).read_text(), re.IGNORECASE)
