**NOT YET.** All 14 window pulls are visibly damaged at full resolution, so 0 of 14 pass the ship gate. Five rooms also have a large orange rectangle across the floor and wall, visible even on the review page thumbnail. The headline near-white drop comes mostly from the highlight shoulder, not the pulls.

Commit reviewed: 9e0515a (HEAD of unit-02-window-pulls, clean tree before and after my work). I edited nothing in the repo.

## 1. Commit, provenance and check

- **HEAD:** `git rev-parse HEAD` returned 9e0515aaa22bc3272f6dcac1e0173bda55705dd9.
- **Timestamps:** the commit is from 12:45:22. The finished photos were written 12:46:26 to 12:56:06, and the manifest and page at 12:56. The manifest and page both stamp the run as 9e0515a, with no dirty marker.
- **Independent reproduction:** I replayed all 17 sets from HEAD into the scratchpad, with the key unset and saved Meta results.
  - Against the shipped JPEGs, at most 0.118% of pixels differ per photo, and the largest single difference is 9 levels. I did not establish why they differ at all.
  - The replay gave the same pull decisions and reasons, and the same look and floor results.
  - The only count that moved is clip_before_n on 001, by 1 pixel.
  - The ledger stayed at 431 lines.
  - **Conclusion:** the outputs I inspected come from this commit.
- **Check:** `env -u META_API_KEY ./scripts/check` exited 0, with 192 tests passed, ruff clean, banned-strings scan clean and CHECK OK.

## 2. Window count

The manifest lists 14 confirmed windows on 9 photos, and all 14 read "pulled" with 0 kept. There are 14 mask files, the page says "Windows pulled 14, kept from merge 0", and my replay gives the same result. **The 14 / 0 count is accurate as a count of what the code did. It is not evidence that the pulls are good.**

## 3. Per-window table (section B ship gate)

"Merge" here means the pipeline's own merge immediately before the pull (balanced and cropped), captured from the real `_gate_window` call during my replay. It is pixel-aligned to the finished photo. Locations are approximate, in finished-photo pixels.

Every window below was viewed at native pixels, side by side, in tiles no wider than about 1,500 px. No window was marked NOT VIEWED.

| Window | Verdict | Specific defect and location |
|---|---|---|
| 001 w0 | FAIL | Brown crack lines across the glass and sill, x 4-310, y 3186-3606. Tan streak on the jamb near x 160, y 776-1756. Frame color not kept. |
| 001 w1 | FAIL | Beige vertical bar on the glass, x 1180-1200, y 1733-1953. Smudge at the lower left, near x 1100, y 2673. Remaining glass is washed out. |
| 001 w2 | FAIL | Brown streak down the white jamb, x 960-1000, y 1706-2500. Brown veins through the bushes, x 540-850, y 2466-2666. Brown scallops along the sill edge, x 560-840, y 2896-3076. Ochre bar on the lawn, x 672-752, y 2306. |
| 003 w0 | FAIL | Orange-brown band under the blinds, x 2383-2843, y 1712. Dark blobs in a white pane, x 2393-2793, y 1880-2000. Olive streaks on the lawn, y 2130-2300. Gold patch, x 3317-3577, y 2230-2330. Brown marks on trim near x 3587, y 1790-1990. |
| 004 w0 | FAIL | Tan streaks on trim, x 3155-3195, y 1730-1950, and on the mullion, x 4240-4315, y 1640-2510. Brown lines along the road, y 2180-2310. Yellow-brown blotches in the upper right pane, x 4561-5090, y 1570-1810. Brown line along the bottom of the glass, y 2530-2560. |
| 005 w0 | FAIL | Worst view: round white holes in dark foliage, like Swiss cheese, with cyan false color around them, x 1679-2475, y 1730-2070. This is the window the report tells Erik to compare. |
| 006 w0 | FAIL | Brown band along the bottom of the glass, x 4547-4857, y 2280. Brown stains, x 5258-5293, y 1470. Olive smudges, x 4827-5053, y 1830. Lavender and pink false-color brick remains. |
| 006 w1 | FAIL | Only 0.8% of the mask changed, so the view stays washed out. Tan smudge on the lawn, x 1545-1745, y 2094. |
| 007 w0 | FAIL | Washed-out view. Faint dark twigs ghosted into the lower pane, x 2170-2560, y 1880-1990. Orange patches, x 2794-2854, y 1992-2052. Streak on trim, x 2894-2944, y 1552-1892. |
| 007 w1 | FAIL | Olive vein mesh over the pane, x 5473-5899, y 1284-1464. Twig-shaped patches in pale glass, x 5533-5899, y 2259-2364. Purple-blue false-color brick remains. |
| 009 w0 | FAIL | Red-brown veins and orange blocks across white brick, x 646-1092, y 1613-2063. Veins in the right sash, x 1100-1460, y 1643-1943. Tan strips on the frame near x 1519, y 1323-1573, and on the sill, x 1250-1480, y 2078. |
| 009 w1 | FAIL | Brown vein mesh through the foliage across the window, x 5168-5962, y 1141-2061. |
| 010 w0 | FAIL | Thick brown rope diagonally across the glass, x 5430-5921, y 1183-1378. Dark blotches, x 5465-5715, y 1408-1568, and x 5715-5921, y 2058-2090 and y 2408-2448. Tan vertical line, x 5440, y 2056-2460. The report also recommends this window for Erik to compare. |
| 011 w0 | FAIL | Orange-brown streaks on white trim, x 1430, y 974-1314, and x 1520, y 854-1354. Orange blotch at the meeting rail, x 1085-1240, y 1294-1354. Yellow strip, x 1390, y 1404-1654. |

