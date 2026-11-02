"""Refusal tests for the spend-capped Meta client.

Every test uses a throwaway ledger and a mocked transport: no network, no
key needed. Run with META_API_KEY unset.
"""

import json
import os
from pathlib import Path

import pytest

from listing_partner import meta_client
from listing_partner.meta_client import (
    CapReached,
    LedgerError,
    MetaRefused,
    MissingKey,
    ModelNotAllowed,
    ResponseUnreadable,
    SettlementFailed,
    TransportFailed,
    UnknownPrice,
    WouldCrossCap,
)

MODEL = "muse-spark-1.3"


def _transport_ok(url, headers, body):
    assert url.startswith("https://"), url
    assert headers["Authorization"].startswith("Bearer "), "key must travel as a Bearer token"
    assert "META_API_KEY" not in headers["Authorization"]
    return {
        "id": "resp-test-1",
        "text": "smoke",
        "usage": {"input_tokens": 10, "output_tokens": 5},
    }


@pytest.fixture()
def ledger(tmp_path):
    return tmp_path / "ledger.jsonl"


@pytest.fixture()
def key(monkeypatch):
    monkeypatch.setenv("META_API_KEY", "test-key-never-a-real-secret")


def _ledger_lines(path):
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]


def test_smoke_call_settles_one_line(ledger, key):
    out = meta_client.call_meta_text(
        MODEL, "Say the word done.", transport=_transport_ok, ledger_path=ledger
    )
    assert out["text"] == "smoke"
    lines = _ledger_lines(ledger)
    assert len(lines) == 2, "one call appends two lines: reservation, then settlement"
    reservation, line = lines
    assert reservation["status"] == "reserved" and reservation["actual_usd"] is None
    assert reservation["call_id"] == line["call_id"]
    assert line["model"] == MODEL
    assert line["actual_usd"] is not None and line["actual_usd"] > 0
    assert line["request_id"] == "resp-test-1"
    assert line["status"] == "complete"
    for banned in ("Say the word", "smoke-test", "test-key"):
        assert banned not in json.dumps(line), "ledger must hold no prompt text and no key"


def test_refuses_at_cap(ledger, key):
    ledger.write_text(
        json.dumps(
            {
                "ts": "2026-10-26T00:00:00+00:00",
                "model": MODEL,
                "estimated_usd": 20.0,
                "actual_usd": 20.0,
                "request_id": "r",
                "call_id": "c",
                "status": "complete",
            }
        )
        + "\n"
    )
    with pytest.raises(CapReached):
        meta_client.call_meta_text(MODEL, "hi", transport=_transport_ok, ledger_path=ledger)


def test_refuses_call_that_would_cross_cap(ledger, key, monkeypatch):
    monkeypatch.setattr(meta_client, "SPEND_CAP_USD", 20.0)
    ledger.write_text(
        json.dumps(
            {
                "ts": "2026-10-26T00:00:00+00:00",
                "model": MODEL,
                "estimated_usd": 19.9999,
                "actual_usd": 19.9999,
                "request_id": "r",
                "call_id": "c",
                "status": "complete",
            }
        )
        + "\n"
    )
    with pytest.raises(WouldCrossCap):
        meta_client.call_meta_text(MODEL, "hi", transport=_transport_ok, ledger_path=ledger)
    assert len(_ledger_lines(ledger)) == 1, "refused calls add no line"


def test_refuses_unreadable_ledger(tmp_path, key):
    missing_dir_ledger = tmp_path / "no-such-dir" / "sub"  # parent created, open fails below
    missing_dir_ledger.mkdir(parents=True)
    import stat

    os.chmod(missing_dir_ledger, stat.S_IRUSR | stat.S_IXUSR)
    bad = tmp_path / "ledger-is-a-dir.jsonl"
    bad.mkdir()
    with pytest.raises(LedgerError):
        meta_client.call_meta_text(MODEL, "hi", transport=_transport_ok, ledger_path=bad)


def test_refuses_corrupt_ledger(ledger, key):
    ledger.write_text("this is not json\n")
    with pytest.raises(LedgerError):
        meta_client.call_meta_text(MODEL, "hi", transport=_transport_ok, ledger_path=ledger)


