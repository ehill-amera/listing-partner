"""Curate, check coverage, write twice, score, build the page.

Usage: python -m listing_partner.run_listing --unit unit-a
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from listing_partner import baseten_client, coverage, curate, listing_page, meta_client, writing
from listing_partner.facts import load_facts

SPARK = "muse-spark-1.3"
# This unit's budgets, from contract 03. The clients' lifetime caps sit behind these.
META_BUDGET_USD = 3.00
BASETEN_BUDGET_USD = 10.00
SPARK_MAX_TOKENS = 4096


class BudgetExceeded(Exception):
    """A call's reservation would pass this unit's budget."""


def ledger_by_model(path, since: str) -> dict:
    """USD and calls per model, from lines at or after `since`. Settled calls
    count at actual cost, open ones at the estimate. A corrupt ledger raises."""
    path = Path(path)
    if not path.exists():
        return {}
    calls: dict[str, dict] = {}
    for number, text in enumerate(path.read_text().splitlines(), 1):
        if not text.strip():
            continue
        try:
            line = json.loads(text)
            ts, model, call_id = line["ts"], line["model"], line["call_id"]
            estimated = float(line["estimated_usd"])
            actual = line.get("actual_usd")
        except (ValueError, KeyError, TypeError) as exc:
            raise meta_client.LedgerError(f"ledger corrupt at line {number}") from exc
        slot = calls.setdefault(call_id, {"ts": ts, "model": model, "est": 0.0, "act": None})
        slot["est"] = max(slot["est"], estimated)
        if actual is not None:
            slot["act"] = float(actual)
    out: dict[str, dict] = {}
    for slot in calls.values():
        if slot["ts"] < since:
            continue
        row = out.setdefault(slot["model"], {"usd": 0.0, "calls": 0})
        row["usd"] = round(
            row["usd"] + (slot["act"] if slot["act"] is not None else slot["est"]), 6
        )
        row["calls"] += 1
    return out


class _Provider:
    """One model behind its capped client and this unit's budget."""

    def __init__(self, model, client_call, reserve, total, budget, baseline, unreadable, refused):
        self.model, self._call, self._reserve, self._total = model, client_call, reserve, total
        self._budget, self._baseline = budget, baseline
        self._unreadable, self._refused = unreadable, refused

    def guard(self, estimate: float) -> None:
        spent = self._total() - self._baseline
        if spent + estimate > self._budget:
            raise BudgetExceeded(
                f"{self.model}: ${spent:.4f} + ${estimate:.4f} over the ${self._budget:.2f} budget"
            )

    def __call__(self, prompt, max_tokens, **kw):
        # One retry on a failed connection: its reservation stays counted.
        for attempt in (1, 2):
            self.guard(self._reserve(prompt, max_tokens, **kw))
            try:
                return self._call(prompt, max_tokens, **kw)
            except self._unreadable as exc:
                return {"text": "", "actual_usd": exc.actual_usd, "request_id": exc.request_id}
            except self._refused as exc:
                if attempt == 2 or "transport failed" not in str(exc):
                    raise
        raise AssertionError("unreachable")


def _baseline(path: Path, meta_ledger, baseten_ledger) -> dict:
    """Ledger totals when this unit first ran, so reruns count against its budget."""
    if path.exists():
        return json.loads(path.read_text())
    data = {
        "meta": meta_client.read_spend_total(meta_ledger),
        "baseten": baseten_client.read_spend_total(baseten_ledger),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))
    return data


