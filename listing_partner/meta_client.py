"""The single spend-capped gateway for every Meta Model API call.

Every model call in this product goes through :func:`call_meta_text`. No
other module should import an HTTP client to reach Meta. That rule lives
here as a convention; the check command does not scan for it. See
contracts/01-hdr-merge-and-meta-client.md section B.
"""

from __future__ import annotations

import fcntl
import json
import math
import os
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path

# Hard cap on lifetime Meta spend, in USD. This is a plain constant on
# purpose: no environment variable, flag, or config file may raise it.
# Changing the cap means editing this line (and needs Erik's yes).
SPEND_CAP_USD = 100.0

# Base URL of the Meta Model API (dev.meta.ai/docs/authentication, read
# 2026-10-26): every request carries the key as a Bearer token in the
# Authorization header.
API_BASE_URL = "https://api.meta.ai/v1"

# Price table. Source: https://dev.meta.ai/docs/pricing-rate-limits, read
# 2026-10-26. Token prices are USD per 1M tokens; image/frame prices are
# flat per unit. Contributor-mode variants are deliberately absent: this
# product never sends data under terms that allow training on it.
PRICE_SOURCE_URL = "https://dev.meta.ai/docs/pricing-rate-limits"
PRICE_SOURCE_DATE = "2026-10-26"
PRICES = {
    "muse-spark-1.3": {
        "input_per_mtok": 1.25,
        "cached_input_per_mtok": 0.15,
        "output_per_mtok": 4.25,
    },
    "muse-spark-1.2": {
        "input_per_mtok": 1.25,
        "cached_input_per_mtok": 0.15,
        "output_per_mtok": 4.25,
    },
    "muse-spark-1.1": {
        "input_per_mtok": 1.25,
        "cached_input_per_mtok": 0.15,
        "output_per_mtok": 4.25,
    },
    "sam-3.1": {"image_usd": 2.50 / 1000, "video_frame_usd": 0.20 / 1000},
    "muse-image-1.0": {"image_usd": 0.01},
}

# First-party Meta models only. Exact ids from
# https://dev.meta.ai/docs/models (read 2026-10-26). Anything else,
# including every Contributor-mode variant, is refused.
MODEL_ALLOWLIST = (
    "muse-spark-1.3",
    "muse-spark-1.2",
    "muse-spark-1.1",
    "sam-3.1",
    "muse-image-1.0",
)

# Text models bill per token; these ids take token usage.
_TOKEN_MODELS = ("muse-spark-1.3", "muse-spark-1.2", "muse-spark-1.1")

# Name of the only environment variable the key is ever read from.
KEY_ENV_VAR = "META_API_KEY"


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def default_ledger_path() -> Path:
    return _repo_root() / ".spend" / "ledger.jsonl"


class MetaRefused(Exception):
    """The call was refused before any money moved. Fail closed."""


class ModelNotAllowed(MetaRefused):
    """The model id is not on the first-party allowlist."""


class UnknownPrice(MetaRefused):
    """The allowlisted model has no row in the price table."""


class MissingKey(MetaRefused):
    """META_API_KEY is not set."""


class LedgerError(MetaRefused):
    """The ledger is unreadable, corrupt, or holds an invalid cost."""


class CapReached(MetaRefused):
    """The ledger total has already reached the $100 cap."""


class WouldCrossCap(MetaRefused):
    """This call's worst-case cost would push the total past $100."""


class TransportFailed(MetaRefused):
    """The HTTP call failed; the ledger reservation is kept."""


def estimate_text_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    """Estimated USD for a text-model call from token counts."""
    price = PRICES.get(model)
    if price is None or "input_per_mtok" not in price:
        raise MetaRefused(f"unknown price for model {model!r}")
    return (
        input_tokens * price["input_per_mtok"] / 1e6
        + output_tokens * price["output_per_mtok"] / 1e6
    )


