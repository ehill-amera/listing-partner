"""Refusal tests for the capped Baseten client. Throwaway ledger, fake far
side, key always a test value. One real-HTTP test against a local server."""

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from listing_partner import baseten_client as bc

MODEL = bc.MODEL


def _ok(url, headers, body):
    return {
        "id": "r1",
        "choices": [{"finish_reason": "stop", "message": {"content": "hello"}}],
        "usage": {"prompt_tokens": 1000, "completion_tokens": 1000},
    }


@pytest.fixture()
def ledger(tmp_path):
    return tmp_path / "baseten-ledger.jsonl"


@pytest.fixture()
def key(monkeypatch):
    monkeypatch.setenv("BASETEN_API_KEY", "test-key-not-real")


def _seed(path, usd):
    path.write_text(
        json.dumps({"estimated_usd": usd, "actual_usd": usd, "call_id": "x", "model": MODEL}) + "\n"
    )


def _no_call(*a):
    raise AssertionError("transport must not be reached")


def test_settles_from_returned_token_counts(ledger, key):
    out = bc.call_baseten_text(MODEL, "hi", 50, transport=_ok, ledger_path=ledger)
    assert out["text"] == "hello"
    assert out["actual_usd"] == pytest.approx((1000 * 1.25 + 1000 * 4.25) / 1e6)
    lines = [json.loads(x) for x in ledger.read_text().splitlines()]
    assert [x["status"] for x in lines] == ["reserved", "complete"]
    assert lines[0]["call_id"] == lines[1]["call_id"]
    assert "test-key" not in ledger.read_text()


def test_reservation_is_twice_worst_case():
    worst = (len(b"abcd") * 1.25 + 100 * 4.25) / 1e6
    assert bc.reserve_text_usd(MODEL, "abcd", 100) == pytest.approx(2 * worst)


def test_cached_tokens_settle_at_cached_rate(ledger, key):
    def reply(url, headers, body):
        r = _ok(url, headers, body)
        r["usage"]["prompt_tokens_details"] = {"cached_tokens": 400}
        return r

    out = bc.call_baseten_text(MODEL, "hi", 50, transport=reply, ledger_path=ledger)
    assert out["actual_usd"] == pytest.approx((600 * 1.25 + 400 * 0.15 + 1000 * 4.25) / 1e6)


def test_no_usage_settles_at_the_reservation(ledger, key):
    def reply(url, headers, body):
        r = _ok(url, headers, body)
        del r["usage"]
        return r

    out = bc.call_baseten_text(MODEL, "hi", 50, transport=reply, ledger_path=ledger)
    assert out["actual_usd"] == pytest.approx(bc.reserve_text_usd(MODEL, "hi", 50), abs=1e-6)


def test_refuses_at_cap(ledger, key):
    _seed(ledger, bc.BASETEN_CAP_USD)
    with pytest.raises(bc.CapReached):
        bc.call_baseten_text(MODEL, "hi", 50, transport=_no_call, ledger_path=ledger)


def test_refuses_call_that_would_cross_the_headroom_ceiling(ledger, key):
    _seed(ledger, bc.BASETEN_CAP_USD - 1.0 - 1e-7)
    with pytest.raises(bc.WouldCrossCap):
        bc.call_baseten_text(MODEL, "hi", 50, transport=_no_call, ledger_path=ledger)


def test_refuses_corrupt_ledger(ledger, key):
    ledger.write_text("{not json\n")
    with pytest.raises(bc.LedgerError):
        bc.call_baseten_text(MODEL, "hi", 50, transport=_no_call, ledger_path=ledger)


def test_refuses_invalid_cost_in_ledger(ledger, key):
    ledger.write_text(json.dumps({"estimated_usd": -1, "call_id": "x"}) + "\n")
    with pytest.raises(bc.LedgerError):
        bc.read_spend_total(ledger)


def test_refuses_unreadable_ledger(tmp_path, key):
    with pytest.raises(bc.LedgerError):
        bc.call_baseten_text(MODEL, "hi", 50, transport=_no_call, ledger_path=tmp_path)


@pytest.mark.parametrize("model", ["muse-spark-1.3", "meta-models/other", "muse-spark-open", ""])
def test_refuses_model_not_on_allowlist(ledger, key, model):
    with pytest.raises(bc.ModelNotAllowed):
        bc.call_baseten_text(model, "hi", 50, transport=_no_call, ledger_path=ledger)


def test_refuses_unknown_price(ledger, key, monkeypatch):
    monkeypatch.setattr(bc, "PRICES", {})
    with pytest.raises(bc.UnknownPrice):
        bc.call_baseten_text(MODEL, "hi", 50, transport=_no_call, ledger_path=ledger)


def test_refuses_without_the_key(ledger, monkeypatch):
    monkeypatch.delenv("BASETEN_API_KEY", raising=False)
    monkeypatch.setenv("META_API_KEY", "other-provider-key")
    with pytest.raises(bc.MissingKey):
        bc.call_baseten_text(MODEL, "hi", 50, transport=_no_call, ledger_path=ledger)


def test_cap_constant_is_80_and_env_cannot_raise_it(ledger, key, monkeypatch):
    assert bc.BASETEN_CAP_USD == 80.0
    monkeypatch.setenv("BASETEN_CAP_USD", "100000")
    _seed(ledger, 80.0)
    with pytest.raises(bc.CapReached):
        bc.call_baseten_text(MODEL, "hi", 50, transport=_no_call, ledger_path=ledger)


def test_failed_transport_keeps_the_reservation(ledger, key):
    def boom(*a):
        raise OSError("network down")

    with pytest.raises(bc.TransportFailed):
        bc.call_baseten_text(MODEL, "hi", 50, transport=boom, ledger_path=ledger)
    assert bc.read_spend_total(ledger) == pytest.approx(bc.reserve_text_usd(MODEL, "hi", 50))


def test_truncated_reply_is_billed_and_raises_not_returned(ledger, key):
    def cut(url, headers, body):
        r = _ok(url, headers, body)
        r["choices"][0]["finish_reason"] = "length"
        return r

    with pytest.raises(bc.ResponseUnreadable):
        bc.call_baseten_text(MODEL, "hi", 50, transport=cut, ledger_path=ledger)
    assert bc.read_spend_total(ledger) == pytest.approx((1000 * 1.25 + 1000 * 4.25) / 1e6)


def test_real_http_request_shape_against_a_local_server(ledger, key, monkeypatch):
    seen = {}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            seen["path"] = self.path
            seen["auth"] = self.headers["Authorization"]
            seen["body"] = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            data = json.dumps(_ok(None, None, None)).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *a):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    monkeypatch.setattr(bc, "API_BASE_URL", f"http://127.0.0.1:{server.server_port}/v1")
    out = bc.call_baseten_text(MODEL, "hi", 50, ledger_path=ledger)
    server.shutdown()
    assert out["text"] == "hello"
    assert seen["path"] == "/v1/chat/completions"
    assert seen["auth"] == "Bearer test-key-not-real"
    assert seen["body"]["model"] == MODEL
    assert seen["body"]["max_tokens"] == 50
    assert seen["body"]["messages"] == [{"role": "user", "content": "hi"}]
