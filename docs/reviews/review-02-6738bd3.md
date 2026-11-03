NOT YET: the finish paints bright surfaces cyan or blue with visible patches and bands, and the check fails on a fresh clone. Most other ship-rule items hold.

Commit reviewed: 6738bd3 on unit-02-window-pulls. HEAD confirmed 6738bd3 and the working tree was clean at the start and at the end (0 tracked changes). No push, merge or remote. No Meta calls: ledger hash unchanged across my replay.

## Ship-rule evidence

| Item | Result | What I did and measured |
|---|---|---|
| Check command | HOLDS in this repo, FAILS on a fresh clone | Ran `./scripts/check`, key unset: exit 0, 213 passed, ruff clean, banned scan clean, CHECK OK. Scratch clone of 6738bd3: pytest 7 failed, 205 passed, 1 skipped. See finding 2. |
| Check not weakened | HOLDS | Diff against main: only the sk- length change (own reasoned commit) and the banned list moving outside the repo. Hook diffs only move the list path, plus a fallback to the old local path. |
| Paint-ramp test | HOLDS | Ran it: pass. My own run: a* 0.40, b* 0.60 on new code; a* 3.75, b* 8.70 on bb5df2b, so the old-code failure is reproduced. Six other paints on the test's own method all within 2 (worst b* 1.40). Caveat in Known limits. |
| Criterion 11 as reported | HOLDS as reported, literal "every shot" not met | Separate sRGB-to-Lab math on the shipped files: 15 of 16 pass, 006 has no twin. 013 fails: b* +19.30 vs +12.23, gap 7.07. Agrees with the report and page on all 16. See "Decision for Erik". |
| Spend cap and hackathon rules | HOLD | Cap constant 40.0, headroom 1.0, guard read in code. Cap tests in the passing suite cover at cap, crossing, unreadable and corrupt ledger, unknown price, non-allowlisted model, constant cap, key from env only. Allowlist holds Muse Spark, SAM 3.1, Muse Image ids only. Only `meta_client.py` imports an HTTP client. Finish path sends photos and fixed prompts. AppFolio labeled existing in docs. Key read only from `META_API_KEY`. |
| Unit budget | HOLDS | Ledger: total $1.458020 minus baseline $0.000988 = $1.457032, under $2.00. 256 ratios, lowest 2.00. Models used: muse-spark-1.3, sam-3.1. Includes 2 unsettled Oct 29 reservations counted at $0.046684. |
| Hygiene | HOLDS, one part not verified | 49 tracked files, no images, ledger, outputs or .navigator ever added. 58 of 58 commits use the private no-reply email. No remote. 4 hooks byte-identical. 0 secret and 0 phone patterns in added lines. Email-shaped hits: example.com plus two encoded-data noise strings (domains seen only). All 17 outputs have 0 EXIF tags. Banned scan clean on names and contents via the check. NOT verified by me: banned strings in commit messages, because I was told not to open the list and the check does not scan messages. I rely on the commit-msg hook there. |
| Honesty rules | HOLD as written | No generative step. Pulls off; windows labeled found, not edited. Tidy rules (4b) start at unit 4. The wrong colors are finding 1. |
| No box, seam, band or patch from the finish | FAILS | Finding 1. |

Provenance: I replayed all 17 sets from this commit into scratch, key unset: 17 replayed, 0 failed, 532 s. Look and floor fields match on 17 of 17; photos differ on at most 0.063% of pixels by at most 9 levels (cause not established). The shipped photos come from this commit.

## NOT YET findings

1. **Bright surfaces turn cyan or blue, with visible patches and bands, on every interior photo I checked at native size.**
   - What it looks like at native size:
     - 008: light shades, the wall around them, and the sink are saturated cyan. Erik's MLS photo shows cream shades and beige walls.
     - 012: the sunlit concrete at the garage door is a solid mint slab; the right door jamb is a solid cyan stripe.
     - Ceiling light domes are cyan on 005, 007, 009, 011; the pendant globe on 002 has a blue spot; recessed bulbs on 001 and 002 too.
     - 003 and 009: the sunlit floor goes from wood through lavender to pale blue, with a ragged edge.
     - 010: through the doorway, cyan bands on the wall and baseboard and a pink floor.
     - 001: sun patches read mint with a pink rim.
     - 004 and 006: window views go cyan, with blocky posterized color. 004 has a blue block across one pane.
     - 007: yellow-green bloom on the wall. I did not separately trace this one to the cause.
   - Measured, bright pixels clearly cyan or blue (mean above 170, B>=G, G-R>=15, B-R>=30), interiors 001-012:
     finished 7.68% to 26.01% of the frame; unit 1 merges 0.00% on all 12; MLS photos 0.00% to 2.54%.
   - Per photo, finished / merged / MLS: 001 7.68/0.00/0.28, 002 26.01/0.00/0.02, 003 22.90/0.00/0.42, 004 12.85/0.00/0.14, 005 14.67/0.00/0.22, 006 11.63/0.00/no twin, 007 11.82/0.00/0.69, 008 18.94/0.00/0.00, 009 16.74/0.00/2.54, 010 9.32/0.00/0.09, 011 12.56/0.00/0.17, 012 9.35/0.00/1.61. Exteriors are left out because real sky trips this measure.
   - Step size: on 012 a* moves -1.7 to -14.9 within about 12 pixels at the jamb stripe (x about 5410-5422). Criterion 14's limit for a correction step is 2. This line coincides with a real edge in the scene, but the color on one side is the finish's.
   - Introduced in this round: balance on the merged JPEGs of 002, 003, 005, 008, 012 gives 12.74% to 22.76% cyan with this commit and 0.00% to 0.02% with bb5df2b.
   - Cause, from code plus measurement: the white balance multiplies blue up to 4.62 times (008) and red down to 0.57. Warm near-clipped pixels cannot be balanced by that, and the shoulder in `balance_exposure` (`listing_partner/finish.py`, lines 165-176) scales the unclipped result down, keeping its tint instead of letting it clip to white. Fully blown pixels in the 008 merge come out mean RGB 127, 220, 255. I did not isolate how much is the vote's strength and how much the shoulder.
   - Why the checks miss it: the ramp paint never clips, criterion 11 uses frame averages, and the floor measure needs R above G.
   - To pass: bright and blown surfaces read neutral or their true color at full resolution, with the color steps above gone, plus a test that feeds a warm near-clipped and a blown patch through the finish and fails on today's code. I tested no fix. If the fix cannot keep the wording "no brightness-dependent color change of any kind", that is a contract question for the navigator, not a builder defect.

