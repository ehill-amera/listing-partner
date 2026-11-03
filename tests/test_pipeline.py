"""scripts/run: one set, units 2 to 4, and a dry run that makes no model call."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from listing_partner import pipeline

ROOT = Path(__file__).resolve().parent.parent


def _root(tmp_path, frames=True, facts=True):
    raw = tmp_path / "inputs" / "s" / "raw"
    raw.mkdir(parents=True)
    if frames:
        (raw / "a.NEF").write_bytes(b"")
    if facts:
        (tmp_path / "facts").mkdir()
        sample = ROOT / "listing_partner" / "sample_data" / "facts_sample.json"
        (tmp_path / "facts" / "s.json").write_text(sample.read_text())
    return tmp_path


def test_refuses_a_set_with_no_raw_frames(tmp_path):
    with pytest.raises(pipeline.RunRefused, match="no raw bracket frames"):
        pipeline.check_inputs(_root(tmp_path, frames=False), "s")


def test_refuses_a_set_with_no_facts(tmp_path):
    with pytest.raises(pipeline.RunRefused, match="facts file missing"):
        pipeline.check_inputs(_root(tmp_path, facts=False), "s")


def test_refuses_a_path_for_a_set_name(tmp_path):
    with pytest.raises(pipeline.RunRefused, match="not a set name"):
        pipeline.check_inputs(_root(tmp_path), "../s")


def test_one_set_at_a_time(tmp_path):
    root = _root(tmp_path)
    with pipeline._Lock(root, "s"):
        with pytest.raises(pipeline.RunRefused, match="One set at a time"):
            with pipeline._Lock(root, "other"):
                pass
    with pipeline._Lock(root, "other"):
        pass  # released after the first run ends


def _fake_saved(root):
    out = root / "output" / "s"
    (out / "writing").mkdir(parents=True)
    for name in ("finish_manifest.json", "listing_summary.json", "writing/log.jsonl"):
        (out / name).write_text("{}")
    (out / "tidy.json").write_text("{}")
    (root / ".spend").mkdir()
    (root / ".spend" / "ledger.jsonl").write_text("")
    return out


def test_dry_run_refuses_when_a_ledger_moves(tmp_path, monkeypatch):
    """The guard under test is the ledger comparison; the far side writes a ledger line."""
    from listing_partner import hdr, rescore, run_finish, tidy_page

    root = _root(tmp_path)
    _fake_saved(root)
    monkeypatch.setattr(hdr, "group_frames", lambda frames: [frames])

    def page(raw, mls, out):
        (out / "review-finish.html").write_text("x")

    def spends(**kwargs):
        with open(root / ".spend" / "ledger.jsonl", "a") as handle:
            handle.write('{"model": "muse-spark-1.3"}\n')

    monkeypatch.setattr(run_finish, "render_finish_page", page)
    monkeypatch.setattr(rescore, "rescore", spends)
    monkeypatch.setattr(tidy_page, "render", lambda summary: "x")
    with pytest.raises(pipeline.RunRefused, match="a model call was made"):
        pipeline.run_dry(root, "s", scratch=tmp_path / "scratch")


def test_dry_run_refuses_a_set_never_run_live(tmp_path, monkeypatch):
    from listing_partner import hdr

    monkeypatch.setattr(hdr, "group_frames", lambda frames: [frames])
    with pytest.raises(pipeline.RunRefused, match="needs a finished live run"):
        pipeline.run_dry(_root(tmp_path), "s")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.mark.skipif(
    not (ROOT / "output" / "home-a" / "tidy.json").exists()
    or not (ROOT / "inputs" / "home-a" / "raw").is_dir(),
    reason="needs home-a's gitignored raw frames and saved outputs",
)
def test_dry_run_on_home_a_writes_every_page_and_touches_nothing(tmp_path, monkeypatch):
    monkeypatch.setenv("META_API_KEY", "dry-run-test-value")
    saved = ROOT / "output" / "home-a"
    watched = [saved / p for _, p in pipeline.PAGES] + [saved / "listing_summary.json"]
    before = {p: _sha(p) for p in watched}
    ledgers = pipeline._ledgers(ROOT)
    out = pipeline.run_dry(ROOT, "home-a", scratch=tmp_path)
    assert out == tmp_path / "home-a"
    for _, page in pipeline.PAGES:
        assert (out / page).stat().st_size > 0, page
    assert "raw brackets, darkest first" in (out / "review-finish.html").read_text()
    assert json.loads((out / "listing_summary.json").read_text())["rescored"]["model_calls"] == 0
    assert {p: _sha(p) for p in watched} == before, "the real output folder is untouched"
    assert pipeline._ledgers(ROOT) == ledgers
    import os

    assert os.environ["META_API_KEY"] == "dry-run-test-value", "the key is put back after"
