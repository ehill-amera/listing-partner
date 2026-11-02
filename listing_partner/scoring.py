"""Deterministic checks, the same for every text from either model."""

from __future__ import annotations

import re

_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")
_WORDS = {
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "twenty": 20,
    "thirty": 30,
    "fifty": 50,
    "hundred": 100,
    "thousand": 1000,
}
_WORD = re.compile(r"\b(" + "|".join(_WORDS) + r")\b", re.I)
# "one" is usually not a count, so it counts only before a room or a car.
_ONE = re.compile(r"\bone[- ](?:bed|bath|car|story|level|floor)", re.I)

# Each group is one amenity and its plain synonyms. A group named in a text
# must have some member in the facts. A term outside this list goes unseen,
# which is why the page and report state this check's reach.
AMENITY_GROUPS = [
    ["air conditioning", "air conditioner", "air-conditioned", "central air", "a/c", "ac"],
    ["dishwasher"],
    ["washer"],
    ["dryer"],
    ["laundry"],
    ["microwave"],
    ["refrigerator", "fridge"],
    ["garbage disposal", "disposal"],
    ["stainless", "stainless steel"],
    ["granite"],
    ["quartz"],
    ["hardwood", "hardwoods"],
    ["carpet", "carpeted", "carpeting"],
    ["vinyl plank", "lvp", "luxury vinyl"],
    ["tile", "tiled"],
    ["fireplace"],
    ["walk-in closet", "walk-in closets"],
    ["balcony"],
    ["patio"],
    ["deck"],
    ["porch"],
    ["yard", "backyard", "fenced yard"],
    ["garage"],
    ["carport"],
    ["parking"],
    ["driveway"],
    ["basement"],
    ["attic"],
    ["storage"],
    ["pool", "swimming pool"],
    ["gym", "fitness center", "fitness room"],
    ["clubhouse"],
    ["elevator"],
    ["doorman", "concierge"],
    ["gated"],
    ["ceiling fan", "ceiling fans"],
    ["skylight", "skylights"],
    ["heat included", "heat paid"],
    ["water included", "water paid"],
    ["utilities included"],
    ["internet", "wifi", "wi-fi"],
    ["furnished"],
    ["renovated", "remodeled", "updated"],
    ["security system", "alarm system"],
    ["cats", "cat"],
    ["dogs", "dog"],
    ["pets", "pet", "pet-friendly", "pet friendly"],
]


def _has(term: str, text: str) -> bool:
    return re.search(rf"(?<![\w-]){re.escape(term)}(?![\w-])", text, re.I) is not None


def _value(raw: str) -> float:
    return float(raw.replace(",", "").rstrip("."))


def _allowed_numbers(facts: dict) -> set[float]:
    allowed: set[float] = set()
    for key in ("bedrooms", "bathrooms", "square_feet", "rent_monthly_usd", "deposit_usd"):
        if facts.get(key) is not None:
            allowed.add(float(facts[key]))
    for text in [facts.get("available_date"), facts.get("pet_policy"), *facts.get("amenities", [])]:
        for raw in _NUMBER.findall(str(text or "")):
            allowed.add(_value(raw))
    return allowed


def check_facts(text: str, facts: dict) -> list[str]:
    """Every number and every listed amenity term must be in the facts."""
    failures = []
    allowed = _allowed_numbers(facts)
    for raw in _NUMBER.findall(text):
        if _value(raw) not in allowed:
            failures.append(f"number not in the facts: {raw}")
    for word in _WORD.findall(text):
        if float(_WORDS[word.lower()]) not in allowed:
            failures.append(f"number not in the facts: {word}")
    if _ONE.search(text) and 1.0 not in allowed:
        failures.append("number not in the facts: one")
    source = " ; ".join(
        str(x)
        for x in [*facts.get("amenities", []), facts.get("pet_policy"), facts.get("property_type")]
        if x
    )
    for group in AMENITY_GROUPS:
        named = [term for term in group if _has(term, text)]
        if named and not any(_has(term, source) for term in group):
            failures.append(f"amenity not in the facts: {named[0]}")
    return failures


def check_description_length(text: str) -> list[str]:
    count = len(text.split())
    return [] if 120 <= count <= 220 else [f"length: {count} words, limit 120 to 220"]


def check_social_caption(text: str) -> list[str]:
    tags = re.findall(r"#\w+", text)
    body = re.sub(r"#\w+", "", text).strip()
    failures = []
    if not body or len(body) >= 300:
        failures.append(f"length: {len(body)} characters before hashtags, limit under 300")
    if len(tags) > 5:
        failures.append(f"length: {len(tags)} hashtags, limit 5")
    return failures


def check_video_caption(text: str) -> list[str]:
    size = len(text.strip())
    return [] if 0 < size < 150 else [f"length: {size} characters, limit under 150"]


def second_opinion(a: str | None, b: str | None) -> str:
    """Two passes pass, two fails fail. Anything else goes to a person."""
    if a == "pass" and b == "pass":
        return "pass"
    if a == "fail" and b == "fail":
        return "fail"
    return "flag"
