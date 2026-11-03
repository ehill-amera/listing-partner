# Listing Partner

**Raw bracketed photos in. A listing you can post out. No Lightroom.**

A property manager or photographer shoots each room as a set of bracketed exposures, drops the raw files in one folder, and runs one command. Listing Partner merges every bracket into one HDR photo, straightens it, balances the light and color, picks and orders the best shots, labels each room, tidies away carry-out clutter (only clutter, never the property), and writes the listing description and social captions from the unit's real facts. Then it shows all of it on one page for a person to approve.

Built solo during Meta's Global AI Developer Hackathon (Oct 26 to Nov 4, 2026), Indie track.

## What is pre-existing (read this first)

Everything in this repo was built during the hackathon. The only pieces from before kickoff are:
- **Bokani's read-only AppFolio connector**, an existing tool I plug in to fill a unit's facts file (beds, baths, square feet, rent, amenities). It is not in this repo and was not built this week. The public demo uses a hand-written demo facts file instead.
- **The planning notes and repo safety hooks** I wrote on the morning of kickoff.

## Meta models it uses

| Job | Model | How |
|---|---|---|
| Find windows, find clutter, re-check every removal | **SAM 3.1** | Meta Model API |
| Confirm windows, pick and order shots, label rooms, list damage, confirm clutter, self-check every fill | **Muse Spark** | Meta Model API |
| Remove confirmed clutter, inside the mask only | **Muse Image** | Meta Model API |
| Write the description and captions, fair housing review | **Muse Spark** and **Muse Spark Open** side by side | Meta Model API, and Baseten partner inference for the open-weight model |

Every Meta call goes through one spend-capped client (`listing_partner/meta_client.py`) with an append-only ledger on disk. It refuses any call that would cross $20, any model not on its allowlist, and any call when the ledger is unreadable. Muse Spark Open has its own capped client and ledger (`listing_partner/baseten_client.py`, $80 cap). Both caps sit inside the free hackathon credits.

**Muse Spark vs Muse Spark Open.** Both models write every description and caption from the same inputs, and both review every text for fair housing wording. Every output is scored by the same automatic checks (facts match, no fair housing phrase, length, no markup) and logged with its cost. The listing page shows both side by side as A and B, so a person can pick without knowing which model wrote which. When the two models' fair housing reviews disagree, the text is flagged for a person instead of passing. Result on the demo set: Muse Spark Open wrote the better description (0 failed checks against Muse Spark's 2, across every attempt). Both models' captions passed every check, so the cheaper one won: Muse Spark ($0.0186 against $0.0202). Neither fair housing review missed or garbled a text, and Muse Spark's cost less ($0.0228 against $0.0408). One text in six needed a rewrite. This is one listing, not a benchmark.

## The honesty rule

> An edit is allowed only if the photo still shows what the place would really look like after a physical cleanup. Never repairs, damage, stains, permanent fixtures, walls, flooring, or anything that changes the property itself.

How the code enforces it:
- Muse Spark lists visible damage first. Damage areas are locked: no clutter mask may touch them.
- SAM 3.1 looks only for a fixed list of carry-out clutter (trash bins, boxes, bags, cords, laundry baskets and similar). Muse Spark must confirm each one, and rejects anything attached, built in, or covering more than one object.
- Muse Image fills the masked area. Every pixel outside the mask is copied from the original, so nothing else in the photo can change. This is measured on every edited photo: on the demo set, 0 pixels changed outside the mask on the one tidied photo (a 28,900-pixel mask), and 0 on the last refused attempt of the photo that shipped untidied.
- After each fill, SAM 3.1 looks again for the removed item, a measured check compares the fill to the surrounding surface for clouds, specks and marks, and Muse Spark self-checks the result. If any check fails after retries, **the photo ships untidied**, with the reason on the page.
- Every edited photo is labeled "Edited: clutter removed", and the original stays beside it.

On the demo set the product refused its own edit when a fill left a faint mark on a bedroom wall, three tries in a row, and shipped that photo untidied. That is the rule working.

## Fair housing

Every description and caption is screened for wording about who should or should not live there (42 U.S.C. 3604(c), 24 CFR 100.75), and both models review every text independently. The screen is a backstop, not legal advice: a person approves everything before it is posted, and nothing is ever posted automatically.

## Cost per listing

What the demo set actually cost, from both spend ledgers: every call its units 2, 3 and 4 made, including every rerun while those units were being built. A single clean pass costs less; it has not been measured on its own. The demo set is 8 finished photos, 7 of them in the listing.

| Provider | Model | Calls | Cost |
|---|---|---:|---:|
| Meta Model API | SAM 3.1 | 135 | $0.3375 |
| Meta Model API | Muse Spark (muse-spark-1.3) | 111 | $1.1104 |
| Meta Model API | Muse Image (muse-image-1.0) | 23 | $0.2300 |
| Baseten | Muse Spark Open (muse-spark-open-1026) | 18 | $0.2173 |
| **Total** | | **287** | **$1.8952** |

