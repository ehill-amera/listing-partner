NOT YET

The floor and baseboard patches are gone, and the cool trigger now changes nothing outside the window masks. But the same trigger now adds a colored band on 003 and 001 and a ragged gray-white patch on 009, so the ship rule's "no band or patch" test fails. Everything else in the ship rule holds, apart from one hygiene item I was told not to check. Erik could accept these two marks as known limits. That is his call, and the navigator's notes do not cover them today.

Reviewed commit 473cff0 on `unit-02-window-pulls`. Tracked files matched the commit and were unchanged after my runs. The only untracked file is `contracts/03-curate-and-write.md`, which I did not open. I made no Meta calls and spent nothing: the ledger had 519 lines before and after. My replay ran with the key unset and wrote only to the scratchpad.

## Ship rule, item by item

| Item | Result | What I did |
|---|---|---|
| Hackathon rules | Holds; SAM text prompts not read | Searched the code, read the Spark prompts, read the ledger's models |
| Hygiene | Holds, with one part unverified | Scans below; banned list against commit messages not checked |
| Cap | Holds | Read the constants, ran the refusal tests |
| Honesty rules | Tidy rules do not apply until unit 4 | Nothing to measure yet; see the page label under Known limits |
| Ramp test | Passes, same contract wording problem as before | Ran it and my own ramps |
| Criterion 11 | Holds under the navigator's note | Re-measured with my own Lab formula |
| `./scripts/check` | **Passes** | Exit 0, 252 passed, banned scan clean, CHECK OK |
| No box, seam, band or patch | **FAILS** | Finding 1 |

## Prior finding 1 (7ee0217): fixed as written, with a new side effect

**The rule asked for: the cool-bright trigger acts only inside feathered window masks. It does.**
- **How I measured it:** I replayed all 17 sets. For each one I rendered the balance stage with and without the masks, then compared them pixel by pixel.
- **Outside the masks:** 0 pixels changed on 17 of 17.
- **Inside the masks:** the trigger fired on 9 of 17: 001, 003, 004, 005, 006, 007, 009, 010, 011. It changed up to 192 levels.
- **One strength per photo:** the code uses one strength for each photo, 0.8 on all nine. The strength fades in from zero at the mask edge over about 60 px.
- **Floors and baseboards at native pixels:** the 009 floor and 005 baseboard no longer have gray-white patches.
  - The 009 lavender floor and the 005 blue baseboard run are still there. They look the same in the render without the trigger, so the trigger did not cause them. They fall under the floor limits Erik accepted.
  - I did not view the 003, 006 or 007 floors at native pixels this round. The zero-change result covers the trigger on those floors.

**The side effect:** the masks are not glass-only, which is a contract limit. They run across frames, blinds, trim and sometimes wall, and sometimes their edge lands on the view itself. The fade then shows up on whatever lies under that edge. That is finding 1.

## Findings

**1. The trigger's fade creates a colored band on window views and a ragged patch on wall and trim. This blocks shipping.**

- **Where:** `listing_partner/finish.py`, `_mask_feather` and `_cool_view_gate`, used with the saved masks.
- **How I attributed it:** I compared native panels of the merge stage, the render without the cool trigger, the shipped photo, and the shipped photo with the mask outlined. Each mark below appears in the shipped photo and not in the render without the trigger.

**003, window view: a saturated band.** A blue and green strip hugs the left and bottom edges of the pane against a pale view. I could see it in the full-frame view too.

Measured at x=2370 to 2550 on three rows (y=1950, 2150, 2350). Each row reads the shipped photo, then the render without the trigger:

| Row | Near the mask edge, 16 px in | About 60 px in and beyond |
|---|---|---|
| y=2150 | a* -25.5, b* +28.4 | a* about -7, b* about +8 |
| y=1950 | b* -39.6 | b* about -11 to -14 |
| Without the trigger, same places | a* about -30 to -33, b* about +34 to +40 (y=2150); b* about -44 to -49 (y=1950) | No band; the view stays saturated across the pane |

**001, window view: the same kind of band.** A strip of yellow and green runs down the left edge of a pane, about 50 px wide by eye, against a pale view.

**009, right window: a patch on wall and trim.** The mask's edge is ragged and lands on peach trim and wall.
- Beside the window at y=2000, b* falls from 20.3 to 3.5 over about 60 px, and a* falls from 9.7 to 0.8. Without the trigger, b* stays at about 18 to 21 over most of that run.
- The result is a gray-white bar with a ragged edge running down the wall side of the frame.
- Along the top trim, the color changes partway along one board. Between x=5500 and x=5540, b* goes from 4.4 to 10.4. Without the trigger it reads about 15 to 18 there.
- I first noticed this in the full-frame view, before any measuring.

