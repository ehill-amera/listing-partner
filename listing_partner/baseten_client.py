"""The single spend-capped gateway to Baseten (Muse Spark Open).

Same safety shape as meta_client.py, with its own ledger and its own cap.
Nothing else in this product talks to Baseten. Text only: no photos are sent.
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

# Hard cap on lifetime Baseten spend, in USD. A plain constant on purpose:
# no environment variable, flag or config file may raise it.
BASETEN_CAP_USD = 80.0
# Reservations stop $1 below the cap, because a bill can exceed its estimate.
RESERVATION_HEADROOM_USD = 1.0
# Every reservation is the worst case times this.
RESERVATION_MULTIPLIER = 2.0

API_BASE_URL = "https://inference.baseten.co/v1"
KEY_ENV_VAR = "BASETEN_API_KEY"
MODEL = "meta-models/muse-spark-open-1026"
MODEL_ALLOWLIST = (MODEL,)

# USD per 1M tokens. Source: https://www.baseten.co/pricing/ and
# https://www.baseten.co/library/muse-spark-open/, read 2026-11-02. Those
# pages name the model without the -1026 suffix.
PRICES = {MODEL: {"input_per_mtok": 1.25, "cached_input_per_mtok": 0.15, "output_per_mtok": 4.25}}


class BasetenRefused(Exception):
    """Refused before any money moved. Fail closed."""


class ModelNotAllowed(BasetenRefused):
    """The model id is not on the allowlist of one."""


class UnknownPrice(BasetenRefused):
    """The model has no row in the price table."""


class MissingKey(BasetenRefused):
    """BASETEN_API_KEY is not set."""


class LedgerError(BasetenRefused):
    """The ledger is unreadable, corrupt, or holds an invalid cost."""


class CapReached(BasetenRefused):
    """The ledger total has reached the cap."""


class WouldCrossCap(BasetenRefused):
    """This call's reservation would pass the ceiling $1 below the cap."""


class TransportFailed(BasetenRefused):
    """The HTTP call failed; the reservation stays counted."""


class ResponseUnreadable(Exception):
    """Billed, but the reply is missing or cut off. Never a refusal: money moved."""

    def __init__(self, message: str, *, actual_usd: float, request_id: str | None):
        super().__init__(message)
        self.actual_usd = actual_usd
        self.request_id = request_id


def default_ledger_path() -> Path:
    return Path(__file__).resolve().parent.parent / ".spend" / "baseten-ledger.jsonl"


def reserve_text_usd(model: str, prompt: str, max_tokens: int) -> float:
    """Twice the worst case: input tokens cannot exceed the prompt's bytes."""
    price = PRICES.get(model)
    if price is None:
        raise UnknownPrice(f"unknown price for model {model!r}")
    if max_tokens < 0:
        raise BasetenRefused(f"max_tokens must be >= 0, got {max_tokens}")
    worst = (
        max(1, len(prompt.encode("utf-8"))) * price["input_per_mtok"]
        + max_tokens * price["output_per_mtok"]
    ) / 1e6
    return RESERVATION_MULTIPLIER * worst