**Result: 0 of 14 pass. Every one should have been kept from the merge under the contract's gate, or the report should say that none passed.** The previous review flagged 7 of 9 window photos. Now all 9 fail.

Evidence on where the brown comes from: at the 001 w2 jamb, I placed the unit 1 merge, the view frame and the finished photo side by side. The merge has no brown streak. The take mask selects pixels that hold real mid-tone trim and foliage in the darker frame and pastes them in at native brightness beside near-white merge pixels. So these are not real scene marks.

## Near-white, measured per window

The report's "before" is read before the shoulder. Its "after" is read after the shoulder. Blown glass only reaches 250 after the shoulder if its pre-shoulder value is about 449 or more, so the two sides are on different scales.

- **"Reported"** is the manifest's gate line.
- **"Same scale"** is 250 on any channel, post-shoulder on both sides: the pre-pull merge against the shipped file.
- **"Still blown"** is the share of mask pixels at or above 250 pre-shoulder that the pull did not touch. It uses post-shoulder 236 or above as the proxy for pre-shoulder 250, which reads about 0.5 points above the manifest's before figure on the one window I checked (001 w0).

| Window | Mask pixels changed | Reported | Same scale | Still blown |
|---|---|---|---|---|
| 001 w0 | 2.2% | .5852→.0386 | .0408→**.0417** | .5679 |
| 001 w1 | 6.2% | .7047→.0068 | .0123→.0081 | .6534 |
| 001 w2 | 7.8% | .6370→.0825 | .0940→.0840 | .5619 |
| 003 w0 | 20.3% | .9259→.2544 | .2743→.2495 | .7250 |
| 004 w0 | 8.5% | .7401→.1372 | .1485→.1384 | .6578 |
| 005 w0 | 26.7% | .8916→.1420 | .2392→.1341 | .6264 |
| 006 w0 | 1.7% | .5552→.0550 | .0563→**.0576** | .5435 |
| 006 w1 | 0.8% | .5195→.1840 | .1854→**.1883** | .5138 |
| 007 w0 | 7.6% | .6128→.1716 | .1727→**.1751** | .5441 |
| 007 w1 | 5.4% | .4490→.0606 | .0668→.0624 | .4005 |
| 009 w0 | 10.8% | .5817→.1097 | .1238→.1072 | .4770 |
| 009 w1 | 19.0% | .4821→.0751 | .1106→.0709 | .2934 |
| 010 w0 | 4.2% | .6185→.0279 | .0383→.0284 | .5812 |
| 011 w0 | 4.5% | .7981→.2899 | .3005→.2868 | .7554 |
| Pooled | 8.86% | 63.32%→11.40% | 12.98%→11.40% | 54.84% |

