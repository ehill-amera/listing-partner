"""End to end on the sample facts: real clients and real ledgers in a temp
folder, a fake far side for both providers, generated photos."""

import json
import re

import numpy as np
import pytest
from PIL import Image

from listing_partner import baseten_client, curate, meta_client
from listing_partner.facts import SAMPLE_FACTS_PATH
from listing_partner.run_listing import BudgetExceeded, ledger_by_model, run_listing

ROOMS = ["front exterior", "kitchen", "living room", "bedroom", "bedroom", "bathroom", "kitchen"]
DESC = "Bright 2 bedroom home with hardwood floors. <script>alert(1)</script> " + "nice " * 120


def _meta(url, headers, body):
    data = json.loads(body)
    inp = data["input"]
    if isinstance(inp, str):
        text = _write_reply(inp)
    else:
        prompt = inp[0]["content"][0]["text"]
        if prompt.startswith("Numbered tiles"):
            text = json.dumps(
                {
                    "duplicates": [{"keep": "002", "drop": "007", "reason": "same view"}],
                    "order": ["002", "003", "001", "004", "005", "006"],
                }
            )
        else:
            _meta.n += 1
            text = json.dumps(
                {
                    "room": ROOMS[_meta.n - 1],
                    "sharpness": 4,
                    "framing": 4,
                    "note": f"visual note {_meta.n} here",
                }
            )
    return {"id": "m", "text": text, "usage": {"input_tokens": 100, "output_tokens": 100}}


def _write_reply(prompt):
    if prompt.startswith("REVIEW"):
        return "PASS"
    if prompt.startswith("CAPTIONS"):
        return json.dumps({"instagram_facebook": "Bright home #home", "video": "Bright home"})
    return DESC


def _baseten(url, headers, body):
    prompt = json.loads(body)["messages"][0]["content"]
    assert "data:image" not in body.decode(), "Muse Spark Open gets text only"
    return {
        "id": "b",
        "choices": [{"finish_reason": "stop", "message": {"content": _write_reply(prompt)}}],
        "usage": {"prompt_tokens": 100, "completion_tokens": 100},
    }


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("META_API_KEY", "test-not-real")
    monkeypatch.setenv("BASETEN_API_KEY", "test-not-real")
    _meta.n = 0
    out = tmp_path / "output" / "unit-x"
    (out / "finished").mkdir(parents=True)
    for i in range(7):
        rgb = np.full((60, 90, 3), 20 * i, dtype=np.uint8)
        Image.fromarray(rgb).save(out / "finished" / f"{i + 1:03d}.jpg")
    return {
        "output_dir": out,
        "facts_path": SAMPLE_FACTS_PATH,
        "meta_ledger": tmp_path / "m.jsonl",
        "baseten_ledger": tmp_path / "b.jsonl",
        "meta_transport": _meta,
        "baseten_transport": _baseten,
        "mls_positions": {"001": 1, "002": 2, "003": 3, "004": 4, "005": 5, "007": 6},
    }


def test_whole_run_on_the_sample(env):
    s = run_listing(**env)
    assert s["kept"] + s["dropped"] == 7
    page = (env["output_dir"] / "listing.html").read_text()
    assert "<script>alert(1)</script>" not in page and "&lt;script&gt;" in page
    assert 'src="finished/002.jpg"' in page and "same view" in page
    assert "Sample data" in page
    assert "Muse Spark Open" in page and "SAM 3.1" in page
    log = (env["output_dir"] / "writing" / "log.jsonl").read_text().splitlines()
    assert len(log) == s["writing_calls"] > 0
    assert {json.loads(x)["provider"] for x in log} == {"meta", "baseten"}
    assert s["benchmark"]["we_dropped_he_kept"] == ["007"]
    assert s["costs"]["meta"]["muse-spark-1.3"]["usd"] > 0
    assert s["costs"]["baseten"][baseten_client.MODEL]["usd"] > 0
    assert s["costs"]["meta"]["sam-3.1"]["usd"] == 0


def test_page_labels_models_a_b_with_names_behind_the_toggle(env):
    run_listing(**env)
    page = (env["output_dir"] / "listing.html").read_text()
    assert re.search(r"show which model", page)
    assert 'class="who"' in page and ".who{display:none}" in page.replace(" ", "")


