# Contract 02: Window pulls and exposure balance

Branch: `unit-02-window-pulls`, from `main` after unit 1 has shipped.
Target: Tue Oct 27, 2026
Meta budget for this unit: **$2.00**, through the capped client only.

Read PRODUCT.md and AGENTS.md first.

## Why

Erik's goal: a photographer drops raw files in a folder and gets listing photos back with Lightroom gone from the workflow. Today he finishes every merged photo by hand in Lightroom: he turns on HDR editing with Visualize HDR (which lowers contrast, opens the view out the windows and lifts the shadows), adjusts sliders, draws window masks plus linear, radial and luminance masks, sets white balance, and denoises last, because HDR processing and lifted shadows bring up noise. This unit does that finishing automatically, and it is the step that turns a merge into a photo he would publish.

## Inputs

- Unit 1's merged photos in `output/unit-a/merged/` and its set manifest (which NEFs belong to each set).
- The NEF brackets in `inputs/unit-a/raw/`.
- Erik's 16 finished MLS photos in `inputs/unit-a/mls/` and the 17 Lightroom merges in `inputs/unit-a/lightroom/`, as benchmarks only.

## Build

### First commit: lower the spend cap to $40

Erik decided on Oct 26 to lower the product's hard spend cap from $100 to $40, because Muse Code's building draws on the same $150 of free credits. Change the constant to $40.00, keep the $1 headroom (calls refused once the worst case would pass $39.00), update every test and the review page footer to match, and update AGENTS.md's spend-cap section to say $40. Nothing (environment, flag, config) can raise it. This is the first commit of the unit, and the check must pass on it before any other work.

### First commit, also: reservations that really cover the bill

In unit 1's last live call the reservation was $0.000077 and the real bill was $0.000082, so the "worst case" reservation came in under the actual cost. The likely cause is tokens Meta bills that the output limit does not cap (reasoning or hidden tokens). Read Meta's pricing and response docs for what is billed, size every reservation from that, and add a safety multiplier until measured calls show the reservation always covers the bill. Record each call's reservation-to-bill ratio in the ledger and report the worst ratio at the end of the unit. The $1 headroom stays as a second layer.

### First commit, also: banned strings moved out of the repo

The banned-strings list and the test-set paths now live outside the repo, in `../.listing-partner-private/`. The git hooks already read from there. Change `./scripts/check` to read `../.listing-partner-private/banned-strings.txt` and fail loudly if it is missing or empty. Never print the file's contents, in the check's output or anywhere else: on a match, report the file and line number and the list entry's number, never the string. Add a test for that.

### Second commit: read Muse Spark's real reply

Unit 1's second live call settled correctly in the ledger, but the client could not read the reply text: Meta's response had no "output" or "text" keys where the parser looked. Before any Muse Spark call in this unit, read Meta's response reference (dev.meta.ai/docs/api-reference) for the real reply shape, teach the parser that shape, and add a test built from a saved real response with any ids and request details stripped. If the shape still cannot be confirmed from the docs, make one minimal live call (16 output tokens), save its response shape with ids removed, and build the parser from that. The ledger must stay correct whether or not the reply text can be read.

### A0. Lens and geometry, first

- Lens profile correction: distortion, vignetting and chromatic aberration, from open lens profile data for the camera and lens in each file's metadata (the D5500 and its lens for unit-a). If no profile matches, skip the step for that photo and say so on the review page.
- Vertical and perspective correction: walls and door frames that should be vertical come out vertical, the most visible fix in real estate photography. Crop only as much as the correction needs.
- Ghosting check: measure ghosting from movement between brackets (ceiling fans, trees, shadows). Deghost in the merge only if unit-a shows it. Report the measurement either way.

### A1. Grouping for longer brackets

Unit 1 starts a new set after a gap of more than 8 seconds between capture times. With longer brackets (7 to 9 frames, the brightest at several seconds of exposure), the gap between one frame's start and the next can pass 8 seconds inside a single set. Measure the gap from the end of each exposure (capture time plus exposure time) instead, and add a test with a synthetic 9-frame set whose brightest frames run 2, 4 and 8 seconds. Re-run unit-a and confirm it still groups into the same 17 sets.

### A2. Choosing which frames to merge