Near-white rose on 4 windows on the same scale (bold).

## 4. Findings, most severe first

1. **All 14 pulls fail the section B gate, criterion 13 and the observable criterion.**
   - **Where:** `_take_mask` and `pull_window` in `listing_partner/segment.py`.
   - **How found:** the 42 full-resolution tiles and the table above.
   - **To pass:** a pulled window must read as one continuous, matched, real view with clean trim on full-resolution inspection. Any window that cannot must keep the merge and say so on the page. Reporting "none passed" is allowed.

2. **A hard-edged orange rectangle lies across the floor and wall on 003, 004, 005, 006 and 007. This breaks section C ("no visible region edges", "keep it natural") and the observable criterion.**
   - **Where:** the zone wood guard in `balance_exposure` (`listing_partner/finish.py`), applied through the unfeathered box from `measure.zone_mask`, called from `finish_tail`. It was introduced in 5296861.
   - **How found:** I viewed the frames, then read the color step across the box edges. b* jumps by 14 on 003 (left edge), 12 on 004, 15 on 005 and 8 on 007. On 009 and 011, where the guard is off, the a* and b* steps are 2 or less.
   - **Where it is most visible:** on 005 it paints the wall under the window orange. On 006 and 007 it cuts straight across the wall and baseboard. It is plainly visible in `output/unit-a/review/finished_004.jpg`, the file on Erik's page.
   - **To pass:** no spatial box in the color correction, or a correction with no visible boundary, and a test that measures the seam.

3. **The near-white measurement is asymmetric, so criterion 4 is not met.**
   - **Where:** `_gate_window` and `finish_tail` in `listing_partner/run_finish.py`.
   - **What is wrong:** the contract says near-white is measured "with no shoulder or clamp hiding it" and that a clamped result does not count. The after side still passes through the shoulder. The pulls changed 8.86% of window pixels, yet the headline claims a drop of about 52 points. On one scale the drop is 1.6 points, and about 55% of window pixels are still blown. The report's sentence "No clamp or cap shapes these counts" is false.
   - **To pass:** use the same scale before and after, per window and per photo, and let the gate keep the merge when that number does not drop.

4. **The automatic gate does not test most of what the contract requires, which is why 14 damaged windows all passed.**
   - **Where:** `_gate_window` checks only refused views, light ratio, the near-white figure above, and the rim's mean light on its unblown pixels.
   - **What is missing:** nothing tests continuity, false color, a hard edge, a halo, or the color of frames, mullions, blinds and sills. A trim scar inside the mask passes because a mean over the rim band hides it.
   - **To pass:** a gate that fails on these defects by measurement, with tests built from real failure shapes, then re-judged at full resolution.

5. **Masks do not cover glass only, which section A requires.**
   - **Where:** saved masks in `output/unit-a/windows/masks/`.
   - **How found:** I overlaid the 003 and 005 masks at full size. They cover the whole window unit, including blinds, trim, sill and mullions, with stair-stepped edges that fit SAM's mask being scaled up from the 1024 px image sent to it. The other 12 boxes span similar areas, but I did not overlay them, so that part is inference.
   - **Why it matters:** this exposes the trim to the pull, and it makes "window pixels" in every percentage include trim and blinds.
   - **To pass:** glass-only masks, measured, with percentages computed on glass.

6. **The floor measurement passes while floors just outside the measured box are still lavender (criterion 13, section C).**
   - **How found:** I ran the builder's own `purple_share` on the shipped files.

   | Photo | Measured box | Same columns, below the box | Lower half of frame |
   |---|---|---|---|
   | 006 | 3.2% | **60.2%** | 15.0% |
   | 007 | 5.7% | **61.3%** | 12.5% |
   | 009 | 3.7% | **23.8%** | 10.3% |
   | 010 | 7.1% | 1.2% | 13.4% |

   - **What it looks like:** in the frames I viewed, 006 and 007 show a purple floor directly below the orange rectangle. The rectangle moved the problem and the metric boxed it out.
   - **To pass:** measure the whole visible floor, and floors must read their real color.

