NOT YET

The finish paints large white patches on walls and ceilings and turns red brick gray, so the photos fail the ship rule's visual test. Every other ship-rule item holds.

Reviewed commit 970ce8f on `unit-02-window-pulls`. The working tree was at that commit and clean before and after my runs. I made no Meta calls, spent nothing and changed no repo files.

## Ship rule, item by item

| Item | Result | What I did |
|---|---|---|
| Hackathon rules | Holds | Read the code and searched it (details below) |
| Hygiene | Holds, with one part unverified | Ran scans (details below) |
| Cap | Holds | Ran each refusal with a fake transport |
| Honesty rules | Tidy rules not applicable; damage rule is a concern | No tidy step exists until unit 4; see finding 1 on wiped wall detail |
| Ramp test | Passes, with a contract wording problem, and misses the defect | Ran it on old and new code (details below) |
| Criterion 11 | Holds as a reporting rule: misses are stated correctly | Re-measured with my own Lab formula (table below) |
| `./scripts/check` | **Passes** | Exit 0, 225 passed, ruff clean, banned scan clean |
| No box, seam, band or patch | **FAILS** | Finding 1 |

### Check command
- It also passes on a clean export of 970ce8f without photos: 216 passed, 9 skipped, 0 failed.
- Compared with the branch point, one pattern changed. The `sk-` secret pattern now needs 20 or more characters, and the code comment gives the reason.
- The banned scan moved out of the repo and still fails loudly if its list is missing.
- `.gitignore` is unchanged on this branch.
- The ramp test changed from a Lab check to a chromaticity check in its own commit (7961b4c), with the reason stated.

### Hackathon rules
- **Single Meta path:** `urllib` appears only in `meta_client.py`, and I found no other provider library in `listing_partner/` or `scripts/`.
- **Call sites:** the only model calls are at `segment.py:129` and `segment.py:268`, and both go through the capped client.
- **Models:** the allowlist holds only Muse Spark 1.1, 1.2 and 1.3, SAM 3.1 and Muse Image. Contributor ids are refused.
- **Key:** read only from `META_API_KEY` (`meta_client.py:313`). The code has no reference to `.config/muse`.
- **What gets sent:** I read the call sites, which pass the finished photo plus prompt text. I did not read every prompt word for word.
- **Provenance:** every AppFolio mention in the docs that describes the connector labels it as existing. The README does not mention it.

### Cap
I ran these with a fake transport and a dummy key value, with fake cap-raising environment variables set.

| Ledger state or request | Result |
|---|---|
| Total $20.00 | `CapReached` |
| Total $19.00 | `WouldCrossCap` |
| Total $18.99999 | `WouldCrossCap` |
| Corrupt ledger | `LedgerError` |
| Non-allowlisted model | `ModelNotAllowed` |
| Contributor model | `ModelNotAllowed` |
| Price removed from table | `UnknownPrice` |

- The cap stayed $20.00 with those variables set.
- Named tests in `tests/test_meta_client.py` cover these refusals.
- Ledger total is $1.4580. Unit spend is $1.457032 of $2.00. The worst ratio across 256 settled unit calls is 2.00. All three match the report.

### Hygiene
- **Tracked files:** 51. No image, ledger, `.env`, `output/`, `inputs/` or `.navigator/` path appears anywhere in any ref's file history.
- **Secret and phone patterns:** none in any commit on the branch.
- **Email-shaped strings:** only `example.com` and two false hits inside the base64-like fixture `sam_window_lane.txt`.
- **Commits and remotes:** all 70 commits use the private noreply address. No remote exists.
- **Hooks:** `.git/hooks` is byte-identical to `scripts/git-hooks/`. Neither approval file exists.
- **Finished photos:** all 17 carry 0 EXIF tags, so no GPS or serial.
- **Tag:** `muse-code-built` is on 17b99c4, as the report says.
- **Unverified:** I did not check commit messages or history against the banned list, because this review was told not to open that folder.
  - An address-shaped search of commit messages since `main`, tracked file names and tracked file contents found 0 hits.
  - The banned scan in `./scripts/check` covers only the tracked files at this commit.
  - The commit-msg hook should have covered messages when they were written, but I did not test that.

