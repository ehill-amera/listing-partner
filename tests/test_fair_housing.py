import pytest

from listing_partner import fair_housing
from listing_partner.fair_housing import PHRASES, SOURCES, find_phrases


@pytest.mark.parametrize(
    "text",
    [
        "No kids please.",
        "Adults only building.",
        "Perfect for couples!",
        "Ideal for a single professional.",
        "Great for young professionals.",
        "Mature tenants preferred.",
        "No wheelchairs.",
        "Must be able to climb stairs.",
        "Able-bodied residents only.",
        "able bodied",
        "Christian home.",
        "Whites only.",
        "English speakers only.",
        "Women only.",
        "No children.",
        "Seniors only.",
        "Family-friendly neighborhood.",
        "Perfect for families",
    ],
)
def test_steering_language_fails(text):
    assert find_phrases(text), text


@pytest.mark.parametrize(
    "text",
    [
        "Large family room with a fireplace.",
        "The master bedroom has a walk-in closet.",
        "Near a park and shops.",
        "Wheelchair ramp at the front door.",
        "Mature trees shade the yard.",
        "White cabinets and black counters.",
        "Quiet street, two bedrooms.",
        "A jewelry cabinet and menu board.",
    ],
)
def test_describing_the_property_stays_fine(text):
    assert find_phrases(text) == [], text


@pytest.mark.parametrize(
    "text",
    [
        # The first review's probes, each of which returned no hit on bc8043b.
        "adults preferred",
        "men preferred",
        "woman preferred",
        "seniors preferred",
        "perfect for a young family",
        "perfect for a growing family",
        "best suited to a couple",
        "suited to a single person",
        "no young children",
        "not for kids",
        "female roommate wanted",
        "single person only",
        "english speakers preferred",
        # The amendment's other wording.
        "preference for adults",
        "A seniors preference applies.",
        "Preference given to young couples.",
        "Not for young kids.",
        "Great for a busy professional.",
    ],
)
def test_review_probes_and_amendment_wording_fail(text):
    assert find_phrases(text), text


@pytest.mark.parametrize(
    "text",
    [
        "Handicapped accessible entrance.",
        "handicapped-accessible bathroom",
        "Wheelchair accessible throughout.",
        "Preferred parking spot behind the building.",
        "No smoking. Not for sale.",
        "Perfect for a home office.",
        "Great for entertaining.",
        "A single-family home.",
        "Ideal for a single-family layout.",
        "The family room is perfect for movie night.",
    ],
)
def test_property_wording_near_the_new_patterns_stays_fine(text):
    assert find_phrases(text) == [], text


@pytest.mark.parametrize(
    "text",
    [
        # The second review's probes, each of which returned no hit on 2a757ba.
        "adults-only building",
        "adult-only",
        "seniors-only",
        "no seniors",
        "no students",
        "no teens",
        "no toddlers",
        "no child",
        "no pets or children",
        "kids not allowed",
        "children not allowed",
        "unsuitable for children",
        "not appropriate for children",
        "not recommended for children",
        "adults strongly preferred",
        "seniors strongly preferred",
        "preference will be given to seniors",
        "preferred tenants: adults",
        "gentleman preferred",
        "lady preferred",
        "perfect for a busy working couple",
        "best suited to a busy working family",
        "ideal for a small quiet family",
        "good for families",
        "families welcome",
        "kid-friendly",
        "professionals only",
        "english only",
    ],
)
def test_second_review_probes_fail(text):
    assert find_phrases(text), text


@pytest.mark.parametrize(
    "text",
    [
        # The amendment's classes applied across the other listed groups.
        "no retirees",
        "no couples or kids",
        "students not permitted",
        "seniors are not allowed",
        "inappropriate for toddlers",
        "good for retirees",
        "good for a young couple",
        "students welcome",
        "seniors are welcome",
        "senior-friendly",
        "student-friendly",
        "couples strongly preferred",
        "men-only",
        "christian-only",
    ],
)
def test_amendment_two_classes_reach_the_other_groups(text):
    assert find_phrases(text), text


@pytest.mark.parametrize(
    "text",
    [
        "No pets or smoking.",
        "No smoking.",
        "No carpet in the bedrooms.",
        "Pets welcome.",
        "A welcome mat at the door.",
        "Good for storage.",
        "Good for a home office and hobbies.",
        "The family room is welcome after a long day.",
        "Ideal for a multi-family layout.",
        "A multi-family building.",
        "Dogs not allowed.",
        "Smoking not allowed.",
        "Unsuitable for storage of chemicals.",
        "Preferred tenants pay on time.",
        "Handicapped accessible entrance, wheelchair accessible.",
        "A master bedroom and mature trees.",
    ],
)
def test_property_wording_near_the_second_round_patterns_stays_fine(text):
    assert find_phrases(text) == [], text


def test_handicapped_about_people_still_fails():
    assert find_phrases("Handicapped tenants welcome.")
    assert find_phrases("No handicapped.")


def test_file_says_it_is_a_screen_and_a_person_approves():
    doc = " ".join(fair_housing.__doc__.split())
    assert "a screen, not legal advice" in doc
    assert "person approves before posting" in doc


def test_matching_ignores_case_and_extra_spaces():
    assert find_phrases("ADULTS   ONLY")


def test_every_hit_names_its_category():
    hit = find_phrases("adults only")[0]
    assert hit["category"] == "familial status" and hit["phrase"]


def test_file_names_its_sources_and_has_every_protected_class():
    joined = " ".join(SOURCES)
    assert "3604(c)" in joined and "100.75" in joined and "1995" in joined
    cats = {p["category"] for p in PHRASES}
    assert {
        "race or color",
        "religion",
        "national origin",
        "sex",
        "disability",
        "familial status",
        "age steering",
    } <= cats