def _amount(value, what: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise LedgerError(f"ledger has non-numeric {what}: {value!r}")
    if not math.isfinite(value) or value < 0:
        raise LedgerError(f"ledger has invalid {what}: {value!r}")
    return float(value)


def _read_total(handle) -> float:
    """Settled calls count at actual cost, open reservations at the estimate."""
    try:
        handle.seek(0)
        raw = handle.read()
    except (OSError, ValueError) as exc:
        raise LedgerError(f"ledger unreadable: {exc}") from exc
    calls: dict[str, dict] = {}
    for number, text in enumerate(raw.splitlines(), 1):
        if not text.strip():
            continue
        try:
            line = json.loads(text)
        except ValueError as exc:
            raise LedgerError(f"ledger corrupt at line {number}") from exc
        if not isinstance(line, dict) or "estimated_usd" not in line or not line.get("call_id"):
            raise LedgerError(f"ledger corrupt at line {number}")
        slot = calls.setdefault(line["call_id"], {"est": 0.0, "act": None})
        slot["est"] = max(slot["est"], _amount(line["estimated_usd"], "estimated_usd"))
        if line.get("actual_usd") is not None:
            slot["act"] = _amount(line["actual_usd"], "actual_usd")
    return sum(s["act"] if s["act"] is not None else s["est"] for s in calls.values())


def read_spend_total(ledger_path: Path | None = None) -> float:
    """Current total. A missing file is $0; anything else unreadable raises."""
    path = Path(ledger_path) if ledger_path is not None else default_ledger_path()
    try:
        with open(path, encoding="utf-8") as handle:  # noqa: PTH123
            return _read_total(handle)
    except FileNotFoundError:
        return 0.0
    except OSError as exc:
        raise LedgerError(f"ledger unreadable: {exc}") from exc


def _default_transport(url: str, headers: dict, body: bytes) -> dict:
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    with urllib.request.urlopen(request, timeout=180) as response:
        return json.loads(response.read().decode("utf-8"))


def _bill(model: str, response: dict) -> float:
    """From the returned token counts. Cached count clamped so a surprising
    report can only overstate the bill."""
    usage = response.get("usage") or {}
    price = PRICES[model]
    prompt = float(usage.get("prompt_tokens", 0) or 0)
    details = usage.get("prompt_tokens_details") or {}
    cached = min(prompt, float(details.get("cached_tokens", 0) or 0))
    return (
        (prompt - cached) * price["input_per_mtok"]
        + cached * price["cached_input_per_mtok"]
        + float(usage.get("completion_tokens", 0) or 0) * price["output_per_mtok"]
    ) / 1e6


def _write(handle, line: dict) -> None:
    handle.write(json.dumps(line) + "\n")
    handle.flush()
    os.fsync(handle.fileno())


def call_baseten_text(
    model: str,
    prompt: str,
    max_tokens: int = 256,
    *,
    transport=None,
    ledger_path: Path | None = None,
) -> dict:
    """One text call through the cap. Returns text, actual_usd, request_id."""
    if model not in MODEL_ALLOWLIST:
        raise ModelNotAllowed(f"model {model!r} is not on the Baseten allowlist")
    estimated = reserve_text_usd(model, prompt, max_tokens)
    key = os.environ.get(KEY_ENV_VAR)
    if not key:
        raise MissingKey(f"{KEY_ENV_VAR} is not set")
    path = Path(ledger_path) if ledger_path is not None else default_ledger_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        handle = open(path, "a+", encoding="utf-8")  # noqa: PTH123
    except OSError as exc:
        raise LedgerError(f"ledger unreadable: {exc}") from exc
    call_id = uuid.uuid4().hex
    with handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        except OSError as exc:
            raise LedgerError(f"ledger lock failed: {exc}") from exc
        total = _read_total(handle)
        if total >= BASETEN_CAP_USD:
            raise CapReached(f"spend cap reached: ${total:.4f} of ${BASETEN_CAP_USD:.2f}")
        ceiling = BASETEN_CAP_USD - RESERVATION_HEADROOM_USD
        if total + estimated > ceiling:
            raise WouldCrossCap(f"${total:.4f} + ${estimated:.4f} > ${ceiling:.2f}")
        base = {"model": model, "call_id": call_id, "estimated_usd": round(estimated, 6)}
        now = datetime.now(timezone.utc).isoformat
        _write(handle, {**base, "ts": now(), "actual_usd": None, "status": "reserved"})
        body = json.dumps(
            {
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": max_tokens,
            }
        ).encode("utf-8")
        headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
        do_call = transport if transport is not None else _default_transport
        try:
            response = do_call(f"{API_BASE_URL}/chat/completions", headers, body)
        except Exception as exc:  # noqa: BLE001 - the reservation survives any failure
            raise TransportFailed(f"transport failed; reservation kept: {exc}") from exc
        actual = _bill(model, response)
        if actual <= 0:
            # No usable usage: stay conservative, never settle at $0.
            actual = estimated
        request_id = response.get("id")
        stored = round(actual, 6)
        _write(
            handle,
            {
                **base,
                "ts": now(),
                "actual_usd": stored,
                "coverage_ratio": round(base["estimated_usd"] / stored, 4) if stored else None,
                "request_id": request_id,
                "status": "complete",
            },
        )
        try:
            choice = response["choices"][0]
            text = choice["message"]["content"]
            reason = choice.get("finish_reason")
        except (KeyError, IndexError, TypeError) as exc:
            raise ResponseUnreadable(
                f"billed ${actual:.6f} (request {request_id}); no reply: {exc}",
                actual_usd=actual,
                request_id=request_id,
            ) from exc
        if not isinstance(text, str) or not text.strip() or reason == "length":
            raise ResponseUnreadable(
                f"billed ${actual:.6f} (request {request_id}); reply empty or cut off "
                f"(finish_reason={reason})",
                actual_usd=actual,
                request_id=request_id,
            )
        return {"text": text, "actual_usd": actual, "request_id": request_id}