### Ramp test
- **Passes on the real measure.** R/G drift is 0.0035 and B/G drift is 0.0033, against a limit of 0.02.
- **Fails on the old code, as it should.** On an export of bb5df2b, the same fixture gives R/G 0.0622 and B/G 0.0716.
- **Contract problem, not a builder defect.** The contract asks for a* and b* within 2.
  - On the test's warm paint at HEAD, a* ranges 3.13 and b* ranges 9.60, even though chromaticity barely moves.
  - Near-neutral paint meets the wording: paint (200, 195, 185) has b* range 1.82. Paint (200, 190, 175) gives 2.94.
  - A constant-chromaticity warm paint cannot meet the Lab bound as written. Chromaticity is the correct measure.
- **It does not catch this defect.** The fixture asserts it stays below 250 (`tests/test_finish.py:175`), so it never reaches the roll-off step that causes finding 1.

### Criterion 11, re-measured per photo
I used my own sRGB-to-Lab formula on the shipped files. Differences from the manifest are rounding or the Lab formula; the largest is 014 brightness, 18.0% against 17.6%.

| Photo | Brightness gap | a* gap | b* gap | Result |
|---|---|---|---|---|
| 001 | 5.9% | 1.5 | 1.0 | Pass |
| 002 | 4.1% | 1.2 | 2.5 | Pass |
| 003 | 4.8% | 3.4 | 1.3 | Pass |
| 004 | 6.0% | 4.5 | 3.7 | Pass |
| 005 | 3.6% | 1.4 | 3.9 | Pass |
| 006 | no twin | | | Not measured |
| 007 | 5.7% | 2.0 | 3.3 | Pass |
| 008 | 13.3% | 0.3 | 4.8 | Pass |
| 009 | 1.0% | 4.1 | **6.1** | Miss |
| 010 | 2.5% | **7.6** | **18.1** | Miss (as-shot fallback) |
| 011 | 1.6% | 1.3 | 0.7 | Pass |
| 012 | 2.1% | 0.6 | 3.7 | Pass |
| 013 | 9.8% | 0.3 | 3.7 | Pass |
| 014 | **18.0%** | 2.0 | 3.5 | Miss (exterior) |
| 015 | 2.1% | 1.5 | 1.7 | Pass |
| 016 | 0.7% | 3.2 | **7.5** | Miss (exterior) |
| 017 | 1.1% | 1.5 | 3.7 | Pass |

- 12 of 16 pass. Interiors within 5 b*: 9 of 11. Both counts match the report, which names each miss and its size.
- These passes are averages. They hold on photos with large white patches, so they do not show the photos look right.

### Outputs match the commit
- I replayed sets 001 and 010 from HEAD into scratch.
- The pixels match the shipped files except 0.022% and 0.014% of pixels, with a maximum difference of 7 and 6 levels.
- So the shipped photos come from this code, with a tiny run-to-run wobble. The review page stamps commit 970ce8f.

## Visual inspection record

**How I looked**
- **All 17 photos, full frame:** side by side, scaled to 620 px high, about 0.16x. Each sat beside its MLS twin; 006 has no twin, so it sat beside its unit 1 merge.
- **001 only:** also viewed at 1500 px wide, plus an amplified-color view.
- **Native 1:1 tiles, 1000 x 1000 px, 12 in total:** 001, 002, 003, 005, 007, 008, 010, 013, 015, and two of 014.
- **Attribution view for 005:** four panels (merge, full balance, roll-off off, gain only), scaled to 900 px wide.

**What I could not or did not inspect**
- 004, 006, 009, 011, 012, 016 and 017 had no native tile. I saw those only at about 0.16x, so finer flaws there would be hidden.
- I did not tile every photo edge to edge. I stopped once the failure was clear, so this is not a complete map of every flaw.
- I made tiles for a second 005 region and one 006 region but did not view them.