def test_facts_with_extra_field_stop_the_run_before_any_call(env, tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text(SAMPLE_FACTS_PATH.read_text().replace('"unit"', '"tenant": "x", "unit"'))
    env["facts_path"] = bad
    with pytest.raises(ValueError):
        run_listing(**env)
    assert not env["meta_ledger"].exists()


def test_missing_facts_file_stops_the_run(env, tmp_path):
    env["facts_path"] = tmp_path / "none.json"
    with pytest.raises(ValueError):
        run_listing(**env)
    assert not env["meta_ledger"].exists()


def test_meta_unit_budget_refuses_before_the_call(env):
    env["meta_budget_usd"] = 0.0
    with pytest.raises(BudgetExceeded):
        run_listing(**env)
    assert not env["meta_ledger"].exists()


def test_baseten_unit_budget_counts_earlier_runs(env):
    run_listing(**env)
    first = baseten_client.read_spend_total(env["baseten_ledger"])
    _meta.n = 0
    env["baseten_budget_usd"] = first + 1e-9
    with pytest.raises(BudgetExceeded):
        run_listing(**env)


def test_ledger_by_model_scopes_to_the_run_and_counts_open_reservations(tmp_path):
    p = tmp_path / "l.jsonl"
    rows = [
        {"ts": "2026-01-01", "model": "a", "call_id": "1", "estimated_usd": 1, "actual_usd": None},
        {"ts": "2026-01-01", "model": "a", "call_id": "1", "estimated_usd": 1, "actual_usd": 0.5},
        {"ts": "2026-02-01", "model": "a", "call_id": "2", "estimated_usd": 1, "actual_usd": None},
        {"ts": "2026-02-01", "model": "a", "call_id": "2", "estimated_usd": 1, "actual_usd": 0.5},
        {"ts": "2026-02-02", "model": "b", "call_id": "3", "estimated_usd": 2, "actual_usd": None},
    ]
    p.write_text("\n".join(json.dumps(r) for r in rows))
    got = ledger_by_model(p, "2026-02-01")
    assert got == {"a": {"usd": 0.5, "calls": 1}, "b": {"usd": 2.0, "calls": 1}}


def test_ledger_by_model_refuses_a_corrupt_ledger(tmp_path):
    p = tmp_path / "l.jsonl"
    p.write_text("{nope\n")
    with pytest.raises(meta_client.LedgerError):
        ledger_by_model(p, "2026")


def test_ordering_call_gets_room_to_think_after_a_live_cutoff(env):
    seen = {}

    def spy(url, headers, body):
        data = json.loads(body)
        if not isinstance(data["input"], str):
            prompt = data["input"][0]["content"][0]["text"]
            if prompt.startswith("Numbered tiles"):
                seen["limit"] = data["max_output_tokens"]
        return _meta(url, headers, body)

    env["meta_transport"] = spy
    run_listing(**env)
    assert seen["limit"] >= 16000


def test_reuse_makes_no_curation_calls_and_keeps_the_saved_result(env):
    first = run_listing(**env)
    saved = json.loads((env["output_dir"] / "curation.json").read_text())
    seen = []

    def counting(url, headers, body):
        seen.append(isinstance(json.loads(body)["input"], str))
        return _meta(url, headers, body)

    env["meta_transport"] = counting
    second = run_listing(**env, reuse_curation=True)
    assert seen and all(seen), "a photo went to the model during a reuse run"
    assert second["kept_order"] == first["kept_order"]
    assert second["curation_source"] == "saved"
    assert first["curation_source"] == "fresh"
    assert json.loads((env["output_dir"] / "curation.json").read_text())["kept"] == saved["kept"]


def test_reuse_counts_the_saved_curation_cost_in_the_listing_total(env):
    run_listing(**env)
    saved = json.loads((env["output_dir"] / "curation.json").read_text())["cost"]
    assert saved["calls"] == 8 and saved["usd"] > 0
    summary = run_listing(**env, reuse_curation=True)
    assert summary["costs"]["curation_saved"] == saved
    page = (env["output_dir"] / "listing.html").read_text()
    assert "saved curation" in page.lower()
    spark = summary["costs"]["meta"]["muse-spark-1.3"]["usd"]
    base = summary["costs"]["baseten"][baseten_client.MODEL]["usd"]
    assert f"${spark + base + saved['usd']:.4f}" in page


def test_reuse_refuses_when_a_photo_changed(env):
    run_listing(**env)
    Image.fromarray(np.full((60, 90, 3), 99, dtype=np.uint8)).save(
        env["output_dir"] / "finished" / "001.jpg"
    )
    with pytest.raises(curate.SavedCurationInvalid):
        run_listing(**env, reuse_curation=True)


def test_reuse_refuses_when_a_photo_is_added(env):
    run_listing(**env)
    Image.fromarray(np.zeros((60, 90, 3), dtype=np.uint8)).save(
        env["output_dir"] / "finished" / "008.jpg"
    )
    with pytest.raises(curate.SavedCurationInvalid):
        run_listing(**env, reuse_curation=True)


def test_reuse_refuses_when_nothing_is_saved(env):
    with pytest.raises(curate.SavedCurationInvalid):
        run_listing(**env, reuse_curation=True)


def test_both_models_get_muse_sparks_notes_and_the_new_description_rules(env):
    seen = {"meta": [], "baseten": []}

    def meta_spy(url, headers, body):
        inp = json.loads(body)["input"]
        if isinstance(inp, str):
            seen["meta"].append(inp)
        return _meta(url, headers, body)

    def baseten_spy(url, headers, body):
        seen["baseten"].append(json.loads(body)["messages"][0]["content"])
        return _baseten(url, headers, body)

    env["meta_transport"], env["baseten_transport"] = meta_spy, baseten_spy
    run_listing(**env)
    for kind in ("DESCRIPTION", "CAPTIONS"):
        a = [p for p in seen["meta"] if p.startswith(kind)]
        b = [p for p in seen["baseten"] if p.startswith(kind)]
        assert len(a) == 1 and a == b
        # Kept shots' notes go to both models. Photo 7 was dropped as a duplicate.
        for n in range(1, 7):
            assert f"visual note {n} here" in a[0]
        assert "visual note 7 here" not in a[0]
    prompt = next(p for p in seen["baseten"] if p.startswith("DESCRIPTION"))
    assert "90 to 200 words" in prompt and "120" not in prompt
    assert "State each fact once" in prompt
    assert "Then describe the rooms" in prompt
