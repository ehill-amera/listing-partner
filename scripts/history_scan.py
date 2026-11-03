"""Full-history hygiene scan: every commit, every file version, every message.

Usage: .venv/bin/python scripts/history_scan.py

Checks every blob reachable from any ref, every path it was ever stored at,
every commit message, author and committer email, and every ref name for:
banned strings (the private list outside the repo), keys and tokens, email
addresses, phone numbers, identifying facts values of every private set
(source, city, unit name, rent, square feet, deposit), and GPS or camera-serial
metadata in any image. Bed and bath counts, property type, state and amenities
are not scanned: small numbers, a state code and common words ("fireplace")
carry no identity, and they occur in the amenity lists, the fictional sample
facts and the tests. The street address and other identifying strings are on
the banned list, which is scanned everywhere.

Never prints a private value: a hit names the check, the entry or field, the
commit or path, and line numbers. Exits 1 on any hit, and on a missing or empty
banned list, so a scan against nothing never reads as clean.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import hygiene_images  # noqa: E402

# Same patterns and exclusions as scripts/check.
SECRET = re.compile(
    r"(sk-[A-Za-z0-9]{20,}|ghp_[A-Za-z0-9]|gho_[A-Za-z0-9]|LLM_[A-Za-z0-9_]{10,}"
    r"|AKIA[0-9A-Z]{16}|xox[bap]-)",
    re.I,
)
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
EMAIL_OK = re.compile(r"users\.noreply\.github\.com|example\.com|@media|@2x|@3x", re.I)
PHONE = re.compile(r"(\+?1[-. ]?)?\(?[0-9]{3}\)?[-. ][0-9]{3}[-. ][0-9]{4}")
#: File versions whose email-shaped text is known not to be an address, by full
#: blob hash: any edit to the file is a new blob and is scanned in full.
EMAIL_SHAPED_OK = {
    # SAM 3.1 arithmetic-coded mask payload: random printable runs in it
    # (letters, an at sign, letters, a dot, two letters) match the email shape.
    "69944849d8c1d6b86a3e07c4c43fc5565afa81de",
}
IMAGE_MAGIC = (b"\xff\xd8\xff", b"\x89PNG", b"II*\x00", b"MM\x00*", b"RIFF", b"GIF8")


def git(*args: str, data: bytes | None = None) -> bytes:
    return subprocess.run(
        ["git", *args], cwd=ROOT, input=data, capture_output=True, check=True
    ).stdout


def banned_list() -> list[str]:
    path = ROOT.parent / ".listing-partner-private" / "banned-strings.txt"
    entries = [
        line.strip()
        for line in path.read_text().splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    if not entries:
        raise SystemExit(f"BANNED LIST EMPTY: {path}")
    return entries


def facts_patterns() -> list[tuple[str, re.Pattern]]:
    out = []
    for path in sorted((ROOT / "facts").glob("*.json")):
        facts = json.loads(path.read_text())
        tag = path.stem
        for key in ("source", "city"):
            if facts.get(key):
                out.append((f"{tag}.{key}", re.compile(re.escape(str(facts[key])), re.I)))
        if facts.get("unit") and facts["unit"] != tag:
            out.append((f"{tag}.unit", re.compile(re.escape(str(facts["unit"])), re.I)))
        for key in ("rent_monthly_usd", "square_feet", "deposit_usd"):
            value = facts.get(key)
            if value:
                forms = "|".join(re.escape(f) for f in {str(value), f"{value:,}"})
                # Not a pixel range ("x 1800-3300") or part of a longer number.
                rx = rf"(?<![\d.,])(?<!x )(?<!y )({forms})(?![\d,]|\.\d|-\d)"
                out.append((f"{tag}.{key}", re.compile(rx)))
    if not out:
        raise SystemExit("no facts files to scan against")
    return out


def lines_of(rx: re.Pattern, text: str, allow: re.Pattern | None = None) -> list[int]:
    hits = []
    for n, line in enumerate(text.splitlines(), 1):
        for m in rx.finditer(line):
            if allow is None or not allow.search(m.group(0)):
                hits.append(n)
                break
    return hits


def scan_text(label: str, text: str, banned, facts, hits: list[str], blob: str = "") -> None:
    low = text.lower()
    for i, entry in enumerate(banned, 1):
        if entry.lower() in low:
            hits.append(f"banned entry #{i}: {label}")
    checks = [("secret pattern", SECRET, None), ("phone number", PHONE, None)]
    if blob not in EMAIL_SHAPED_OK:
        checks.append(("email address", EMAIL, EMAIL_OK))
    for name, rx, allow in checks:
        found = lines_of(rx, text, allow)
        if found:
            hits.append(f"{name}: {label} lines {found[:10]}")
    for key, rx in facts:
        found = lines_of(rx, text)
        if found:
            hits.append(f"facts value {key}: {label} lines {found[:10]}")


def main() -> int:
    banned = banned_list()
    facts = facts_patterns()
    hits: list[str] = []
    refs = git("for-each-ref", "--format=%(refname)").decode().split()
    commits = git("rev-list", "--all").decode().split()
    for ref in refs:
        scan_text(f"ref name {ref}", ref, banned, facts, hits)
    for sha in commits:
        meta = git("show", "-s", "--format=%ae%n%ce%n%an%n%cn%n%B", sha).decode("utf-8", "replace")
        emails = meta.splitlines()[:2]
        for email in emails:
            if not EMAIL_OK.search(email):
                hits.append(f"commit email not the noreply address: {sha[:7]}")
        scan_text(
            f"commit {sha[:7]} message", "\n".join(meta.splitlines()[4:]), banned, facts, hits
        )
    objects = git("rev-list", "--objects", "--all").decode().splitlines()
    blobs: dict[str, set[str]] = {}
    for line in objects:
        sha, _, path = line.partition(" ")
        if path:
            blobs.setdefault(sha, set()).add(path)
    kinds = git("cat-file", "--batch-check", data="\n".join(blobs).encode()).decode().split("\n")
    images = []
    scanned = 0
    with tempfile.TemporaryDirectory() as tmp:
        for row in kinds:
            if not row:
                continue
            sha, kind, _size = row.split()
            if kind != "blob":
                continue
            scanned += 1
            paths = sorted(blobs[sha])
            label = f"{paths[0]} (blob {sha[:7]})"
            for path in paths:
                scan_text(f"path {path}", path, banned, facts, hits)
            data = git("cat-file", "blob", sha)
            suffix = Path(paths[0]).suffix.lower()
            if data.startswith(IMAGE_MAGIC) or suffix in hygiene_images.EXIF_SUFFIXES:
                out = Path(tmp) / f"{sha}{suffix or '.bin'}"
                out.write_bytes(data)
                images.append(str(out))
                continue
            if b"\x00" in data[:8000]:
                hits.append(f"binary file that is not an image: {label}")
                continue
            scan_text(label, data.decode("utf-8", "replace"), banned, facts, hits, blob=sha)
        bad_images = hygiene_images.scan(images) if images else []
    hits.extend(f"image metadata: {line}" for line in bad_images)
    print(
        f"scanned {len(refs)} refs, {len(commits)} commits, {scanned} file versions "
        f"({len(images)} images), {len(banned)} banned entries, {len(facts)} facts values"
    )
    for hit in hits:
        print(f"HIT {hit}")
    print("HISTORY SCAN CLEAN" if not hits else f"HISTORY SCAN FAILED: {len(hits)} hits")
    return 1 if hits else 0


if __name__ == "__main__":
    sys.exit(main())
