"""The single spend-capped gateway for every Meta Model API call.

Every model call in this product goes through :func:`call_meta_text`. No
other module should import an HTTP client to reach Meta. That rule lives
here as a convention; the check command does not scan for it. See
contracts/01-hdr-merge-and-meta-client.md section B.
"""

from __future__ import annotations

import base64
import fcntl
import json
import math
import os
import urllib.request
import uuid
from datetime import datetime, timezone
from functools import partial
from pathlib import Path

# Hard cap on lifetime Meta spend, in USD. This is a plain constant on
# purpose: no environment variable, flag, or config file may raise it.
# Changing the cap means editing this line (and needs Erik's yes).
# Lowered from $100 to $40 on 2026-10-29 (Erik's call, contract 02):
# Muse Code's own building draws on the same free credits.
SPEND_CAP_USD = 40.0

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
    """The ledger total has already reached the $40 cap."""


# The reservation ceiling sits $1 below the lifetime cap. A settled bill
# can come in above its reservation (the API reports the real cost), so
# refusing once total + worst case would pass $39 keeps the settled total
# from ever passing $40. Like the lifetime figure, this headroom is a
# plain constant: nothing outside this file may change it.
RESERVATION_HEADROOM_USD = 1.0


class WouldCrossCap(MetaRefused):
    """This call's worst-case cost would push the total past the $39 ceiling."""


class TransportFailed(MetaRefused):
    """The HTTP call failed; the ledger reservation is kept."""


class ResponseUnreadable(Exception):
    """The call was billed but its reply could not be read.

    Deliberately NOT a MetaRefused: a refusal means no money moved, while
    this error means the settlement line is already written and the cost
    counts. This names the billed cost and the request id so the money stays
    visible; when the reply has no text the response status and incomplete
    reason ride along too.
    """

    def __init__(self, message: str, *, actual_usd: float, request_id: str | None):
        super().__init__(message)
        self.actual_usd = actual_usd
        self.request_id = request_id


class SettlementFailed(Exception):
    """The call was billed but its settlement line could not be written.

    Deliberately NOT a MetaRefused: the transport already returned, so the
    money moved and the reservation line stays counted. Reports the billed
    cost and the request id so the money stays visible until a person
    reconciles the ledger.
    """

    def __init__(self, message: str, *, actual_usd: float, request_id: str | None):
        super().__init__(message)
        self.actual_usd = actual_usd
        self.request_id = request_id


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
            if "estimated_usd" not in line:
                raise LedgerError("missing estimated_usd")
            estimated = _checked_amount(line["estimated_usd"], "estimated_usd")
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


# Safety multiplier on every reservation. Docs basis (pricing and
# Responses schemas, read 2026-10-29): text models bill input tokens (which
# can never exceed the prompt's byte length for a single-iteration call
# with no tools) plus output tokens (visible plus reasoning, bounded by
# the max_output_tokens sent on the call), with cached input tokens as a
# subset at the lower cached rate. But unit 1's live calls settled above
# the bare worst case (worst bill-to-reservation ratio 1.065 on current
# code), so the reservation is the docs worst case times this multiplier.
# The $1 headroom stays as a second layer. Every settlement records its
# reservation-to-bill ratio; if any ratio drops below 1, raise this.
RESERVATION_MULTIPLIER = 2.0


def _text_message(prompt: str, images: list[bytes] | None = None) -> list[dict]:
    """User message with optional inline JPEG images (base64 data URLs)."""
    content: list[dict] = [{"type": "input_text", "text": prompt}]
    for raw in images or []:
        encoded = base64.b64encode(raw).decode("ascii")
        content.append({"type": "input_image", "image_url": f"data:image/jpeg;base64,{encoded}"})
    return [{"type": "message", "role": "user", "content": content}]


# Bound on billed input tokens per attached image, from measured calls: a
# 1024x684 JPEG bills ~875 input tokens (2026-10-29), so 4000 covers our
# send sizes (at most ~0.7MP, crops smaller) with margin to spare, and the
# multiplier sits on top.
IMAGE_INPUT_TOKEN_BOUND = 4000


def reserve_text_usd(
    model: str, prompt: str, max_output_tokens: int, image_count: int = 0
) -> float:
    _, _, bound = _text_estimate_parts(model, prompt, max_output_tokens, image_count)
    return bound


