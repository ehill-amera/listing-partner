"""Score and render a finished run again from its saved log. Makes no model call:
no client is imported here, and the only inputs are files the run already saved.

Usage: python -m listing_partner.rescore --unit unit-a
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from listing_partner import coverage, curate, fair_housing, listing_page, scoring, writing
from listing_partner.facts import load_facts

PROVIDERS = ("meta", "baseten")
TEXT_IDS = ("description", "caption_social", "caption_video")
NOTE = (
    "Scored and rendered again from this run's saved outputs, with no model call. {n} saved "
    "text(s) had a wrapper removed. Every word is what the model wrote."
)


class SavedLogInvalid(Exception):
    """The saved log does not hold one complete run. Nothing is rendered from it."""


def _read_rows(path: Path) -> list[dict]:
    try:
        rows = [json.loads(x) for x in Path(path).read_text().splitlines() if x.strip()]
    except (OSError, ValueError) as exc:
        raise SavedLogInvalid(f"saved log unreadable: {type(exc).__name__}") from exc
    if not rows:
        raise SavedLogInvalid("saved log is empty")
    return rows


def _authored(rows: list[dict]) -> dict:
    """(provider, text id, attempt) -> (raw text the old run reviewed, its row, format failure)."""
    out = {}

    def add(key, raw, row, bad):
        if key in out:
            raise SavedLogInvalid(f"saved log repeats {key}")
        out[key] = (raw, row, bad)

    for row in rows:
        job, provider, attempt = row["job"], row["provider"], row["attempt"]
        if job == "review":
            continue
        if row["text_id"] == "captions":
            social, video, bad = writing.raw_captions(row["output"])
            add((provider, "caption_social", attempt), social, row, bad)
            add((provider, "caption_video", attempt), video, row, bad)
        else:
            add((provider, row["text_id"], attempt), row["output"].strip(), row, None)
    return out


def _reviews_of(rows, author, text_id, attempt, raw, final) -> tuple[dict, bool]:
    """The saved reviews of this attempt, and whether they read it with the wrapper on.
    A review whose prompt matches neither form was of some other text, and that raises."""
    hashes = {
        writing.prompt_hash(writing.review_prompt(final)): False,
        writing.prompt_hash(writing.review_prompt(raw)): raw != final,
    }
    reviews, wrapped = {}, set()
    for row in rows:
        same = (row["text_id"], row["attempt"], row.get("reviewed_author")) == (
            text_id,
            attempt,
            author,
        )
        if row["job"] != "review" or not same:
            continue
        if row["prompt_hash"] not in hashes:
            raise SavedLogInvalid(f"a saved review of {author}/{text_id} read a different text")
        wrapped.add(hashes[row["prompt_hash"]])
        verdict, reason = writing.parse_review(row["output"])
        if verdict != row["verdicts"][row["provider"]]:
            raise SavedLogInvalid(f"a saved verdict on {author}/{text_id} does not match its reply")
        reviews[row["provider"]] = {"verdict": verdict, "reason": reason}
    if set(reviews) != set(PROVIDERS):
        raise SavedLogInvalid(f"saved log lacks both reviews of {author}/{text_id}")
    return {p: reviews[p] for p in PROVIDERS}, True in wrapped


def rescore_log(rows: list[dict], facts: dict) -> dict:
    """The run's texts, statuses and picks from its saved rows, by the current checks."""
    authored = _authored(rows)
    costs = {p: {"description": 0.0, "captions": 0.0, "review": 0.0} for p in PROVIDERS}
    stats = {p: {"unreadable": 0, "missed": 0} for p in PROVIDERS}
    for row in rows:
        costs[row["provider"]][row["job"]] += row["cost_usd"]

    def rebuild(author, text_id, attempt):
        raw, row, bad = authored[(author, text_id, attempt)]
        final = writing.parse_text_reply(raw)
        if not bad and not final:
            bad = "format: reply unreadable"
        reviews, wrapped = _reviews_of(rows, author, text_id, attempt, raw, final)
        for p, review in reviews.items():
            if review["verdict"] is None:
                stats[p]["unreadable"] += 1
            elif review["verdict"] == "pass" and fair_housing.find_phrases(final):
                stats[p]["missed"] += 1
        opinion = scoring.second_opinion(reviews["meta"]["verdict"], reviews["baseten"]["verdict"])
        failures = writing.text_failures(text_id, final, facts, bad)
        failures += writing.opinion_failures(opinion)
        built = {
            "text": final,
            "failures": failures,
            "reviews": reviews,
            "second_opinion": opinion,
            "reviewed_with_wrapper": wrapped,
        }
        return built, row["model"]

    texts = []
    for author in PROVIDERS:
        for text_id in TEXT_IDS:
            if (author, text_id, 0) not in authored:
                raise SavedLogInvalid(f"saved log has no {author}/{text_id}")
            first, model = rebuild(author, text_id, 0)
            attempts = [first]
            if (author, text_id, 1) in authored:
                attempts.append(rebuild(author, text_id, 1)[0])
            texts.append(
                {
                    "id": text_id,
                    "job": writing.JOB_OF[text_id],
                    "provider": author,
                    "model": model,
                    "attempts": attempts,
                    "final": attempts[-1]["text"],
                    "status": writing.status_of(attempts[-1]),
                    "first_version_flagged": len(attempts) > 1
                    and first["second_opinion"] == "flag",
                }
            )
    return {"texts": texts, "picks": writing.pick_better(texts, costs, stats)}


def rescore(*, output_dir, facts_path) -> dict:
    """Rewrite the page and the summary from saved files. The log is only read."""
    output_dir = Path(output_dir)
    facts = load_facts(facts_path)
    log_path = output_dir / "writing" / "log.jsonl"
    rows = _read_rows(log_path)
    summary = json.loads((output_dir / "listing_summary.json").read_text())
    curation = curate.load_saved(output_dir / "curation.json", output_dir / "finished")
    result = rescore_log(rows, facts)
    unwrapped = [
        f"{t['id']}/{t['provider']}"
        for t in result["texts"]
        if t["attempts"][-1]["reviewed_with_wrapper"]
    ]
    listing_page.build_page(
        output_dir / "listing.html",
        facts=facts,
        curation=curation,
        coverage=coverage.check_coverage(facts, curation["kept"]),
        writing=result,
        costs=summary["costs"],
        benchmark=summary["benchmark"],
        note=NOTE.format(n=len(unwrapped)),
    )
    summary.update(
        picks=result["picks"],
        statuses={f"{t['id']}/{t['provider']}": t["status"] for t in result["texts"]},
        rewrites=sum(len(t["attempts"]) > 1 for t in result["texts"]),
        descriptions={
            t["provider"]: {
                "words": len(t["final"].split()),
                "fact_mentions": scoring.fact_mentions(t["final"], facts),
            }
            for t in result["texts"]
            if t["id"] == "description"
        },
        rescored={
            "at": datetime.now(timezone.utc).isoformat(),
            "model_calls": 0,
            "log_sha256": hashlib.sha256(log_path.read_bytes()).hexdigest(),
            "wrapper_removed_from": unwrapped,
        },
    )
    (output_dir / "listing_summary.json").write_text(json.dumps(summary, indent=1))
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--unit", default="unit-a")
    args = parser.parse_args()
    root = Path(__file__).resolve().parent.parent
    summary = rescore(
        output_dir=root / "output" / args.unit, facts_path=root / "facts" / f"{args.unit}.json"
    )
    print(f"done: {len(summary['statuses'])} texts, 0 model calls")


if __name__ == "__main__":
    main()
