NOT YET

Walls and brick are fixed, but the new cool-bright trigger paints gray-white patches on floors, baseboards and window views, so the ship rule's "no patch" test fails. Everything else in the ship rule holds, apart from one hygiene part I could not verify.

Reviewed commit 7ee0217 on `unit-02-window-pulls`. The tree was clean before and after my runs. I made no Meta calls, spent nothing and changed no repo files. My replay ran with the key unset and wrote only to the scratchpad.

## Ship rule, item by item

| Item | Result | What I did |
|---|---|---|
| Hackathon rules | Holds; prompt wording not re-read | Searched the code and ran the tests |
| Hygiene | Holds, with one part unverified | Ran scans; banned list against commit messages not checked (details below) |
| Cap | Holds | Ran the refusal tests and read the constants |
| Honesty rules | Tidy rules not applicable until unit 4; floor color is a concern | See finding 1 |
| Ramp test | Passes, same contract wording problem as last review | Ran it and measured Lab ranges |
| Criterion 11 | Holds under the navigator note: every miss is stated | Re-measured with my own Lab formula |
| `./scripts/check` | **Passes** | Exit 0, 230 passed, ruff clean, banned scan clean |
| No box, seam, band or patch | **FAILS** | Finding 1 |

## Check of the two prior findings

**Prior finding 1 (white patches, gray brick): fixed for what it named. A new patch of a different kind replaces it (see finding 1 below).**
- **Flat white share, re-measured on the shipped files:** 0.0% to 5.4%, down from 3.8% to 42.8%. It matches the report's table.
- **005 right wall:** native tile viewed. Across the region I tested, roll-off blend is 0.000 and the wall holds its color.
  - A faint pale glow remains there. It is in the merge input too, so the finish did not create it.
  - I did not repeat the report's exact b* row.
- **014 brick:** native tiles viewed. The brick reads red, with no gray fragments.
- **Clipped-in-merge trigger:** in my panels for 002, 005, 007, 009, 014 and 016 I saw no patch from it on walls or brick. On 016 and 017 it pushes bright sky further toward white (see Known limits).

**Prior finding 2 (tests blind, false comments): fixed as written, with the same kind of gap now on the cool trigger (finding 2 below).**
- I ran `test_one_wall_keeps_one_color_through_the_highlight_range` on an export of 970ce8f. It fails for the behavior: color step 0.064, limit 0.01.
- The two false comments are rewritten.
- The cool-window, exterior-sky, clip-trigger and wall-detail tests also fail on 970ce8f. The report says the wall-detail test was not run on old code and the first three were not either; I ran them. The cool-window and exterior-sky failures may be partly fixture-driven; I did not read those two failure messages in full.

## Findings

**1. The cool-bright trigger creates visible patches. This blocks shipping.**

- **Where:** `listing_partner/finish.py:140-145`, constants at `finish.py:87-90`.
- **The rule:** the navigator accepted this trigger only if it creates no band, patch or edge. The ship rule and the observable criterion ask the same thing.
- **How I attributed it:** I replayed all 17 sets into scratch and saved each merge and balance stage. The replay matches the shipped files except for 0.0016% to 0.0326% of pixels, at most 8 levels. For each region I then rendered the same pixels with the finish's own code three ways: shipped, without the cool trigger, and without any roll-off. In each case below the patch appears only in the shipped version.

What I saw at native pixels:

| Photo | Where | What the finish does |
|---|---|---|
| 009 | Floor | A large area of wood goes flat gray-white with a speckled edge. Neighboring boards stay lavender-pink. Its MLS twin shows wood color there. |
| 003 | Floor by the sun patches | A gray-white patch with speckled edges, in a lavender floor |
| 006, 007 | Floor | Gray-white blotches on boards, with speckled edges |
| 002, 005 | White baseboard | Runs turn white beside bluish runs. 005 has a white block with a short, near-vertical end. |
| 003 | Window view | The neighbor's house and yard go gray-white with ragged edges against saturated green lawn. The twin shows a readable house and lawn. |
| 004 | Window view | The upper half of a tree goes gray-white, stopping at the sash |
| 005, 006, 007 | Window view | Trees or the neighboring house go largely white with leftover green or pink flecks. The merge has a readable view. |

Measured on the shipped files (Lab, small averaged blocks):
- **009 floor, x=2600, y=3200 to 3760:** a* falls from 9.1 to 0.0 and b* runs from -10.2 to 0.0. From y=3480 to 3760 it reads a* 0.0, b* 0.0, exactly neutral. Real wood does not read that way.
- **003 floor, x=3050:** a* goes from 1.8 to 9.1 between y=2850 and y=2930. From y=2730 to 2810 it reads about a* 0, b* 0 to -0.7.
- **005 baseboard, y=2985:** a* 0.0, b* 0.0 up to x=1660, then a* 6.2, b* -8.7 by x=1720. That is about 60 px.

