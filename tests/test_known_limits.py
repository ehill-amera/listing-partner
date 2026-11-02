"""Every limit the page states is true of the code, measured here."""

import pytest

from listing_partner import known_limits as kl
from listing_partner.facts import SAMPLE_FACTS_PATH, load_facts
from listing_partner.fair_housing import find_phrases
from listing_partner.scoring import check_facts, fact_mentions


@pytest.fixture()
def facts():
    return load_facts(SAMPLE_FACTS_PATH)


@pytest.mark.parametrize("text", kl.FAIR_HOUSING_MISSES)
def test_stated_fair_housing_miss_is_really_missed(text):
    assert find_phrases(text) == []


@pytest.mark.parametrize(
    "text", [*kl.NUMBER_MISSES, *kl.AMENITY_MISSES, *kl.INVENTED_DETAIL_MISSES]
)
def test_stated_facts_miss_is_really_missed(text, facts):
    assert check_facts(text, facts) == []


@pytest.mark.parametrize("text", kl.OVER_FAILS)
def test_stated_over_failure_really_fails(text, facts):
    assert check_facts(text, facts)


def test_every_limit_group_is_on_the_page_text():
    joined = " ".join(kl.LIMITS)
    for example in [
        *kl.FAIR_HOUSING_MISSES,
        *kl.NUMBER_MISSES,
        *kl.AMENITY_MISSES,
        *kl.INVENTED_DETAIL_MISSES,
        *kl.OVER_FAILS,
    ]:
        assert example in joined


def test_fact_mentions_counts_each_fact_each_time_it_is_stated(facts):
    text = (
        "A 2 bedroom home in Sampleville, MI. Two bedrooms, 1 bath, 900 sq ft, $1,400 a month, "
        "rent is $1,400. Hardwood floors, hardwood-floored halls, a dishwasher."
    )
    got = fact_mentions(text, facts)
    assert got["bedrooms"] == 2
    assert got["bathrooms"] == 1
    assert got["square_feet"] == 1
    assert got["rent_monthly_usd"] == 2
    assert got["city"] == 1 and got["state"] == 1
    assert got["amenity: Dishwasher"] == 1
    assert got["amenity: Central air"] == 0
    assert got["amenity: Hardwood floors"] == 2


def test_fact_mentions_ignores_a_wrong_number_beside_the_fact(facts):
    assert fact_mentions("3 bedrooms and $900 rent", facts)["bedrooms"] == 0
    assert fact_mentions("3 bedrooms and $900 rent", facts)["rent_monthly_usd"] == 0


def test_a_deposit_equal_to_the_rent_is_counted_as_the_deposit_only(facts):
    got = fact_mentions("$1,400 deposit", facts)
    assert got["deposit_usd"] == 1 and got["rent_monthly_usd"] == 0
