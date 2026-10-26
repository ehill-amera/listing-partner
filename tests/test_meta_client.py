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
                "estimated_usd": 100.0,
                "actual_usd": 100.0,
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
    monkeypatch.setattr(meta_client, "SPEND_CAP_USD", 100.0)
    ledger.write_text(
        json.dumps(
            {
                "ts": "2026-10-26T00:00:00+00:00",
                "model": MODEL,
                "estimated_usd": 99.9999,
                "actual_usd": 99.9999,
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
    # allows up to 4000. At 99.9960 the naive estimate fits under $100 while
    # the worst case crosses it: the call must be refused.
    ledger.write_text(
        json.dumps(
            {
                "ts": "2026-10-26T00:00:00+00:00",
                "model": MODEL,
                "estimated_usd": 99.996,
                "actual_usd": 99.996,
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
    assert meta_client.read_spend_total(ledger) == pytest.approx(99.996)


def test_actual_above_estimate_never_crosses_cap(ledger, key):
    # The API bills 4000 input tokens (4x the naive len/4 guess) for a
    # 4000-char prompt. Old code reserved the guess, settled the real cost,
    # and landed past $100. Worst-case reservation must refuse instead.
    ledger.write_text(
        json.dumps(
            {
                "ts": "2026-10-26T00:00:00+00:00",
                "model": MODEL,
                "estimated_usd": 99.996,
                "actual_usd": 99.996,
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
    assert meta_client.read_spend_total(ledger) <= 100.0
    assert meta_client.read_spend_total(ledger) == pytest.approx(99.996)


def test_headroom_refuses_when_actual_would_break_cap(ledger, key):
    # Worst-case reservation fits under $100 but not under the $99
    # headroom. The transport then bills $0.60, far above the $0.0011
    # reservation. Old code lets it through and settles past $100; the
    # headroom must refuse instead, so the total never passes $100.
    ledger.write_text(
        json.dumps(
            {
                "ts": "2026-10-26T00:00:00+00:00",
                "model": MODEL,
                "estimated_usd": 99.50,
                "actual_usd": 99.50,
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
    assert meta_client.read_spend_total(ledger) <= 100.0
    assert meta_client.read_spend_total(ledger) == pytest.approx(99.50)


def test_actual_above_reservation_settles_under_cap(ledger, key):
    # Same over-billing, but the reservation fits inside the headroom: the
    # call goes through and the settled total still never passes $100.
    ledger.write_text(
        json.dumps(
            {
                "ts": "2026-10-26T00:00:00+00:00",
                "model": MODEL,
                "estimated_usd": 98.90,
                "actual_usd": 98.90,
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
    assert meta_client.read_spend_total(ledger) == pytest.approx(99.40)


def test_heavy_but_fitting_call_settles_under_cap(ledger, key):
    # Same 4x-actual usage, but the worst case still fits inside the $99
    # headroom: the call goes through and the settled total stays under $100.
    ledger.write_text(
        json.dumps(
            {
                "ts": "2026-10-26T00:00:00+00:00",
                "model": MODEL,
                "estimated_usd": 98.99,
                "actual_usd": 98.99,
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
    assert meta_client.read_spend_total(ledger) <= 100.0


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

    def _crash(handle, call_id, actual, request_id):
        raise RuntimeError("died while settling")

    monkeypatch.setattr(meta_client, "_settle", _crash)
    with pytest.raises(MetaRefused):
        meta_client.call_meta_text(MODEL, "hi", transport=_transport_ok, ledger_path=ledger)
    after = meta_client.read_spend_total(ledger)
    assert after >= before, "a crash at settle time keeps the reservation counted"


def test_transport_failure_is_its_own_refusal(ledger, key):
    def _boom(url, headers, body):
        raise RuntimeError("network down")

    with pytest.raises(TransportFailed):
        meta_client.call_meta_text(MODEL, "hi", transport=_boom, ledger_path=ledger)


def test_cap_is_a_constant_not_configurable():
    import inspect

    source = inspect.getsource(meta_client)
    assert "SPEND_CAP_USD = 100.0" in source
    assert "SPEND_CAP" not in source.replace("SPEND_CAP_USD = 100.0", "").replace(
        "SPEND_CAP_USD", ""
    ), "nothing may raise the cap"
    assert ".config/muse" not in source, "never touch Muse Code credentials"


def test_docstring_claims_no_check_enforcement():
    import inspect

    source = inspect.getsource(meta_client)
    assert "enforced by the check" not in source, (
        "the check command does not scan for HTTP imports; the docstring must not say it does"
    )


def test_key_only_from_env(ledger, monkeypatch):
    monkeypatch.delenv("META_API_KEY", raising=False)
    monkeypatch.setenv("META_MODEL_API_KEY", "wrong-var")
    monkeypatch.setenv("MODEL_API_KEY", "wrong-var")
    with pytest.raises(MetaRefused):
        meta_client.call_meta_text(MODEL, "hi", transport=_transport_ok, ledger_path=ledger)
