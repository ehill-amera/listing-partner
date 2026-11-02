import pytest

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
