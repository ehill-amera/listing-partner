import pytest

from listing_partner.facts import SAMPLE_FACTS_PATH, FactsError, load_facts, prompt_facts
from listing_partner.scoring import (
    check_description_length,
    check_facts,
    check_social_caption,
    check_video_caption,
    second_opinion,
)


@pytest.fixture()
def facts():
    return load_facts(SAMPLE_FACTS_PATH)


def test_sample_is_labeled_as_sample(facts):
    assert facts["source"].startswith("SAMPLE DATA")


def test_facts_with_a_field_outside_the_contract_are_refused(tmp_path):
    p = tmp_path / "f.json"
    p.write_text(SAMPLE_FACTS_PATH.read_text().replace('"unit"', '"street_address": "x", "unit"'))
    with pytest.raises(FactsError):
        load_facts(p)


def test_missing_required_field_is_refused(tmp_path):
    p = tmp_path / "f.json"
    p.write_text('{"bedrooms": 2}')
    with pytest.raises(FactsError):
        load_facts(p)


def test_prompt_facts_drop_source_and_unit(facts):
    sent = prompt_facts(facts)
    assert "source" not in sent and "unit" not in sent and sent["bedrooms"] == 2


def test_true_numbers_pass(facts):
    assert check_facts("2 bedrooms, 1 bath, 900 sq ft, $1,400 a month, two-bedroom", facts) == []


@pytest.mark.parametrize(
    "text",
    ["3 bedrooms", "950 sq ft", "$1,500 a month", "three bedrooms", "open 24/7", "#3BR"],
)
def test_invented_number_fails(text, facts):
    assert any("number" in f for f in check_facts(text, facts)), text


def test_true_amenity_passes(facts):
    assert check_facts("Hardwood floors, a dishwasher and central air.", facts) == []


def test_synonym_of_a_listed_amenity_passes(facts):
    assert check_facts("Air conditioning throughout.", facts) == []


@pytest.mark.parametrize(
    "text", ["In-unit washer.", "A private balcony.", "Swimming pool.", "Attached garage", "A yard"]
)
def test_invented_amenity_fails(text, facts):
    assert any("amenity" in f for f in check_facts(text, facts)), text


def test_washer_is_not_matched_inside_dishwasher(facts):
    assert check_facts("A dishwasher.", facts) == []


def test_pets_fail_when_policy_is_empty(facts):
    assert check_facts("Cats welcome.", facts) == []
    assert check_facts("Cats welcome.", {**facts, "pet_policy": None})


def test_description_limits():
    assert check_description_length(" ".join(["w"] * 120)) == []
    assert check_description_length(" ".join(["w"] * 220)) == []
    assert check_description_length(" ".join(["w"] * 119))
    assert check_description_length(" ".join(["w"] * 221))


def test_social_caption_limits():
    assert check_social_caption("x" * 299 + " #a #b #c #d #e") == []
    assert check_social_caption("x" * 300 + " #a")
    assert check_social_caption("x #a #b #c #d #e #f")


def test_video_caption_limit():
    assert check_video_caption("x" * 149) == []
    assert check_video_caption("x" * 150)


@pytest.mark.parametrize(
    "a,b,want",
    [
        ("pass", "pass", "pass"),
        ("fail", "fail", "fail"),
        ("pass", "fail", "flag"),
        ("fail", "pass", "flag"),
        ("pass", None, "flag"),
        (None, None, "flag"),
    ],
)
def test_second_opinion_disagreement_is_never_a_pass(a, b, want):
    assert second_opinion(a, b) == want