**Milder, and I would not block on these alone.** On 004, 006 and 007, trim goes from warm to gray-white where the mask crosses it, softly. On 009's left window, trim goes gray inside the mask. On 005, 010 and 011, I saw no distinct band in the regions I viewed.

**Why the numbers did not catch it.** The criterion 14 readings on this run are a* 1.07 and b* 1.33 at most, under the limit of 2, and my replay matched them. That measure limits the step between neighboring pixels. A change of about 30 b* over 45 px passes it, so criterion 14's number holds and its "seen on the page" half does not. No test covers a mask edge crossing a saturated view or a warm wall.

**What would make it pass:**
- No saturated strip along any pane edge on 001 and 003, and no ragged gray-white shape on 009's wall or trim. This also needs to hold wherever else a mask edge crosses a view or a warm surface.
- A failing-first test where a mask edge crosses a saturated view and a warm wall, with a limit on the color change across the whole fade rather than per pixel. The failure must be observed on 473cff0.
- A fresh full replay and a fresh full-resolution review.
- Or Erik accepts these marks as a known limit, and the report and page say so.

## Known limits (not blocking under the ship rule)

The contract sends everything except the ship-rule items to Known limits, so these are for Erik to see. Items 1 and 2 are cheap to fix and I would fix them in the same round.

1. **A fresh run would say "none" on the known-limit line.**
   - **Cause:** `run_finish.py:1195-1196` calls `_summarize` before `attach_look`, so no photo has its bright-surface reading yet. The replay path at lines 1128-1130 has the right order, and that is the only path that produced this page.
   - **How I checked:** I fed the function a record without the reading and it returned an empty list, and the page line read "none". I did not run a fresh set, because that would call Meta. Today's page correctly names 012.
   - **Why it matters:** the contract says any photo over 1% is listed, and a false "none" looks complete. Unit 7 will use the fresh path.
2. **The page says "found, not edited" 35 times, but the trigger edits those windows.** It changes views on 9 of 17 photos, by up to 192 levels. The contract's limit "window views stay as merged" is no longer true either. The page does show the trigger's share and strength for each photo, but the label is wrong.
3. **The report's table does not explain every look miss.** It lists 014 as FAIL beside a b* gap of 4.96, which is under the limit. The real miss is brightness, 16.7% against 15%. It also omits 004's a* gap, which I measured at 5.82. The page gives the reason for both.
4. **Window views are very pale at native pixels** on all nine photos where the trigger fired.
5. **016's stepped purple and cyan outlines around leaves come from moving leaves.** The merge has no deghost step, which is a contract limit. The ghosting reading of 0.1985 is under its 0.25 limit, though the outlines are plain to see.
6. **017's sky is blotchy and pale** and has a lens-flare spot. I did not attribute this at native pixels this round. The last review found the sky the same without the highlight roll-off.
7. **008 has a blown white oval above the mirror.** It is not from the cool trigger, which did not fire on this photo. It starts as glare in the merge stage and gain widens it.
8. **Soft color drift and red specks.**
   - Interior ceilings on some photos drift softly in color. On 011 I attributed this: the drift is in the merge stage too, with no hard edge.
   - Single red specks show on walls, as on 002 and 005. Last review found them in the merge; I saw the 005 speck in the merge stage this round.

**Already accepted by Erik, as relayed by the navigator; I did not count these:**
- Floor FAILs on 003, 004, 006, 007, 008, 009 and 012.
- 012's bright-surface share of 1.51%. It is on the page.
- Criterion 11 misses, because the report names each one.
- The missing "Built-by" trailer.
- The page stamp `473cff0-dirty`, caused only by the untracked contract.

**Standing contract limits:** no deghost step, masks not glass-only, lit-wall noise not measured, verdicts and masks saved from earlier runs.

## Criterion by criterion