How far it reaches, computed with the finish's own gate. "Gate" means pixels where the cool trigger is above 0.5. "Outside" excludes window masks grown by 20 px.

| Photo | Gate, % of frame | % of window pixels | Outside, % of frame | Largest outside area (px) |
|---|---|---|---|---|
| 001 | 1.81 | 15.1 | 0.17 | 12,400 |
| 002 | 0.62 | no window | 0.62 | 62,480 |
| 003 | 2.70 | 44.3 | 0.98 | 227,536 |
| 004 | 1.83 | 20.7 | 0.03 | 112 |
| 005 | 2.31 | 48.8 | 0.32 | 56,144 |
| 006 | 4.29 | 20.1 | 1.85 | 220,544 |
| 007 | 6.17 | 30.1 | 3.39 | 551,424 |
| 008 | 0.16 | no window | 0.16 | 3,856 |
| 009 | 10.86 | 28.7 | 7.30 | 1,140,800 |
| 010 | 1.94 | 27.3 | 0.60 | 78,816 |
| 011 | 1.22 | 29.6 | 0.38 | 16,096 |
| 012 | 1.75 | 0.6 | 1.75 | 66,208 |

Exteriors do not use this trigger. Not every gated pixel is a visible flaw: on 001, 010 and 011 the regions I viewed showed no sharp patch. The worst are 003, 005, 006, 007 and 009.

- **Why it patches:** the gate reads the tint of each pixel after gain, and the merge's floors and trim sit right at its cool threshold. Small differences and noise flip neighboring pixels. In its transition zones, the gate's 95th-percentile slope is 0.11 to 0.16 per pixel after a small blur, so it goes from off to on within about 10 px.
- **Why it matters beyond looks:** the 009 and 003 floors read as flat neutral, which misstates the floor to a renter. Removing the trigger alone is not a fix, because the same pixels then read lavender or cyan-blue.
- **What would make it pass:**
  - On interiors, no floor, trim or wall goes neutral in patches.
  - Window views stay continuous, with no gray-white patch against saturated areas. Blown-bright views are fine.
  - Then a fresh full replay and a fresh full-resolution review.
- **If Erik prefers:** accepting these patches as a known limit is his call. The navigator notes do not currently cover them.

**2. No test can see finding 1, and the code and report say the opposite.**

- **Tests:** `test_cool_window_view_does_not_read_cyan` uses a uniform view patch, so it never crosses the gate's edge. No test puts one surface across the gate's threshold.
- **Code:** `finish.py:13` says "Warm surfaces far from clipping never move", and `finish.py:76` says neither trigger can fire on a warm surface far from clipping. In the 009 and 003 regions the merge peak is about 66 to 102 and the wood goes neutral. The wood is warm as a material, but it reads cool in the merge.
- **Report:** item 3 says "Warm surfaces cannot trigger it" and treats a blue wall as the limit. The real reach is floors and baseboards.
- **Numbers:** `finish.py:82` says peak 46 to 160; the report says 42 to 174. I reproduced neither.
- **What would make it pass:** a failing-first test where one surface with noise crosses the cool threshold and its color change per pixel is bounded, observed failing on 7ee0217. Correct the comments and the report line.

## Criterion by criterion

| # | Result | How verified |
|---|---|---|
| 1 | Holds | Ran the check: exit 0 |
| 2 | Holds: 17 finished, 0 failed | Files and manifest |
| 3 | Holds: 39 found, 17 confirmed, 22 rejected | Manifest. Page has 89 images, 0 missing. I did not re-count rejection reasons this round. |
| 4, 5, 6, 13 | Paused by contract | Pulls are off |
| 7 | Holds at this commit; banned list against commit messages unverified | All 17 finished photos have 0 EXIF tags, so no GPS or serial. Banned scan is clean on tracked files. |
| 8 | Holds: unit spend $1.457032 of $2.00 | Ledger: settled $1.411336 plus 2 open reservations $0.046684 gives $1.4580, less baseline $0.000988 |
| 9 | Holds: noise drops on 17 of 17, median 2.87 to 1.45; edge ratio 0.911 to 1.023 | Manifest numbers, from a run my replay reproduces. I did not measure them separately. |
| 10 | Holds: straightness improves on 17 of 17; largest final vertical 0.31 degrees; not measured on 005, 016, 017 | Manifest |
| 11 | Holds under the navigator note | Table below |
| 12 | Holds as far as I checked | Page and manifest show "not measured" rows. I did not audit each one. |
| 14 | Fails on "seen on the page" | Finding 1 is a patch. There is no regional correction edge to measure, because the trigger has none. Ghosting 0.0006 to 0.1985 per manifest. |

**Criterion 11, re-measured per photo**