Erik often re-merges a set with fewer frames, for example dropping the darkest frame when it only darkens the room without adding useful window detail. Do the same automatically: for each set, try the full set and sensible subsets (drop the darkest, drop the brightest, drop both), score each merge on the measured checks (window highlights held, shadow detail and noise, overall brightness against the shared look target), never against the shot's own MLS photo (amended Oct 30 to agree with criterion 11), keep the best, and record which frames were used and why. The window pull still uses the darkest frame that holds the view, even when that frame is left out of the room merge.

### A. Find the windows

- SAM 3.1 segments every window in each merged photo through the capped client, using a text prompt for windows (and glass doors with an outdoor view). Masks are saved as PNGs in `output/unit-a/windows/masks/`.
- Muse Spark checks each candidate with crop and zoom tools (it asks for a crop of a region and gets that region back at full detail) and rejects anything that is not a view to the outdoors: mirrors, screens, framed pictures, light fixtures, cabinet glass. Each rejection is listed on the review page with its reason.
- The mask covers glass only. Window frames, sills and trim stay from the merge.
- Every crop and zoom round goes through the capped client and counts toward the budget.

### Final round: simplify the color and ship (Erik's decision, Oct 31, after the fifth review)

The tone-dependent color steps (blue cap, daylight-spill guard and any other step whose color change depends on brightness or position) caused pink floors, color bands on walls and ceilings, and patches in window views. Erik's decision: replace them with the simplest honest finish, then ship unit 2.

- Per photo: one global exposure gain and one global white balance (one multiplier per channel for the whole photo, chosen from neutral surfaces). No regional, positional or brightness-dependent color change of any kind.
- One shared tone curve applied to luminance only, so hue and saturation do not change with brightness. Lens, verticals, edge trim and denoise stay as they are.
- The shared look may be refitted once in this round on the same 16 photos. The new constants are pinned by a test, the report says plainly that the look changed in this round, and unit 5 still measures it unchanged on the held-out home set.
- Required proof: a test feeds one paint color under a smooth brightness ramp through the finish and its a* and b* stay within 2 across the ramp (observed failing on the old code first). Criterion 11 is measured again and reported per photo.
- Also fix: the check passes on a fresh clone without the gitignored raw photos (fixtures or explicit skips that print their reason), the window near-white line uses one scale on both sides or is removed, the stale comments about window pulls are corrected, and rejected window candidates get their masks saved and shown.
- Known limits, accepted by Erik for this unit and listed in the report and later the README: no deghost step (016 reads above the ghosting limit and is flagged), window views stay as merged, masks are not glass-only, lit-wall noise is not measured. These are not ship blockers.
- Ship rule for the next review: SHIP if the hackathon rules, hygiene, cap, honesty rules, the ramp test, criterion 11 and the check all hold, and the finished photos at full resolution show no box, seam, band or patch introduced by the finish. Anything else the reviewer finds goes to Known limits for Erik to see, not another round.

### Final round, part two (navigator clarification, Oct 31, after the sixth review)

The global white balance pushed blue up as far as 4.6 times, so warm bright and blown surfaces came out cyan or blue (7.7% to 26% of each interior frame, against 0% in the unit 1 merges). This part keeps Erik's "simplify and ship" decision and closes the gap:

- Cap the white balance: each channel multiplier stays between 0.80 and 1.25, relative to green.
- Highlights roll to neutral: pixels approaching clipping blend smoothly toward neutral white, the way a camera does. This single smooth roll-off is the one brightness-dependent step allowed. It must create no band, edge or patch, and nothing else may depend on brightness.
- A bright-surface check runs per interior photo: the share of bright pixels reading cyan or blue (mean above 170, B at least G, G minus R at least 15, B minus R at least 30) must stay at or below 1% of the frame, or at or below the MLS twin's share, whichever is higher. A test feeds a warm near-clipped patch and a blown patch through the finish and fails on commit 6738bd3.
- Automatic fallback, so this converges: any photo that still fails the bright-surface check ships with white balance off (exposure gain and the luminance curve only), and the page says "white balance off: <reason>". No further round is needed for those photos.
- Fresh clone: pytest passes on a clone without the gitignored photos and outputs, because tests that need them skip and print their reason. `./scripts/check` failing loudly on a clone without the private banned list is by design, and the README will say so.
- Erik accepted, under his ship rule: 013's look miss and the floor FAILs on 001, 006 and 010 are known limits, along with the limits listed above.

