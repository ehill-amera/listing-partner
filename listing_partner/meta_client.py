"""The single spend-capped gateway for every Meta Model API call.

Every model call in this product goes through :func:`call_meta`. No other
module may import an HTTP client to reach Meta (enforced by the check
command). See contracts/01-hdr-merge-and-meta-client.md section B.
"""

from __future__ import annotations

import fcntl
import json
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


def estimate_text_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    """Estimated USD for a text-model call from token counts."""
    price = PRICES.get(model)
    if price is None or "input_per_mtok" not in price:
        raise MetaRefused(f"unknown price for model {model!r}")
    return (
        input_tokens * price["input_per_mtok"] / 1e6
        + output_tokens * price["output_per_mtok"] / 1e6
    )


def _line_total(line: dict) -> float:
    # A line whose actual cost is still null is a live reservation (possibly
    # a crashed call): it counts at the estimated cost.
    actual = line.get("actual_usd")
    if actual is None:
        return float(line.get("estimated_usd", 0.0))
    return float(actual)


def _read_total(handle) -> float:
    """Sum the ledger. Raises MetaRefused when it cannot be read."""
    try:
        handle.seek(0)
        raw = handle.read()
    except OSError as exc:
        raise MetaRefused(f"ledger unreadable: {exc}") from exc
    total = 0.0
    for lineno, text in enumerate(raw.splitlines(), 1):
        if not text.strip():
            continue
        try:
            line = json.loads(text)
            total += _line_total(line)
        except (ValueError, TypeError, AttributeError) as exc:
            raise MetaRefused(f"ledger corrupt at line {lineno}") from exc
    return total


def _default_transport(url: str, headers: dict, body: bytes) -> dict:
    """Real HTTPS transport. Returns the decoded JSON response."""
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    with urllib.request.urlopen(request, timeout=120) as response:
        return json.loads(response.read().decode("utf-8"))


def _approx_input_tokens(text: str) -> int:
    # Rough pre-call estimate only; the real cost reconciles from API usage.
    return max(1, len(text) // 4)


def call_meta_text(
    model: str,
    prompt: str,
    max_output_tokens: int = 256,
    *,
    transport=None,
    ledger_path: Path | None = None,
) -> dict:
    """Make one minimal text-model call through the spend cap.

    Returns the response's text. Refuses (raising MetaRefused) when the key
    is missing, the model is not allowlisted, its price is unknown, the
    ledger cannot be read, or the cap is reached / would be crossed.
    A reservation is appended to the ledger before the HTTP call and
    reconciled to the real cost after; a crash between the two leaves the
    reservation counted.
    """
    if model not in MODEL_ALLOWLIST:
        raise MetaRefused(f"model {model!r} is not on the first-party allowlist")
    if model not in PRICES:
        raise MetaRefused(f"unknown price for model {model!r}")

    key = os.environ.get(KEY_ENV_VAR)
    if not key:
        raise MetaRefused(f"{KEY_ENV_VAR} is not set")

    path = Path(ledger_path) if ledger_path is not None else default_ledger_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        handle = open(path, "a+", encoding="utf-8")  # noqa: PTH123 - intentional low-level open for locking
    except OSError as exc:
        raise MetaRefused(f"ledger unreadable: {exc}") from exc

    call_id = uuid.uuid4().hex
    with handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        except OSError as exc:
            raise MetaRefused(f"ledger lock failed: {exc}") from exc
        total = _read_total(handle)
        if total >= SPEND_CAP_USD:
            raise MetaRefused(f"spend cap reached: ${total:.4f} of ${SPEND_CAP_USD:.2f}")
        estimated = estimate_text_usd(model, _approx_input_tokens(prompt), max_output_tokens)
        if total + estimated > SPEND_CAP_USD:
            raise MetaRefused(
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
        handle.write(json.dumps(reservation) + "\n")
        handle.flush()

        url = f"{API_BASE_URL}/responses"
        headers = {
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        }
        # Body keeps to the documented fields (dev.meta.ai/docs quickstart):
        # {"model", "input"}. max_output_tokens only sizes the pre-call
        # cost reservation, never goes on the wire.
        body = json.dumps({"model": model, "input": prompt}).encode("utf-8")

        do_call = transport if transport is not None else _default_transport
        try:
            response = do_call(url, headers, body)
        except MetaRefused:
            raise
        except Exception as exc:  # noqa: BLE001 - reservation must survive any transport failure
            raise MetaRefused(f"transport failed; reservation kept: {exc}") from exc

        actual, request_id = _reconcile_text(model, response)
        if actual <= 0:
            # The API returned no usable cost or usage: stay conservative
            # and settle at the reserved estimate rather than $0.
            actual = estimated
        _settle(handle, call_id, actual, request_id)
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


def _settle(handle, call_id: str, actual: float, request_id: str | None) -> None:
    """Rewrite our reservation line with the real cost (one line per call)."""
    handle.seek(0)
    lines = handle.read().splitlines()
    for i, text in enumerate(lines):
        if not text.strip():
            continue
        line = json.loads(text)
        if line.get("call_id") == call_id:
            line["actual_usd"] = round(actual, 6)
            line["request_id"] = request_id
            line["status"] = "complete"
            lines[i] = json.dumps(line)
            break
    handle.seek(0)
    handle.truncate()
    handle.write("\n".join(lines) + "\n")
    handle.flush()


def read_spend_total(ledger_path: Path | None = None) -> float:
    """Current total (actuals where settled, estimates where reserved)."""
    path = Path(ledger_path) if ledger_path is not None else default_ledger_path()
    try:
        with open(path, encoding="utf-8") as handle:  # noqa: PTH123
            return _read_total(handle)
    except FileNotFoundError:
        return 0.0
    except OSError as exc:
        raise MetaRefused(f"ledger unreadable: {exc}") from exc
