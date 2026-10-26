# Contract 01: HDR merge and the spend-capped Meta client

Branch: `unit-01-hdr-merge`
Target: Tue Oct 27, 2026
Meta budget for this unit: **$0.50**. Live smoke calls only: the first on Oct 26, plus one more on the final code before review (amended Oct 26 after the third review).

Read PRODUCT.md and AGENTS.md first.

## Why

Every later unit works on merged photos and calls Meta through one capped function. Both have to exist and be trustworthy before anything else gets built on top of them.

## Test set: unit-a

A vacant Bokani unit Erik shot on a Nikon D5500 and already finished by hand. Source paths are in `local/test-sets.md` (gitignored). The street address must not appear anywhere in the repo, in a file name, a commit message, a branch name or a report. Refer to it only as `unit-a`.

The sources sit on Google Drive for Desktop, so files may download as they are read. About 2.5 GB in the raw folder, measured Oct 26. Copy, never move, rename in place, or edit the originals. Copy into this layout (all gitignored):
- `inputs/unit-a/raw/`: the 86 `.NEF` camera originals, names unchanged. **These are the only merge inputs.**
- `inputs/unit-a/lightroom/`: the 17 `-HDR.dng` files, Lightroom's own merges, names unchanged. Benchmark only, never inputs.
- `inputs/unit-a/mls/`: Erik's 16 finished MLS JPEGs. Their source names contain the street address, so rename each copy to its trailing number only (`001.jpg` to `016.jpg`). Benchmark only.

Measured by the navigator on Oct 26 (re-measure, do not trust):
- Brackets step the shutter speed. Exposure bias reads 0 on every frame checked, so grouping cannot use exposure bias.
- Splitting the 86 NEFs wherever capture times are more than 8 seconds apart gives 17 sets: 16 sets of 5 frames and one set of 6 (`_DSC0056` to `_DSC0061`). Each set's first frame matches the name of one Lightroom merge (`_DSC0001-HDR.dng`, `_DSC0006-HDR.dng`, and so on).
- All 16 MLS JPEGs carry a capture time. For 15 it sits in the standard Exif block. For `007.jpg` it sits only in the XMP block, which the navigator's first measurement missed (corrected Oct 26 after the fourth review). Read capture times from every metadata block, Exif and XMP. The MLS photos are 2096 by 1397, cropped and edited by hand.
- The NEFs carry a GPS block with no coordinates.

## Build

### A. The check command

`./scripts/check` runs everything mechanical and exits non-zero on any failure:
- Lint and the full test suite.
- A public-hygiene scan of every tracked file and file name: API-key and token patterns, email addresses, phone numbers, `.env` files, image files with GPS or camera serial metadata, every string in `local/banned-strings.txt` (case-insensitive; fail if that file is missing), and any tracked file under a gitignored path.
- A check that `.gitignore` still covers `inputs/`, `output/`, `.spend/`, `.navigator/`, `local/`, `.muse/` and `facts/`.
- A check that every hook in `scripts/git-hooks/` is installed in `.git/hooks` and identical. It reports a mismatch. It never installs or edits hooks itself.

Tests must run with `META_API_KEY` unset and no network.

### B. The spend-capped Meta client

`listing_partner/meta_client.py`, one function every Meta call goes through:
- Running total on disk in `.spend/ledger.jsonl`, one line per call (time, model, estimated cost, actual cost, request id). No prompt text, no image data, no key.
- Reserves the estimated cost before the call. Reconciles to the real cost after. A crash mid-call leaves the reservation counted.
- Refuses when the total has reached $100, and refuses a call whose estimate would cross $100.
- Fails closed: refuses if the ledger is unreadable or corrupt, if the model's price is unknown, or if the key is missing.
- The $100 cap is a constant. No environment variable, flag or config can raise it.
- Model allowlist of first-party Meta models only (Muse Spark, SAM 3.1, Muse Image), with exact ids taken from Meta's Model API documentation (dev.meta.ai/docs). Any other id is refused. No Contributor models.
- Prices in one table with the source URL (dev.meta.ai/docs/pricing-rate-limits) and the date read. If the API returns actual cost or usage, use it to reconcile.
- Reads the key from `META_API_KEY` only. Never reads Muse Code's stored credentials. Never logs or prints the key.
- Safe if two processes call at once (file lock).

