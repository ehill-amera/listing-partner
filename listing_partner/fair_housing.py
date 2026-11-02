"""Fixed list of words that say who should or should not live somewhere.

Built for contract 03 from these sources:
- 42 U.S.C. 3604(c): no advertisement may state a preference, limitation or
  discrimination based on race, color, religion, sex, handicap, familial
  status or national origin.
- 24 CFR 100.75(c)(1): words or phrases that convey dwellings are available
  or not available to a particular group. Read 2026-11-02. It gives categories,
  not a word list.
- HUD's January 9, 1995 advertising guidance (the Achtenberg memo). Its text
  could not be retrieved on 2026-11-02, so its specific examples were NOT
  checked against this list. Property descriptions that stay allowed here
  (family room, master bedroom, walk-in closet, near a park, wheelchair ramp)
  come from contract 03's reading of it.

The phrases themselves are a builder's selection, not legal advice. A clean
result means no listed phrase was found, not that a text is compliant, which
is why both models also review every text and a person sees any disagreement.
"""

from __future__ import annotations

import re

SOURCES = [
    "42 U.S.C. 3604(c)",
    "24 CFR 100.75",
    "HUD advertising guidance, January 9, 1995 (Achtenberg memo); text not retrieved",
]

_PEOPLE = (
    r"couples?|famil(?:y|ies)(?! room)|kids|children|singles?|bachelors?|bachelorettes?|"
    r"(?:young |single |working )?professionals?|retirees?|seniors?|students?|newlyweds|"
    r"empty[- ]nesters?|men|women|ladies|gentlemen"
)
_FIT = (
    r"(?:perfect|ideal|great|best|suited|suitable|made|wonderful) for "
    rf"(?:an? |the |your )?(?:{_PEOPLE})"
)

_GROUPS = {
    "familial status": [
        r"no (?:kids|children|minors|teenagers|infants|babies)",
        r"adults? only",
        r"adult (?:community|building|living)",
        r"no famil(?:y|ies)(?! room)",
        r"famil(?:y|ies) only",
        r"couples? only",
        r"singles? only",
        r"family[- ]friendly",
        r"child[- ]free",
        r"not suitable for (?:kids|children|families)",
        _FIT,
    ],
    "age steering": [
        r"mature(?! (?:trees?|landscaping|shade|gardens?|plantings?|oaks?|maples?))",
        r"young (?:professionals?|couples?|people|adults?|tenants?|residents?)",
        r"seniors? only",
        r"retirees? only",
        r"older (?:tenants?|residents?|adults?|persons?)",
        r"senior (?:living|community)",
        r"empty[- ]nesters?",
    ],
    "race or color": [
        r"(?:whites?|blacks?|caucasians?|african[- ]americans?|asians?|hispanics?|latinos?) only",
        r"no (?:whites?|blacks?|caucasians?|asians?|hispanics?|latinos?)",
        r"(?:white|black|caucasian|hispanic|asian) (?:neighborhood|community|area|tenants?|family)",
        r"integrated (?:neighborhood|community)",
        r"segregated",
    ],
    "religion": [
        r"christians?",
        r"catholics?",
        r"protestants?",
        r"jewish",
        r"jews?",
        r"muslims?",
        r"mormons?",
        r"hindus?",
        r"buddhists?",
        r"sikhs?",
        r"church[- ]going",
        r"god[- ]fearing",
    ],
    "national origin": [
        r"english[- ]speak(?:ing|ers?) only",
        r"must speak english",
        r"citizens? only",
        r"no (?:immigrants?|foreigners?)",
        r"american[- ]born",
        r"(?:mexican|irish|italian|polish|arab|chinese|indian) (?:neighborhood|community|family)",
    ],
    "sex": [
        r"(?:men|males?|women|females?|ladies|gentlemen|girls|boys) only",
        r"no (?:men|males?|women|females?)",
        r"single (?:man|woman|male|female|mother|father|dad|mom)",
    ],
    "disability": [
        r"no wheelchairs?",
        r"able[- ]bodied",
        r"must be able to (?:climb|walk|use)",
        r"physically fit",
        r"no (?:handicapped|disabled|disabilities|crutches|walkers)",
        r"not (?:suitable|suited) for (?:the )?(?:handicapped|disabled|wheelchairs?)",
        r"no mental(?:ly)? ill(?:ness)?",
        r"handicapped",
        r"crippled",
    ],
}

PHRASES = [
    {"pattern": pattern, "category": category}
    for category, patterns in _GROUPS.items()
    for pattern in patterns
]
_COMPILED = [(re.compile(rf"\b(?:{p['pattern']})\b", re.I), p["category"]) for p in PHRASES]


def find_phrases(text: str) -> list[dict]:
    """Every listed phrase in the text, with its category."""
    flat = re.sub(r"\s+", " ", text)
    hits = []
    for pattern, category in _COMPILED:
        for match in pattern.finditer(flat):
            hits.append({"phrase": match.group(0), "category": category})
    return hits