### Window pulls are off for this unit (Erik's decision, Oct 30, after the fourth review)

All 14 pulls failed at full resolution in the fourth review, and the builder's report had called them clean. Erik's decision: window pulls are turned off for unit 2. Remove the pull and its gate from the finish path. Every window keeps the balanced merge's pixels. Section A still runs (SAM finds the windows, Muse Spark confirms or rejects each one with its reason), and the page shows the found, confirmed and rejected windows with their masks, labeled "found, not edited". Section B below and criteria 4, 5, 6 and the pull parts of 13 are paused, not deleted. A later unit may return to the pull only if Erik says so. The builder never states a visual verdict ("clean", "natural", "no halo") in the report or status. It reports measured numbers, and the reviewer and Erik judge how photos look.

### B. Window pull

- Inside each confirmed window mask, the view comes from the same set's real bracket frames: the frame or blend of frames whose window region is best exposed (fewest clipped highlights, detail in the view), aligned to the merge.
- Match the pulled view's brightness and color to read naturally against the room, then blend with a feathered edge sized to the image. No halos, no hard edges, no dark outline on the frame.
- Real pixels only. No generative model touches a window. Outside the window masks this step changes nothing, measured.
- Ship gate (Erik's decision, Oct 30, after the third review). A pull is kept only when it passes on that window: one continuous, matched, feathered, real view; frames, mullions, blinds and sills keep their merged color; no halo, hard edge or dark outline; no false color; near-white inside the mask measured honestly (any channel, 250 of 255, on glass, with no shoulder or clamp hiding it) is lower than the merge's. When a pull fails any of these, that window keeps the merge's pixels untouched and the review page shows "window kept from merge" with the plain reason. A damaged or fake-looking window never ships. The gate is automatic, so the unit 7 agent can use it with no person in the loop.

### C. Exposure balance

The automatic version of Erik's linear, radial and luminance masks:
- Even out exposure region by region: dark corners and ceilings lifted, hot floors and walls near windows brought down, dim hallways opened up. SAM 3.1 region masks (walls, ceiling, floor) may guide it.
- The target look is what Erik gets from Lightroom's Visualize HDR plus his sliders: lower overall contrast, shadows lifted, highlights held, windows readable. Output stays a standard JPEG, the same format Erik uploads to the MLS today. His MLS photos are the reference for how far to take it.
- Keep it natural. No crushed shadows, no gray haze, no visible region edges, no change inside the pulled windows.
- (Added Oct 30, fourth review.) No spatial box or hard-edged zone in any color or exposure correction. Any regional correction blends with no visible boundary, and a test measures the color step across its edge (it must fail on a hard edge, observed failing first). Floors are measured across the whole visible floor, not a box, and read their real color with no lavender or purple cast.
- Neutral white balance, so walls and ceilings read as their real color under mixed light.

### D. Denoise, last

- Denoise every finished photo as the final step, because the merge, the shadow lift and the exposure balance raise noise, mostly in shadows and flat walls.
- Non-generative only: the denoiser may smooth noise but must not invent texture or detail. No generative model.
- Measure it: noise in flat shadow and wall patches drops, and edge detail in textured areas (trim, flooring grain, cabinet edges) is not smeared, measured as edge strength before and after.

### E. Output and review page

- Finished photos in `output/unit-a/finished/` (`001.jpg` and so on, full resolution, sRGB, no GPS or camera serial).
- `output/unit-a/review-finish.html`, one row per shot: our merge from unit 1, our finished photo, the window mask over the merge, and Erik's MLS photo of the same shot.
- Top line: photos processed, median shadow-noise before and after denoise, windows found, windows confirmed, candidates rejected, photos with at least one window, clipped highlights inside confirmed windows before and after (as a percentage of window pixels), run time, and Meta spend. All measured from this run.
- Footer: Meta spend to date and the $40 cap, read from the ledger (or "unknown" if the ledger cannot be read).

## For the unit 7 agent

Every measured check in this unit (clipped highlights in windows, outside-mask pixels unchanged, noise and edge strength, line straightness) is also a pass or fail function with its threshold, so the listing agent can call it, retry a step a different way, and record why.

## Acceptance criteria

1. `./scripts/check` passes on the final commit.
2. Every merged photo has a finished photo, or a plain-words reason it failed. Processed plus failed equals 17.
3. Every window mask and every rejection is saved and shown. Rejections carry Muse Spark's reason.
4. (Amended Oct 30, ship gate.) Applies to windows whose pull was kept. Windows kept from the merge are listed with their reason and their numbers are unchanged by step B. Near-white pixels inside confirmed windows (measured on the final output with no clamp or cap applied, threshold 250 of 255 on any channel) drop from before to after on every photo whose window had near-white pixels before. Photos with none before (unit-a sets 013, 014 and 017 measured by the reviewer) must not gain any. Report before and after per photo. A result produced by clamping or capping values does not count as a measurement.
5. Outside the window masks, step B changes no pixels, measured on every photo.
6. A test with a synthetic room and window proves the pull uses real bracket pixels inside the mask, blends with no hard edge, and leaves outside pixels unchanged.
7. No output carries GPS or camera serial metadata. No banned string appears in any tracked file, file name, commit message or branch name.
8. Meta spend for this unit is under $2.00, every call through the capped client.
9. Denoise lowers measured noise in flat shadow and wall patches on every photo, and edge strength in textured areas stays within 10% of before. Report both per photo.
10. Lens correction: line straightness is measured on the same frame before and after lens correction, per photo. It improves on every photo with a lens profile match, or the page names the photo and the plain reason it did not (amended Oct 30). Verticals: near-vertical lines are measured as the length-weighted median angle of near-vertical segments, before and after, and end within 0.5 degrees of vertical. Rotation is required. Perspective correction is not required for this unit.
11. The finished look matches Erik's: on every shot with an MLS photo, the finished photo's median brightness is within 15% of the MLS photo's, and its average color (mean a* and b* in Lab) is within 5 units of the MLS photo's. Report per photo. The shared look settings were fitted on these same 16 photos, and the report must say so plainly. They are frozen from this round on, and unit 5 measures the same settings, unchanged, on Erik's home set as the honest held-out test (amended Oct 30). Per-photo automatic exposure and white balance are expected, but processing a photo must never read its MLS twin. The MLS photos are used only to tune the shared settings once and to measure the result, because a new listing has no MLS photo to copy.
12. A check that finds nothing to measure (no lines, no window pixels, no flat patches) reports "not measured", never pass. Every skipped step (vignetting, verticals, lens profile) is shown on the review page with its reason.
13. (Paused Oct 30 with the pulls. Replaced by 14.) (Added Oct 30.) The review page counts windows pulled and windows kept from the merge, with the reason for each kept one. At least one window photo in unit-a ships with a kept pull, or the report says plainly that none passed. No pulled window shows washed-out, patchy, falsely colored or hard-edged view, darkened frames, or a purple or magenta cast on the nearby floor or wall (measured across the floor area near each window, per photo).

14. (Added Oct 30, fourth review.) No orange, purple or other color box or seam on any finished photo, measured as the a* and b* step across every regional correction edge (2 or less) and seen on the page. The ghosting check normalizes exposure before comparing frames and reports a real number and the deghost decision. The page reports the lowest reservation-to-bill ratio for the unit as the worst. Rows along the image edges that read darker or tinted are cropped. Every number in the report comes from the final run.
## Observable criterion (Erik, two minutes, no code)

Finder, Shift+Cmd+G, `~/projects/listing-partner/output/unit-a`, then open `review-finish.html`. Pick three rooms with windows. In our finished photo, the windows may be bright, but they show no streaks, patches or pasted marks (pulls are off this unit), there is no colored box or seam on any floor or wall, the window frames are clean with no halo, the room reads evenly bright with no dark corners, and the walls look their true color, and the shadows and walls are clean, not grainy. Next to it, your MLS photo of the same shot lets you judge whether ours could go out without opening Lightroom.

## Out of scope

Crop to listing aspect ratio, output sharpening, export sizing and naming (unit 7), curation, room labels, tidying, writing, AppFolio, and any generative edit.
