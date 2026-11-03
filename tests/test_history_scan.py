"""The full-history scan's detectors fire on what they claim to catch."""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _scan():
    spec = importlib.util.spec_from_file_location("history_scan", ROOT / "scripts/history_scan.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# Built at run time so this file never matches the repo's own email and phone scans.
EMAIL = "jane" + "@" + "corp.org"
SHAPED = "x" + "@" + "K8.hZ"
PHONE = "555" + "-867-" + "5309"
RENT = (
    "t.rent_monthly_usd",
    re.compile(r"(?<![\d.,])(?<!x )(?<!y )(1234|1,234)(?![\d,]|\.\d|-\d)"),
)


def _hits(text, blob=""):
    hits = []
    _scan().scan_text("f", text, ["Elm Street"], [RENT], hits, blob=blob)
    return hits


def test_each_detector_fires_and_names_its_check():
    assert _hits("at 12 elm street") == ["banned entry #1: f"]
    assert _hits("key sk-" + "a" * 24)[0].startswith("secret pattern")
    assert _hits("mail " + EMAIL)[0].startswith("email address")
    assert _hits("call " + PHONE)[0].startswith("phone number")
    assert _hits("rent is $1,234 a month")[0].startswith("facts value t.rent_monthly_usd")
    assert _hits("rent 1234")[0].startswith("facts value t.rent_monthly_usd")


def test_clean_text_and_known_shapes_pass():
    assert _hits("plain words, no secrets") == []
    assert _hits("x 1234-3300, y 3000-3978") == [], "a pixel range is not the rent"
    assert _hits("12345 pixels") == []
    assert _hits("users.noreply.github.com address: 1+x@users.noreply.github.com") == []


def test_the_email_allowance_is_one_blob_and_one_check():
    scan = _scan()
    (blob,) = scan.EMAIL_SHAPED_OK
    assert _hits(SHAPED, blob=blob) == []
    assert _hits(SHAPED, blob="0" * 40)[0].startswith("email address")
    assert _hits("call " + PHONE, blob=blob)[0].startswith("phone number"), (
        "the allowance skips the email check only"
    )