| Photo | Brightness gap | a* gap | b* gap | Result |
|---|---|---|---|---|
| 001 | 4.3% | 2.25 | 4.11 | Pass |
| 002 | 3.8% | 1.40 | 3.24 | Pass |
| 003 | 1.1% | 4.69 | 3.97 | Pass |
| 004 | 5.8% | 5.38 | 6.35 | Miss |
| 005 | 3.7% | 2.01 | 5.52 | Miss |
| 006 | no twin | | | Not measured |
| 007 | 5.8% | 1.98 | 5.01 | Miss |
| 008 | 12.2% | 0.54 | 3.03 | Pass |
| 009 | 1.0% | 4.24 | 7.73 | Miss |
| 010 | 2.6% | 1.86 | 3.37 | Pass |
| 011 | 1.5% | 1.73 | 1.98 | Pass |
| 012 | 3.0% | 2.64 | 3.17 | Pass |
| 013 | 9.4% | 1.19 | 5.48 | Miss |
| 014 | 16.7% | 1.36 | 4.97 | Miss |
| 015 | 2.8% | 0.93 | 3.58 | Pass |
| 016 | 0.9% | 3.36 | 1.20 | Pass |
| 017 | 1.6% | 1.61 | 6.35 | Miss |

9 of 16 pass. Interiors within 5 b*: 7 of 11. Both match the report, which names each miss. These are averages, and they pass on photos with patches.

## Check command

- **Result:** `env -u META_API_KEY ./scripts/check` exits 0, with "All checks passed!", 230 passed, banned scan clean, CHECK OK.
- **Clean export without photos, pytest only:** 221 passed, 9 skipped, 0 failed. Each skip prints its reason.
- **Not weakened:**
  - Since 970ce8f the diff touches only `checks.py`, `finish.py`, `measure.py`, `run_finish.py` and `tests/test_finish.py`.
  - In that test diff, one assertion that the old roll-off fires is replaced, and pinned constants change with the code. Both match the fix.
  - Compared with `main`, the `sk-` pattern needs 20 or more characters and the banned scan moved out of the repo. The last review covered both, with reasons in the code.
- **Hooks:** `.git/hooks` is byte-identical to `scripts/git-hooks/` for all four. Neither approval file exists, and `core.hooksPath` is unset.

## Ramp test

- It passes at HEAD.
- **Contract wording problem, not a builder defect:** the contract says a* and b* within 2, but constant chromaticity cannot satisfy that on warm paint. On my own ramps at HEAD, the a* and b* ranges were 1.84 and 4.70 (warm paint), 2.05 and 3.94 (near-neutral), and 7.08 and 9.58 (the 005 wall under full gain). The old code read higher on b*: 11.0, 7.36 and 21.55.
- As last review, the chromaticity check is the honest measure.

## Hackathon rules, cap, hygiene

- **Single path:** `urllib` is imported only in `meta_client.py`. I found no other provider library. The only model calls are at `segment.py:129` and `segment.py:268`, through the capped client.
- **Models:** the allowlist holds Muse Spark 1.1, 1.2, 1.3, SAM 3.1 and Muse Image 1.0. The ledger contains only `sam-3.1` and `muse-spark-1.3`.
- **Key:** read only from `META_API_KEY` (`meta_client.py:313`). There is no reference to `.config/muse`.
- **Cap:**
  - `SPEND_CAP_USD` is 20.0 and headroom is 1.0.
  - The tests for refusal at cap, would-cross, unreadable ledger, corrupt ledger, unknown price, non-allowlisted and Contributor models, constant cap and env-only key all pass: 10 passed.
  - `meta_client.py` and `segment.py` are unchanged since 970ce8f, so I did not repeat last review's hand-run refusals.
- **What gets sent, unverified this round:** I did not re-read the prompts. Those call sites are unchanged since last review, and last review also did not read every prompt word for word.
- **Provenance:** AppFolio connector mentions in `docs/` and `PRODUCT.md` that describe it label it as existing. The README does not mention it.
- **Hygiene:**
  - 51 tracked files.
  - No image, ledger, `.env`, `output/`, `inputs/` or `.navigator/` path in the branch's object history.
  - 0 secret-pattern hits across the branch's commit diffs.
  - The only email-shaped added line is in the base64-like SAM fixture, plus `example.com`.
  - No phone-shaped added lines.
  - All 73 commits use the private noreply address, and no remote exists.
  - `.gitignore` is unchanged against `main`.
- **Unverified:** I did not check commit messages or history against the banned list, because this review was told not to open that folder. An address-shaped search of commit messages and tracked contents found 0 hits. A count-only search for the house number visible in the exterior photos found 0 in tracked names, in commit messages, in branch names and in tracked contents (the SAM fixture excluded).

## Denoise change from 15 to 12