def test_refuses_unknown_price(ledger, key, monkeypatch):
    # Allowlisted but absent from the price table: proves the price check
    # fires on its own, past the allowlist check.
    monkeypatch.setattr(
        meta_client, "MODEL_ALLOWLIST", meta_client.MODEL_ALLOWLIST + ("muse-spark-9.9",)
    )
    with pytest.raises(UnknownPrice):
        meta_client.call_meta_text(
            "muse-spark-9.9", "hi", transport=_transport_ok, ledger_path=ledger
        )
    assert not Path(ledger).exists(), "refused calls add no line"


def test_worst_reserve_ratio_reports_minimum(ledger):
    ledger.write_text(
        "\n".join(
            [
                '{"model": "muse-spark-1.3", "estimated_usd": 0.0001, '
                '"actual_usd": 0.00005, "status": "complete"}',
                '{"model": "sam-3.1", "estimated_usd": 0.00009, '
                '"actual_usd": 0.0001, "status": "complete"}',
                '{"model": "sam-3.1", "estimated_usd": 0.0002, '
                '"actual_usd": null, "status": "reserved"}',
            ]
        )
        + "\n"
    )
    stats = meta_client.reserve_ratio_stats(ledger)
    assert stats["worst"] == pytest.approx(0.9), "worst means the lowest coverage"
    assert stats["under_one"] == 1, "reservations under the real bill are counted"
    assert stats["settled"] == 2, "open reservations never join the ratio"


def test_reserve_ratio_stats_scopes_to_since(ledger):
    ledger.write_text(
        "\n".join(
            [
                '{"ts": "2026-10-26T17:00:00+00:00", "model": "muse-spark-1.3", '
                '"estimated_usd": 0.000078, "actual_usd": 0.000822, '
                '"status": "complete"}',
                '{"ts": "2026-10-29T14:00:00+00:00", "model": "sam-3.1", '
                '"estimated_usd": 0.0002, "actual_usd": 0.0001, '
                '"status": "complete"}',
            ]
        )
        + "\n"
    )
    scoped = meta_client.reserve_ratio_stats(ledger, since="2026-10-29T00:00:00+00:00")
    assert scoped["worst"] == pytest.approx(2.0), "earlier unit lines stay out"
    assert scoped["settled"] == 1
    assert scoped["under_one"] == 0
    unscoped = meta_client.reserve_ratio_stats(ledger)
    assert unscoped["under_one"] == 1, "the earlier under-covered call still counts"


def test_refuses_non_allowlisted_and_contributor_models(ledger, key):
    for bad in ("gpt-5", "muse-spark-1.3-contributor", "muse-spark-1.2-contributor", "claude-opus"):
        with pytest.raises(ModelNotAllowed):
            meta_client.call_meta_text(bad, "hi", transport=_transport_ok, ledger_path=ledger)
    assert not Path(ledger).exists(), "refused calls add no line"


def test_refuses_missing_key(ledger, monkeypatch):
    monkeypatch.delenv("META_API_KEY", raising=False)
    with pytest.raises(MissingKey):
        meta_client.call_meta_text(MODEL, "hi", transport=_transport_ok, ledger_path=ledger)


def test_reservation_survives_simulated_crash(ledger, key):
    def _crashing_transport(url, headers, body):
        raise RuntimeError("process died here")

    with pytest.raises(MetaRefused):
        meta_client.call_meta_text(MODEL, "hi", transport=_crashing_transport, ledger_path=ledger)
    lines = _ledger_lines(ledger)
    assert len(lines) == 1
    assert lines[0]["actual_usd"] is None, "crashed call stays a reservation"
    assert lines[0]["status"] == "reserved"
    total = meta_client.read_spend_total(ledger)
    assert total == pytest.approx(lines[0]["estimated_usd"]), (
        "reservation still counts toward the total"
    )


def test_output_limit_is_sent_on_every_call(ledger, key):
    seen = {}

    def _capture(url, headers, body):
        seen.update(json.loads(body.decode("utf-8")))
        return {"id": "r-cap", "text": "ok", "usage": {"input_tokens": 4, "output_tokens": 3}}

    meta_client.call_meta_text(
        MODEL, "hi", max_output_tokens=64, transport=_capture, ledger_path=ledger
    )
    assert seen.get("max_output_tokens") == 64, "the API must enforce the output bound we reserved"


