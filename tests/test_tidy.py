"""Unit 4: the honest tidy. Model far side faked at the transport, no network."""

import base64
import hashlib
import io
import json

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


class World:
    """The far side of the capped client: Spark, SAM and Muse Image."""

    def __init__(self):
        self.sam = {"cardboard box": [ITEM_BOX]}
        self.damage = []
        self.damage_reply = None
        self.confirm = {}
        self.selfcheck = {
            "item_gone": True,
            "property_changed": False,
            "damage_softened": False,
            "reason": "the box is gone and the wall is the same",
        }
        self.image_error = None
        self.edit_shift = 0
        self.edit_size = None
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
            reply = json.dumps(self.sam.get(text, []))
        elif text.startswith(tidy.DAMAGE_PROMPT[:40]):
            self.calls["damage"] += 1
            first = self.calls["damage"] % 5 == 1
            reply = self.damage_reply
            if reply is None:
                reply = json.dumps({"damage": self.damage if first else []})
        elif text.startswith(tidy.CONFIRM_PROMPT[:40]):
            self.calls["confirm"] += 1
            label = next(x for x in tidy.CLUTTER_LIST if f'"{x}"' in text)
            reply = json.dumps(self.confirm.get(label, {"confirm": True, "reason": "loose item"}))
        elif text.startswith(tidy.SELFCHECK_PROMPT[:40]):
            self.calls["selfcheck"] += 1
            reply = json.dumps(self.selfcheck)
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
        "hose",
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
    assert tuple(seen) == tidy.CLUTTER_LIST


def test_build_mask_refuses_a_label_off_the_list():
    item = {"label": "sofa", "mask": _rect(ITEM_BOX), "reason": "r"}
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
    item = {"label": "hose", "mask": _rect(ITEM_BOX), "reason": "r"}
    final, removed, left = tidy.build_final_mask([item], [], (H, W))
    margin = tidy.grow_px((H, W))
    assert final[100, 100 - margin] and not final[100, 100 - margin - 2]
    assert [r["label"] for r in removed] == ["hose"] and left == []


def test_candidate_whose_own_mask_touches_damage_is_left_in_place():
    item = {"label": "hose", "mask": _rect(ITEM_BOX), "reason": "r"}
    damage = [{"box": (190, 190, 260, 260), "note": "crack"}]
    final, removed, left = tidy.build_final_mask([item], damage, (H, W))
    assert not final.any() and removed == []
    assert left == [{"label": "hose", "reason": "left in place: overlaps damage"}]


def test_grown_margin_touching_damage_is_cut_and_the_item_still_goes():
    item = {"label": "hose", "mask": _rect(ITEM_BOX), "reason": "r"}
    damage = [{"box": (201, 100, 260, 200), "note": "crack"}]
    final, removed, left = tidy.build_final_mask([item], damage, (H, W))
    assert [r["label"] for r in removed] == ["hose"] and left == []
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


@pytest.mark.parametrize(
    ("pixels_ok", "spark_ok", "ships"),
    [(True, True, "tidied"), (True, False, "untidied"), (False, True, "untidied")],
)
def test_ship_decision_needs_both_to_pass(pixels_ok, spark_ok, ships):
    assert tidy.ship_decision(pixels_ok, spark_ok)[0] == ships


def test_ship_decision_names_a_disagreement():
    assert "disagree" in tidy.ship_decision(True, False)[1]
    assert "disagree" in tidy.ship_decision(False, True)[1]


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


@pytest.mark.parametrize("verdict", [{"confirm": True}, {"confirm": True, "reason": " "}, {}])
def test_confirm_without_a_reason_never_removes(unit, world, verdict):
    world.confirm["cardboard box"] = verdict
    photo = _run(unit, world)["photos"][0]
    assert photo["status"] == "nothing to tidy"
    assert photo["removed"] == []
    assert photo["rejected"][0]["reason"]


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
    assert world.calls["sam"] == first["sam"]
    assert world.calls["confirm"] == first["confirm"]
    assert world.calls["edit"] == first["edit"] + 1


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