def _checked_amount(value, what: str) -> float:
    """A ledger cost must be finite and non-negative. NaN, infinities,
    negatives, and non-numbers all fail closed."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise LedgerError(f"ledger has non-numeric {what}: {value!r}")
    if not math.isfinite(value) or value < 0:
        raise LedgerError(f"ledger has invalid {what}: {value!r}")
    return float(value)


def _read_total(handle) -> float:
    """Sum the ledger. Raises LedgerError when it cannot be read.

    Each call appends two lines (reservation, then settlement) sharing one
    call_id. A settled call counts once at its actual cost; a call with only
    a reservation line (possibly a crashed call) counts at the estimate.
    Lines without a call_id count on their own (actual, else estimate).
    """
    try:
        handle.seek(0)
        raw = handle.read()
    except OSError as exc:
        raise LedgerError(f"ledger unreadable: {exc}") from exc
    by_call: dict[str, dict] = {}
    orphan = 0.0
    for lineno, text in enumerate(raw.splitlines(), 1):
        if not text.strip():
            continue
        try:
            line = json.loads(text)
        except ValueError as exc:
            raise LedgerError(f"ledger corrupt at line {lineno}") from exc
        if not isinstance(line, dict):
            raise LedgerError(f"ledger corrupt at line {lineno}: not an object")
        try:
            estimated = _checked_amount(line.get("estimated_usd", 0.0), "estimated_usd")
            raw_actual = line.get("actual_usd")
            actual = None if raw_actual is None else _checked_amount(raw_actual, "actual_usd")
        except LedgerError as exc:
            raise LedgerError(f"ledger invalid at line {lineno}: {exc}") from exc
        call_id = line.get("call_id")
        if not call_id:
            orphan += actual if actual is not None else estimated
            continue
        slot = by_call.setdefault(call_id, {"estimated": 0.0, "actual": None})
        slot["estimated"] = max(slot["estimated"], estimated)
        if actual is not None:
            slot["actual"] = actual
    total = orphan
    for slot in by_call.values():
        total += slot["actual"] if slot["actual"] is not None else slot["estimated"]
    return total


def _default_transport(url: str, headers: dict, body: bytes) -> dict:
    """Real HTTPS transport. Returns the decoded JSON response."""
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    with urllib.request.urlopen(request, timeout=120) as response:
        return json.loads(response.read().decode("utf-8"))


def reserve_text_usd(model: str, prompt: str, max_output_tokens: int) -> float:
    """Worst-case USD this request is allowed to cost.

    Input side: a byte-level tokenizer emits at most one token per byte, so
    the prompt's byte length bounds its token count from above, whatever the
    real tokenizer counts. Output side: the full output limit at the output
    price (the limit is sent on every call, so the API cannot return more).
    Refusing on this bound means the settled total can never pass the cap.
    """
    price = PRICES.get(model)
    if price is None or "input_per_mtok" not in price:
        raise UnknownPrice(f"unknown price for model {model!r}")
    if max_output_tokens < 0:
        raise MetaRefused(f"max_output_tokens must be >= 0, got {max_output_tokens}")
    worst_input = max(1, len(prompt.encode("utf-8")))
    return (
        worst_input * price["input_per_mtok"] / 1e6
        + max_output_tokens * price["output_per_mtok"] / 1e6
    )


def call_meta_text(
    model: str,
    prompt: str,
    max_output_tokens: int = 256,
    *,
    transport=None,
    ledger_path: Path | None = None,
) -> dict:
    """Make one minimal text-model call through the spend cap.

    Returns the response's text. Refuses (raising a MetaRefused subclass
    that names the reason) when the key is missing, the model is not
    allowlisted, its price is unknown, the ledger cannot be read, or the
    cap is reached / would be crossed. A reservation sized at the request's
    worst-case cost is appended to the ledger before the HTTP call and a
    settlement line is appended after; a crash anywhere in between leaves
    the reservation counted, never less.
    """
    if model not in MODEL_ALLOWLIST:
        raise ModelNotAllowed(f"model {model!r} is not on the first-party allowlist")
    if model not in PRICES:
        raise UnknownPrice(f"unknown price for model {model!r}")

    key = os.environ.get(KEY_ENV_VAR)
    if not key:
        raise MissingKey(f"{KEY_ENV_VAR} is not set")

    path = Path(ledger_path) if ledger_path is not None else default_ledger_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        handle = open(path, "a+", encoding="utf-8")  # noqa: PTH123 - intentional low-level open for locking
    except OSError as exc:
        raise LedgerError(f"ledger unreadable: {exc}") from exc

    call_id = uuid.uuid4().hex
    with handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        except OSError as exc:
            raise LedgerError(f"ledger lock failed: {exc}") from exc
        total = _read_total(handle)
        if total >= SPEND_CAP_USD:
            raise CapReached(f"spend cap reached: ${total:.4f} of ${SPEND_CAP_USD:.2f}")
        estimated = reserve_text_usd(model, prompt, max_output_tokens)
        if not math.isfinite(estimated) or estimated < 0:
            raise LedgerError(f"refusing to reserve invalid cost: {estimated!r}")
        if total + estimated > SPEND_CAP_USD:
            raise WouldCrossCap(
                f"call would cross the cap: ${total:.4f} + ${estimated:.4f} > ${SPEND_CAP_USD:.2f}"
            )
        reservation = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "model": model,
            "estimated_usd": round(estimated, 6),
            "actual_usd": None,
            "request_id": None,
            "call_id": call_id,
            "status": "reserved",
        }
        try:
            handle.write(json.dumps(reservation) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        except OSError as exc:
            raise LedgerError(f"ledger write failed: {exc}") from exc

        url = f"{API_BASE_URL}/responses"
        headers = {
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        }
        # The output limit rides along so the API cannot return (and bill)
        # more output tokens than the reservation covers.
        body = json.dumps(
            {"model": model, "input": prompt, "max_output_tokens": max_output_tokens}
        ).encode("utf-8")

        do_call = transport if transport is not None else _default_transport
        try:
            response = do_call(url, headers, body)
        except MetaRefused:
            raise
        except Exception as exc:  # noqa: BLE001 - reservation must survive any transport failure
            raise TransportFailed(f"transport failed; reservation kept: {exc}") from exc

        actual, request_id = _reconcile_text(model, response)
        if actual <= 0:
            # The API returned no usable cost or usage: stay conservative
            # and settle at the reserved estimate rather than $0.
            actual = estimated
        try:
            _settle(handle, call_id, model, estimated, actual, request_id)
        except LedgerError:
            raise
        except Exception as exc:  # noqa: BLE001 - a settle crash keeps the reservation
            raise MetaRefused(f"settlement failed; reservation kept: {exc}") from exc
        try:
            text = _response_text(response)
        except (KeyError, TypeError, IndexError) as exc:
            raise MetaRefused(f"unrecognized API response shape: {exc}") from exc
        return {"text": text, "actual_usd": actual, "request_id": request_id}


def _reconcile_text(model: str, response: dict) -> tuple[float, str | None]:
    """Real cost for a text call: API-reported cost wins, else usage."""
    if isinstance(response.get("cost_usd"), (int, float)):
        return float(response["cost_usd"]), response.get("id")
    usage = response.get("usage") or {}
    price = PRICES[model]
    actual = (
        float(usage.get("input_tokens", 0)) * price["input_per_mtok"] / 1e6
        + float(usage.get("cached_input_tokens", 0)) * price["cached_input_per_mtok"] / 1e6
        + float(usage.get("output_tokens", 0)) * price["output_per_mtok"] / 1e6
    )
    return actual, response.get("id")


def _response_text(response: dict) -> str:
    # Responses API shape: {output: [{content: [{text: ...}]}]}; accept a
    # plain {"text": ...} from test doubles as well.
    if isinstance(response.get("text"), str):
        return response["text"]
    parts = []
    for item in response.get("output", []):
        for block in item.get("content", []):
            if isinstance(block.get("text"), str):
                parts.append(block["text"])
    if not parts:
        raise KeyError("no text in response")
    return "".join(parts)


def _settle(
    handle,
    call_id: str,
    model: str,
    estimated: float,
    actual: float,
    request_id: str | None,
) -> None:
    """Append a settlement line for our reservation. Never rewrites the
    file in place: a crash here leaves the reservation line counted, so the
    total can only stay the same, never drop."""
    if (
        isinstance(actual, bool)
        or not isinstance(actual, (int, float))
        or not math.isfinite(actual)
        or actual < 0
    ):
        raise LedgerError(f"refusing to settle invalid cost: {actual!r}")
    settlement = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "model": model,
        "estimated_usd": round(estimated, 6),
        "actual_usd": round(float(actual), 6),
        "request_id": request_id,
        "call_id": call_id,
        "status": "complete",
    }
    handle.write(json.dumps(settlement) + "\n")
    handle.flush()
    os.fsync(handle.fileno())


def read_spend_total(ledger_path: Path | None = None) -> float:
    """Current total (actuals where settled, estimates where reserved).

    A missing file means no call has ever been recorded: $0. Anything
    present but unreadable, corrupt, or holding an invalid cost raises
    LedgerError instead of reading as $0.
    """
    path = Path(ledger_path) if ledger_path is not None else default_ledger_path()
    try:
        with open(path, encoding="utf-8") as handle:  # noqa: PTH123
            return _read_total(handle)
    except FileNotFoundError:
        return 0.0
    except OSError as exc:
        raise LedgerError(f"ledger unreadable: {exc}") from exc