def test_worst_case_reservation_refuses_where_estimate_fits(ledger, key):
    # 4000-char prompt: naive input guess is ~1000 tokens but the request
    # allows up to 4000. At 19.9960 the naive estimate fits under the $19
    # ceiling while the worst case (times the safety multiplier) crosses it:
    # the call must be refused.
    ledger.write_text(
        json.dumps(
            {
                "ts": "2026-10-26T00:00:00+00:00",
                "model": MODEL,
                "estimated_usd": 19.996,
                "actual_usd": 19.996,
                "request_id": "r",
                "call_id": "c",
                "status": "complete",
            }
        )
        + "\n"
    )
    with pytest.raises(WouldCrossCap):
        meta_client.call_meta_text(
            MODEL, "x" * 4000, max_output_tokens=256, transport=_transport_ok, ledger_path=ledger
        )
    assert meta_client.read_spend_total(ledger) == pytest.approx(19.996)


def test_actual_above_estimate_never_crosses_cap(ledger, key):
    # The API bills 4000 input tokens (4x the naive len/4 guess) for a
    # 4000-char prompt. Old code reserved the guess, settled the real cost,
    # and landed past the cap. Worst-case reservation must refuse instead.
    ledger.write_text(
        json.dumps(
            {
                "ts": "2026-10-26T00:00:00+00:00",
                "model": MODEL,
                "estimated_usd": 19.996,
                "actual_usd": 19.996,
                "request_id": "r",
                "call_id": "c",
                "status": "complete",
            }
        )
        + "\n"
    )

    def _heavy_usage(url, headers, body):
        return {
            "id": "r-heavy",
            "text": "ok",
            "usage": {"input_tokens": 4000, "output_tokens": 256},
        }

    with pytest.raises(WouldCrossCap):
        meta_client.call_meta_text(
            MODEL, "x" * 4000, max_output_tokens=256, transport=_heavy_usage, ledger_path=ledger
        )
    assert meta_client.read_spend_total(ledger) <= 20.0
    assert meta_client.read_spend_total(ledger) == pytest.approx(19.996)


def test_headroom_refuses_when_actual_would_break_cap(ledger, key):
    # Worst-case reservation fits under $20 but not under the $19
    # headroom. The transport then bills $0.60, far above the $0.0022
    # reservation. Old code lets it through and settles past $20; the
    # headroom must refuse instead, so the total never passes $20.
    ledger.write_text(
        json.dumps(
            {
                "ts": "2026-10-26T00:00:00+00:00",
                "model": MODEL,
                "estimated_usd": 19.50,
                "actual_usd": 19.50,
                "request_id": "r",
                "call_id": "c",
                "status": "complete",
            }
        )
        + "\n"
    )

    def _overbilled(url, headers, body):
        return {"id": "r-over", "text": "ok", "cost_usd": 0.6}

    with pytest.raises(WouldCrossCap):
        meta_client.call_meta_text(MODEL, "hi", transport=_overbilled, ledger_path=ledger)
    assert meta_client.read_spend_total(ledger) <= 20.0
    assert meta_client.read_spend_total(ledger) == pytest.approx(19.50)


def test_actual_above_reservation_settles_under_cap(ledger, key):
    # Same over-billing, but the reservation fits inside the headroom: the
    # call goes through and the settled total still never passes $20.
    ledger.write_text(
        json.dumps(
            {
                "ts": "2026-10-26T00:00:00+00:00",
                "model": MODEL,
                "estimated_usd": 18.90,
                "actual_usd": 18.90,
                "request_id": "r",
                "call_id": "c",
                "status": "complete",
            }
        )
        + "\n"
    )

    def _overbilled(url, headers, body):
        return {"id": "r-over", "text": "ok", "cost_usd": 0.5}

    out = meta_client.call_meta_text(MODEL, "hi", transport=_overbilled, ledger_path=ledger)
    assert out["actual_usd"] == pytest.approx(0.5)
    assert meta_client.read_spend_total(ledger) == pytest.approx(19.40)


