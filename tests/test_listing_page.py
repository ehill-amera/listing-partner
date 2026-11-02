"""What the page says about a text, from real writing results on fake models."""

import random
import re

import pytest
from test_writing import GOOD_DESC, Fake, _splits_on

from listing_partner.facts import SAMPLE_FACTS_PATH, load_facts
from listing_partner.listing_page import build_page
from listing_partner.scoring import AMENITY_GROUPS
from listing_partner.writing import run_writing

MODEL = "meta-models/muse-spark-open-1026"
COSTS = {
    "meta": {"muse-spark-1.3": {"usd": 0.1, "calls": 2}, "sam-3.1": {"usd": 0.0, "calls": 0}},
    "baseten": {MODEL: {"usd": 0.1, "calls": 2}},
}


@pytest.fixture()
def facts():
    return load_facts(SAMPLE_FACTS_PATH)


def _page(tmp_path, facts, meta, baseten, costs=COSTS):
    writing = run_writing(facts, ["kitchen"], {"meta": meta, "baseten": baseten}, lambda row: None)
    path = tmp_path / "listing.html"
    build_page(
        path,
        facts=facts,
        curation={"kept": [], "dropped": []},
        coverage=[],
        writing=writing,
        costs=costs,
        benchmark=None,
        rng=random.Random(1),
    )
    return path.read_text()


def test_a_passing_text_is_labeled_passed_the_automatic_checks(tmp_path, facts):
    page = _page(tmp_path, facts, Fake("meta"), Fake("baseten"))
    assert "Passed every check" not in page
    assert page.count("Passed the automatic checks") == 6


def test_page_states_what_the_amenity_check_cannot_see(tmp_path, facts):
    page = _page(tmp_path, facts, Fake("meta"), Fake("baseten"))
    assert f"fixed list of {len(AMENITY_GROUPS)} known amenity groups" in page
    assert "An amenity outside those groups cannot be detected" in page
    assert "A person approves every text before posting" in page


def test_the_flag_on_a_rewritten_original_stays_visible(tmp_path, facts):
    bad = GOOD_DESC.replace("2 bedroom", "3 bedroom")
    page = _page(
        tmp_path, facts, Fake("meta", desc=bad), Fake("baseten", review=_splits_on("3 bedroom"))
    )
    outside_details = re.sub(r"<details>.*?</details>", "", page, flags=re.S)
    assert "The first version was FLAGGED" in outside_details
