"""Three text jobs, both models, the same prompts and the same checks."""

from __future__ import annotations

import hashlib
import json
import re

from listing_partner import fair_housing, scoring
from listing_partner.facts import prompt_facts

# A live run on the longer prompt spent all 8192 output tokens on reasoning, four times of four.
MAX_TOKENS = 16000
_RULES = (
    "Use only these facts and these photo notes. Every number and every amenity you state must "
    "be in the facts. Do not state one that is not, even if a room label or a photo note "
    "mentions it, and give no count of windows, photos or anything else the facts do not count. "
    "Anything else you say about how a room looks must come from the room labels and the notes. "
    "Invent nothing. A note's remarks about the photo itself (clear, centered, visible) say "
    "nothing about the home, and several photos can show the same room. Describe the property "
    "only: never say who should or should not live there (family status, age, religion, race, "
    "color, national origin, sex, disability). Reply with the requested text only, no preface."
)
_DESCRIPTION_SHAPE = (
    "90 to 200 words. State each fact once and do not repeat any of them. Then describe the "
    "rooms that were photographed, in the order listed, as plain prose for a renter. Combine "
    "photos of the same room into one passage and never mention the photos. An amenity that "
    "belongs to a room is stated once, where that room is described"
)
_LIMITS = {
    "description": _DESCRIPTION_SHAPE,
    "caption_social": "under 300 characters, plus up to 5 hashtags",
    "caption_video": "under 150 characters",
}
_LENGTH = {
    "description": scoring.check_description_length,
    "caption_social": scoring.check_social_caption,
    "caption_video": scoring.check_video_caption,
}
JOB_OF = {"description": "description", "caption_social": "captions", "caption_video": "captions"}


def prompt_hash(prompt: str) -> str:
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:16]


def _photo_line(photo: dict) -> str:
    note = str(photo.get("note") or "").strip()
    return f"- {photo['room']}: {note}" if note else f"- {photo['room']}"


def _context(facts: dict, photos: list[dict]) -> str:
    lines = "\n".join(_photo_line(p) for p in photos)
    outside = scoring.amenities_outside_the_facts(lines, facts)
    leave_out = (
        f"Leave out completely, they are not in the facts: {', '.join(outside)}.\n"
        if outside
        else ""
    )
    return (
        f"Facts: {json.dumps(prompt_facts(facts), sort_keys=True)}\n"
        f"Photos in walk-through order, each a room label and a short note:\n{lines}\n"
        f"{leave_out}{_RULES}"
    )


def description_prompt(facts, photos):
    head = f"DESCRIPTION. Write a rental listing description, {_DESCRIPTION_SHAPE}."
    return f"{head}\n{_context(facts, photos)}"


def captions_prompt(facts, photos):
    return (
        "CAPTIONS. Write two social captions. Reply with JSON only: "
        '{"instagram_facebook": "...", "video": "..."}. instagram_facebook is under 300 '
        "characters plus up to 5 hashtags. video is for a short video post, under 150 "
        f"characters.\n{_context(facts, photos)}"
    )


def review_prompt(text: str) -> str:
    return (
        "REVIEW. You are checking rental advertising under the U.S. Fair Housing Act, 42 U.S.C. "
        "3604(c). Does this text state or imply a preference, limitation or discrimination based "
        "on race, color, religion, sex, disability, familial status or national origin? "
        "Describing the property itself is fine. Reply on one line: PASS, or FAIL - and the "
        f"reason.\nText:\n{text}"
    )


def rewrite_prompt(text_id, text, failures, facts, photos):
    named = "\n".join(f"- {f}" for f in failures)
    return (
        f"REWRITE. This text failed these checks:\n{named}\nText:\n{text}\nRewrite it to pass, "
        f"{_LIMITS[text_id]}. Reply with the text only.\n{_context(facts, photos)}"
    )


def parse_review(text: str | None) -> tuple[str | None, str]:
    """(pass, fail, or None when the reply says neither), and the reason."""
    match = re.match(r"\s*\W*(PASS|FAIL)\b\W*(.*)", text or "", re.I | re.S)
    if not match:
        return None, "reply was neither PASS nor FAIL"
    return match.group(1).lower(), match.group(2).strip()