| # | Result | How verified |
|---|---|---|
| 1 | Holds | Ran the check: exit 0 |
| 2 | Holds: 17 finished, 0 failed | Replay and manifest |
| 3 | Holds: 39 found, 17 confirmed, 22 rejected | 39 mask files on disk, 22 rejection images on the page, 0 empty reasons; 89 images on the page, 0 missing |
| 4, 5, 6, 13 | Paused by contract | Pulls are off |
| 7 | Holds; banned list against commit messages unverified | All 17 finished photos have 0 EXIF tags; banned scan clean on tracked files |
| 8 | Holds: $1.457032 of $2.00 | Ledger total $1.45802, less baseline $0.000988 |
| 9 | Holds | Noise drops on 17 of 17, median 2.87 to 1.44. Edge ratio 0.909 to 1.023. From my replay's numbers |
| 10 | Holds | Straightness improves on 17 of 17. Largest final vertical 0.34 degrees; not measured on 005, 012, 016, 017. From my replay's numbers |
| 11 | Holds under the navigator's note | Table below |
| 12 | Holds as far as I checked | Saw "not measured" paths in the code and page; did not audit each row |
| 14 | Number holds; "seen on the page" fails | Finding 1. Ghosting 0.0006 to 0.1985 |

**Criterion 11, re-measured from the shipped files with my own Lab formula:**

| Photo | Brightness gap | a* gap | b* gap | Result |
|---|---|---|---|---|
| 001 | 4.3% | 2.41 | 3.74 | Pass |
| 002 | 3.8% | 1.39 | 3.17 | Pass |
| 003 | 1.1% | 4.87 | 3.52 | Pass |
| 004 | 5.3% | 5.82 | 5.60 | Miss |
| 005 | 3.7% | 1.90 | 5.40 | Miss |
| 006 | no twin | | | Not measured |
| 007 | 5.8% | 2.29 | 4.13 | Pass |
| 008 | 12.2% | 0.54 | 3.05 | Pass |
| 009 | 1.0% | 4.81 | 5.44 | Miss |
| 010 | 2.6% | 2.00 | 3.30 | Pass |
| 011 | 1.5% | 1.70 | 1.89 | Pass |
| 012 | 3.0% | 2.61 | 2.93 | Pass |
| 013 | 9.4% | 1.19 | 5.48 | Miss |
| 014 | 16.7% | 1.36 | 4.97 | Miss |
| 015 | 2.8% | 0.93 | 3.58 | Pass |
| 016 | 0.9% | 3.36 | 1.20 | Pass |
| 017 | 1.6% | 1.61 | 6.35 | Miss |

