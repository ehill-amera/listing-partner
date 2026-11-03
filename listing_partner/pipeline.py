"""One command for one set: units 2, 3 and 4 end to end, then where the pages are.

Usage: scripts/run <set-name> [--dry-run]

Reads inputs/<set>/raw and facts/<set>.json, writes output/<set>/. One set at a
time: a lock in output/ refuses a second run while one is going.

--dry-run makes no model call. It checks the inputs, copies output/<set> to a
scratch folder, and re-renders every unit's page there from the saved results
(unit 2 from its manifest, unit 3 from its writing log, unit 4 from tidy.json),
with both API keys removed from the environment and both ledgers checked
byte-for-byte before and after. The real output folder is not touched.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PAGES = (
    ("unit 2, finished photos", "review-finish.html"),
    ("unit 3, listing", "listing.html"),
    ("unit 4, tidy", "tidy.html"),
)
KEYS = ("META_API_KEY", "BASETEN_API_KEY")


class RunRefused(Exception):
    """The run cannot start or did not hold its promise. Nothing is reported as done."""


def check_inputs(root: Path, set_name: str) -> dict:
    """The set's raw frames and facts, or a plain reason they cannot be used."""
    from listing_partner import hdr
    from listing_partner.facts import FactsError, load_facts

    if not set_name or "/" in set_name or set_name.startswith("."):
        raise RunRefused(f"not a set name: {set_name!r}")
    raw = root / "inputs" / set_name / "raw"
    frames = sorted(raw.glob("*.NEF")) + sorted(raw.glob("*.nef")) if raw.is_dir() else []
    if not frames:
        raise RunRefused(f"no raw bracket frames (.NEF) in inputs/{set_name}/raw")
    facts_path = root / "facts" / f"{set_name}.json"
    if not facts_path.exists():
        raise RunRefused(f"facts file missing: facts/{set_name}.json")
    try:
        load_facts(facts_path)
    except FactsError as exc:
        raise RunRefused(f"facts/{set_name}.json: {exc}") from exc
    sets = hdr.group_frames(frames)
    return {"raw": raw, "facts": facts_path, "frames": len(frames), "sets": len(sets)}


class _Lock:
    """output/.run.lock, created exclusively: one set at a time."""

    def __init__(self, root: Path, set_name: str):
        self.path = root / "output" / ".run.lock"
        self.set_name = set_name

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            held = self.path.read_text().strip() or "unknown"
            raise RunRefused(
                f"another run holds {self.path.relative_to(self.path.parents[1])} ({held}). "
                "One set at a time. If no run is going, delete that file."
            ) from None
        with os.fdopen(fd, "w") as handle:
            handle.write(f"{self.set_name} pid {os.getpid()}\n")
        return self

    def __exit__(self, *exc):
        self.path.unlink(missing_ok=True)


def _ledgers(root: Path) -> dict:
    spend = root / ".spend"
    out = {}
    for name in ("ledger.jsonl", "baseten-ledger.jsonl"):
        path = spend / name
        out[name] = hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None
    return out


def run_live(root: Path, set_name: str) -> Path:
    """Units 2, 3 and 4 with model calls, each inside its own capped budget."""
    from listing_partner import run_finish, run_listing, tidy

    inputs = check_inputs(root, set_name)
    out = root / "output" / set_name
    unit_dir = root / "inputs" / set_name
    with _Lock(root, set_name):
        print(f"{set_name}: {inputs['frames']} frames in {inputs['sets']} sets", flush=True)
        print("unit 2: finishing photos", flush=True)
        run_finish.run_finish(unit_dir / "raw", unit_dir / "mls", out)
        print("unit 3: curating and writing", flush=True)
        positions = run_listing._mls_positions(unit_dir, out)
        run_listing.run_listing(output_dir=out, facts_path=inputs["facts"], mls_positions=positions)
        print("unit 4: tidying", flush=True)
        tidy.run_tidy(output_dir=out)
    return out


def run_dry(root: Path, set_name: str, scratch: Path | None = None) -> Path:
    """Every unit's page again from saved results, in a scratch copy. No model call."""
    from listing_partner import rescore, run_finish, tidy_page

    inputs = check_inputs(root, set_name)
    saved = root / "output" / set_name
    needed = ["finish_manifest.json", "listing_summary.json", "writing/log.jsonl", "tidy.json"]
    missing = [n for n in needed if not (saved / n).exists()]
    if missing:
        raise RunRefused(
            f"dry run needs a finished live run to replay; output/{set_name} lacks {missing}"
        )
    removed = {k: os.environ.pop(k) for k in KEYS if k in os.environ}
    try:
        before = _ledgers(root)
        with _Lock(root, set_name):
            base = Path(scratch) if scratch else Path(tempfile.mkdtemp(prefix="dry-run-"))
            out = base / set_name
            shutil.copytree(saved, out)
            unit_dir = root / "inputs" / set_name
            print(f"{set_name}: {inputs['frames']} frames in {inputs['sets']} sets", flush=True)
            print("unit 2: page from the saved manifest", flush=True)
            run_finish.render_finish_page(unit_dir / "raw", unit_dir / "mls", out)
            print("unit 3: page from the saved writing log", flush=True)
            rescore.rescore(output_dir=out, facts_path=inputs["facts"])
            print("unit 4: page from the saved tidy results", flush=True)
            summary = json.loads((out / "tidy.json").read_text())
            (out / "tidy.html").write_text(tidy_page.render(summary))
        if _ledgers(root) != before:
            raise RunRefused("a ledger changed during the dry run: a model call was made")
    finally:
        os.environ.update(removed)
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="scripts/run", description=__doc__.splitlines()[0])
    parser.add_argument("set_name", help="the folder name under inputs/, e.g. home-a")
    parser.add_argument("--dry-run", action="store_true", help="no model calls; see module doc")
    args = parser.parse_args(argv)
    try:
        out = run_dry(ROOT, args.set_name) if args.dry_run else run_live(ROOT, args.set_name)
    except RunRefused as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    label = "dry run, 0 model calls, pages in a scratch copy" if args.dry_run else "done"
    print(f"{args.set_name}: {label}")
    for what, page in PAGES:
        path = out / page
        if not path.exists():
            print(f"refused: {what} page was not written: {path}", file=sys.stderr)
            return 2
        print(f"  {what}: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