By unit: finishing the photos $0.1356 (27 calls), picking shots and writing $0.6127 (47 calls), tidying $1.1470 (213 calls, every tidy run on the demo set from the first on Nov 2 through the shipped one). One 9-call tidy rerun of a private test set ($0.0643) landed in the same hours and is not counted here.

Whole project to date, every set and every rerun: $6.1528 of the $20 Meta cap, $0.81 of the $80 Baseten cap. `scripts/measure_docs.py` recomputes every number in this section from the ledgers.

## Run it

Needs Python 3.12 or later, [uv](https://docs.astral.sh/uv/), a Meta Model API key in `META_API_KEY` and a Baseten key in `BASETEN_API_KEY`.

```sh
uv sync
# raw bracket frames:  inputs/<set>/raw/*.NEF
# the unit's facts:    facts/<set>.json   (shape: listing_partner/sample_data/facts_sample.json)
scripts/run <set>
```

It runs the three stages one after another on one set (finish the photos, pick and write, tidy), each inside its own capped budget, and prints where the three review pages are: `output/<set>/review-finish.html`, `listing.html` and `tidy.html`. A second run while one is going is refused.

`scripts/run <set> --dry-run` makes no model call. It re-renders all three pages from a finished run's saved results in a scratch copy, with both keys removed from the environment, and fails if either ledger changes. On the demo set: 40 frames in 8 bracket sets, 3 pages written, 0 model calls, both ledgers byte-identical before and after.

The raw frames and outputs are not in this repo.

## How it was built: Muse Code, then Claude Code, with a separate reviewer

- **Muse Code** (Meta's coding agent, muse-spark-1.3) built units 1 and 2: the spend-capped Meta client, the HDR merge, lens and vertical correction, window finding, exposure and white balance, and denoise. The git tag `muse-code-built` marks its last commit (87 commits).
- **Claude Code** (Opus 5.5) built from there: the final color fix, curation, writing on both models, scoring, fair housing, the Baseten client, and the tidy unit (51 commits after the tag, through the unit 4 commit `f93deaa`).
- **A separate reviewer** (a fresh-context Claude Code agent from a fixed prompt in `.claude/agents/reviewer.md`) reviewed every unit and could only say SHIP or NOT YET. The builder never graded its own work. Every saved review is in `docs/reviews/` (unit 1's reports were not kept).
- **A navigator** (Claude) wrote the product spec and every contract in `contracts/`, and made the calls on scope.

Full breakdown in [`docs/who-built-what.md`](docs/who-built-what.md).

## Known limits

Measured, and listed here rather than fixed.

**Finished photos**
- **Window views are not edited.** Window pulls were turned off after a review found all 14 pulls on a private test set damaged at full resolution. Windows are found and confirmed, then left as merged.
- **Colored strips and streaks near windows.** On a private test set, the edge of the cool-view correction leaves a colored strip along the pane edges in 2 photos and a gray-white streak on trim and wall in 1.
- **Floor color check.** It fails (purple cast near windows over 8%) on 7 of 17 photos of a private test set and 3 of 8 on the demo set (8.1%, 8.5%, 11.0%).
- **Bright cyan or blue surfaces** cover more than 1% of the frame outside the windows on 1 of 17 photos of a private test set and 3 of 8 on the demo set (3.51%, 8.54%, 1.16%). Listed, not changed.
- No deghosting step, window masks are not glass-only, and noise on lit walls is not measured.

**Shot picking and writing**
- The fair housing screen is a fixed list, not legal advice, and other phrasings get past it (8 tested examples, such as "a great place to raise a family"). Two model reviews and a person's approval sit behind it.
- The number, amenity and invented-detail checks have tested gaps: wording like "an extra bedroom", amenities outside the known groups, and room details no check compares to the photos. A clause with a negative word counts as a denial, so a correct sentence can fail.
- The demo set has no exterior photo, so the listing page shows the front exterior as missing.
- The model comparison above is one listing.

**Tidy**
- The mark check judges flat surfaces only. On the demo set's one tidied photo, a tile backsplash, it judged 0% of the fill, so a mark there rests on Muse Spark's self-check and a person's eye.
- The damage list came back empty on all 7 demo photos, so the damage lock is proven by tests, not by the demo set.
- The mark check can refuse a clean fill. The cost is a photo shipped untidied, never a bad edit shipped.
- The slider and the mask flash on the tidy page were checked in the page source, not clicked in a browser.
- The tidy page's spend line includes the set's earlier units, so it reads high, never low.
- The private test set's tidy output was made before the last two tidy checks and was not rerun.
- 3 Meta ledger reservations never settled (two on Oct 29, one on Nov 2); they count at their estimate, so the totals read high, never low.

## Fresh clone

`pytest` passes on a clone without the private raw photos and outputs: tests that need them skip and print why. `./scripts/check` refuses to run without the private banned-strings list, which lives outside the repo on purpose, so it never scans against nothing.

## License

MIT. See `LICENSE`.
