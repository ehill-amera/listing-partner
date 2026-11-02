"""The facts file is the interface. No AppFolio code lives here: the connector
that fills facts/unit-a.json existed before the hackathon and is run by hand."""

from __future__ import annotations

import json
from pathlib import Path

# The contract's place for this is facts/sample.json. The pre-commit hook
# refuses every path under facts/, so it is tracked here until that is settled.
SAMPLE_FACTS_PATH = Path(__file__).parent / "sample_data" / "facts_sample.json"

_SENT = (
    "bedrooms",
    "bathrooms",
    "square_feet",
    "rent_monthly_usd",
    "deposit_usd",
    "available_date",
    "amenities",
    "pet_policy",
    "property_type",
    "city",
    "state",
)
_REQUIRED = ("bedrooms", "bathrooms", "square_feet", "rent_monthly_usd", "amenities")
#: A demo set is someone's home, not for rent. Its price and size stay out on purpose.
_REQUIRED_DEMO = ("bedrooms", "bathrooms", "amenities")
_ALLOWED = set(_SENT) | {"source", "unit"}


class FactsError(ValueError):
    """The facts file is missing, unreadable or holds a field it must not."""


def load_facts(path) -> dict:
    """Refuses any field outside the contract's list, so an address or a name
    added to the file by mistake never reaches a prompt or a page."""
    try:
        facts = json.loads(Path(path).read_text())
    except (OSError, ValueError) as exc:
        raise FactsError(f"facts file unreadable: {type(exc).__name__}") from exc
    if not isinstance(facts, dict):
        raise FactsError("facts file is not an object")
    extra = sorted(set(facts) - _ALLOWED)
    if extra:
        raise FactsError(f"facts file holds fields outside the contract: {extra}")
    required = _REQUIRED_DEMO if is_demo(facts) else _REQUIRED
    missing = [k for k in required if facts.get(k) is None]
    if missing:
        raise FactsError(f"facts file is missing: {missing}")
    return facts


def prompt_facts(facts: dict) -> dict:
    """Only the fields models may see. Empty fields stay out."""
    return {k: facts[k] for k in _SENT if facts.get(k) not in (None, [], "")}


def is_sample(facts: dict) -> bool:
    return str(facts.get("source", "")).upper().startswith("SAMPLE")


def is_demo(facts: dict) -> bool:
    return str(facts.get("source", "")).upper().startswith("DEMO")