10 of 16 pass, and interiors within 5 b* are 8 of 11. Both match the report, whose b* figures match mine within 0.06 (the manifest's own Lab reading). I matched each MLS file to its photo using the manifest's readings, not the program's capture-time match.

## Check command and tests

- **Check:** `env -u META_API_KEY ./scripts/check` exits 0 with 252 passed.
- **Clean export without photos, pytest only:** 243 passed, 9 skipped, 0 failed.
- **Weakening, compared with `main`:**
  - `scripts/check`: the `sk-` pattern needs 20 or more characters and the banned scan moved out of the repo. Both have reasons in the code, and earlier reviews covered them. No new skip or xfail marker appears in the test diff.
  - Test changes since 7ee0217: the fallback assertions went with the fallback, as the contract directs.
  - `test_cool_window_view_does_not_read_cyan` changed its fixture to a less saturated view, dropped its 15-level spread limit, and now holds only the view's core to zero. The test still fails without the trigger, but it no longer looks at the fade. That is the gap finding 1 sits in.
- **Hooks:** all four in `.git/hooks` are byte-identical to `scripts/git-hooks/`. Neither approval file exists, and `core.hooksPath` is unset.

## Ramp test

- It passes at this commit: 2 passed.
- **Contract wording problem, not a builder defect:** the contract says a* and b* stay within 2, and constant color ratios cannot satisfy that on real paint across a long ramp. My own wide ramps read a* ranges of 2.73 to 3.70 and b* ranges of 4.23 to 12.41. The test checks channel ratios instead, with limits of 0.02 and 0.03, and last review judged that the honest measure.

## Hackathon rules, cap, hygiene

- **Single path:** `urllib` appears only in `meta_client.py`. I found no other provider library and no reference to `.config/muse`.
- **Models:** the allowlist holds Muse Spark 1.1, 1.2, 1.3, SAM 3.1 and Muse Image 1.0. The ledger holds only `muse-spark-1.3` (305 lines) and `sam-3.1` (214 lines).
- **Key:** read only from `META_API_KEY`, at `meta_client.py:313`.
- **Cap:**
  - The constants are 20.0 and 1.0 headroom, and the ceiling is computed from them at lines 324-326.
  - The named refusal tests cover: at the cap, would cross, unreadable ledger, corrupt ledger, unknown price, non-allowlisted and Contributor models, constant cap, env-only key. 25 selected tests passed.
  - I read test names, not their bodies, this round. `meta_client.py` and `segment.py` have no changes since 7ee0217.
- **What gets sent:**
  - I read the verify, zoom and crop prompts. They ask only about windows.
  - **Unverified:** I did not read the SAM text prompt strings or every call site this round.
- **Provenance:** connector mentions in `PRODUCT.md` and `docs/` label it as existing, in the lines I read. The README does not mention it.
- **Hygiene:**
  - 0 image, ledger, `.env`, `output/`, `inputs/` or `.navigator/` paths in tracked files or in the branch's objects.
  - 0 key-, email- or phone-shaped added lines since 7ee0217. The check's scans are clean on all tracked files.
  - All 78 commits use one private noreply address, and no remote exists.
  - `.gitignore` shows no change against `main`.
- **Unverified:** I did not check commit messages or history against the banned list, because this review was told not to open that folder. An address-shaped search of commit messages found 0 hits, but that is not the same check.

## Photo inspection record

**All 17 viewed full-frame**, each shipped file scaled to 1500 px on its long side. **I did not tile any photo edge to edge at native pixels**, so a flaw in a region not listed here could be missed.

"Panel" means four native-pixel crops of 750 by 700 px: merge stage, render without the cool trigger, shipped, and shipped with the mask outlined. The render without the trigger is before denoise and JPEG, so it looks noisier. "Crop" means a native crop of about 1400 px from the shipped file. No photo failed to open.

| Photo | Native regions viewed | Seen |
|---|---|---|
| 001 | Blinds corner panel; left window edge panel | Band, finding 1 |
| 002 | Pendant and wall crop | No patch; red speck |
| 003 | Two window panels | Band, finding 1 |
| 004 | Two window panels | Pale view, soft trim change |
| 005 | Window panel; baseboard panel | No distinct band; blue baseboard run also in the merge stage and the render without the trigger |
| 006 | Two window panels | Pale view, soft trim change |
| 007 | Window panel | Pale view, soft trim change |
| 008 | Mirror and lamp crop; same area panel | Blown oval, from merge-stage glare and gain |
| 009 | Right window crop and two panels; left window panel; floor panel | Patch, finding 1; floor not patched |
| 010 | Window panel | No distinct band |
| 011 | Window panel; ceiling crop and panel | No distinct band; soft ceiling drift, also in the merge stage |
| 012 | Door jamb crop | Hard split looks like real sun and shadow, as last review found. Window not viewed natively |
| 013 | Trees and sky crop | No patch |
| 014 | Tree and sky crop | No patch |
| 015 | Trees and sky crop | No patch |
| 016 | Leaves and sky crop | Stepped outlines from moving leaves; not compared to the merge this round |
| 017 | Sky crop | Blotchy pale sky and flare spot; not compared to the merge this round |

I also ran a rough search for strong color in the fade zone on the 9 photos where the trigger fired, to choose where to look. The readings were 0% to 33.56% of each photo's fade zone, and it also counts warm trim. I do not offer it as a pass or fail number.

## Report numbers

**Reproduced:**
- Replay against shipped files: 0.0043% to 0.0251% of pixels differ, by at most 7 levels.
- Cool trigger on 9 of 17, 0.00% outside the masks, largest edge step a* 1.07 and b* 1.33.
- The bright-surface shares in the report's table, including 009 at 1.01 and 0.91, 012 at 1.67 and 1.51, and exteriors at 1.69 to 9.20.
- Floor verdicts and readings (10 PASS, 7 FAIL), and the highest flat white reading of 3.5%.
- Near-white window pixels from 7.47% to 7.09%. My replay read 1,185,530 pixels and the report reads 1,185,532.
- Look counts, window counts, spend, and the check and clean-export counts.

**Not reproduced, relying on the builder:**
- 626 s and 7,807 MB. I read them only from the builder's log and page. My replay took 841 s and peaked at 8,089 MB, but it did extra stage work, so the two are not comparable.
- Worst reservation ratio 2.00 over 256 calls. Read from the manifest, not recomputed from the ledger.
- All "before" figures from the a4f4ffd run.
- The count of 6 flat-white photos above their twin.

## Scratch files

- 003 window band panel: <scratch path>
- 001 window band panel: <scratch path>
- 009 trim patch panel: <scratch path>
- 009 wall patch panel: <scratch path>
- Replay measurements per photo: <scratch path>
