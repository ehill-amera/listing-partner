import json

import pytest

from listing_partner.coverage import check_coverage, required_rooms
from listing_partner.curate import ROOMS, benchmark, decide, enforce_walkthrough, parse_rating


def _facts(bed=2, bath=1):
    return {"bedrooms": bed, "bathrooms": bath}


def _photo(pid, room, sharp=4, frame=4):
    return {"id": pid, "room": room, "sharpness": sharp, "framing": frame}


def test_required_rooms_counts_every_bedroom_and_bath():
    assert required_rooms(_facts(2, 2)) == [
        "bedroom 1",
        "bedroom 2",
        "bathroom 1",
        "bathroom 2",
        "kitchen",
        "living area",
        "front exterior",
    ]


def test_half_bath_counts_as_a_room():
    assert required_rooms(_facts(1, 1.5)).count("bathroom 2") == 1


def test_coverage_says_found_missing_or_no_strong_shot():
    kept = [
        _photo("1", "front exterior"),
        _photo("2", "kitchen"),
        _photo("3", "bedroom"),
        _photo("4", "bathroom", sharp=2),
    ]
    got = {r["room"]: r for r in check_coverage(_facts(2, 1), kept)}
    assert got["front exterior"]["status"] == "found"
    assert got["bedroom 1"]["photo"] == "3"
    assert got["bedroom 2"]["status"] == "missing"
    assert got["living area"]["status"] == "missing"
    assert got["bathroom 1"]["status"] == "no strong shot"
    assert set(got) == set(required_rooms(_facts(2, 1)))


def test_one_photo_cannot_cover_two_bedrooms():
    got = check_coverage(_facts(2, 0), [_photo("3", "bedroom")])
    assert [r["status"] for r in got if r["room"].startswith("bedroom")] == ["found", "missing"]


def test_rooms_list_is_the_contract_list():
    assert len(ROOMS) == 14 and "front exterior" in ROOMS and "other" in ROOMS


def test_rating_parses_with_a_code_fence():
    text = '```json\n{"room": "kitchen", "sharpness": 4, "framing": 3, "note": "n"}\n```'
    assert parse_rating(text)["room"] == "kitchen"


@pytest.mark.parametrize(
    "text",
    [
        "no json here",
        '{"room": "ballroom", "sharpness": 4, "framing": 3, "note": "n"}',
        '{"room": "kitchen", "sharpness": 9, "framing": 3, "note": "n"}',
    ],
)
def test_bad_rating_raises_instead_of_guessing(text):
    with pytest.raises(ValueError):
        parse_rating(text)


def _set_reply(order, dups=()):
    return json.dumps({"duplicates": list(dups), "order": order})


def test_decide_keeps_plus_drops_equal_all_with_reasons():
    ratings = [_photo("1", "front exterior"), _photo("2", "kitchen"), _photo("3", "kitchen")]
    ratings.append(_photo("4", "bedroom", sharp=1))
    for r in ratings:
        r["note"] = "note"
    dup = {"keep": "2", "drop": "3", "reason": "same view, 2 is sharper"}
    got = decide(ratings, _set_reply(["1", "2"], [dup]))
    assert [p["id"] for p in got["kept"]] == ["1", "2"]
    dropped = {p["id"]: p["reason"] for p in got["dropped"]}
    assert set(dropped) == {"3", "4"} and "sharper" in dropped["3"] and dropped["4"]


def test_decide_raises_when_order_is_not_exactly_the_kept_shots():
    ratings = [_photo("1", "kitchen"), _photo("2", "bedroom")]
    with pytest.raises(ValueError):
        decide(ratings, _set_reply(["1"]))
    with pytest.raises(ValueError):
        decide(ratings, _set_reply(["1", "2", "9"]))


def test_decide_raises_on_a_duplicate_of_an_unknown_shot():
    ratings = [_photo("1", "kitchen")]
    dup = {"keep": "1", "drop": "9", "reason": "r"}
    with pytest.raises(ValueError):
        decide(ratings, _set_reply(["1"], [dup]))


def test_walkthrough_puts_front_first_and_rear_and_yard_last():
    labels = {"a": "kitchen", "b": "yard", "c": "front exterior", "d": "rear exterior", "e": "bath"}
    got = enforce_walkthrough(["a", "b", "e", "c", "d"], labels)
    assert got == ["c", "a", "e", "b", "d"]


def test_benchmark_numbers():
    # Erik: 1,2,3,4 in that order, never published 5. Ours: 2,1,3,5 and dropped 4.
    got = benchmark(["2", "1", "3", "5"], ["4"], {"1": 1, "2": 2, "3": 3, "4": 4})
    assert got["kept_both"] == ["1", "2", "3"]
    assert got["we_kept_he_dropped"] == ["5"]
    assert got["we_dropped_he_kept"] == ["4"]
    assert got["we_dropped_he_dropped"] == []
    assert got["different_position"] == 2
    assert got["rank_correlation"] == pytest.approx(0.5)


def test_benchmark_identical_order_is_one():
    got = benchmark(["1", "2", "3"], [], {"1": 1, "2": 2, "3": 3})
    assert got["different_position"] == 0 and got["rank_correlation"] == pytest.approx(1.0)
