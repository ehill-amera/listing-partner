"""Scoring again from a saved log: same answers as the run, no model call."""

import hashlib
import json
import subprocess
import sys

import pytest
from test_reply_format import PLAIN_DESC, PLAIN_SOCIAL, SAMPLE_INNER, SAMPLE_WRAPPED, Fake
from test_run_listing import env  # noqa: F401

from listing_partner.facts import SAMPLE_FACTS_PATH, load_facts
from listing_partner.rescore import SavedLogInvalid, rescore, rescore_log
from listing_partner.run_listing import run_listing
from listing_partner.writing import prompt_hash, review_prompt, run_writing

PHOTOS = [{"room": "kitchen", "note": "bright clean kitchen"}]


@pytest.fixture()
def facts():
    return load_facts(SAMPLE_FACTS_PATH)


def _live(facts, **kw):
    models = {"meta": Fake("meta"), "baseten": Fake("baseten", **kw)}
    log = []
    out = run_writing(facts, PHOTOS, models, log.append)
    return out, json.loads(json.dumps(log))


def _as_saved_before_the_fix(rows):
    """What the old run logged: its two reviews read the caption with the wrapper on."""
    for row in rows:
        if (row["job"], row["text_id"], row["attempt"]) == ("review", "caption_video", 1):
            row["prompt_hash"] = prompt_hash(review_prompt(SAMPLE_WRAPPED))
    return rows


def test_a_saved_log_gives_the_same_answers_as_the_run_that_wrote_it(facts):
    out, rows = _live(facts, caps="", video="Bright home", social=PLAIN_SOCIAL)
    again = rescore_log(rows, facts)
    assert again["picks"] == out["picks"]
    for a, b in zip(out["texts"], again["texts"]):
        assert (a["id"], a["provider"], a["final"], a["status"]) == (
            b["id"],
            b["provider"],
            b["final"],
            b["status"],
        )
        assert [x["failures"] for x in a["attempts"]] == [x["failures"] for x in b["attempts"]]
        assert [x["reviews"] for x in a["attempts"]] == [x["reviews"] for x in b["attempts"]]


def test_the_wrapped_caption_is_unwrapped_and_only_it_is_marked(facts):
    _, rows = _live(facts, caps="", video=SAMPLE_WRAPPED)
    result = rescore_log(_as_saved_before_the_fix(rows), facts)
    marked = [t for t in result["texts"] if t["attempts"][-1]["reviewed_with_wrapper"]]
    assert [(t["id"], t["provider"]) for t in marked] == [("caption_video", "baseten")]
    assert marked[0]["final"] == SAMPLE_INNER
    assert marked[0]["status"] == "pass"
    desc = next(t for t in result["texts"] if t["id"] == "description")
    assert desc["final"] == PLAIN_DESC


def test_a_saved_wrapped_text_that_stays_bad_still_fails(facts):
    _, rows = _live(facts, caps="", video="Bright <b>home</b>")
    result = rescore_log(rows, facts)
    text = next(
        t for t in result["texts"] if (t["id"], t["provider"]) == ("caption_video", "baseten")
    )
    assert text["status"] == "failed"


def test_a_review_of_some_other_text_refuses(facts):
    _, rows = _live(facts)
    next(r for r in rows if r["job"] == "review")["prompt_hash"] = "0" * 16
    with pytest.raises(SavedLogInvalid, match="different text"):
        rescore_log(rows, facts)


def test_a_missing_review_refuses(facts):
    _, rows = _live(facts)
    rows.remove(next(r for r in rows if r["job"] == "review"))
    with pytest.raises(SavedLogInvalid, match="both reviews"):
        rescore_log(rows, facts)


def test_a_missing_text_refuses(facts):
    _, rows = _live(facts)
    kept = [r for r in rows if not (r["job"] == "description" and r["provider"] == "baseten")]
    with pytest.raises(SavedLogInvalid, match="no baseten/description"):
        rescore_log(kept, facts)


def test_a_verdict_that_does_not_match_its_reply_refuses(facts):
    _, rows = _live(facts)
    review = next(r for r in rows if r["job"] == "review")
    review["verdicts"][review["provider"]] = "fail"
    with pytest.raises(SavedLogInvalid, match="does not match"):
        rescore_log(rows, facts)


def test_rescoring_imports_no_client_and_no_http():
    code = (
        "import sys, listing_partner.rescore\n"
        "bad = {'listing_partner.meta_client', 'listing_partner.baseten_client', "
        "'urllib.request', 'requests', 'httpx', 'http.client'} & set(sys.modules)\n"
        "sys.exit(repr(bad) if bad else 0)"
    )
    done = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert done.returncode == 0, done.stderr


def test_a_whole_rescore_changes_the_page_and_summary_and_never_the_log_or_ledgers(env):  # noqa: F811
    run_listing(**env)
    out = env["output_dir"]
    watched = [out / "writing" / "log.jsonl", env["meta_ledger"], env["baseten_ledger"]]
    before = [hashlib.sha256(p.read_bytes()).hexdigest() for p in watched]
    (out / "listing.html").write_text("old page")
    summary = rescore(output_dir=out, facts_path=env["facts_path"])
    assert [hashlib.sha256(p.read_bytes()).hexdigest() for p in watched] == before
    page = (out / "listing.html").read_text()
    assert "Listing package" in page and "with no model call" in page
    assert summary["rescored"]["model_calls"] == 0
    assert summary["rescored"]["log_sha256"] == before[0]
    assert json.loads((out / "listing_summary.json").read_text())["rescored"]


def test_the_page_says_when_the_reviews_read_the_wrapper(env):  # noqa: F811
    run_listing(**env)
    out = env["output_dir"]
    path = out / "writing" / "log.jsonl"
    rows = [json.loads(x) for x in path.read_text().splitlines()]
    for row in rows:
        if row["job"] == "captions" and row["text_id"] == "captions":
            pair = json.loads(row["output"])
            pair["video"] = SAMPLE_WRAPPED
            row["output"] = json.dumps(pair)
        if (row["job"], row["text_id"]) == ("review", "caption_video"):
            row["prompt_hash"] = prompt_hash(review_prompt(SAMPLE_WRAPPED))
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))
    rescore(output_dir=out, facts_path=env["facts_path"])
    page = (out / "listing.html").read_text()
    assert "read this text with its wrapper still on" in page
    assert "{&quot;text&quot;" not in page.split("Known limits")[0].split("First version")[0]