2. **The check does not pass on a fresh clone, which the final round requires and the report implies is done.**
   - In a scratch clone with pytest run directly: 7 failures, all in `tests/test_geometry.py`, because the helper at line 49 asserts that gitignored `output/unit-a/merged/*.jpg` exists: fit-strength, correct-distortion, verticals (interior and laundry), line-measure, wooded-lot, vertical-roundtrip.
   - To pass: fixtures, or skips that print their reason.
   - Contract note: `./scripts/check` itself also fails on any clone, by design, because the private banned list and installed hooks are absent. A contract line says the list must fail loudly when missing. The navigator should say what a fresh clone is expected to do about those two, and the builder should not guess.

## Decision for Erik (not a builder defect)

Criterion 11 says every shot; 013 misses by 2.07 units of b*. The contract's accepted-limits list does not name it, while the report lists it under "accepted by Erik". You were told it was measured and reported, so I count it as holding. Please confirm you accept it. The same applies to the floor FAILs on 001, 006 and 010.

## Known limits

Contract-accepted:
- No deghost: 016 reads 0.2970 against a 0.25 limit. Stair-stepped leaf echoes with pink and cyan edges are plainly visible at native size.
- Window views stay as merged.
- Masks are not glass-only.
- Lit-wall noise is not measured.

Found or reproduced here:
- 013 look fails; floor FAILs 001 8.0%, 006 13.8%, 010 22.1% (from the manifest, replay matches). The report calls these accepted, but the contract list does not.
- Ramp test uses band means and drops the top and bottom 10% of rows. Per row, a* and b* span 2 to 3, mostly 8-bit rounding. In a mixed-scene version with denoise, near-white paint drifts b* 3.23 (over 2), the same family as finding 1.
- Verticals not measured on 005 and 016. 001, 009, 012 ran with distortion strength 0. Vignetting skipped on 17 of 17. All stated on the page or manifest.
- Single-pixel colored specks remain on walls (002, 017). 017 noise stays high: 11.73 to 6.72.
- Edge ratio 0.912 to 1.017, noise down on 17 of 17, medians 2.83 to 1.44: reproduced by replay, not by separate math.
- Near-white window 65.98% to 63.39%: reproduced by replay. Most of the windows are near-white either way.
- Replay is not byte-identical from run to run. Cause not established.
- The check scans no commit messages or branch names; the hooks cover those at commit time.
- Unverified report figures: peak memory 7755-8355 MB (my run peaked at 9447 MB in a different session), and "2 earlier unit-1 calls under 1" (the ledger's ratio field covers only the 256 calls, so I saw 0 under 1 there; the figure is on the page).
- Failing-first of `test_process_set_scales_masks_width_first` and the report's account of the failed fresh sets were not reproduced.

## What I viewed

- Overviews of all 17 finished photos at 510 px wide.
- 33 native-resolution crops of 1400 x 1000: 001 (3), 002 (2), 003 (2), 004 (1), 005 (1), 006 (2), 007 (2), 008 (3), 009 (2), 010 (2), 011 (2), 012 (2), 013 (1), 014 (1), 015 (1), 016 (2), 017 (2).
- Downscaled finished / merged / MLS side by side for 008 and 012.
- Each crop is about 6% of a frame. No photo was viewed edge to edge. The 013, 014, 015 crops showed no finish patch, but each is one crop only. The 016 and 017 crops show the ghosting and a pale sky.
- The review page was not opened in a browser. I read its HTML: 89 image references, 0 missing, 22 rejected-mask thumbs. Mask files: 39 (17 confirmed, 22 rejected), each rejection with a reason.
