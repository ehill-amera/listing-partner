import json

import pytest

from listing_partner.facts import SAMPLE_FACTS_PATH, FactsError, load_facts, prompt_facts
from listing_partner.scoring import (
    fact_mentions,
    AMENITY_GROUPS,
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


@pytest.mark.parametrize(
    "text",
    [
        # The first review's probes, moved onto the sample's 2 bed, 1 bath, 900 sq ft, $1,400.
        "1 bedroom and 2 baths",
        "$900 a month and 1,400 sq ft",
        "2 bedrooms and 2 baths",
        # The same mistake in other forms.
        "1,400 square feet",
        "900 a month",
        "Rent of $900",
        "$900 rent",
        "Bedrooms: 1",
        "two baths",
        "one bedroom",
        "nine hundred dollars a month",
        "fourteen hundred square feet",
        "2 sunny baths",
        "#1BR",
    ],
)
def test_a_real_number_next_to_the_wrong_fact_fails(text, facts):
    assert any("next to" in f for f in check_facts(text, facts)), text


@pytest.mark.parametrize(
    "text",
    [
        "Two bedrooms and one bath",
        "nine hundred square feet",
        "fourteen hundred dollars a month",
        "$1,400",
        "2 sunny bedrooms",
        "2BR/1BA",
        "two-bedroom, one-bath",
        "Rent: $1,400",
        "Bedrooms: 2",
        "900-square-foot home",
        "$1,400 deposit",
        "Available 2030-01-15",
        "One of the best streets.",
    ],
)
def test_numbers_next_to_their_own_fact_pass(text, facts):
    assert check_facts(text, facts) == [], text


@pytest.mark.parametrize(
    "text",
    [
        "Forty feet of frontage",
        "Sixty windows",
        "Fifteen closets",
        "Ninety steps to the door",
        "Two closets",
        "2 parking spaces near the bedrooms",
        "900 feet of frontage",
        "A one-car driveway",
    ],
)
def test_a_number_beside_no_fact_is_invented(text, facts):
    failures = check_facts(text, {**facts, "amenities": [*facts["amenities"], "Driveway"]})
    assert any(f.startswith("number not in the facts") for f in failures), text


@pytest.mark.parametrize(
    "text",
    [
        "Offered at 1400 USD per month",
        "1,400 usd a month",
        "USD 1,400 a month",
        "USD 1400",
        "1400 USD",
        "1400 USD deposit",
    ],
)
def test_money_written_as_usd_passes_after_a_live_false_failure(text, facts):
    assert check_facts(text, facts) == [], text


@pytest.mark.parametrize("text", ["Offered at 900 USD per month", "900 USD", "USD 900"])
def test_a_wrong_figure_written_as_usd_fails(text, facts):
    assert check_facts(text, facts), text


def test_a_wrong_usd_rent_is_named_as_the_rent(facts):
    assert any("next to the rent" in f for f in check_facts("900 USD per month", facts))


@pytest.mark.parametrize("text", ["Available January 15, 2030", "Available Jan 15", "Open 1/15"])
def test_the_available_date_in_common_forms_passes(text, facts):
    assert check_facts(text, facts) == [], text


def test_the_wrong_available_day_fails(facts):
    assert check_facts("Available January 16", facts)


def test_a_deposit_figure_fails_when_the_facts_have_no_deposit(facts):
    assert check_facts("$1,400 deposit", {**facts, "deposit_usd": None})


@pytest.mark.parametrize(
    "text",
    [
        "sauna, hot tub and rooftop terrace",
        "A sauna.",
        "A hot tub.",
        "A rooftop terrace.",
    ],
)
def test_invented_amenity_from_the_review_fails(text, facts):
    assert any("amenity" in f for f in check_facts(text, facts)), text


def test_detached_garage_fails_when_the_facts_only_say_garage(facts):
    with_garage = {**facts, "amenities": [*facts["amenities"], "Garage"]}
    assert check_facts("A garage.", with_garage) == []
    assert any("amenity" in f for f in check_facts("A detached garage.", with_garage))


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


def test_description_limits_are_90_to_200_words():
    assert check_description_length(" ".join(["w"] * 90)) == []
    assert check_description_length(" ".join(["w"] * 200)) == []
    assert check_description_length(" ".join(["w"] * 89))
    assert check_description_length(" ".join(["w"] * 201))


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


NO_AMENITIES = {"bedrooms": 2, "bathrooms": 1, "square_feet": 900, "rent_monthly_usd": 1400}


@pytest.mark.parametrize(
    "text",
    [
        # The second review's probes, each of which passed on 2a757ba.
        "private patios",
        "balconies",
        "decks",
        "resort pools and saunas",
        "front and rear porches",
        "new dishwashers",
        "stainless-steel appliances",
        "fully-furnished",
        "air-conditioning",
        "pool-side",
    ],
)
def test_second_review_amenity_probes_fail(text):
    assert any("amenity" in f for f in check_facts(text, NO_AMENITIES)), text


# Terms that are not nouns have no plural to test.
_NOT_NOUNS = {
    "air-conditioned",
    "air conditioning",
    "central air",
    "carpeted",
    "carpeting",
    "tiled",
    "gated",
    "furnished",
    "renovated",
    "remodeled",
    "updated",
    "stainless",
    "stainless steel",
    "heat included",
    "heat paid",
    "water included",
    "water paid",
    "utilities included",
    "pet-friendly",
    "pet friendly",
    "a/c",
    "ac",
    "ev charging",
    "lvp",
    "luxury vinyl",
    "internet",
    "wifi",
    "wi-fi",
    "laundry",
    "storage",
    "parking",
    "hardwood",
    "granite",
    "quartz",
    "vinyl plank",
    "carpet",
    "tile",
}
_TERMS = [term for group in AMENITY_GROUPS for term in group]


def _plural(term: str) -> str:
    if term.endswith(("ch", "sh", "x")) or term.endswith("ss"):
        return term + "es"
    if term.endswith("y") and term[-2] not in "aeiou":
        return term[:-1] + "ies"
    return term + "s"


@pytest.mark.parametrize("term", [t for t in _TERMS if t not in _NOT_NOUNS and not t.endswith("s")])
def test_every_amenity_noun_is_caught_in_the_plural(term):
    text = f"Two words: {_plural(term)} here."
    assert any("amenity" in f for f in check_facts(text, NO_AMENITIES)), text


@pytest.mark.parametrize("term", _TERMS)
def test_every_amenity_term_is_caught_as_a_hyphenated_compound(term):
    text = f"A {term}-style extra."
    assert any("amenity" in f for f in check_facts(text, NO_AMENITIES)), text


@pytest.mark.parametrize("term", [t for t in _TERMS if " " in t or "-" in t])
def test_every_two_word_amenity_is_caught_spaced_or_hyphenated(term):
    flipped = term.replace(" ", "\0").replace("-", " ").replace("\0", "-")
    assert any("amenity" in f for f in check_facts(f"A {flipped}.", NO_AMENITIES)), flipped


@pytest.mark.parametrize("text", ["A carpool lane.", "Unfurnished.", "A bathtub and a deckhand."])
def test_a_term_inside_a_longer_word_is_not_an_amenity(text):
    assert not any("amenity" in f for f in check_facts(text, NO_AMENITIES)), text


def test_a_plural_or_hyphenated_fact_covers_the_plain_form_and_back():
    facts = {**NO_AMENITIES, "amenities": ["Private patios", "stainless-steel appliances"]}
    assert check_facts("A patio and stainless steel appliances.", facts) == []
    facts = {**NO_AMENITIES, "amenities": ["patio"]}
    assert check_facts("Two words: private patios.".replace("Two words: ", ""), facts) == []


@pytest.mark.parametrize(
    "text",
    [
        # The second review's probes, each of which passed on 2a757ba. Sample: 2 bed, 1 bath.
        "one and a half baths",
        "one and a half bedrooms",
        "a second bathroom",
        "a half bath",
        # The same wording in its other forms.
        "one-and-a-half baths",
        "1 and a half baths",
        "two and a half baths",
        "half-bath",
        "a third bedroom",
        "a 3rd bedroom",
        "a 2nd bath",
        "a second full bath",
    ],
)
def test_half_and_ordinal_bed_or_bath_wording_that_contradicts_the_facts_fails(text, facts):
    assert any("next to" in f for f in check_facts(text, facts)), text


@pytest.mark.parametrize("text", ["The second bedroom.", "A 2nd bedroom.", "The first bathroom."])
def test_an_ordinal_within_the_count_is_true_and_passes(text, facts):
    assert check_facts(text, facts) == [], text


@pytest.mark.parametrize(
    "text", ["one and a half baths", "1.5 baths", "a half bath", "the second bathroom"]
)
def test_half_and_ordinal_wording_passes_when_the_facts_say_so(text, facts):
    assert check_facts(text, {**facts, "bathrooms": 1.5}) == [], text


@pytest.mark.parametrize(
    "policy,text",
    [
        # The second review's probes, each of which passed on 2a757ba.
        ("No pets allowed", "pets welcome"),
        ("No pets allowed", "pet-friendly"),
        # The same mistake in other forms.
        ("Pets not allowed", "pets welcome"),
        ("Cats OK, no dogs", "dogs welcome"),
    ],
)
def test_a_negated_pet_policy_never_counts_as_pets_present(policy, text):
    facts = {**NO_AMENITIES, "pet_policy": policy}
    assert any("amenity" in f for f in check_facts(text, facts)), text


@pytest.mark.parametrize("amenity", ["no garage", "garage not included", "Without a garage"])
def test_a_negated_amenity_never_counts_as_present(amenity):
    facts = {**NO_AMENITIES, "amenities": [amenity]}
    assert any("amenity" in f for f in check_facts("A garage.", facts)), amenity


@pytest.mark.parametrize(
    "facts_extra,text",
    [
        ({"pet_policy": "No pets allowed"}, "No pets allowed."),
        ({"pet_policy": "Cats OK, no dogs"}, "Cats welcome, no dogs."),
        ({"amenities": ["no garage"]}, "No garage."),
        ({"amenities": ["Garage"]}, "Not only a garage."),
    ],
)
def test_a_text_repeating_the_facts_true_wording_passes(facts_extra, text):
    assert check_facts(text, {**NO_AMENITIES, **facts_extra}) == [], text


@pytest.mark.parametrize(
    "facts_extra,text",
    [
        ({"amenities": ["Garage"]}, "No garage."),
        ({"pet_policy": None}, "No pets."),
    ],
)
def test_a_text_denying_what_the_facts_do_not_deny_fails(facts_extra, text):
    assert any("amenity" in f for f in check_facts(text, {**NO_AMENITIES, **facts_extra})), text


def _demo_file(tmp_path, source="DEMO FACTS: a home, not a listing."):
    path = tmp_path / "demo.json"
    data = {
        "source": source,
        "bedrooms": 1,
        "bathrooms": 1,
        "square_feet": None,
        "rent_monthly_usd": None,
        "amenities": [],
    }
    path.write_text(json.dumps(data))
    return path


def test_labeled_demo_facts_may_leave_out_rent_and_square_feet(tmp_path):
    assert load_facts(_demo_file(tmp_path))["rent_monthly_usd"] is None


def test_facts_not_labeled_demo_still_need_rent_and_square_feet(tmp_path):
    with pytest.raises(FactsError, match="rent_monthly_usd"):
        load_facts(_demo_file(tmp_path, source="AppFolio"))


def test_demo_facts_still_need_bedrooms(tmp_path):
    path = _demo_file(tmp_path)
    data = json.loads(path.read_text())
    data["bedrooms"] = None
    path.write_text(json.dumps(data))
    with pytest.raises(FactsError, match="bedrooms"):
        load_facts(path)


def test_fact_mentions_with_no_rent_counts_the_facts_it_has(tmp_path):
    facts = load_facts(_demo_file(tmp_path))
    counts = fact_mentions("A home with 1 bedroom, and 25 dollars of charm.", facts)
    assert counts["bedrooms"] == 1 and "rent_monthly_usd" not in counts
