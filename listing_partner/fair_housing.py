"""Fixed list of words that say who should or should not live somewhere.

This list is a screen, not legal advice. A clean result means no listed phrase
was found, not that a text is compliant, so both models also review every text
and a person approves before posting.

Built for contract 03, as amended Nov 2, from:
- 42 U.S.C. 3604(c): no advertisement may state a preference, limitation or
  discrimination based on race, color, religion, sex, handicap, familial
  status or national origin.
- 24 CFR 100.75: words or phrases that convey dwellings are available or not
  available to a particular group, and expressing a preference or limitation.

Background only: HUD's January 9, 1995 advertising guidance (the Achtenberg
memo). Its text could not be retrieved from hud.gov during the build, so its
examples were NOT checked against this list. The phrases are a builder's
selection under these sources.
"""

from __future__ import annotations

import re

SOURCES = [
    "42 U.S.C. 3604(c)",
    "24 CFR 100.75",
    "HUD advertising guidance, January 9, 1995 (Achtenberg memo); background only, not retrieved",
]

_FAMILY = (
    r"couples?|(?<!single[- ])(?<!multi[- ])famil(?:y|ies)(?! room)|kids?|child(?:ren)?|minors?|"
    r"teens?|teenagers?|toddlers?|infants?|bab(?:y|ies)|"
    r"singles?(?![- ](?:family|level|story|car))|single (?:persons?|people)|bachelors?|"
    r"bachelorettes?|newlyweds|adults?|students?|(?:\w+ )?professionals?"
)
_AGE = r"retirees?|seniors?|elderly|empty[- ]nesters?"
_SEX = r"men|man|women|woman|males?|females?|lad(?:y|ies)|gentlem[ae]n|girls|boys"
_RACE = r"whites?|blacks?|caucasians?|african[- ]americans?|asians?|hispanics?|latinos?"
_RELIGION = r"christians?|catholics?|protestants?|jewish|jews?|muslims?|mormons?|hindus?|buddhists?"
_ORIGIN = r"english[- ]speak(?:ing|ers?)|citizens?|immigrants?|foreigners?|american[- ]born"
_GAP = r"(?:[\w'-]+ ){0,3}"
_OCCUPANT = r"roommates?|housemates?|tenants?|renters?|residents?|occupants?|applicants?"
# Who a "no ..." may name: "no seniors", "no young children", "no pets or children".
_DENIED = (
    r"kids?|child(?:ren)?|minors?|teens?|teenagers?|toddlers?|infants?|bab(?:y|ies)|"
    r"famil(?:y|ies)(?! room)|couples?|singles|adults?|students?|retirees?|seniors?|elderly"
)
_NOT_LET_IN = r"(?:not (?:allowed|permitted|welcome|accepted)|prohibited|forbidden|barred)"


def _aimed_at(group: str) -> list[str]:
    """Wording that points a home at a group or away from it. Up to three words
    may sit before the group: "a busy working couple"."""
    return [
        rf"(?:perfect|ideal|great|good|best|suited|suitable|made|wonderful|designed|intended|meant)"
        rf" (?:for|to) {_GAP}(?:{group})",
        rf"not (?:for|(?:suitable|suited|intended|meant|designed|appropriate|recommended)"
        rf" (?:for|to)) {_GAP}(?:{group})",
        rf"(?:unsuitable|inappropriate) for {_GAP}(?:{group})",
        rf"(?:{group})[- ]only",
        rf"(?:{group}) (?:(?:are|is) )?(?:\w+ly )?(?:preferred|preference)",
        rf"(?:preferred|preference|prefers?)(?: (?:{_OCCUPANT}):?)?"
        rf"(?: (?:(?:will be |shall be |is )?given )?(?:for|to))? {_GAP}(?:{group})",
        rf"(?:{group}) (?:(?:are|is) )?{_NOT_LET_IN}",
        rf"(?:{group}) (?:(?:are|is|all|always) )*welcome",
        rf"(?:{group})[- ]friendly",
    ]


_GROUPS = {
    "familial status": [
        rf"no (?:[\w'-]+(?: or|,)? ){{0,2}}(?:{_DENIED})",
        r"adult (?:community|building|living)",
        r"single (?:persons?|people|occupants?|tenants?|residents?) only",
        r"child[- ]free",
        r"(?:young|growing) (?:famil(?:y|ies)|kids|children)",
        *_aimed_at(_FAMILY),
    ],
    "age steering": [
        r"mature(?! (?:trees?|landscaping|shade|gardens?|plantings?|oaks?|maples?))",
        r"young (?:professionals?|couples?|people|adults?|tenants?|residents?)",
        r"older (?:tenants?|residents?|adults?|persons?)",
        r"senior (?:living|community)",
        r"empty[- ]nesters?",
        *_aimed_at(_AGE),
    ],
    "race or color": [
        r"no (?:whites?|blacks?|caucasians?|asians?|hispanics?|latinos?)",
        r"(?:white|black|caucasian|hispanic|asian) (?:neighborhood|community|area|tenants?|family)",
        r"integrated (?:neighborhood|community)",
        r"segregated",
        *_aimed_at(_RACE),
    ],
    "religion": [
        rf"{_RELIGION}",
        rf"(?:{_RELIGION})[- ]only",
        r"sikhs?",
        r"church[- ]going",
        r"god[- ]fearing",
    ],
    "national origin": [
        r"english[- ]only",
        r"must speak english",
        r"citizens? only",
        r"no (?:immigrants?|foreigners?)",
        r"american[- ]born",
        r"(?:mexican|irish|italian|polish|arab|chinese|indian) (?:neighborhood|community|family)",
        *_aimed_at(_ORIGIN),
    ],
    "sex": [
        r"no (?:men|males?|women|females?)",
        r"single (?:man|woman|male|female|mother|father|dad|mom)",
        rf"(?:male|female|men|women|man|woman) (?:{_OCCUPANT})",
        *_aimed_at(_SEX),
    ],
    "disability": [
        r"no wheelchairs?",
        r"able[- ]bodied",
        r"must be able to (?:climb|walk|use)",
        r"physically fit",
        r"no (?:handicapped|disabled|disabilities|crutches|walkers)",
        r"not (?:suitable|suited) for (?:the )?(?:handicapped|disabled|wheelchairs?)",
        r"no mental(?:ly)? ill(?:ness)?",
        # About people it fails. About the building it describes a feature.
        r"handicapped(?![- ](?:accessible|accessibility|access|parking|ramps?|bathrooms?|"
        r"entrances?|showers?|features?))",
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
