"""A model's wrapper never reaches a text, and no text with JSON, a code fence or
markup passes. Everything here goes through run_writing against fake models."""

import hashlib
import json
from pathlib import Path

import pytest

from listing_partner.facts import SAMPLE_FACTS_PATH, load_facts
from listing_partner.writing import run_writing

ROOT = Path(__file__).resolve().parent.parent
PHOTOS = [{"room": "kitchen", "note": "bright clean kitchen"}]
PLAIN_DESC = " ".join(["nice"] * 120)
PLAIN_SOCIAL = "Bright home #home"
PLAIN_VIDEO = "Bright home with a clean kitchen"
# Same shape as the live caption, on the fictional sample unit.
SAMPLE_INNER = "2 bed, 1 bath, 900 sq ft in Sampleville, MI $1400. Hardwood floors, central air."
SAMPLE_WRAPPED = json.dumps({"text": SAMPLE_INNER}, separators=(",", ":"))
# The live caption itself holds a real unit's facts, which stay out of the repo.
# It is read from the saved log and pinned here by its hash.
LIVE_CAPTION_SHA256 = "c7de3d03a265c24590fd2725b5114eaec8adfa90461a2bc067fabe981ae874e5"


class Fake:
    """Answers by prompt kind. Rewrites answer per text, chosen by the prompt's limit."""

    def __init__(self, name, desc=PLAIN_DESC, caps=None, video=PLAIN_VIDEO, social=PLAIN_SOCIAL):
        self.name, self.model, self.prompts = name, f"model-{name}", []
        pair = {"instagram_facebook": PLAIN_SOCIAL, "video": PLAIN_VIDEO}
        self.desc = desc
        self.caps = json.dumps(pair) if caps is None else caps
        self.video, self.social = video, social

    def __call__(self, prompt, max_tokens):
        self.prompts.append(prompt)
        if prompt.startswith("REVIEW"):
            text = "PASS"
        elif prompt.startswith("REWRITE"):
            head = prompt.split("Text:\n", 1)[1]
            if "Reply with the text only" not in head:
                raise AssertionError("unexpected rewrite prompt")
            limit = head.split("Rewrite it to pass, ", 1)[1]
            if limit.startswith("under 150"):
                text = self.video
            elif limit.startswith("under 300"):
                text = self.social
            else:
                text = PLAIN_DESC
        elif prompt.startswith("CAPTIONS"):
            text = self.caps
        else:
            text = self.desc
        return {"text": text, "actual_usd": 0.01, "request_id": "r"}


def _run(facts, author, **kw):
    models = {"meta": Fake("meta"), "baseten": Fake("baseten")}
    models[author] = Fake(author, **kw)
    log = []
    return run_writing(facts, PHOTOS, models, log.append), log, models


def _text(out, provider, job):
    return next(t for t in out["texts"] if t["provider"] == provider and t["id"] == job)


@pytest.fixture()
def facts():
    return load_facts(SAMPLE_FACTS_PATH)


def _live_caption():
    for path in sorted((ROOT / "output" / "unit-a" / "writing").glob("log*.jsonl")):
        for line in path.read_text().splitlines():
            output = json.loads(line).get("output") or ""
            if hashlib.sha256(output.encode()).hexdigest() == LIVE_CAPTION_SHA256:
                return output
    return None


def test_the_exact_live_caption_loses_its_wrapper_and_passes():
    caption = _live_caption()
    facts_path = ROOT / "facts" / "unit-a.json"
    if caption is None or not facts_path.exists():
        pytest.skip("this machine has no saved unit-a run")
    inner = json.loads(caption)["text"]
    out, _, _ = _run(load_facts(facts_path), "baseten", caps="", video=caption)
    text = _text(out, "baseten", "caption_video")
    assert text["final"] == inner
    assert text["status"] == "pass"
    assert text["attempts"][-1]["failures"] == []


