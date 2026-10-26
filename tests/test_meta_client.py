"""Refusal tests for the spend-capped Meta client.

Every test uses a throwaway ledger and a mocked transport: no network, no
key needed. Run with META_API_KEY unset.
"""

import json
import os
from pathlib import Path

import pytest

from listing_partner import meta_client
from listing_partner.meta_client import MetaRefused

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
    assert len(lines) == 1, "exactly one ledger line per call"
    line = lines[0]
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
    with pytest.raises(MetaRefused):
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
    with pytest.raises(MetaRefused):
        meta_client.call_meta_text(MODEL, "hi", transport=_transport_ok, ledger_path=ledger)
    assert len(_ledger_lines(ledger)) == 1, "refused calls add no line"


def test_refuses_unreadable_ledger(tmp_path, key):
    missing_dir_ledger = tmp_path / "no-such-dir" / "sub"  # parent created, open fails below
    missing_dir_ledger.mkdir(parents=True)
    import stat

    os.chmod(missing_dir_ledger, stat.S_IRUSR | stat.S_IXUSR)
    bad = tmp_path / "ledger-is-a-dir.jsonl"
    bad.mkdir()
    with pytest.raises(MetaRefused):
        meta_client.call_meta_text(MODEL, "hi", transport=_transport_ok, ledger_path=bad)


def test_refuses_corrupt_ledger(ledger, key):
    ledger.write_text("this is not json\n")
    with pytest.raises(MetaRefused):
        meta_client.call_meta_text(MODEL, "hi", transport=_transport_ok, ledger_path=ledger)


def test_refuses_unknown_price(ledger, key):
    with pytest.raises(MetaRefused):
        meta_client.call_meta_text(
            "muse-spark-9.9", "hi", transport=_transport_ok, ledger_path=ledger
        )


def test_refuses_non_allowlisted_and_contributor_models(ledger, key):
    for bad in ("gpt-5", "muse-spark-1.3-contributor", "muse-spark-1.2-contributor", "claude-opus"):
        with pytest.raises(MetaRefused):
            meta_client.call_meta_text(bad, "hi", transport=_transport_ok, ledger_path=ledger)
    assert not Path(ledger).exists(), "refused calls add no line"


def test_refuses_missing_key(ledger, monkeypatch):
    monkeypatch.delenv("META_API_KEY", raising=False)
    with pytest.raises(MetaRefused):
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


def test_cap_is_a_constant_not_configurable():
    import inspect

    source = inspect.getsource(meta_client)
    assert "SPEND_CAP_USD = 100.0" in source
    assert "SPEND_CAP" not in source.replace("SPEND_CAP_USD = 100.0", "").replace(
        "SPEND_CAP_USD", ""
    ), "nothing may raise the cap"
    assert ".config/muse" not in source, "never touch Muse Code credentials"


def test_key_only_from_env(ledger, monkeypatch):
    monkeypatch.delenv("META_API_KEY", raising=False)
    monkeypatch.setenv("META_MODEL_API_KEY", "wrong-var")
    monkeypatch.setenv("MODEL_API_KEY", "wrong-var")
    with pytest.raises(MetaRefused):
        meta_client.call_meta_text(MODEL, "hi", transport=_transport_ok, ledger_path=ledger)