def test_heavy_but_fitting_call_settles_under_cap(ledger, key):
    # Same 4x-actual usage, but the worst case (times the multiplier) still
    # fits inside the $19 headroom: the call goes through and the settled
    # total stays under $20.
    ledger.write_text(
        json.dumps(
            {
                "ts": "2026-10-26T00:00:00+00:00",
                "model": MODEL,
                "estimated_usd": 18.98,
                "actual_usd": 18.98,
                "request_id": "r",
                "call_id": "c",
                "status": "complete",
            }
        )
        + "\n"
    )

    def _heavy_usage(url, headers, body):
        return {
            "id": "r-heavy",
            "text": "ok",
            "usage": {"input_tokens": 4000, "output_tokens": 256},
        }

    out = meta_client.call_meta_text(
        MODEL, "x" * 4000, max_output_tokens=256, transport=_heavy_usage, ledger_path=ledger
    )
    assert out["actual_usd"] > meta_client.estimate_text_usd(MODEL, 1000, 256)
    assert meta_client.read_spend_total(ledger) <= 20.0


def test_ledger_rejects_nan_cost(ledger, key):
    ledger.write_text(
        json.dumps(
            {
                "ts": "2026-10-26T00:00:00+00:00",
                "model": MODEL,
                "estimated_usd": float("nan"),
                "actual_usd": None,
                "request_id": None,
                "call_id": "c",
                "status": "reserved",
            }
        )
        + "\n"
    )
    with pytest.raises(LedgerError):
        meta_client.call_meta_text(MODEL, "hi", transport=_transport_ok, ledger_path=ledger)
    with pytest.raises(LedgerError):
        meta_client.read_spend_total(ledger)


def test_ledger_rejects_negative_cost(ledger, key):
    ledger.write_text(
        json.dumps(
            {
                "ts": "2026-10-26T00:00:00+00:00",
                "model": MODEL,
                "estimated_usd": 0.001,
                "actual_usd": -0.5,
                "request_id": "r",
                "call_id": "c",
                "status": "complete",
            }
        )
        + "\n"
    )
    with pytest.raises(LedgerError):
        meta_client.call_meta_text(MODEL, "hi", transport=_transport_ok, ledger_path=ledger)
    with pytest.raises(LedgerError):
        meta_client.read_spend_total(ledger)


def test_settle_appends_and_counts_once(ledger, key):
    meta_client.call_meta_text(MODEL, "hi", transport=_transport_ok, ledger_path=ledger)
    lines = _ledger_lines(ledger)
    assert len(lines) == 2, "settle appends a line; it never rewrites the file"
    assert lines[0]["status"] == "reserved" and lines[0]["actual_usd"] is None
    assert lines[1]["status"] == "complete" and lines[1]["actual_usd"] is not None
    assert lines[0]["call_id"] == lines[1]["call_id"]
    total = meta_client.read_spend_total(ledger)
    assert total == pytest.approx(lines[1]["actual_usd"]), "one call counts once"


def test_crash_during_settle_cannot_lower_total(ledger, key, monkeypatch):
    meta_client.call_meta_text(MODEL, "hi", transport=_transport_ok, ledger_path=ledger)
    before = meta_client.read_spend_total(ledger)

    # Same signature as the real _settle: a wrong-shaped stub would raise
    # TypeError and pass for the wrong reason, so the names are pinned here.
    def _crash(handle, call_id, model, estimated, actual, request_id):
        raise RuntimeError("died while settling")

    monkeypatch.setattr(meta_client, "_settle", _crash)
    with pytest.raises(SettlementFailed, match="[Bb]illed") as excinfo:
        meta_client.call_meta_text(MODEL, "hi", transport=_transport_ok, ledger_path=ledger)
    assert not isinstance(excinfo.value, MetaRefused), "billed is not refused"
    lines = _ledger_lines(ledger)
    assert len(lines) == 3, "the crashed call leaves its reservation, nothing else"
    crashed = lines[2]
    assert crashed["status"] == "reserved" and crashed["actual_usd"] is None
    assert crashed["model"] == MODEL
    after = meta_client.read_spend_total(ledger)
    assert after == pytest.approx(before + crashed["estimated_usd"]), (
        "a crash at settle time keeps the reservation counted"
    )


def test_transport_failure_is_its_own_refusal(ledger, key):
    def _boom(url, headers, body):
        raise RuntimeError("network down")

    with pytest.raises(TransportFailed):
        meta_client.call_meta_text(MODEL, "hi", transport=_boom, ledger_path=ledger)


def test_cap_is_a_constant_not_configurable():
    import inspect

    source = inspect.getsource(meta_client)
    assert "SPEND_CAP_USD = 20.0" in source
    assert "SPEND_CAP" not in source.replace("SPEND_CAP_USD = 20.0", "").replace(
        "SPEND_CAP_USD", ""
    ), "nothing may raise the cap"
    assert ".config/muse" not in source, "never touch Muse Code credentials"


