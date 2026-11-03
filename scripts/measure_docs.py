"""Measure every number the README and docs/who-built-what.md print.

Usage: .venv/bin/python scripts/measure_docs.py [set-name]   (default home-a)

Reads only files on disk: the set's saved outputs, both spend ledgers, git and
.navigator/review-*.md (every saved review of units 1 to 4, including the one
withheld from docs/reviews/). Makes no model call and imports no client. Prints one
JSON object. Any shape it does not recognise raises instead of printing a
number, so a short or empty answer never reads as complete.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TAG = "muse-code-built"
# Commit counts are measured through the unit 4 ship commit, so the README's
# number stays true as later commits land.
THROUGH = "f93deaa"
EPS = 1e-6


class Unmeasurable(Exception):
    pass


def _calls(ledger: Path) -> list[dict]:
    """One row per call in first-seen order, priced the way the clients total a
    ledger: actual where settled, the estimate where only reserved."""
    by_call: dict[str, dict] = {}
    for n, text in enumerate(ledger.read_text().splitlines(), 1):
        if not text.strip():
            continue
        line = json.loads(text)
        cid = line.get("call_id") or f"line-{n}"
        slot = by_call.setdefault(
            cid, {"model": line["model"], "ts": line["ts"], "est": 0.0, "actual": None}
        )
        slot["est"] = max(slot["est"], float(line["estimated_usd"]))
        if line.get("actual_usd") is not None:
            slot["actual"] = float(line["actual_usd"])
    rows, total = [], 0.0
    for slot in by_call.values():
        usd = slot["actual"] if slot["actual"] is not None else slot["est"]
        rows.append({**slot, "usd": usd, "before": total, "after": total + usd})
        total += usd
    return rows


def _segment(rows: list[dict], start: float, end: float | None) -> list[dict]:
    """Calls between two ledger totals. Each total must fall on a call boundary."""
    marks = [0.0] + [r["after"] for r in rows]
    for value in (start, end):
        if value is not None and not any(abs(value - m) < EPS for m in marks):
            raise Unmeasurable(f"ledger total {value} is not on a call boundary")
    return [
        r for r in rows if r["before"] >= start - EPS and (end is None or r["after"] <= end + EPS)
    ]


def _by_model(rows: list[dict]) -> dict:
    out: dict[str, dict] = {}
    for r in rows:
        slot = out.setdefault(r["model"], {"calls": 0, "usd": 0.0})
        slot["calls"] += 1
        slot["usd"] = round(slot["usd"] + r["usd"], 6)
    return out


def _other_tidy_runs(set_name: str, window: list[dict]) -> dict:
    """Calls in window that belong to another set's saved tidy run."""
    saved = [ROOT / "output" / d.name / "tidy.json" for d in (ROOT / "output").iterdir()]
    saved += list((ROOT / ".navigator" / "evidence").glob("tidy-*/*/tidy.json"))
    ids: set[int] = set()
    runs = []
    seen = set()
    for path in saved:
        other = path.parent.name
        if other == set_name or not path.exists():
            continue
        run = json.loads(path.read_text())
        key = (other, run["generated_at"])
        if key in seen or not window or run["generated_at"] < window[0]["ts"]:
            continue
        seen.add(key)
        want = {m: v["calls"] for m, v in run["this_run"].items()}
        taken, have = [], {}
        for r in window:
            if r["ts"] < run["generated_at"]:
                continue
            if have == want:
                break
            taken.append(r)
            have[r["model"]] = have.get(r["model"], 0) + 1
        got = _by_model(taken)
        for model, v in run["this_run"].items():
            if (
                got.get(model, {}).get("calls") != v["calls"]
                or abs(got[model]["usd"] - v["usd"]) > EPS
            ):
                raise Unmeasurable(
                    f"{other}'s tidy run at {run['generated_at']} does not match the ledger"
                )
        if set(got) != set(run["this_run"]):
            raise Unmeasurable(f"{other}'s tidy run at {run['generated_at']} has extra models")
        ids.update(id(r) for r in taken)
        runs.append(
            {
                "set": other,
                "at": run["generated_at"],
                "calls": len(taken),
                "usd": round(sum(r["usd"] for r in taken), 6),
            }
        )
    return {"ids": ids, "runs": runs}