_WHOLE_FENCE = re.compile(r"\A```[\w-]*[ \t]*\n?(.*?)\n?```\Z", re.S)
# A wrapper inside a wrapper is unwrapped too. Past this depth the format check fails it.
_MAX_WRAPPERS = 4


def parse_text_reply(reply: str | None) -> str:
    """The text inside a whole-reply wrapper from either model: a code fence, a JSON
    string or a JSON object with one string value. Anything else comes back as it was,
    and the format check fails what should not go out."""
    text = (reply or "").strip()
    for _ in range(_MAX_WRAPPERS):
        fence = _WHOLE_FENCE.match(text)
        if fence:
            text = fence.group(1).strip()
            continue
        try:
            data = json.loads(text)
        except ValueError:
            break
        if isinstance(data, dict) and len(data) == 1:
            data = next(iter(data.values()))
            if isinstance(data, dict):
                data = json.dumps(data)
        if not isinstance(data, str):
            break
        text = data.strip()
    return text


def _parse_captions(text: str) -> tuple[str, str] | None:
    start, end = text.find("{"), text.rfind("}")
    try:
        data = json.loads(text[start : end + 1])
        social, video = data["instagram_facebook"], data["video"]
    except (ValueError, KeyError, TypeError):
        return None
    return (social, video) if isinstance(social, str) and isinstance(video, str) else None


def raw_captions(reply: str) -> tuple[str, str, str | None]:
    """(social, video, format failure), before any wrapper comes off. A reply that is
    not the requested pair stands in for both, as a failure."""
    pair = _parse_captions(reply)
    if pair:
        return pair[0].strip(), pair[1].strip(), None
    text = reply.strip()
    return text, text, "format: reply was not the requested JSON"


def text_failures(text_id: str, text: str, facts: dict, extra_failure: str | None = None) -> list:
    """Every check that reads only the text. The second opinion is added by the caller."""
    failures = [extra_failure] if extra_failure else []
    failures += scoring.check_plain_text(text)
    failures += scoring.check_facts(text, facts)
    failures += [
        f"fair housing: {h['phrase']} ({h['category']})" for h in fair_housing.find_phrases(text)
    ]
    failures += _LENGTH[text_id](text)
    return failures


def opinion_failures(opinion: str) -> list[str]:
    if opinion == "fail":
        return ["second opinion: both models failed this text"]
    if opinion == "flag":
        return ["second opinion: the models did not agree, a person decides"]
    return []


def status_of(attempt: dict) -> str:
    hard = [f for f in attempt["failures"] if not f.startswith("second opinion")]
    if hard or attempt["second_opinion"] == "fail":
        return "failed"
    return "flagged" if attempt["second_opinion"] == "flag" else "pass"


def pick_better(texts: list[dict], costs: dict, review_stats: dict) -> dict:
    """Which model did better on each job, from every attempt and its cost."""
    picks = {}
    for job in ("description", "captions"):
        rows = {
            p: {
                "failed_checks": sum(
                    len(a["failures"])
                    for t in texts
                    if t["provider"] == p and t["job"] == job
                    for a in t["attempts"]
                ),
                "cost_usd": round(costs[p][job], 6),
            }
            for p in costs
        }
        picks[job] = {"rows": rows, "better": choose(rows)}
    rows = {
        p: {
            "failed_checks": review_stats[p]["unreadable"] + review_stats[p]["missed"],
            "cost_usd": round(costs[p]["review"], 6),
            **review_stats[p],
        }
        for p in costs
    }
    picks["review"] = {"rows": rows, "better": choose(rows)}
    return picks


def choose(rows: dict) -> str:
    """Fewer failed checks first, then lower cost. A dead heat is a tie."""
    a, b = rows["meta"], rows["baseten"]
    if a["failed_checks"] != b["failed_checks"]:
        return "meta" if a["failed_checks"] < b["failed_checks"] else "baseten"
    if round(a["cost_usd"], 6) != round(b["cost_usd"], 6):
        return "meta" if a["cost_usd"] < b["cost_usd"] else "baseten"
    return "tie"


