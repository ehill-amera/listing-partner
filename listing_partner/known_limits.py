"""What the automatic screens are known not to see. Shown on the page and in
the report. Every example here is tested to pass the screen it names, so this
list cannot quietly go stale. The screens are a backstop behind two model
reviews and a person's approval before posting."""

from __future__ import annotations

FAIR_HOUSING_MISSES = [
    "a quiet working couple",
    "room for the kids to play",
    "a great place to raise a family",
    "bachelor pad",
    "exclusive community",
    "steps from the church",
    "mom and dad will love it",
    "married only",
]
NUMBER_MISSES = [
    "the second floor",
    "another bathroom",
    "an extra bedroom",
    "bath and a half",
    "one spacious and bright bedroom",
]
AMENITY_MISSES = ["a wine cellar", "heated floors", "dual vanities"]
INVENTED_DETAIL_MISSES = ["steps from downtown", "sunny, spacious rooms"]
OVER_FAILS = ["no shortage of parking"]


def _quoted(examples: list[str]) -> str:
    return ", ".join(f'"{e}"' for e in examples)


LIMITS = [
    "The fair housing screen is a fixed list, not legal advice, and other phrasings get past it, "
    f"such as {_quoted(FAIR_HOUSING_MISSES)}.",
    "The number check reads a number beside its fact. Wording like "
    f"{_quoted(NUMBER_MISSES)} gets past it.",
    "The amenity check knows a fixed list of groups. An amenity outside them gets past it, such "
    f"as {_quoted(AMENITY_MISSES)}.",
    "No check compares a text's room descriptions to Muse Spark's photo notes, so an invented "
    f"detail gets past them, such as {_quoted(INVENTED_DETAIL_MISSES)}.",
    "A check can fail a correct sentence. A clause with a negative word counts as a denial, so "
    f"{_quoted(OVER_FAILS)} fails when the facts list parking.",
    "A person approves every text before posting.",
]
