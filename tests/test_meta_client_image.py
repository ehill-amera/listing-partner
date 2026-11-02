"""Muse Image edits through the capped client. Fake far side, throwaway ledger."""

import base64
import json

import pytest

from listing_partner import meta_client
from listing_partner.meta_client import (
    CapReached,
    MissingKey,
    ModelNotAllowed,
    ResponseUnreadable,
    TransportFailed,
)

PNG = b"fake-image-bytes"


@pytest.fixture
def ledger(tmp_path):
    return tmp_path / "ledger.jsonl"


@pytest.fixture
def key(monkeypatch):
    monkeypatch.setenv(meta_client.KEY_ENV_VAR, "test-key")


def _ok(url, headers, body):
    return {"created": 1, "data": [{"b64_json": base64.b64encode(PNG).decode()}]}


def _edit(ledger, transport=_ok, model="muse-image-1.0"):
    return meta_client.call_meta_image_edit(
        model, "fill it", b"jpeg", size="100x50", transport=transport, ledger_path=ledger
    )


def _lines(ledger):
    return [json.loads(x) for x in ledger.read_text().splitlines()]


def test_edit_returns_the_decoded_image_and_settles_at_the_flat_price(ledger, key):
    out = _edit(ledger)
    assert out["image"] == PNG
    assert out["actual_usd"] == pytest.approx(0.01)
    assert [x["status"] for x in _lines(ledger)] == ["reserved", "complete"]
    assert meta_client.read_spend_total(ledger) == pytest.approx(0.01)


def test_edit_posts_to_the_edits_endpoint_with_tools_off_and_no_mask_field(ledger, key):
    seen = {}

    def transport(url, headers, body):
        seen.update(url=url, body=json.loads(body))
        return _ok(url, headers, body)

    _edit(ledger, transport)
    assert seen["url"] == "https://api.meta.ai/v1/images/edits"
    body = seen["body"]
    assert body["model"] == "muse-image-1.0" and body["n"] == 1 and body["size"] == "100x50"
    assert body["images"][0]["image_url"].startswith("data:image/jpeg;base64,")
    assert "mask" not in body
    assert set(body["tool_enablement"].values()) == {False}


def test_edit_refuses_any_other_model_even_an_allowlisted_one(ledger, key):
    with pytest.raises(ModelNotAllowed):
        _edit(ledger, model="muse-spark-1.3")
    assert not ledger.exists() or ledger.read_text() == ""


def test_edit_refuses_without_a_key(ledger, monkeypatch):
    monkeypatch.delenv(meta_client.KEY_ENV_VAR, raising=False)
    with pytest.raises(MissingKey):
        _edit(ledger)


def test_edit_refuses_at_the_cap(ledger, key):
    ledger.write_text(json.dumps({"estimated_usd": 20.0, "actual_usd": 20.0}) + "\n")
    with pytest.raises(CapReached):
        _edit(ledger)


def test_edit_failed_transport_keeps_the_reservation(ledger, key):
    def boom(url, headers, body):
        raise OSError("down")

    with pytest.raises(TransportFailed):
        _edit(ledger, boom)
    assert meta_client.read_spend_total(ledger) == pytest.approx(0.02)


def test_edit_reply_with_no_image_is_unreadable_and_stays_counted(ledger, key):
    with pytest.raises(ResponseUnreadable):
        _edit(ledger, lambda u, h, b: {"created": 1, "data": []})
    assert meta_client.read_spend_total(ledger) == pytest.approx(0.02)