def test_docstring_claims_no_check_enforcement():
    import inspect

    source = inspect.getsource(meta_client)
    assert "enforced by the check" not in source, (
        "the check command does not scan for HTTP imports; the docstring must not say it does"
    )


def test_billed_call_with_unreadable_reply_is_not_a_refusal(ledger, key):
    """A billed call whose reply cannot be read says so plainly, never refused."""

    def _nonsense(url, headers, body):
        return {"id": "resp-nonsense", "usage": {"input_tokens": 10, "output_tokens": 5}}

    with pytest.raises(ResponseUnreadable, match="[Bb]illed") as excinfo:
        meta_client.call_meta_text(MODEL, "hi", transport=_nonsense, ledger_path=ledger)
    assert not isinstance(excinfo.value, MetaRefused), "billed is not refused"
    assert "resp-nonsense" in str(excinfo.value), "the error carries the request id"
    assert excinfo.value.actual_usd > 0, "the error carries the billed cost"
    assert type(excinfo.value) is ResponseUnreadable, "exactly this error, no refusal wrapper"
    lines = _ledger_lines(ledger)
    assert len(lines) == 2 and lines[1]["status"] == "complete", "the call settled: money moved"
    text = str(excinfo.value).lower()
    assert "reply" in text and "could not be read" in text


def test_oddly_shaped_billed_reply_is_not_a_refusal(ledger, key):
    """A reply the reader chokes on (None item: AttributeError, not
    KeyError) is still a billed call, never a refusal and never a crash."""

    def _odd(url, headers, body):
        return {
            "id": "resp-odd",
            "usage": {"input_tokens": 10, "output_tokens": 5},
            "output": [None],
        }

    with pytest.raises(ResponseUnreadable, match="[Bb]illed") as excinfo:
        meta_client.call_meta_text(MODEL, "hi", transport=_odd, ledger_path=ledger)
    assert not isinstance(excinfo.value, MetaRefused), "billed is not refused"
    assert type(excinfo.value) is ResponseUnreadable
    lines = _ledger_lines(ledger)
    assert len(lines) == 2 and lines[1]["status"] == "complete", "the call settled: money moved"


def test_settle_failure_is_not_a_refusal(ledger, key, monkeypatch):
    """Transport succeeded, so money moved; a crash while writing the
    settlement line must say billed, never refused."""

    # Same signature as the real _settle: a wrong-shaped stub would raise
    # TypeError and pass for the wrong reason, so the names are pinned here.
    def _crash(handle, call_id, model, estimated, actual, request_id):
        raise RuntimeError("died while settling")

    monkeypatch.setattr(meta_client, "_settle", _crash)
    with pytest.raises(meta_client.SettlementFailed, match="[Bb]illed") as excinfo:
        meta_client.call_meta_text(MODEL, "hi", transport=_transport_ok, ledger_path=ledger)
    assert not isinstance(excinfo.value, MetaRefused), "billed is not refused"
    assert "reservation kept" in str(excinfo.value).lower()
    assert excinfo.value.actual_usd > 0, "the error carries the billed cost"
    lines = _ledger_lines(ledger)
    assert len(lines) == 1, "the crashed call leaves its reservation, nothing else"
    assert lines[0]["status"] == "reserved" and lines[0]["actual_usd"] is None


def _transport_image_ok(url, headers, body):
    request = json.loads(body.decode("utf-8"))
    assert request["model"] == "sam-3.1"
    assert request["input"][0]["content"][1]["type"] == "input_image"
    return {
        "id": "resp-seg-1",
        "output": [
            {
                "type": "message",
                "content": [{"type": "output_text", "text": "<0f>"}],
            }
        ],
        "usage": {"images_processed": 1},
    }


def test_segment_call_bills_per_image(ledger, key):
    out = meta_client.call_meta_segment(
        "sam-3.1",
        "window",
        b"fake-jpeg-bytes",
        transport=_transport_image_ok,
        ledger_path=ledger,
    )
    assert out["text"] == "<0f>"
    assert out["actual_usd"] == pytest.approx(2.50 / 1000)
    lines = _ledger_lines(ledger)
    assert len(lines) == 2
    assert lines[1]["coverage_ratio"] >= 1.0, "flat-price reservation covers the bill"


