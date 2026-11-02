"""Deterministic checks, the same for every text from either model."""

from __future__ import annotations

import re
from datetime import date

_DIGITS = re.compile(r"\d+(?:,\d{3})*(?:\.\d+)?")
_WORDS = {
    "one": 1,
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
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "sixteen": 16,
    "seventeen": 17,
    "eighteen": 18,
    "nineteen": 19,
    "twenty": 20,
    "thirty": 30,
    "forty": 40,
    "fifty": 50,
    "sixty": 60,
    "seventy": 70,
    "eighty": 80,
    "ninety": 90,
    "hundred": 100,
    "thousand": 1000,
}
_W = "|".join(_WORDS)
_WORD_RUN = re.compile(
    rf"\b(?:{_W})(?:(?:[ -]|(?<=hundred) and |(?<=thousand) and )(?:{_W}))*\b", re.I
)
# "one" is usually not a count, so alone it counts only before these or a fact.
_ONE_COUNTS = re.compile(r"[ -](?:car|story|level|floor)\b", re.I)

_BED = r"bed(?:room)?s?|bdrms?\b|br\b|bd\b"
_BATH = r"bath(?:room)?s?(?!tub)|ba\b"
_SQFT = r"sq(?:uare)?\.?[ -]*(?:f(?:ee|oo)t|ft)\b\.?|sqft\b|sf\b"
# Words between a number and its noun, as in "2 sunny bedrooms". These end the
# reach, so "2 parking spaces near the bedrooms" is not a count of bedrooms.
_STOP = (
    r"(?:with|and|or|near|in|of|to|plus|per|for|a|an|the|car|cars|story|stories|level|levels|"
    rf"floor|floors|parking|spaces?|{_BED}|{_BATH})\b"
)
_REACH = rf"[\s-]*(?:(?!{_STOP})[a-z'-]+,?\s+){{0,2}}?"
_FOLLOWED_BY = {
    "bedrooms": re.compile(rf"{_REACH}(?:{_BED})", re.I),
    "bathrooms": re.compile(rf"{_REACH}(?:{_BATH})", re.I),
    "square_feet": re.compile(rf"{_REACH}(?:{_SQFT})", re.I),
    "deposit_usd": re.compile(r"\s*(?:dollars?\s+)?(?:security\s+)?deposit\b", re.I),
    "rent_monthly_usd": re.compile(
        r"\s*(?:dollars?\s*)?(?:(?:per|a|each|every)\s+month\b|/\s*mo(?:nth)?\b|monthly\b|rent\b)",
        re.I,
    ),
}
_PRECEDED_BY = {
    "bedrooms": re.compile(r"bed(?:room)?s?\s*(?::|=|\bis\b|\bare\b|\bof\b)\s*$", re.I),
    "bathrooms": re.compile(r"bath(?:room)?s?\s*(?::|=|\bis\b|\bare\b|\bof\b)\s*$", re.I),
    "square_feet": re.compile(
        r"(?:square foot(?:age)?|sq\.?\s*ft\.?|square feet)\s*(?::|=|\bis\b|\bof\b)\s*$", re.I
    ),
    "deposit_usd": re.compile(r"deposit(?:\s+(?:is|of))?\s*:?\s*\$?\s*$", re.I),
    "rent_monthly_usd": re.compile(
        r"\brent(?:s|ing)?(?:\s+(?:is|of|at|for))?\s*:?\s*\$?\s*$", re.I
    ),
}
_FACT_NAMES = {
    "bedrooms": "bedrooms",
    "bathrooms": "bathrooms",
    "square_feet": "square feet",
    "deposit_usd": "the deposit",
    "rent_monthly_usd": "the rent",
}
_MONEY_AFTER = re.compile(r"\s*dollars?\b", re.I)

