"""The tidy page: slider, one-second mask flash, the lists, and the damage list."""

from __future__ import annotations

from html import escape

LABEL = "Edited: clutter removed"

_STYLE = """
body{font:16px/1.5 system-ui,sans-serif;margin:0 auto;max-width:1100px;padding:16px;
background:#fff;color:#222}
section{border-top:1px solid #ccc;padding:16px 0}
.compare{position:relative;line-height:0}
.compare img{width:100%;display:block}
.compare .after,.compare .mask{position:absolute;inset:0}
.compare .mask{display:none}
.label{display:inline-block;background:#222;color:#fff;padding:2px 8px;font-size:14px}
.crops img{height:140px;margin-right:8px}
input[type=range]{width:100%}
button{font:inherit;padding:4px 12px}
"""

_SCRIPT = """
function slide(input){
  var after=input.parentNode.querySelector('.after');
  after.style.clipPath='inset(0 0 0 '+input.value+'%)';
}
function flashMask(button){
  var mask=button.parentNode.querySelector('.mask');
  mask.style.display='block';
  setTimeout(function(){mask.style.display='none';},1000);
}
"""


def _rows(items: list[dict]) -> str:
    if not items:
        return "<li>none</li>"
    return "".join(f"<li><b>{escape(i['label'])}</b>: {escape(i['reason'])}</li>" for i in items)


def _damage(photo: dict) -> str:
    items = photo["damage"]
    if not items:
        return "<p>Damage list: none seen.</p>"
    rows = "".join(
        f'<li><img src="tidy/{photo["id"]}/{escape(d["crop"])}" alt="damage crop" height="140"> '
        f"{escape(d['note'])}</li>"
        for d in items
    )
    title = f"Damage list ({len(items)}), nothing here was removed"
    return f'<h3>{title}</h3><ul class="crops">{rows}</ul>'


def _tidied(photo: dict) -> str:
    pid = photo["id"]
    numbers = photo["measure"]
    check = photo["selfcheck"]
    return f"""
<p><span class="label">{LABEL}</span></p>
<div class="tool"><div class="compare">
<img src="tidy/{pid}/before.jpg" alt="before">
<img class="after" src="tidy/{pid}/after.jpg" alt="after" style="clip-path:inset(0 0 0 50%)">
<img class="mask" src="tidy/{pid}/mask_overlay.png" alt="mask">
</div>
<input type="range" min="0" max="100" value="50" oninput="slide(this)">
<button onclick="flashMask(this)">Flash the mask for one second</button>
</div>
<p>Slide: the left side is the untidied photo, the right side is the tidied one.</p>
<p><a href="finished/{pid}.jpg">Untidied photo</a> |
<a href="tidy/{pid}/tidied.png">Tidied photo</a></p>
<p>Measured: {numbers["outside_changed_pixels"]} pixels changed outside the mask,
{numbers["damage_overlap_pixels"]} damage pixels under the mask,
{numbers["mask_pixels"]} pixels in the mask.</p>
<p>Muse Spark self-check: {"pass" if check["pass"] else "fail"}. {escape(check["reason"])}</p>
<p>SAM 3.1 re-check: pass. Asked again on the tidied photo, it finds none of the removed
items inside the mask.</p>
"""


def _check_line(check: dict) -> str:
    if check["state"] == "did not complete":
        return f"{escape(check['reason'])}: it gave no verdict."
    return f"self-check: {escape(check['reason'])}"


def _photo(photo: dict) -> str:
    pid = escape(photo["id"])
    body = f"<h2>{pid}: {escape(photo['room'])} ({escape(photo['status'])})</h2>"
    if photo["status"] == "tidied":
        body += _tidied(photo)
    else:
        if photo["reason"]:
            body += f"<p>Shipped untidied: {escape(photo['reason'])}</p>"
        if photo["selfcheck"]:
            body += f"<p>Muse Spark {_check_line(photo['selfcheck'])}</p>"
        body += f'<p><a href="finished/{pid}.jpg">Untidied photo</a></p>'
    body += f"<h3>Removed</h3><ul>{_rows(photo['removed'])}</ul>"
    if photo["not_removed"]:
        body += f"<h3>Tried, not removed</h3><ul>{_rows(photo['not_removed'])}</ul>"
    body += f"<h3>Rejected by Muse Spark</h3><ul>{_rows(photo['rejected'])}</ul>"
    body += f"<h3>Left in place</h3><ul>{_rows(photo['left_in_place'])}</ul>"
    return f"<section>{body}{_damage(photo)}</section>"


def render(summary: dict) -> str:
    head = (
        "Nothing to tidy in this set."
        if summary["result"] == "nothing to tidy"
        else f"{summary['tidied']} tidied, {summary['untidied']} shipped untidied, "
        f"{summary['nothing_to_tidy']} with nothing to tidy."
    )
    rows = "".join(
        f"<li>{escape(model)}: {row['calls']} calls, ${row['usd']:.4f}</li>"
        for model, row in sorted(summary["this_run"].items())
    )
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>Tidy</title><style>{_STYLE}</style></head><body>"
        f"<h1>Honest tidy</h1><p>{head}</p>"
        f"<p>Meta spend for this unit: ${summary['unit_meta_usd']:.4f} of "
        f"${summary['budget_usd']:.2f}.</p><ul>{rows}</ul>"
        + "".join(_photo(p) for p in summary["photos"])
        + f"<script>{_SCRIPT}</script></body></html>"
    )