def _text_estimate_parts(model, prompt, max_output_tokens, image_count):
    price = PRICES.get(model)
    if price is None or "input_per_mtok" not in price:
        raise UnknownPrice(f"unknown price for model {model!r}")
    if max_output_tokens < 0:
        raise MetaRefused(f"max_output_tokens must be >= 0, got {max_output_tokens}")
    worst_input = max(1, len(prompt.encode("utf-8"))) + image_count * IMAGE_INPUT_TOKEN_BOUND
    base = (
        worst_input * price["input_per_mtok"] / 1e6
        + max_output_tokens * price["output_per_mtok"] / 1e6
    )
    return price, worst_input, RESERVATION_MULTIPLIER * base


def reserve_segment_usd() -> float:
    """Worst-case USD for one still-image segmentation: flat price times
    the multiplier (SAM bills per image, not per token)."""
    return RESERVATION_MULTIPLIER * PRICES["sam-3.1"]["image_usd"]


def _open_ledger(ledger_path: Path | None):
    path = Path(ledger_path) if ledger_path is not None else default_ledger_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        handle = open(path, "a+", encoding="utf-8")  # noqa: PTH123 - intentional low-level open for locking
    except OSError as exc:
        raise LedgerError(f"ledger unreadable: {exc}") from exc
    return handle


