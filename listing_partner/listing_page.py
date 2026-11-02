"""One page: photos in order, facts, coverage, both models side by side, cost."""

from __future__ import annotations

import random
from html import escape
from pathlib import Path

from listing_partner.facts import is_sample, prompt_facts

NAMES = {"meta": "Muse Spark", "baseten": "Muse Spark Open"}
TITLES = {
    "description": "Listing description",
    "caption_social": "Instagram and Facebook caption",
    "caption_video": "Short video caption",
}
CSS = """
:root{--bg:#fff;--fg:#1a1a1a;--line:#ddd;--bad:#a4161a;--warn:#8a5a00;--ok:#1b6e3c}
@media (prefers-color-scheme:dark){:root{--bg:#161616;--fg:#eee;--line:#444;--bad:#ff8b8b;
--warn:#f0c060;--ok:#7fd8a0}}
body{background:var(--bg);color:var(--fg);font:16px/1.5 system-ui;max-width:1200px;
margin:0 auto;padding:16px}
.who{display:none}
body.show .who{display:inline}
.photos{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:12px}
.photos img{width:100%;display:block}
.pair{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:16px}
.card{border:1px solid var(--line);padding:12px}
table{border-collapse:collapse;width:100%}
td,th{border:1px solid var(--line);padding:4px 8px;text-align:left;vertical-align:top}
.pass{color:var(--ok)}.failed{color:var(--bad)}.flagged{color:var(--warn)}
button{font:inherit;padding:6px 12px}
"""


def _who(provider: str) -> str:
    return f' <span class="who">({NAMES[provider]})</span>'


def _photo(p: dict, position: int | None) -> str:
    head = f"{position}. " if position else ""
    extra = f"<p>{escape(p['reason'])}</p>" if p.get("reason") else ""
    return (
        f'<figure><img loading="lazy" src="finished/{escape(p["id"])}.jpg" '
        f'alt="{escape(p["room"])}">'
        f"<figcaption>{head}{escape(p['room'])} (photo {escape(p['id'])}, sharpness "
        f"{p['sharpness']}, framing {p['framing']}){extra}</figcaption></figure>"
    )


def _status(text: dict) -> str:
    words = {
        "pass": "Passed every check",
        "failed": "FAILED. Do not post",
        "flagged": "FLAGGED for a person. The models did not agree",
    }
    return f'<p class="{text["status"]}"><strong>{words[text["status"]]}</strong></p>'


def _card(label: str, text: dict, reviewers: dict) -> str:
    last = text["attempts"][-1]
    checks = "".join(f"<li>{escape(f)}</li>" for f in last["failures"]) or "<li>no failures</li>"
    reviews = "".join(
        f"<li>Reviewer {reviewers[p]}{_who(p)}: {escape(str(r['verdict'] or 'no verdict'))}"
        f"{' - ' + escape(r['reason']) if r['reason'] else ''}</li>"
        for p, r in last["reviews"].items()
    )
    earlier = ""
    if len(text["attempts"]) > 1:
        first = text["attempts"][0]
        named = "; ".join(escape(f) for f in first["failures"])
        earlier = (
            f"<details><summary>First version, rewritten once</summary><p>{escape(first['text'])}"
            f"</p><p>Failed: {named}</p></details>"
        )
    return (
        f'<div class="card"><h4>{label}{_who(text["provider"])}</h4>{_status(text)}'
        f'<p style="white-space:pre-wrap">{escape(text["final"])}</p>'
        f"<p>Checks on the text shown:</p><ul>{checks}</ul>"
        f"<p>Fair housing review:</p><ul>{reviews}</ul>{earlier}</div>"
    )


def _pick(job: str, pick: dict) -> str:
    rows = "".join(
        f"<li>{NAMES[p]}: {r['failed_checks']} failed checks, ${r['cost_usd']:.6f}</li>"
        for p, r in pick["rows"].items()
    )
    better = "tie" if pick["better"] == "tie" else NAMES[pick["better"]]
    return f'<div class="who"><p>Better on {job}: {better}</p><ul>{rows}</ul></div>'