Tests with a mocked transport prove each refusal: at $100, a call that would cross $100, unreadable ledger, unknown price, non-allowlisted model, missing key. A test proves the reservation survives a simulated crash.

Live smoke call: one minimal Muse Spark text call through the client. Confirm a ledger line appears with a real cost. If `META_API_KEY` is not set, stop and ask Erik one plain question. Do not ask him to paste the key anywhere.

### C. HDR merge

`listing_partner/hdr.py` plus a run command that takes a unit folder and writes `output/unit-a/merged/`.
- Reads the NEFs (and JPEG, for future units shot that way).
- Groups frames into sets by capture time (a new set starts after a gap of more than 8 seconds), not by a fixed set size and not by exposure bias. Any set whose size differs from the most common size is listed on the review page as a flag, still merged.
- Aligns each set, then fuses exposures (exposure fusion, not tone-mapped HDR) for a natural look: window views visible, dark corners readable, no halos.
- Writes full-resolution sRGB JPEGs named in capture order (`001.jpg`, `002.jpg`, ...). Output carries no GPS and no camera serial.
- No Meta calls. Merging is local.

### D. Review page

`output/unit-a/review.html`, a single page that opens in a browser with no server:
- Top line: frames found, sets found, sets merged, sets failed, sets flagged, merge run time. All measured from this run.
- One row per set, side by side: the darkest frame, the brightest frame, **our merge**, **Lightroom's merge** of the same set, and **Erik's MLS photo** of the same shot.
- Lightroom match: by the set's first frame name. Show the largest preview Lightroom embedded in the DNG (1024 pixels wide in unit-a's files, not the 256-pixel thumbnail), labeled "Lightroom's own preview". That is what Lightroom itself shows, so the comparison is fair. Do not render the DNG with our own color processing (amended Oct 26: our rendering came out about 27% darker and yellow-skied, which tilted the comparison in our favor). If a DNG has no embedded preview, say so in that cell.
- MLS match: by capture time falling inside the set's capture window. For an MLS photo with no capture time, match by visual similarity (the MLS photos are cropped and edited, so allow for that) and label the match "matched by look". A set with no MLS photo shows "not published". Every MLS photo appears exactly once.
- Footer: Meta spend to date and the $100 cap, read from the ledger.

## Acceptance criteria

1. `./scripts/check` passes on the final commit.
2. Every refusal case in B has a passing test, and the cap cannot be raised without editing the constant.
3. A live smoke call made with the final client code appears in the ledger with a real cost, and total spend for this unit is under $0.50. Reading the reply text moves to unit 2 (amended Oct 26 after the fourth review). Until then, a billed call whose reply cannot be read must say so plainly and must never be reported as refused.
4. All 86 NEFs are accounted for on the review page, each in exactly one set. The grouping finds the same 17 sets Lightroom merged.
5. Sets merged plus sets failed equals sets found. Failures are listed with a plain-words reason.
6. Every one of the 16 MLS photos and 17 Lightroom merges appears on the page, matched to a set.
7. No output JPEG carries GPS or camera serial metadata.
8. The merge (not counting the copy from Drive) finishes in under 10 minutes on Erik's M1 Max. Report the measured time.
9. Originals are untouched: file count and total size of each source folder are the same before and after the run.
10. No tracked file, file name, commit message or branch name contains a banned string.

## Report extras for this unit

Because this is the first unit through Muse Code, the report also says, in plain words:
- Muse Code's version.
- Whether committing needed an approval, and whether reaching Meta's API needed an approval for that destination.
- Anything the sandbox or a hook refused, and what you did instead.

## Observable criterion (Erik, two minutes, no code)

Finder, Shift+Cmd+G, `~/projects/listing-partner/output/unit-a`, then open `review.html`. The top line shows 86 frames, 17 sets, zero failed. Scroll to any three rooms with windows. In our merge, the view out the window is visible (not blown white) and the darkest corner is readable (not black). Next to it, Lightroom's merge and your MLS photo of the same shot let you judge whether ours is a usable starting point. The footer shows Meta spend under $0.50 of $100.

## Out of scope

Culling, room labels, ordering, tidying, writing, AppFolio. Resizing for listing sites. Matching Erik's hand edits (crop, white balance, color). Any Meta call beyond the one smoke call.