# Each group is one amenity and its plain synonyms. A group named in a text
# must have some member in the facts. A term outside this list goes unseen,
# which is why the page and report state this check's reach. An attached or
# detached garage is its own group: the facts saying "garage" do not say which.
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
    ["detached garage"],
    ["attached garage"],
    ["carport"],
    ["parking"],
    ["driveway"],
    ["basement"],
    ["attic"],
    ["storage"],
    ["pool", "swimming pool"],
    ["gym", "fitness center", "fitness room"],
    ["clubhouse"],
    ["sauna"],
    ["hot tub", "hot-tub", "jacuzzi", "whirlpool"],
    ["rooftop", "roof deck", "terrace"],
    ["tennis court", "tennis courts"],
    ["playground"],
    ["dog park"],
    ["ev charging", "ev charger"],
    ["fire pit"],
    ["gazebo"],
    ["sunroom"],
    ["home theater"],
    ["game room"],
    ["solar panels"],
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


def _word_value(run: str) -> float:
    total = current = 0
    for word in re.split(r"[ -]|\band\b", run.lower()):
        if not word:
            continue
        value = _WORDS[word]
        if value == 100:
            current = max(current, 1) * 100
        elif value == 1000:
            total += max(current, 1) * 1000
            current = 0
        else:
            current += value
    return float(total + current)


def _numbers(text: str) -> list[tuple[int, int, float, str]]:
    """(start, end, value, as written) for every digit number and number word."""
    found = [
        (m.start(), m.end(), float(m.group(0).replace(",", "")), m.group(0))
        for m in _DIGITS.finditer(text)
    ]
    found += [
        (m.start(), m.end(), _word_value(m.group(0)), m.group(0)) for m in _WORD_RUN.finditer(text)
    ]
    return sorted(found)


def _fact_beside(text: str, start: int, end: int) -> str | None:
    """Which fact this number sits next to, if any. What follows it wins."""
    for key, pattern in _FOLLOWED_BY.items():
        if pattern.match(text, end):
            return key
    for key, pattern in _PRECEDED_BY.items():
        if pattern.search(text[:start]):
            return key
    return None


def _other_numbers(facts: dict) -> set[float]:
    """Numbers written in the facts' free text. Only these may stand beside no fact."""
    allowed: set[float] = set()
    for text in [facts.get("pet_policy"), *facts.get("amenities", [])]:
        for raw in _DIGITS.findall(str(text or "")):
            allowed.add(float(raw.replace(",", "")))
    return allowed


def _without_the_date(text: str, facts: dict) -> str:
    """Blank out the available date in the forms people write it, so its day and
    year are not free numbers: with a date of the 15th, "15 closets" still fails."""
    raw = str(facts.get("available_date") or "")
    if not raw:
        return text
    forms = [raw]
    try:
        day = date.fromisoformat(raw)
    except ValueError:
        day = None
    if day:
        month, short = day.strftime("%B"), day.strftime("%b")
        for name in (month, short):
            forms += [f"{name} {day.day}, {day.year}", f"{name} {day.day}"]
        forms += [f"{day.month}/{day.day}/{day.year}", f"{day.month}/{day.day}"]
    for form in forms:
        text = re.sub(re.escape(form), lambda m: " " * len(m.group(0)), text, flags=re.I)
    return text


def _number_failures(text: str, facts: dict) -> list[str]:
    failures = []
    text = _without_the_date(text, facts)
    other = _other_numbers(facts)
    money = {
        float(facts[k]) for k in ("rent_monthly_usd", "deposit_usd") if facts.get(k) is not None
    }
    for start, end, value, raw in _numbers(text):
        key = _fact_beside(text, start, end)
        if key:
            fact = facts.get(key)
            if fact is None or float(fact) != value:
                said = "none" if fact is None else fact
                failures.append(
                    f"number not in the facts: {raw} next to {_FACT_NAMES[key]}, "
                    f"the facts say {said}"
                )
        elif text[max(0, start - 1) : start] == "$" or _MONEY_AFTER.match(text, end):
            if value not in money:
                failures.append(f"number not in the facts: {raw} as money")
        elif raw.lower() == "one" and not _ONE_COUNTS.match(text, end):
            continue
        elif value not in other:
            failures.append(f"number not in the facts: {raw}")
    return failures


def check_facts(text: str, facts: dict) -> list[str]:
    """Bed, bath, rent, deposit and square-foot numbers must equal the fact they
    sit next to. Any other number must be written in the facts' free text. Every
    listed amenity term must be in the facts."""
    failures = _number_failures(text, facts)
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
