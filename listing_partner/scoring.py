"""Deterministic checks, the same for every text from either model."""

from __future__ import annotations

import math
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
# "one and a half", "1-and-a-half": the half belongs to the number before it.
_AND_A_HALF = re.compile(r"[\s-]+and[\s-]+(?:a|one)[\s-]+half\b", re.I)
_ORDINALS = {
    "first": 1,
    "second": 2,
    "third": 3,
    "fourth": 4,
    "fifth": 5,
    "sixth": 6,
    "seventh": 7,
    "eighth": 8,
    "ninth": 9,
    "tenth": 10,
}
_ORDINAL_WORD = re.compile(rf"\b(?:{'|'.join(_ORDINALS)})\b", re.I)
_ORDINAL_SUFFIX = re.compile(r"(?:st|nd|rd|th)\b", re.I)

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
_LONE_HALF = re.compile(r"(?<!and a )(?<!and one )(?<!and-a-)(?<!and-one-)\bhalf(?=[\s-])", re.I)
_FOLLOWED_BY = {
    "bedrooms": re.compile(rf"{_REACH}(?:{_BED})", re.I),
    "bathrooms": re.compile(rf"{_REACH}(?:{_BATH})", re.I),
    "square_feet": re.compile(rf"{_REACH}(?:{_SQFT})", re.I),
    "deposit_usd": re.compile(r"\s*(?:(?:dollars?|usd)\s+)?(?:security\s+)?deposit\b", re.I),
    "rent_monthly_usd": re.compile(
        r"\s*(?:(?:dollars?|usd)\s*)?(?:(?:per|a|each|every)\s+month\b|/\s*mo(?:nth)?\b|monthly\b|rent\b)",
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
_MONEY_AFTER = re.compile(r"\s*(?:dollars?|usd)\b", re.I)
_MONEY_BEFORE = re.compile(r"(?:\$|\busd\s*)$", re.I)

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


def _term_pattern(term: str) -> str:
    """A term in its plural and with spaces or hyphens between its words. The
    same pattern reads the text and the facts, so neither side is favored."""
    words = re.split(r"[\s-]+", term)
    last = words[-1]
    if last.endswith("y") and last[-2:-1] not in "aeiou":
        end = re.escape(last[:-1]) + "(?:y|ies)"
    elif last.endswith("s"):
        end = re.escape(last)
    else:
        end = re.escape(last) + "(?:s|es)?"
    return r"[\s-]+".join([*map(re.escape, words[:-1]), end])


def _has(term: str, text: str) -> bool:
    return re.search(rf"(?<!\w){_term_pattern(term)}(?!\w)", text, re.I) is not None


_CLAUSE_END = re.compile(r"[,;.!?\n]|\bbut\b", re.I)
_NEGATED = re.compile(
    r"\b(?:no|not(?! only\b| just\b)|non|none|never|without|excludes?|excluded|prohibited|"
    r"forbidden|cannot|can't|isn't|aren't|doesn't|don't)\b",
    re.I,
)


def _said_and_denied(text: str) -> tuple[str, str]:
    """A text split into the clauses that state something and the clauses that
    deny it, so "No pets allowed" is never read as pets being there."""
    said, denied = [], []
    for clause in _CLAUSE_END.split(text):
        (denied if _NEGATED.search(clause) else said).append(clause)
    return " ; ".join(said), " ; ".join(denied)


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
    out: list[tuple[int, int, float, str]] = []
    reached = 0
    for start, end, value, raw in sorted(found):
        if start < reached:  # the "one" of "and one half"
            continue
        half = _AND_A_HALF.match(text, end)
        if half:
            start, end, value, raw = start, half.end(), value + 0.5, text[start : half.end()]
        out.append((start, end, value, raw))
        reached = end
    return out


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
        suffix = _ORDINAL_SUFFIX.match(text, end)
        key = _fact_beside(text, start, suffix.end() if suffix else end)
        if suffix and key in ("bedrooms", "bathrooms"):
            # "the 2nd bedroom" is true of any home with at least 2.
            if facts.get(key) is None or value > math.ceil(float(facts[key])):
                failures.append(_beside_failure(raw + suffix.group(0), key, facts))
        elif key:
            fact = facts.get(key)
            if fact is None or float(fact) != value:
                failures.append(_beside_failure(raw, key, facts))
        elif _MONEY_BEFORE.search(text[:start]) or _MONEY_AFTER.match(text, end):
            if value not in money:
                failures.append(f"number not in the facts: {raw} as money")
        elif raw.lower() == "one" and not _ONE_COUNTS.match(text, end):
            continue
        elif value not in other:
            failures.append(f"number not in the facts: {raw}")
    return failures + _ordinal_and_half_failures(text, facts)


def _beside_failure(raw: str, key: str, facts: dict) -> str:
    said = "none" if facts.get(key) is None else facts[key]
    return f"number not in the facts: {raw} next to {_FACT_NAMES[key]}, the facts say {said}"


def _bed_or_bath_after(text: str, end: int) -> str | None:
    for key in ("bedrooms", "bathrooms"):
        if _FOLLOWED_BY[key].match(text, end):
            return key
    return None


def _ordinal_and_half_failures(text: str, facts: dict) -> list[str]:
    """ "a second bathroom" says at least 2. "a half bath" says the count has a half."""
    failures = []
    for match in _ORDINAL_WORD.finditer(text):
        key = _bed_or_bath_after(text, match.end())
        rank = _ORDINALS[match.group(0).lower()]
        if key and (facts.get(key) is None or rank > math.ceil(float(facts[key]))):
            failures.append(_beside_failure(match.group(0), key, facts))
    for match in _LONE_HALF.finditer(text):
        key = _bed_or_bath_after(text, match.end())
        if key and (facts.get(key) is None or float(facts[key]) % 1 != 0.5):
            failures.append(_beside_failure(match.group(0), key, facts))
    return failures


def check_facts(text: str, facts: dict) -> list[str]:
    """Bed, bath, rent, deposit and square-foot numbers must equal the fact they
    sit next to. Any other number must be written in the facts' free text. An
    amenity a text states must be stated in the facts. One it denies must be
    denied in the facts, and a fact that denies an amenity never counts as it."""
    failures = _number_failures(text, facts)
    source = " ; ".join(
        str(x)
        for x in [*facts.get("amenities", []), facts.get("pet_policy"), facts.get("property_type")]
        if x
    )
    source_said, source_denied = _said_and_denied(source)
    text_said, text_denied = _said_and_denied(text)
    for group in AMENITY_GROUPS:
        for wording, allowed in ((text_said, source_said), (text_denied, source_denied)):
            named = [term for term in group if _has(term, wording)]
            if named and not any(_has(term, allowed) for term in group):
                failures.append(f"amenity not in the facts: {named[0]}")
    return failures


def fact_mentions(text: str, facts: dict) -> dict[str, int]:
    """How many times a text states each fact. A measurement, not a check."""
    scrubbed = _without_the_date(text, facts)
    counts = {
        key: 0
        for key in ("bedrooms", "bathrooms", "square_feet", "rent_monthly_usd", "deposit_usd")
        if facts.get(key) is not None
    }
    for start, end, value, _raw in _numbers(scrubbed):
        key = _fact_beside(scrubbed, start, end)
        if key in counts and value == float(facts[key]):
            counts[key] += 1
        elif (
            not key
            and value == float(facts["rent_monthly_usd"])
            and (_MONEY_BEFORE.search(scrubbed[:start]) or _MONEY_AFTER.match(scrubbed, end))
        ):
            counts["rent_monthly_usd"] += 1
    for key in ("city", "state"):
        if facts.get(key):
            counts[key] = len(re.findall(rf"(?<!\w){re.escape(facts[key])}(?!\w)", text, re.I))
    for amenity in facts.get("amenities", []):
        terms = {
            t for group in AMENITY_GROUPS if any(_has(t, amenity) for t in group) for t in group
        }
        terms = {t for t in terms if _has(t, amenity)} or {amenity}
        forms = "|".join(_term_pattern(t) for t in sorted(terms, key=len, reverse=True))
        counts[f"amenity: {amenity}"] = len(re.findall(rf"(?<!\w)(?:{forms})(?!\w)", text, re.I))
    return counts


def check_description_length(text: str) -> list[str]:
    count = len(text.split())
    return [] if 90 <= count <= 200 else [f"length: {count} words, limit 90 to 200"]


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