def run_writing(facts: dict, photos: list[dict], providers: dict, log) -> dict:
    """photos are the kept shots in order, each with its room and note. providers
    maps meta and baseten to (prompt, max_tokens) -> client result. log receives
    one row per model call."""
    costs = {p: {"description": 0.0, "captions": 0.0, "review": 0.0} for p in providers}
    review_stats = {p: {"unreadable": 0, "missed": 0} for p in providers}

    def call(provider, prompt):
        out = providers[provider](prompt, MAX_TOKENS)
        return out, prompt_hash(prompt)

    def row(job, text_id, attempt, provider, phash, out, **extra):
        log(
            {
                "job": job,
                "text_id": text_id,
                "attempt": attempt,
                "provider": provider,
                "model": providers[provider].model,
                "prompt_hash": phash,
                "cost_usd": round(out["actual_usd"], 6),
                "request_id": out.get("request_id"),
                "output": out["text"],
                **extra,
            }
        )

    def evaluate(text_id, author, text, attempt, extra_failure=None):
        failures = text_failures(text_id, text, facts, extra_failure)
        words = fair_housing.find_phrases(text)
        reviews = {}
        prompt = review_prompt(text)
        for reviewer in providers:
            out, phash = call(reviewer, prompt)
            verdict, reason = parse_review(out["text"])
            costs[reviewer]["review"] += out["actual_usd"]
            if verdict is None:
                review_stats[reviewer]["unreadable"] += 1
            elif verdict == "pass" and words:
                review_stats[reviewer]["missed"] += 1
            reviews[reviewer] = {"verdict": verdict, "reason": reason}
            row(
                "review",
                text_id,
                attempt,
                reviewer,
                phash,
                out,
                reviewed_author=author,
                verdicts={reviewer: verdict},
            )
        opinion = scoring.second_opinion(reviews["meta"]["verdict"], reviews["baseten"]["verdict"])
        failures += opinion_failures(opinion)
        return {
            "text": text,
            "failures": failures,
            "reviews": reviews,
            "second_opinion": opinion,
        }

    def needs_rewrite(attempt):
        # A disagreement alone goes to a person as written. A hard failure gets its
        # one rewrite either way, and the page keeps showing the original's flag.
        if attempt["second_opinion"] == "fail":
            return True
        return any(not f.startswith("second opinion") for f in attempt["failures"])

    def finish(text_id, author, first):
        attempts = [first]
        if needs_rewrite(first):
            prompt = rewrite_prompt(text_id, first["text"], first["failures"], facts, photos)
            out, phash = call(author, prompt)
            costs[author][JOB_OF[text_id]] += out["actual_usd"]
            rewritten = parse_text_reply(out["text"])
            second = evaluate(
                text_id, author, rewritten, 1, None if rewritten else "format: reply unreadable"
            )
            row(
                JOB_OF[text_id],
                text_id,
                1,
                author,
                phash,
                out,
                checks={text_id: second["failures"]},
                verdicts={text_id: second["reviews"]},
            )
            attempts.append(second)
        last = attempts[-1]
        return {
            "id": text_id,
            "job": JOB_OF[text_id],
            "provider": author,
            "model": providers[author].model,
            "attempts": attempts,
            "final": last["text"],
            "status": status_of(last),
            "first_version_flagged": len(attempts) > 1 and first["second_opinion"] == "flag",
        }

    texts = []
    for author in providers:
        prompt = description_prompt(facts, photos)
        out, phash = call(author, prompt)
        costs[author]["description"] += out["actual_usd"]
        text = parse_text_reply(out["text"])
        first = evaluate(
            "description", author, text, 0, None if text else "format: reply unreadable"
        )
        row(
            "description",
            "description",
            0,
            author,
            phash,
            out,
            checks={"description": first["failures"]},
            verdicts={"description": first["reviews"]},
        )
        texts.append(finish("description", author, first))

        prompt = captions_prompt(facts, photos)
        out, phash = call(author, prompt)
        costs[author]["captions"] += out["actual_usd"]
        social, video, bad = raw_captions(out["text"])
        firsts = {
            "caption_social": evaluate("caption_social", author, parse_text_reply(social), 0, bad),
            "caption_video": evaluate("caption_video", author, parse_text_reply(video), 0, bad),
        }
        row(
            "captions",
            "captions",
            0,
            author,
            phash,
            out,
            checks={k: v["failures"] for k, v in firsts.items()},
            verdicts={k: v["reviews"] for k, v in firsts.items()},
        )
        texts.extend(finish(k, author, v) for k, v in firsts.items())

    return {"texts": texts, "picks": pick_better(texts, costs, review_stats)}