7. **The report contains false or unreproducible statements.** All refer to `.navigator/report.md`.
   - "No pulled window shows patchy inserts, false color, hard edges, darkened frames, or a purple cast." Findings 1 and 6 contradict this.
   - Status says "trim white and clean everywhere" (`.navigator/status.md`). Finding 1 contradicts this.
   - 001's per-window after numbers (.0421, .0119, .0902) appear neither in the manifest (.0386, .0068, .0825) nor in my replay.
   - "Nothing under 1" for reservations. `reserve_ratio_stats` reports under_one = 2 (both unit 1 lines from Oct 26).
   - **To pass:** rewrite the report from a measured run.

8. **The ghosting check does not measure ghosting (A0).**
   - **Where:** `geometry.ghosting_score` counts pixels whose spread exceeds 15 levels across differently exposed frames.
   - **What happens:** it reads 0.9547 to 1.0 on all 17 photos, that is, "99% of pixels moved", simply because brackets differ in exposure. The report gives no ghosting measurement, and no deghost decision can follow from this number.
   - **To pass:** normalize exposure before comparing, then report the number and the decision.

9. **"Worst reservation-to-bill ratio 26.89" is the best-covered call, not the worst.**
   - **Where:** `reserve_ratio_stats` and the page.
   - **Measured:** the lowest ratio on unit 2's calls is 2.0, which is the number that says whether reservations cover the bill. The page labels the largest as worst, and the test name enshrines that.
   - **To pass:** report the minimum (2.0 for this unit) and the 2 unit 1 calls under 1 separately.

10. **Criterion 6's "no hard edge" is not proven by any test.**
    - **How found:** I forced feather alpha to 1 (a pure hard edge) in a scratch run, without touching the repo. `tests/test_segment.py`, `tests/test_run_finish.py` and `tests/test_finish.py` still passed, 61 of 61. The seam test only checks that values stay between the two inputs, which a hard edge satisfies.
    - **To pass:** a test that fails on a step at the seam, observed failing first.

11. **Dark greenish fringe on the top rows of some files (smaller issue).**
    - **Measured:** on 002, 004, 007, 010 and 013, the top rows read darker than the rows below. 004 row 0 averages about 133/161/155 in file channel order, against about 199/208/205 at row 20. A pale olive line along the top edge is visible on 004.
    - **To pass:** crop those rows.

**Contract question for the navigator (not a builder defect):** the pre-pull merges themselves carry false color (cyan trees, lavender and pink brick) and pale glass, while unit 1's merge at the 001 jamb holds a dark, natural view. It looks as if the balance step causes much of this, with auto_gain 3.29 on 001. That link is an inference, not something I proved. Keeping a window "from the merge" will therefore prevent damage but will not produce a clear view. The contract says "merge's pixels" without saying whether that means unit 1's merge or the balanced merge. The builder may need that settled when reworking this.

## 5. The rest of the contract, by section

**Pass, reproduced or read:**
- **Cap, first commit:**
  - Constant is $40.00 with $1 headroom.
  - A stub-transport probe refused at $40, over $40, and at $38.9999 plus worst case. It also refused a corrupt ledger, an unreadable ledger, an unknown price and non-allowlisted ids. Setting an environment variable with that name did not change the cap.
  - Named tests exist for these refusals in `tests/test_meta_client.py`.
- **Parser, second commit:** saved-response fixtures and a parser test exist and pass.
- **Banned-strings scan:** `scripts/banned_scan.sh` reads the outside list and reports entry numbers only (read, and it ran clean through the check).
- **A0:**
  - Lens: every photo reports a profile match, and straightness rises on all 17 per the check lines. 001, 009 and 012 are named on the page with the plain reason. The missing-profile path now continues rather than failing (read, not exercised on a real other lens).
  - Verticals: 13 photos are within 0.5 degrees on the shipped file (worst 0.36, 008), and 4 read NOT MEASURED.
  - Vignetting: skipped with the reason shown.