def _guarded_post(
    model: str,
    estimated: float,
    body: bytes,
    reconcile,
    transport,
    ledger_path,
) -> tuple[dict, float, str | None]:
    """Reserve, POST, and settle one call. Shared by text and segment calls.

    Returns (response, actual_usd, request_id). Refusals raise MetaRefused
    before money moves; anything after the POST reports billed, never
    refused.
    """
    if not math.isfinite(estimated) or estimated < 0:
        raise LedgerError(f"refusing to reserve invalid cost: {estimated!r}")
    key = os.environ.get(KEY_ENV_VAR)
    if not key:
        raise MissingKey(f"{KEY_ENV_VAR} is not set")
    handle = _open_ledger(ledger_path)
    call_id = uuid.uuid4().hex
    with handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        except OSError as exc:
            raise LedgerError(f"ledger lock failed: {exc}") from exc
        total = _read_total(handle)
        if total >= SPEND_CAP_USD:
            raise CapReached(f"spend cap reached: ${total:.4f} of ${SPEND_CAP_USD:.2f}")
        ceiling = SPEND_CAP_USD - RESERVATION_HEADROOM_USD
        if total + estimated > ceiling:
            raise WouldCrossCap(
                f"call would cross the reservation ceiling: "
                f"${total:.4f} + ${estimated:.4f} > ${ceiling:.2f}"
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
        do_call = transport if transport is not None else _default_transport
        try:
            response = do_call(url, headers, body)
        except MetaRefused:
            raise
        except Exception as exc:  # noqa: BLE001 - reservation must survive any transport failure
            raise TransportFailed(f"transport failed; reservation kept: {exc}") from exc

        actual, request_id = reconcile(response)
        if actual <= 0:
            # The API returned no usable cost or usage: stay conservative
            # and settle at the reserved estimate rather than $0.
            actual = estimated
        try:
            _settle(handle, call_id, model, estimated, actual, request_id)
        except SettlementFailed:
            raise
        except Exception as exc:  # noqa: BLE001 - billed already; never a refusal
            raise SettlementFailed(
                f"call was billed ${actual:.6f} (request {request_id}); "
                f"settlement failed, reservation kept: {exc}",
                actual_usd=actual,
                request_id=request_id,
            ) from exc
        try:
            text = _response_text(response)
        except Exception as exc:  # noqa: BLE001 - billed already; any unreadable shape counts
            raise ResponseUnreadable(
                f"call was billed ${actual:.6f} (request {request_id}); "
                f"the reply could not be read: {exc}",
                actual_usd=actual,
                request_id=request_id,
            ) from exc
        return {"text": text, "actual_usd": actual, "request_id": request_id}


def call_meta_text(
    model: str,
    prompt: str,
    max_output_tokens: int = 256,
    *,
    images: list[bytes] | None = None,
    transport=None,
    ledger_path: Path | None = None,
) -> dict:
    """Make one text-model call through the spend cap, images optional.

    Returns the response's text. Refuses (raising a MetaRefused subclass
    that names the reason) when the key is missing, the model is not
    allowlisted, its price is unknown, the ledger cannot be read, or the
    cap is reached / would be crossed. A billed call whose reply cannot be
    read raises ResponseUnreadable instead (never a refusal: money moved).
    A reservation sized at the request's worst-case cost is appended to
    the ledger before the HTTP call and a settlement line is appended
    after; a crash anywhere in between leaves the reservation counted,
    never less.
    """
    if model not in MODEL_ALLOWLIST:
        raise ModelNotAllowed(f"model {model!r} is not on the first-party allowlist")
    if model not in PRICES:
        raise UnknownPrice(f"unknown price for model {model!r}")
    estimated = reserve_text_usd(model, prompt, max_output_tokens, len(images or []))
    # The output limit rides along so the API cannot return (and bill)
    # more output tokens than the reservation covers.
    body = json.dumps(
        {
            "model": model,
            # Plain string when no images ride along (unit 1's proven form);
            # a user message with inline data URLs otherwise.
            "input": prompt if not images else _text_message(prompt, images),
            "max_output_tokens": max_output_tokens,
        }
    ).encode("utf-8")
    return _guarded_post(
        model,
        estimated,
        body,
        partial(_reconcile_text, model),
        transport,
        ledger_path,
    )


def _reconcile_segment(response: dict) -> tuple[float, str | None]:
    """Real cost for a segmentation call: flat per-image price.

    SAM bills per image segmented, not per token, so the usage count wins
    over any token fields present.
    """
    if isinstance(response.get("cost_usd"), (int, float)):
        return float(response["cost_usd"]), response.get("id")
    usage = response.get("usage") or {}
    images = usage.get("images_processed", 1)
    return float(images) * PRICES["sam-3.1"]["image_usd"], response.get("id")


def call_meta_segment(
    model: str,
    prompt: str,
    image_jpeg: bytes,
    *,
    transport=None,
    ledger_path: Path | None = None,
) -> dict:
    """Segment one still image through the spend cap (SAM 3.1).

    Returns the response's output-text lane (the special-token line);
    decoding it into masks is the caller's job. Same refusal and ledger
    rules as text calls: flat per-image reservation, billed settles at the
    real per-image cost.
    """
    if model not in MODEL_ALLOWLIST:
        raise ModelNotAllowed(f"model {model!r} is not on the first-party allowlist")
    if model != "sam-3.1":
        raise ModelNotAllowed(f"segment calls take sam-3.1, not {model!r}")
    estimated = reserve_segment_usd()
    body = json.dumps({"model": model, "input": _text_message(prompt, [image_jpeg])}).encode(
        "utf-8"
    )
    return _guarded_post(model, estimated, body, _reconcile_segment, transport, ledger_path)


def _reconcile_text(model: str, response: dict) -> tuple[float, str | None]:
    """Real cost for a text call: API-reported cost wins, else usage.

    Cached tokens arrive nested at usage.input_tokens_details.cached_tokens
    (Responses usage schema) as a subset of input_tokens at the lower cached
    rate; a top-level cached_input_tokens key is still accepted from older
    doubles. The cached count is clamped to input_tokens so a surprising
    report can only overstate, never understate, the bill.
    """
    if isinstance(response.get("cost_usd"), (int, float)):
        return float(response["cost_usd"]), response.get("id")
    usage = response.get("usage") or {}
    price = PRICES[model]
    details = usage.get("input_tokens_details") or {}
    cached = details.get("cached_tokens", usage.get("cached_input_tokens", 0))
    full_input = max(0.0, float(usage.get("input_tokens", 0)) - float(cached))
    actual = (
        full_input * price["input_per_mtok"] / 1e6
        + float(cached) * price["cached_input_per_mtok"] / 1e6
        + float(usage.get("output_tokens", 0)) * price["output_per_mtok"] / 1e6
    )
    return actual, response.get("id")


def _response_text(response: dict) -> str:
    # Responses API shape: output holds items; assistant message items carry
    # content blocks of type output_text with the text, while reasoning items
    # carry none. A plain {"text": ...} is accepted from test doubles.
    # Live shape confirmed 2026-10-29; see tests/fixtures/spark_*.json.
    if isinstance(response.get("text"), str):
        return response["text"]
    parts = []
    for item in response.get("output", []) or []:
        for block in item.get("content", []) or []:
            if isinstance(block, dict) and isinstance(block.get("text"), str):
                parts.append(block["text"])
    if not parts:
        status = response.get("status", "?")
        details = response.get("incomplete_details") or {}
        raise KeyError(f"no text in response (status={status}, reason={details.get('reason')})")
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
    est_stored = round(estimated, 6)
    act_stored = round(float(actual), 6)
    settlement = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "model": model,
        "estimated_usd": est_stored,
        "actual_usd": act_stored,
        # Reservation-to-bill ratio: reservation divided by bill, from the
        # stored rounded values. Values at or above 1 mean the reservation
        # covered the call; anything below 1 means the multiplier needs
        # raising.
        "coverage_ratio": round(est_stored / act_stored, 4) if act_stored > 0 else None,
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