def test_segment_reservation_is_flat_price_times_multiplier():
    assert meta_client.reserve_segment_usd() == pytest.approx(
        meta_client.RESERVATION_MULTIPLIER * 2.50 / 1000
    )


def test_image_reservation_uses_measured_token_bound():
    without = meta_client.reserve_text_usd(MODEL, "hi", 256)
    with_image = meta_client.reserve_text_usd(MODEL, "hi", 256, 1)
    assert with_image - without == pytest.approx(
        meta_client.RESERVATION_MULTIPLIER * meta_client.IMAGE_INPUT_TOKEN_BOUND * 1.25 / 1e6
    )
    assert meta_client.IMAGE_INPUT_TOKEN_BOUND >= 875, (
        "the bound must cover the measured 875 tokens of a 1024x684 photo"
    )


def test_text_call_with_image_bills_input_tokens(ledger, key):
    def _image_ok(url, headers, body):
        request = json.loads(body.decode("utf-8"))
        assert request["input"][0]["content"][1]["type"] == "input_image"
        assert request["input"][0]["content"][1]["image_url"].startswith("data:image/jpeg;base64,")
        return {
            "id": "r-img",
            "output": [{"type": "message", "content": [{"type": "output_text", "text": "yes"}]}],
            "usage": {"input_tokens": 1500, "output_tokens": 3},
        }

    out = meta_client.call_meta_text(
        MODEL,
        "is this a window?",
        images=[b"fake-jpeg-bytes"],
        transport=_image_ok,
        ledger_path=ledger,
    )
    assert out["text"] == "yes"
    assert out["actual_usd"] == pytest.approx((1500 * 1.25 + 3 * 4.25) / 1e6)


def test_key_only_from_env(ledger, monkeypatch):
    monkeypatch.delenv("META_API_KEY", raising=False)
    monkeypatch.setenv("META_MODEL_API_KEY", "wrong-var")
    monkeypatch.setenv("MODEL_API_KEY", "wrong-var")
    with pytest.raises(MetaRefused):
        meta_client.call_meta_text(MODEL, "hi", transport=_transport_ok, ledger_path=ledger)


def test_reservation_is_docs_worst_case_times_multiplier():
    # Docs basis (pricing + Responses schemas, read 2026-10-29): input tokens
    # can never exceed the prompt's byte length, and max_output_tokens bounds
    # visible plus reasoning output. The reservation is that worst case times
    # the safety multiplier, so a bill above the bare worst case still fits.
    base = 4000 * 1.25 / 1e6 + 256 * 4.25 / 1e6
    assert meta_client.reserve_text_usd(MODEL, "x" * 4000, 256) == pytest.approx(
        meta_client.RESERVATION_MULTIPLIER * base
    )
    assert meta_client.RESERVATION_MULTIPLIER >= 2.0, (
        "the multiplier must cover the worst measured bill-to-reservation ratio"
    )


def test_settlement_records_reservation_to_bill_ratio(ledger, key):
    meta_client.call_meta_text(MODEL, "hi", transport=_transport_ok, ledger_path=ledger)
    lines = _ledger_lines(ledger)
    assert len(lines) == 2
    reservation, settlement = lines
    assert settlement["status"] == "complete"
    assert settlement["coverage_ratio"] == pytest.approx(
        reservation["estimated_usd"] / settlement["actual_usd"]
    ), "every settled call records reservation divided by bill"


def _fixture(name):
    from pathlib import Path as _Path
    import json as _json

    return _json.loads((_Path(__file__).resolve().parent / "fixtures" / name).read_text())


def test_response_text_reads_saved_live_message_shape(ledger, key):
    # Fixture is a real Muse Spark reply (ids stripped): a reasoning item
    # plus an assistant message whose output_text block holds the text.
    def _live(url, headers, body):
        return _fixture("spark_text_response.json")

    out = meta_client.call_meta_text(MODEL, "hi", transport=_live, ledger_path=ledger)
    assert out["text"] == "done"
    assert out["actual_usd"] == pytest.approx((15 * 1.25 + 140 * 4.25) / 1e6), (
        "the live usage reconciles from input plus output tokens"
    )