**Accepted: it creates no band, patch or edge.** I ran both settings on the balance stage of 001, 003, 005, 007, 009, 012 and 014. Mean difference is 0.02 to 0.28 levels and the largest single pixel is 8. Blurred at sigma 25, the largest difference is 0.04 levels, so there is no broad offset that could read as a patch. I did not run this on the other 10 photos; the filter is applied the same way to every photo.

## Photo inspection record

**How I looked**
- **All 17, full frame:** the shipped file scaled to 1600 px wide.
- **Native pixels:** crops of 800 to 1400 px per side, or four-panel attribution views built from native-pixel crops. These cover regions I chose, not every tile of every photo. **I did not tile any photo edge to edge**, so a flaw elsewhere could be missed.
- **Viewer artifact:** some panels (004, 006, 007) looked posterized in my viewer, including their merge panels. The shipped files have 100,000 or more distinct colors in those crops for 006 and 007 (004 not counted), so I do not count this as a defect.

| Photo | Native regions viewed | Seen |
|---|---|---|
| 001 | Window | No sharp patch; slight tint; fringe on glass edge also present without roll-off |
| 002 | Baseboard | White and bluish runs along one baseboard, from the cool trigger |
| 003 | Window (twice), floor | Patches, finding 1 |
| 004 | Window | Tree half gray-white at the sash, finding 1. Floor native not viewed. |
| 005 | Wall, baseboard (twice), window corner | Baseboard block and white view, finding 1. Wall glow is from the merge. |
| 006 | Floor, window | Patches, finding 1. Lamp crop made, not viewed. |
| 007 | Lamp, floor, window | Patches, finding 1. Orange glow on the ceiling above the lamp, not attributed. |
| 008 | Mirror top and lamp wall | Bright wall oval; present before the roll-off, slightly larger with it. No distinct patch. |
| 009 | Wall, floor | Floor patch, finding 1, the worst case. Pale wall shapes on the right wall not attributed. Window panel made, not viewed. |
| 010 | Window corner | No distinct patch |
| 011 | Window corner | No distinct patch |
| 012 | Door jamb (twice) | Hard split is real sun and shadow, also in the merge. Window panel made, not viewed. |
| 013 | Front windows | No patch seen. Reflections are real. Other crops made, not viewed. |
| 014 | Roof, garage, brick | No patch; brick reads red |
| 015 | Trees | No patch seen. Other crops made, not viewed. |
| 016 | Leaves (twice) | Stepped cyan and purple outlines; present in the merge (see Known limits) |
| 017 | Sky | Blotchy pale pink clouds and a lens-flare spot; also without roll-off |

Full-frame only for the rest of each photo. I saw no rectangular box or straight-line seam from the finish on any view. The nearest thing is the short, near-vertical end of the 005 baseboard block.

## Known limits (not blocking)

**Accepted by Erik, as relayed by the navigator; I did not count these:**
- Floor FAILs on 004, 006, 007, 008, 009, 012. My manifest readings match the report.
- Criterion 11 misses, because the report states each one.
- The missing "Built-by" trailer.

The report's line that the 008 and 012 floor FAILs are "not accepted by anyone yet" is now out of date.

**Standing limits from the contract:** no deghost step, window views as merged, masks not glass-only, lit-wall noise not measured, window masks and verdicts saved from earlier runs.

**Other things for Erik to see:**
- 016 has stepped outlines around moving leaves. They are in the merge, so this is the no-deghost limit. The ghosting reading of 0.1985 is under the 0.25 limit, so the number does not flag what is plainly visible.
- 016's sky goes white where the merge has pale blue and clouds; the clip trigger adds to this. 017's sky is pale and blotchy with or without the trigger.
- Tiny single-pixel red dots show on walls and ceilings on 005, 009 and 011. They are also in the merge on the regions I compared, and gain makes them easier to see. 014's garage door has a red and a green dot.
- Noise is highest on 017: 11.39 to 6.78.
- The near-white figure of 8.12% to 7.65% moves only because of denoise and JPEG saving, as the report says.

**Report numbers I reproduced:** look table, flat white, bright-surface shares on interiors, noise, edge range, window counts, near-white counts, spend and ledger total, as noted above. Replay pixel match is above.

**Not reproduced, relying on the builder:**
- 581 s and 8,291 MB (read from the manifest and log only; my replay's peak read 8,728 MB in a different setup).
- Worst reservation ratio 2.00 over 256 calls. This round I read it from the manifest; last review reproduced it, and the ledger is unchanged in spend.
- The 005 wall b* row and the quarter-size window cyan sweep.

## Scratch files

- 009 floor attribution: <scratch path>
- 003 window attribution: <scratch path>
- 003 window beside its MLS twin: <scratch path>
- 003 floor attribution: <scratch path>
- 005 baseboard attribution: <scratch path>
- 007 window beside its MLS twin: <scratch path>
- 009 beside its MLS twin: <scratch path>
