"""The writing flow against fake far-side models. The checks are real."""

import json

import pytest

from listing_partner.facts import SAMPLE_FACTS_PATH, load_facts
from listing_partner.writing import choose, run_writing

GOOD_DESC = "Bright 2 bedroom home with hardwood floors and central air. " + " ".join(
    ["nice"] * 120
)
GOOD_CAPS = json.dumps(
    {"instagram_facebook": "Bright home, 2 bedrooms #home", "video": "Bright home"}
)


class Fake:
    """A model: answers by prompt kind, records what it was sent."""

    def __init__(self, name, desc=GOOD_DESC, caps=GOOD_CAPS, review="PASS", rewrite=None):
        self.name, self.model, self.prompts = name, f"model-{name}", []
        self.desc, self.caps, self.review, self.rewrite = desc, caps, review, rewrite

    def __call__(self, prompt, max_tokens):
        self.prompts.append(prompt)
        if prompt.startswith("REVIEW"):
            text = self.review(prompt) if callable(self.review) else self.review
        elif prompt.startswith("REWRITE"):
            text = self.rewrite or GOOD_DESC
        elif prompt.startswith("CAPTIONS"):
            text = self.caps
        else:
            text = self.desc
        return {"text": text, "actual_usd": 0.01, "request_id": "r"}


@pytest.fixture()
def facts():
    return load_facts(SAMPLE_FACTS_PATH)


def _run(facts, a, b):
    log = []
    out = run_writing(facts, ["kitchen", "bedroom"], {"meta": a, "baseten": b}, log.append)
    return out, log


def _text(out, provider, job="description"):
    return next(t for t in out["texts"] if t["provider"] == provider and t["id"] == job)


def test_both_models_get_the_same_generation_prompt_and_no_source_field(facts):
    a, b = Fake("meta"), Fake("baseten")
    _run(facts, a, b)
    for kind in ("DESCRIPTION", "CAPTIONS"):
        x = [p for p in a.prompts if p.startswith(kind)]
        y = [p for p in b.prompts if p.startswith(kind)]
        assert len(x) == 1 and x == y
    assert "SAMPLE DATA" not in a.prompts[0] and "Dishwasher" in a.prompts[0]


def test_every_text_is_reviewed_by_both_models(facts):
    out, log = _run(facts, Fake("meta"), Fake("baseten"))
    assert len(out["texts"]) == 6
    for t in out["texts"]:
        assert set(t["attempts"][-1]["reviews"]) == {"meta", "baseten"}
        assert t["status"] == "pass"


def test_every_call_is_logged_with_job_model_cost_hash_and_checks(facts):
    _, log = _run(facts, Fake("meta"), Fake("baseten"))
    # 2 descriptions, 2 caption calls, 12 reviews.
    assert len(log) == 16
    for row in log:
        assert {"job", "model", "provider", "prompt_hash", "cost_usd", "output"} <= set(row)
    assert all("checks" in r and "verdicts" in r for r in log if r["job"] != "review")


def test_failed_text_is_rewritten_once_naming_the_failure_and_then_passes(facts):
    bad = GOOD_DESC.replace("2 bedroom", "3 bedroom")
    a = Fake("meta", desc=bad)
    out, _ = _run(facts, a, Fake("baseten"))
    t = _text(out, "meta")
    assert len(t["attempts"]) == 2 and t["status"] == "pass" and t["final"] == GOOD_DESC
    rewrite = next(p for p in a.prompts if p.startswith("REWRITE"))
    assert "number not in the facts: 3" in rewrite


def test_text_that_still_fails_is_shown_failed_not_hidden(facts):
    bad = GOOD_DESC.replace("2 bedroom", "3 bedroom")
    out, _ = _run(facts, Fake("meta", desc=bad, rewrite=bad), Fake("baseten"))
    t = _text(out, "meta")
    assert len(t["attempts"]) == 2 and t["status"] == "failed" and t["final"] == bad


def test_no_third_attempt(facts):
    bad = GOOD_DESC.replace("2 bedroom", "3 bedroom")
    a = Fake("meta", desc=bad, rewrite=bad)
    _run(facts, a, Fake("baseten"))
    assert sum(p.startswith("REWRITE") for p in a.prompts) == 1


def test_fair_housing_phrase_fails_even_when_both_reviewers_pass(facts):
    bad = GOOD_DESC + " Perfect for couples."
    out, _ = _run(facts, Fake("meta", desc=bad, rewrite=bad), Fake("baseten"))
    assert _text(out, "meta")["status"] == "failed"


def test_reviewers_disagreeing_flags_the_text_never_passes(facts):
    out, _ = _run(facts, Fake("meta"), Fake("baseten", review="FAIL - steers"))
    for t in out["texts"]:
        assert t["attempts"][-1]["second_opinion"] == "flag"
        assert t["status"] == "flagged"


def test_unreadable_review_flags_the_text_and_counts_against_that_model(facts):
    out, _ = _run(facts, Fake("meta"), Fake("baseten", review="I think it is fine"))
    assert _text(out, "meta")["status"] == "flagged"
    row = out["picks"]["review"]["rows"]["baseten"]
    assert row["failed_checks"] > out["picks"]["review"]["rows"]["meta"]["failed_checks"]


def test_unparseable_captions_fail_as_format_and_are_rewritten(facts):
    a = Fake("meta", caps="not json", rewrite="Bright home #home")
    out, _ = _run(facts, a, Fake("baseten"))
    t = _text(out, "meta", "caption_social")
    assert any("format" in f for f in t["attempts"][0]["failures"])
    assert t["status"] == "pass"


def test_choose_fewer_failures_then_lower_cost_then_tie():
    r = choose(
        {
            "meta": {"failed_checks": 1, "cost_usd": 0.1},
            "baseten": {"failed_checks": 2, "cost_usd": 0.0},
        }
    )
    assert r == "meta"
    r = choose(
        {
            "meta": {"failed_checks": 1, "cost_usd": 0.2},
            "baseten": {"failed_checks": 1, "cost_usd": 0.1},
        }
    )
    assert r == "baseten"
    r = choose(
        {
            "meta": {"failed_checks": 1, "cost_usd": 0.1},
            "baseten": {"failed_checks": 1, "cost_usd": 0.1},
        }
    )
    assert r == "tie"