**What I saw**

| Photo | Seen | Scale |
|---|---|---|
| 001 | Pale oval on the back wall; ceiling splits into neutral white and warm areas | Downscaled; the native tile caught only the edge of the oval |
| 002 | Flat gray-white disc on the ceiling around the pendant, with a warm fringe | Native, clear |
| 003 | White field across ceiling and right wall, with an irregular edge against tan wall | Native, clear |
| 004 | Neutral ceiling area with warm and pink bands | Downscaled only |
| 005 | Large white oval on the right wall and a matching ceiling patch; MLS twin has neither | Native, clear |
| 006 | White patch on the ceiling around the lamp; not in the merge | Downscaled only |
| 007 | Same ceiling patch around the lamp, with a visible edge | Native, clear |
| 008 | White patch on the tan wall beside the mirror, with a ragged edge | Native, clear |
| 009 | Ceiling disc around the lamp; white and purple patch on the floor | Downscaled only |
| 010 | Orange walls with speckled gray-white patches | Native, clear; not counted as a blocker on its own |
| 011 | Mildest case: whitened ceiling and cabinets with a greenish tint; no sharp patch seen | Downscaled only |
| 012 | Garage door and panels washed out; white areas meet tan wall | Downscaled only |
| 013 | Driveway bleached pale with patches of original color; siding part white, masonry gray | Native for the driveway; downscaled for siding and masonry |
| 014 | Red brick gray-white with red fragments left, ragged color edges on chimney, corner and neighbor's wall | Native, clear |
| 015 | Gray sky with dark streaks where the MLS twin shows blue; siding part white, masonry gray | Native for sky; downscaled for the rest |
| 016 | Sky blown white; no distinct patch seen | Downscaled only |
| 017 | Sky blown white; no distinct patch seen | Downscaled only |

I saw no rectangular box or straight-line seam on any photo I viewed. The defects are irregular patches and color breaks.

## Findings

**1. The highlight roll-off creates visible white patches and removes real surface color. This blocks shipping.**

- **Where:** `listing_partner/finish.py:181-186`, with its constants at `finish.py:76-77`.
- **What is wrong:** the roll-off triggers on brightness after the tone and gain steps, not on real clipping. Ordinary walls cross 250 and go fully neutral. The shoulder at `finish.py:194-199` then flattens them to about 235.
- **Contract clauses broken:**
  - Part two allows this step only for pixels "approaching clipping" and says it "must create no band, edge or patch".
  - The final-round ship rule requires no box, seam, band or patch.
  - The observable criterion requires walls that look their true color.
- **Measured on 005,** one row across the right wall of the shipped file (the merge was read about 20 px away, because the crop shifts coordinates):
  - The merge reads RGB 89, 76, 65 at the middle of the patch, which is nowhere near clipping.
  - b* falls from +16.7 at x=3400 to +0.1 at x=3600.
  - It then stays flat at RGB 235-236 from x=3600 to x=4400.
  - It climbs back to +19.9 by x=4700.
  - So one painted wall reads three different colors, and the merge shows no such patch.
- **Attribution on 005:** the merge has no patch and the full balance does. Turning only the roll-off off removes the wall patch, and gain alone does not create it. With the roll-off off, the window view goes cyan, which is why the step exists. Any fix has to handle both.
- **How widespread:** I measured the share of each frame that is flat neutral white (channel spread 4 or less, mean 225 or more). Real white trim and blown windows count too, so this shows scale and does not isolate the defect.

| Photo | Finished | MLS twin |
|---|---|---|
| 001 | 28.8% | 0.3% |
| 002 | 15.7% | 4.6% |
| 003 | 28.7% | 0.8% |
| 004 | 22.2% | 9.0% |
| 005 | 10.6% | 0.4% |
| 006 | 10.2% | no twin |
| 007 | 7.9% | 0.4% |
| 008 | 27.5% | 0.7% |
| 009 | 14.4% | 0.4% |
| 010 | 29.3% | 0.9% |
| 011 | 13.4% | 0.9% |
| 012 | 42.8% | 6.0% |
| 013 | 11.6% | 0.0% |
| 014 | 3.8% | 0.0% |
| 015 | 14.9% | 0.0% |
| 016 | 9.9% | 0.2% |
| 017 | 13.3% | 0.3% |