@pytest.mark.parametrize("author", ["meta", "baseten"])
def test_a_wrapped_rewrite_from_either_provider_is_unwrapped(facts, author):
    out, _, _ = _run(facts, author, caps="", video=SAMPLE_WRAPPED)
    text = _text(out, author, "caption_video")
    assert text["final"] == SAMPLE_INNER
    assert text["status"] == "pass"


@pytest.mark.parametrize("author", ["meta", "baseten"])
def test_a_wrapped_description_is_unwrapped_and_costs_no_rewrite(facts, author):
    out, _, models = _run(facts, author, desc=json.dumps({"description": PLAIN_DESC}))
    text = _text(out, author, "description")
    assert text["final"] == PLAIN_DESC
    assert len(text["attempts"]) == 1
    assert not [p for p in models[author].prompts if p.startswith("REWRITE")]


def test_wrapped_fields_inside_the_captions_reply_are_unwrapped(facts):
    caps = json.dumps({"instagram_facebook": PLAIN_SOCIAL, "video": SAMPLE_WRAPPED})
    out, _, _ = _run(facts, "baseten", caps=caps)
    assert _text(out, "baseten", "caption_video")["final"] == SAMPLE_INNER


@pytest.mark.parametrize(
    "reply",
    [
        f"```json\n{SAMPLE_WRAPPED}\n```",
        f"```\n{SAMPLE_INNER}\n```",
        json.dumps(SAMPLE_INNER),
        json.dumps({"caption": {"text": SAMPLE_INNER}}),
    ],
    ids=["fenced-json", "fenced-text", "quoted-json-string", "nested"],
)
def test_other_whole_reply_wrappers_are_removed(facts, reply):
    out, _, _ = _run(facts, "meta", caps="", video=reply)
    assert _text(out, "meta", "caption_video")["final"] == SAMPLE_INNER


def test_the_log_keeps_the_raw_reply(facts):
    _, log, _ = _run(facts, "baseten", caps="", video=SAMPLE_WRAPPED)
    row = next(r for r in log if r["job"] == "captions" and r["text_id"] == "caption_video")
    assert row["output"] == SAMPLE_WRAPPED


@pytest.mark.parametrize(
    ("reply", "kind"),
    [
        ('{"text":"Bright home","video":"Bright home"}', "JSON"),
        ('Here it is: {"text":"Bright home"}', "JSON"),
        ('{"text":"Bright home', "JSON"),
        ('Bright home "text": "kitchen"', "JSON"),
        ('["Bright home"]', "JSON"),
        ("Bright home\\nclean kitchen", "JSON"),
        ("Bright home ```kitchen``` clean", "code fence"),
        ("Bright `home`", "code fence"),
        ("Bright <b>home</b>", "markup"),
        ("Bright home<br/>clean", "markup"),
        ("Bright &amp; clean home", "markup"),
        ("A **bright** home", "markup"),
        ("A __bright__ home", "markup"),
        ("A *bright* home", "markup"),
        ("# Bright home", "markup"),
        ("Home:\n- bright\n- clean", "markup"),
        ("A [bright home](https://example.com)", "markup"),
    ],
)
def test_a_text_with_json_a_fence_or_markup_fails(facts, reply, kind):
    out, _, _ = _run(facts, "meta", caps="", video=reply)
    text = _text(out, "meta", "caption_video")
    assert text["status"] == "failed"
    assert any(f.startswith(f"format: contains {kind}") for f in text["attempts"][-1]["failures"])


@pytest.mark.parametrize(
    "reply",
    [
        "Bright home #home #kitchen",
        "It's a bright home: clean kitchen & hall.",
        '"Bright" is the word for this home',
        "Bright home - clean kitchen",
        "Sunny 2-bed at $1400/month!",
    ],
)
def test_ordinary_punctuation_is_not_markup(facts, reply):
    out, _, _ = _run(facts, "meta", caps="", video=reply)
    text = _text(out, "meta", "caption_video")
    assert text["final"] == reply
    assert text["attempts"][-1]["failures"] == []