def cost(set_name: str) -> dict:
    out = ROOT / "output" / set_name
    meta = _calls(ROOT / ".spend" / "ledger.jsonl")
    base = _calls(ROOT / ".spend" / "baseten-ledger.jsonl")
    finish = json.loads((out / "finish_manifest.json").read_text())
    u2_start = float(finish["spend_baseline_usd"])
    u2_end = u2_start + float(finish["summary"]["unit_spend_usd"])
    baseline = json.loads((out / "unit_budget_baseline.json").read_text())
    summary = json.loads((out / "listing_summary.json").read_text())
    u3_meta_end = float(baseline["meta"]) + float(summary["unit_meta_usd"])
    u3_base_end = float(baseline["baseten"]) + float(summary["unit_baseten_usd"])
    if abs(float(baseline["meta"]) - u2_end) > EPS:
        raise Unmeasurable("unit 3 did not start where unit 2 ended on the Meta ledger")
    unit2 = _segment(meta, u2_start, u2_end)
    unit3_meta = _segment(meta, float(baseline["meta"]), u3_meta_end)
    unit3_base = _segment(base, float(baseline["baseten"]), u3_base_end)
    # Unit 4 has one ledger-wide baseline, so this set's tidy calls are every Meta
    # call after its unit 3, less every other set's saved tidy run that landed in
    # that window. Each excluded run must match its saved this_run exactly.
    window = _segment(meta, u3_meta_end, None)
    excluded = _other_tidy_runs(set_name, window)
    unit4 = [r for r in window if id(r) not in excluded["ids"]]
    if _segment(base, u3_base_end, None):
        raise Unmeasurable("Baseten calls after this set's unit 3 are not attributed")
    units = {
        "unit 2 (finish)": {"meta": _by_model(unit2), "baseten": {}},
        "unit 3 (curate and write)": {
            "meta": _by_model(unit3_meta),
            "baseten": _by_model(unit3_base),
        },
        "unit 4 (tidy)": {"meta": _by_model(unit4), "baseten": {}},
    }
    total = {"meta": {}, "baseten": {}}
    for unit in units.values():
        for provider, models in unit.items():
            for model, v in models.items():
                slot = total[provider].setdefault(model, {"calls": 0, "usd": 0.0})
                slot["calls"] += v["calls"]
                slot["usd"] = round(slot["usd"] + v["usd"], 6)
    grand = round(sum(v["usd"] for p in total.values() for v in p.values()), 6)
    photos = int(finish["summary"]["photos_finished"])
    return {
        "units": units,
        "unit4_excluded_other_sets": excluded["runs"],
        "total_by_model": total,
        "total_usd": grand,
        "finished_photos": photos,
        "first_call": (unit2 or unit3_meta)[0]["ts"],
        "last_call": max(r["ts"] for r in unit2 + unit3_meta + unit3_base + unit4),
        "ledger_lifetime": {
            "meta_usd": round(meta[-1]["after"], 6),
            "baseten_usd": round(base[-1]["after"], 6),
        },
    }


def picks(set_name: str) -> dict:
    summary = json.loads((ROOT / "output" / set_name / "listing_summary.json").read_text())
    out = {}
    for job, pick in summary["picks"].items():
        rows = pick["rows"]
        out[job] = {
            "better": pick["better"],
            "failed_checks": {p: rows[p]["failed_checks"] for p in rows},
            "cost_usd": {p: rows[p]["cost_usd"] for p in rows},
        }
    out["rewrites"] = summary["rewrites"]
    out["description_words"] = {p: d["words"] for p, d in summary["descriptions"].items()}
    return out


def outside(set_name: str) -> dict:
    tidy = json.loads((ROOT / "output" / set_name / "tidy.json").read_text())
    measured = [p for p in tidy["photos"] if p["measure"] is not None]
    edited = [p for p in measured if p["status"] == "tidied"]
    if not edited:
        raise Unmeasurable("no edited photo carries a measurement")
    return {
        "photos": len(tidy["photos"]),
        "tidied": tidy["tidied"],
        "untidied": tidy["untidied"],
        "nothing_to_tidy": tidy["nothing_to_tidy"],
        "edited_outside_changed": {p["id"]: p["measure"]["outside_changed_pixels"] for p in edited},
        "edited_mask_pixels": {p["id"]: p["measure"]["mask_pixels"] for p in edited},
        "all_measured_outside_changed": {
            p["id"]: p["measure"]["outside_changed_pixels"] for p in measured
        },
        "untidied_reasons": {
            p["id"]: p["reason"] for p in tidy["photos"] if p["status"] == "untidied"
        },
    }


def commits() -> dict:
    def count(spec: str) -> int:
        return int(subprocess.check_output(["git", "rev-list", "--count", spec], cwd=ROOT))

    return {
        "muse_code": count(TAG),
        "claude_code_through_unit_4": count(f"{TAG}..{THROUGH}"),
        "through": THROUGH,
    }


VERDICT = re.compile(r"\b(NOT YET|SHIP)\b")


def reviews() -> dict:
    table: dict[str, dict] = {}
    # Units 1 to 4: the publishing step's own reviews are written after the
    # commit they review, so no committed table can count them.
    files = [
        f
        for f in sorted((ROOT / ".navigator").glob("review-*.md"))
        if f.name.split("-")[1].removesuffix(".md") in ("01", "02", "03", "04")
    ]
    if not files:
        raise Unmeasurable("no review files")
    for f in files:
        unit = f.name.split("-")[1].removesuffix(".md")
        first = next((m.group(1) for m in VERDICT.finditer(f.read_text())), None)
        if first is None:
            raise Unmeasurable(f"{f.name} carries no verdict")
        slot = table.setdefault(unit, {"files": 0, "NOT YET": 0, "SHIP": 0})
        slot["files"] += 1
        slot[first] += 1
    return table


def main() -> None:
    set_name = sys.argv[1] if len(sys.argv) > 1 else "home-a"
    print(
        json.dumps(
            {
                "set": set_name,
                "cost": cost(set_name),
                "picks": picks(set_name),
                "outside": outside(set_name),
                "commits": commits(),
                "reviews": reviews(),
            },
            indent=1,
        )
    )


if __name__ == "__main__":
    main()