- **Why it matters beyond looks:**
  - On 014 the red brick reads as gray with red fragments, which misstates the property's material color to a renter.
  - Flattening a wall to one value also wipes out any marks on it, which conflicts with the rule against softening damage. I did not confirm that a specific mark was lost.
- **What would make it pass:**
  - The roll-off (or its replacement) changes only pixels that were really clipped or close to clipping before the tone and gain steps, or the tone path is reworked so walls never reach it.
  - On interiors, the same wall holds its color across its brightness range. On exteriors, brick keeps its color.
  - The window views do not go cyan.
  - A fresh full replay, then a fresh review at full resolution.

**2. The tests cannot see this defect, and two code comments claim the opposite.**

- **Where:** `tests/test_finish.py:175` stops the ramp below the roll-off, and `test_warm_bright_and_blown_patches_stay_neutral` (`tests/test_finish.py:203`) checks uniform patches only. `finish.py:74-75` and `finish.py:178-179` both say the roll-off makes no band or edge. On real photos it does.
- **How I found it:** read the tests and comments, then compared them with the 005 measurement in finding 1. The check passes 225 of 225 tests on these photos.
- **What would make it pass:** a failing-first test where one wall color crosses the roll-off under a smooth brightness ramp and the color change per pixel is bounded. It must be observed failing on 970ce8f. Correct the two comments in the same fix.

## Known limits (not blocking)

**Accepted by Erik, as relayed by the navigator.** I did not count these. My readings match the report.
- Floor FAILs:
  - 004: 11.2%, twin 6.3%
  - 006: 38.2%, no twin
  - 007: 31.1%, twin 21.8%
  - 009: 22.2%, twin 12.1%
- 010 as-shot fallback: bright share 1.01% against the 1% bar. It is labeled on the page and has the largest color miss in the set.
- The report's line that the floor fails on 004, 007 and 009 are "not accepted by anyone yet" is older than this acceptance.
- The missing "Built-by" trailer is not counted. No commit has one, and the tag marks the builder boundary.

**Standing limits from the contract**
- No deghost step. 016 now reads 0.1985, under the 0.25 limit, while the contract's older text says it reads above. The report's number is the current one.
- Window views stay as merged.
- Masks are not glass-only.
- Lit-wall noise is not measured.
- Window masks and verdicts are saved results from earlier runs, not re-run on the new color.

**Other things for Erik to see**
- The exterior misses on 014 and 016 are named in the report.
- Verticals are NOT MEASURED on 005, 012, 016 and 017.
- 017 has the highest noise, 11.41 to 6.43.
- The page's top-line near-white figure, 9.59% to 8.41%, moves only because of denoise and JPEG saving. No pull ran.
- Stale number: the docstring at `tests/test_finish.py:162` says bb5df2b drifts R/G 0.045 and B/G 0.067. On the current fixture I measured 0.0622 and 0.0716, and the report's 0.062 matches.
- `docs/build-plan.md` and the contract's history still mention $40, as the report says. The enforced cap is $20.

**Report numbers I reproduced from the shipped outputs and manifest**
- Look table, bright-surface values, floor shares, multipliers and edge trim.
- Noise, edge ratio range and ghosting range.
- Window counts (39, 17, 22, 12). The review page has 22 rejections, 0 without a saved mask, and 0 missing images.
- 591 s run time and 8,267 MB peak (read from the manifest and log; I did not repeat the full run).

**Not reproduced, relying on the builder**
- The part-three failing-first results, apart from the ramp.
- The claim that 0856852 landed with the check failing.
- The half-size tint trade-off the report describes.

## Scratch files
- Attribution view for 005: `<scratch path>`
- Brick tile for 014: `<scratch path>`
- Wall tile for 005: `<scratch path>`