def test_billed_incomplete_reply_names_status_and_reason(ledger, key):
    # Fixture is a real reply whose output holds only a reasoning item: the
    # budget ran out (status incomplete, reason max_output_tokens), so there
    # is no text to read. Billed, but the error must say why.
    def _incomplete(url, headers, body):
        return _fixture("spark_incomplete_reasoning.json")

    with pytest.raises(ResponseUnreadable, match="[Bb]illed") as excinfo:
        meta_client.call_meta_text(MODEL, "hi", transport=_incomplete, ledger_path=ledger)
    assert "incomplete" in str(excinfo.value)
    assert "max_output_tokens" in str(excinfo.value)


def test_reconcile_prices_nested_cached_tokens(ledger, key):
    # The Responses usage schema nests cached tokens at
    # input_tokens_details.cached_tokens, as a subset of input_tokens billed
    # at the cached rate. A reader that looks for a top-level key prices the
    # cached subset at the full rate instead.
    def _cached(url, headers, body):
        return {
            "id": "r-cached",
            "text": "ok",
            "usage": {
                "input_tokens": 100,
                "input_tokens_details": {"cached_tokens": 80},
                "output_tokens": 10,
            },
        }

    out = meta_client.call_meta_text(MODEL, "hi", transport=_cached, ledger_path=ledger)
    expected = (20 * 1.25 + 80 * 0.15 + 10 * 4.25) / 1e6
    assert out["actual_usd"] == pytest.approx(expected)


def test_worst_case_guard_refuses_from_below_ceiling(ledger, key):
    # The total sits BELOW the $19 reservation ceiling: only this call's
    # worst-case cost pushes past it (18.996 + 0.0122 > 19). A guard that
    # refuses only when the total is already past the ceiling, or a naive
    # len/4 estimate (18.996 + 0.0023 < 19, still fits), lets this through.
    ledger.write_text(
        json.dumps(
            {
                "ts": "2026-10-26T00:00:00+00:00",
                "model": MODEL,
                "estimated_usd": 18.996,
                "actual_usd": 18.996,
                "request_id": "r",
                "call_id": "c",
                "status": "complete",
            }
        )
        + "\n"
    )
    with pytest.raises(WouldCrossCap):
        meta_client.call_meta_text(
            MODEL, "x" * 4000, max_output_tokens=256, transport=_transport_ok, ledger_path=ledger
        )
    assert len(_ledger_lines(ledger)) == 1, "refused calls add no line"


def _good_line(call_id, actual=0.0009):
    return {
        "ts": "2026-10-26T00:00:00+00:00",
        "model": MODEL,
        "estimated_usd": 0.001,
        "actual_usd": actual,
        "request_id": "r-" + call_id,
        "call_id": call_id,
        "status": "complete",
    }


def test_corrupt_middle_line_refuses(ledger, key):
    before = (
        json.dumps(_good_line("c1"))
        + "\n{gah, truncated mid-write\n"
        + json.dumps(_good_line("c3"))
        + "\n"
    )
    ledger.write_text(before)
    with pytest.raises(LedgerError, match="line 2"):
        meta_client.call_meta_text(MODEL, "hi", transport=_transport_ok, ledger_path=ledger)
    with pytest.raises(LedgerError, match="line 2"):
        meta_client.read_spend_total(ledger)
    assert Path(ledger).read_text() == before, "a refused call writes nothing"


def test_line_missing_estimated_usd_refuses(ledger, key):
    damaged = _good_line("c2")
    del damaged["estimated_usd"]
    ledger.write_text(
        json.dumps(_good_line("c1"))
        + "\n"
        + json.dumps(damaged)
        + "\n"
        + json.dumps(_good_line("c3"))
        + "\n"
    )
    with pytest.raises(LedgerError, match="estimated_usd"):
        meta_client.call_meta_text(MODEL, "hi", transport=_transport_ok, ledger_path=ledger)
    with pytest.raises(LedgerError, match="estimated_usd"):
        meta_client.read_spend_total(ledger)


def test_incomplete_reply_with_partial_text_is_not_returned_as_complete(ledger, key):
    def _cut(url, headers, body):
        return {
            "id": "resp-cut",
            "status": "incomplete",
            "incomplete_details": {"reason": "max_output_tokens"},
            "output": [{"content": [{"type": "output_text", "text": "half a descri"}]}],
            "usage": {"input_tokens": 10, "output_tokens": 5},
        }

    with pytest.raises(ResponseUnreadable):
        meta_client.call_meta_text(MODEL, "hi", transport=_cut, ledger_path=ledger)