def build_page(path: Path, *, facts, curation, coverage, writing, costs, benchmark, rng=None):
    rng = rng or random.SystemRandom()
    parts = [
        "<!doctype html><meta charset=utf-8><title>Listing Package</title>",
        '<meta name="viewport" content="width=device-width,initial-scale=1">',
        f"<style>{CSS}</style><h1>Listing package</h1>",
        "<p><button onclick=\"document.body.classList.toggle('show')\">show which model</button></p>",
    ]
    origin = (
        "Sample data: a fictional unit."
        if is_sample(facts)
        else "From Bokani's existing read-only AppFolio connector, built before the hackathon."
    )
    kept, dropped = curation["kept"], curation["dropped"]
    parts.append(f"<h2>Kept photos, in order ({len(kept)})</h2><div class=photos>")
    parts += [_photo(p, i + 1) for i, p in enumerate(kept)]
    parts.append(f"</div><h2>Dropped photos ({len(dropped)})</h2><div class=photos>")
    parts += [_photo(p, None) for p in dropped]
    parts.append(f"</div><h2>Facts</h2><p>{origin}</p><table>")
    for key, value in prompt_facts(facts).items():
        shown = ", ".join(map(str, value)) if isinstance(value, list) else value
        parts.append(
            f"<tr><th>{escape(key.replace('_', ' '))}</th><td>{escape(str(shown))}</td></tr>"
        )
    parts.append(
        "</table><h2>Coverage check</h2><table><tr><th>Room</th><th>Result</th><th>Photo</th></tr>"
    )
    for row in coverage:
        css = {"found": "pass", "missing": "failed"}.get(row["status"], "flagged")
        parts.append(
            f"<tr><td>{escape(row['room'])}</td><td class={css}>{escape(row['status'])}</td>"
            f"<td>{escape(row['photo'] or '')}</td></tr>"
        )
    parts.append("</table>")
    if benchmark:
        parts.append(
            "<h2>Against the published MLS set</h2>"
            f"<p>Kept by both: {len(benchmark['kept_both'])}. "
            f"Kept here only: {', '.join(benchmark['we_kept_he_dropped']) or 'none'}. "
            "Dropped here but published: "
            f"{', '.join(benchmark['we_dropped_he_kept']) or 'none'}. "
            f"Different position: {benchmark['different_position']}. "
            f"Rank correlation: {benchmark['rank_correlation']}.</p>"
        )
    else:
        parts.append("<h2>Against the published MLS set</h2><p>Not measured: no MLS set here.</p>")

    review_order = ["meta", "baseten"]
    rng.shuffle(review_order)
    reviewers = dict(zip(review_order, "AB"))
    by_id = {(t["id"], t["provider"]): t for t in writing["texts"]}
    parts.append("<h2>Writing</h2>")
    for job in ("description", "caption_social", "caption_video"):
        order = ["meta", "baseten"]
        rng.shuffle(order)
        parts.append(f"<h3>{TITLES[job]}</h3><div class=pair>")
        parts += [_card(lab, by_id[(job, p)], reviewers) for lab, p in zip("AB", order)]
        parts.append("</div>")
    parts.append("<h3>Which model did better</h3>")
    parts += [_pick(job, writing["picks"][job]) for job in ("description", "captions", "review")]
    parts.append('<p>Names and results stay hidden until "show which model" is on.</p>')

    parts.append(
        "<h2>Cost per listing, this run</h2><table><tr><th>Provider</th><th>Model</th>"
        "<th>Calls</th><th>USD</th></tr>"
    )
    rows = [
        ("Meta", "Muse Spark", costs["meta"]["muse-spark-1.3"]),
        ("Meta", "SAM 3.1", costs["meta"]["sam-3.1"]),
        ("Baseten", "Muse Spark Open", next(iter(costs["baseten"].values()))),
    ]
    for provider, model, c in rows:
        parts.append(
            f"<tr><td>{provider}</td><td>{model}</td><td>{c['calls']}</td><td>${c['usd']:.4f}</td></tr>"
        )
    total = sum(c["usd"] for _, _, c in rows)
    parts.append(f"<tr><th colspan=3>Total this run</th><th>${total:.4f}</th></tr></table>")
    earlier = costs.get("sam_all_runs_usd", 0.0)
    parts.append(
        f"<p>This run makes no SAM 3.1 calls: window masks come from the earlier finish step. All "
        f"SAM 3.1 calls in the ledger so far, including repeat test runs, cost ${earlier:.4f}.</p>"
    )
    Path(path).write_text("".join(parts), encoding="utf-8")