def run_listing(
    *,
    output_dir,
    facts_path,
    meta_ledger=None,
    baseten_ledger=None,
    meta_transport=None,
    baseten_transport=None,
    mls_positions=None,
    meta_budget_usd=META_BUDGET_USD,
    baseten_budget_usd=BASETEN_BUDGET_USD,
) -> dict:
    output_dir = Path(output_dir)
    facts = load_facts(facts_path)
    meta_path = Path(meta_ledger) if meta_ledger else meta_client.default_ledger_path()
    base_path = Path(baseten_ledger) if baseten_ledger else baseten_client.default_ledger_path()
    baseline = _baseline(output_dir / "unit_budget_baseline.json", meta_path, base_path)
    started = datetime.now(timezone.utc).isoformat()

    meta = _Provider(
        SPARK,
        lambda prompt, max_tokens, images=None: meta_client.call_meta_text(
            SPARK,
            prompt,
            max_tokens,
            images=images,
            transport=meta_transport,
            ledger_path=meta_path,
        ),
        lambda prompt, max_tokens, images=None: meta_client.reserve_text_usd(
            SPARK, prompt, max_tokens, len(images or [])
        ),
        lambda: meta_client.read_spend_total(meta_path),
        meta_budget_usd,
        baseline["meta"],
        meta_client.ResponseUnreadable,
        meta_client.MetaRefused,
    )
    baseten = _Provider(
        baseten_client.MODEL,
        lambda prompt, max_tokens: baseten_client.call_baseten_text(
            baseten_client.MODEL,
            prompt,
            max_tokens,
            transport=baseten_transport,
            ledger_path=base_path,
        ),
        lambda prompt, max_tokens: baseten_client.reserve_text_usd(
            baseten_client.MODEL, prompt, max_tokens
        ),
        lambda: baseten_client.read_spend_total(base_path),
        baseten_budget_usd,
        baseline["baseten"],
        baseten_client.ResponseUnreadable,
        baseten_client.BasetenRefused,
    )

    def spark(prompt, images):
        return meta(prompt, SPARK_MAX_TOKENS, images=images)["text"]

    curation = curate.run_curation(output_dir / "finished", spark)
    kept, dropped = curation["kept"], curation["dropped"]
    rows = coverage.check_coverage(facts, kept)
    rooms = [f"{n} {room}" for room, n in Counter(p["room"] for p in kept).items()]

    log_dir = output_dir / "writing"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "log.jsonl"
    if log_path.exists():
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
        log_path.rename(log_dir / f"log-{stamp}.jsonl")
    written = 0

    def log(row):
        nonlocal written
        written += 1
        with open(log_path, "a", encoding="utf-8") as handle:  # noqa: PTH123
            handle.write(json.dumps(row) + "\n")

    result = writing.run_writing(facts, rooms, {"meta": meta, "baseten": baseten}, log)

    bench = None
    if mls_positions:
        bench = curate.benchmark([p["id"] for p in kept], [p["id"] for p in dropped], mls_positions)
    meta_costs = ledger_by_model(meta_path, started)
    base_costs = ledger_by_model(base_path, started)
    zero = {"usd": 0.0, "calls": 0}
    costs = {
        "meta": {SPARK: meta_costs.get(SPARK, zero), "sam-3.1": meta_costs.get("sam-3.1", zero)},
        "baseten": {baseten_client.MODEL: base_costs.get(baseten_client.MODEL, zero)},
        "sam_all_runs_usd": ledger_by_model(meta_path, "").get("sam-3.1", zero)["usd"],
    }
    listing_page.build_page(
        output_dir / "listing.html",
        facts=facts,
        curation=curation,
        coverage=rows,
        writing=result,
        costs=costs,
        benchmark=bench,
    )
    summary = {
        "started": started,
        "kept": len(kept),
        "dropped": len(dropped),
        "benchmark": bench,
        "writing_calls": written,
        "costs": costs,
        "unit_meta_usd": round(meta_client.read_spend_total(meta_path) - baseline["meta"], 6),
        "unit_baseten_usd": round(
            baseten_client.read_spend_total(base_path) - baseline["baseten"], 6
        ),
        "picks": result["picks"],
        "statuses": {f"{t['id']}/{t['provider']}": t["status"] for t in result["texts"]},
        "rewrites": sum(len(t["attempts"]) > 1 for t in result["texts"]),
        "coverage": [{"room": r["room"], "status": r["status"]} for r in rows],
        "crop_rounds": sum(1 for p in [*kept, *dropped] if p.get("cropped")),
        "kept_order": [p["id"] for p in kept],
        "dropped_ids": [p["id"] for p in dropped],
    }
    (output_dir / "curation.json").write_text(json.dumps(curation, indent=1))
    (output_dir / "listing_summary.json").write_text(json.dumps(summary, indent=1))
    return summary


def _mls_positions(unit_inputs: Path, output_dir: Path) -> dict | None:
    """Published position per finished photo, by capture time. None when this
    machine has no MLS set."""
    from listing_partner import hdr, run_merge

    raw, mls = unit_inputs / "raw", unit_inputs / "mls"
    if not mls.is_dir() or not raw.is_dir():
        return None
    frames = sorted(raw.glob("*.NEF")) + sorted(raw.glob("*.nef"))
    matches = run_merge.match_mls(hdr.group_frames(frames), mls, output_dir / "merged")
    return {f"{v['set'] + 1:03d}": int(Path(k).stem) for k, v in matches.items()}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--unit", default="unit-a")
    args = parser.parse_args()
    root = Path(__file__).resolve().parent.parent
    facts_path = root / "facts" / f"{args.unit}.json"
    if not facts_path.exists():
        raise SystemExit(f"facts file missing: facts/{args.unit}.json")
    output_dir = root / "output" / args.unit
    positions = _mls_positions(root / "inputs" / args.unit, output_dir)
    summary = run_listing(output_dir=output_dir, facts_path=facts_path, mls_positions=positions)
    print(f"done: {summary['kept']} kept, {summary['dropped']} dropped")


if __name__ == "__main__":
    main()