- **A1:** 86 frames group into 17 sets (ran), and the long-bracket test exists.
- **A2:** the chosen frames and reason are recorded per set. By reading the code, the MLS twin is read only after processing, in `attach_look`.
- **Section A counts:** 33 found, 14 confirmed, 19 rejected, all 19 with reasons, all on the page.
- **Criterion 2:** 17 finished, 0 failed.
- **Criterion 5:** pull candidates changed 0 pixels outside their own mask across all 14 windows, measured in my replay. The 8 photos without confirmed windows read NOT MEASURED.
- **Criterion 7:** 152 output JPEGs have no GPS or serial (EXIF, plus an XMP string check).
- **Criterion 8:** ledger gives $1.198008 for the unit against a $2.00 budget. Page footer shows $1.1990 to date, and my read total is $1.198996. I found no HTTP client outside `meta_client.py`.
- **Criterion 9 (section D):** noise drops on all 17 (median 2.75→1.43), and edge ratios run 0.916 to 1.021. These numbers come from the builder's metric under my replay. I ran no independent noise metric.
- **Criterion 11, numerically:** 16 rows pass and 006 has no twin. The report states the fit was on the same 16 photos. Those passes do not rescue findings 2 and 6, since the colored rectangles are inside the measured photos.
- **Criterion 12:** NOT MEASURED lines appear: 8 highlights, 8 outside, 8 floor, 4 verticals.
- **Unit 7 checks:** `checks.py` holds them, but see finding 4 for the gate.

**Fail:** section A's glass-only rule (finding 5), section B (findings 1, 3, 4), section C (findings 2, 6), criterion 4 (finding 3), criterion 6's hard-edge part (finding 10), criterion 13 (findings 1, 6), the observable criterion (findings 1, 2), and the ghosting report in A0 (finding 8).

**Tests and checks:**
- No check was deleted or skipped on the branch.
- The only loosened scan is the `sk-` pattern, in its own commit (d680c13) with its reason.
- This round removed old pull tests along with the code they tested, and narrowed some "real pixel" asserts to the deep interior with a comment. That is what let finding 10 survive.

**Hackathon rules:**
- Allowlist is first-party Meta models only.
- The key is read only from `META_API_KEY`, and I found no path to Muse Code's credentials.
- By reading the code, only downsized photos and fixed prompts go to Meta.
- AppFolio is labeled pre-existing in `docs/provenance.md` and the build plan.

**Hygiene:**
- Hooks are byte-identical to `scripts/git-hooks/`, and no approval files exist.
- No remote, and all 46 commits use the private noreply address.
- `.gitignore` covers secrets, inputs, outputs, ledger, `.navigator/`, `local/` and `.muse/`.
- No image or ledger file is tracked, and none was added in branch history.

## 6. Not verified

- **Banned strings in commit messages, history diffs and the branch name.** You told me not to open the private folder, so I did not scan these myself. Only the check's scan of tracked file names and contents ran, and it was clean.
- **Live Meta behavior.** I made no Meta calls, so SAM masks and Spark verdicts are the saved ones, not re-run. The rejection reasons are what the saved manifest holds.
- **Windowless photos.** I did not visually review the 8 photos with no confirmed window. Full-frame overviews (downscaled, for overall look only) were viewed for 001, 003, 004, 005, 006, 007 and 010, but not 009 or 011. I measured no guard on 009 or 011, and their a* and b* steps are 2 or less.
- **Unit 1 merge JPEGs.** I opened one full-resolution unit 1 merge crop, the 001 w2 jamb. The per-window comparison used the pre-pull pipeline merge, because the unit 1 JPEG has different exposure and no rotation or lens correction.
- **Image display.** Tiles were built at native pixels and returned at those sizes. I cannot see inside the viewer beyond that.
- **sRGB.** The finished JPEGs carry no embedded color profile. I did not verify the working color space beyond that.
- **Section 4b (tidy honesty)** does not apply until unit 4.

Evidence is in `<scratch path>` (tiles) and `<scratch path>` (replay outputs).
