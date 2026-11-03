# Build plan: Oct 26 to Nov 4, 2026

Submission due **Wed Nov 4, 9:00 PM ET**: public repo, three minute demo video, working product.

The goal Erik set on Oct 26: a photographer drops one unit's raw files into a folder and gets back a listing ready to post, with Lightroom gone from the workflow entirely. Core pipeline first. Each unit ends with the reviewer's SHIP and Erik's look at the running thing before it merges. The navigator writes each unit's contract before the unit starts. Test unit for every unit: `unit-a` (paths in `local/test-sets.md`).

Every unit's measurable checks are built as pass or fail functions the unit 7 agent can call, not only as numbers on a review page.

How every unit runs in Muse Code: one kickoff that sets the unit's `/goal`, then `/plan` and `/grill` before any code, with the plan written to `.navigator/plan.md`. Muse Code then stops. The navigator checks the plan against the contract, Erik replies `approved` (or sends the navigator's corrections), Muse Code builds toward the goal, and the reviewer runs at the end.

Muse Spark image tools: wherever Muse Spark judges photos (curation, clutter detection, the maintenance pass, the honesty audit), it gets crop and zoom tools so it can inspect parts of a photo up close instead of judging the whole frame at once. Meta reports this lifts its image results by more than 10 points. Every tool call goes through the capped client and counts toward the $40 cap.

## Replan, Thu Oct 29 (two build days lost, Oct 27 and 28)

Five build days remain for six units, so units are merged and the stretch goal is dropped:
- Thu Oct 29: unit 2, window pulls and exposure balance (as written below).
- Fri Oct 30: unit 3, curation, unit facts, coverage check, writing, fair housing check, and the Muse Spark Open comparison (old units 3 and 4).
- Sat Oct 31: unit 4, maintenance pass, then tidy with sky replacement and the honesty audit (old units 5 and 6).
- Sun Nov 1: unit 5, the listing agent, drop folder, export, README, public sample from Erik's home shoot, private GitHub repo (old unit 7).
- Mon Nov 2: buffer. Then raw versus JPEG and the cleanup benchmark only if everything above has shipped. Brush touch-up is dropped until after Nov 4.
- Tue Nov 3 demo, Wed Nov 4 submission, unchanged.
Erik's home shoot (public sample and baseline timing) must happen by Sun Nov 1.

## Units (original detail; dates above win)

**Mon Oct 26. Setup.** Done by the navigator. PRODUCT.md, AGENTS.md, the reviewer, .gitignore, git-hook fence, this plan, the demo outline, contract 01. No Meta calls.

**Mon Oct 26 (a day early). Unit 1: HDR merge and the spend-capped Meta client.**
- unit-a's 86 NEFs become one merged photo per bracket set.
- The single capped Meta function, with the hard cap proven by tests ($100 in unit 1, $40 from unit 2) and one tiny live call.
- The check command and the public-hygiene scan.
- Erik sees: a review page with each merge beside the darkest and brightest bracket, Lightroom's merge of the same set, and his finished MLS photo of the same shot.

**Tue Oct 27. Unit 2: Window pulls and exposure balance, Lightroom out of the workflow.** Contract 02.
- Lens profile correction (distortion, vignetting, chromatic aberration), vertical and perspective correction, and a measured ghosting check (deghost only if unit-a shows ghosting).
- SAM 3.1 finds every window in each merged photo. Muse Spark, using crop and zoom, confirms each one is a real window (not a mirror, screen, picture or light fixture).
- Window pull: inside a feathered window mask, the view comes from the real darker brackets of the same set, matched in exposure and color. Real pixels only, never generated, so the honesty rule holds. Window frames stay from the merge.
- Exposure balance, the automatic version of Erik's linear, radial and luminance masks: dark corners, hot floors near windows and dim hallways evened out region by region, keeping a natural look.
- Neutral white balance, so walls read as their real color. The target look matches Erik's Lightroom Visualize HDR plus sliders: lower contrast, lifted shadows, windows readable, saved as a standard JPEG.
- Denoise last, non-generative, because the merge and the shadow lift raise noise. Measured: less noise in flat areas, edges not smeared.
- Benchmark: Erik's 16 finished MLS photos carry his hand masking. Every automatic result sits beside his on the review page.
- Erik sees: a page per shot with our merge, our finished photo, the window mask and his MLS photo side by side.

**Wed Oct 28. Unit 3: Curate with Muse Spark.**
- Drop weak and duplicate shots, label each room, put the best in walkthrough order. Muse Spark uses crop and zoom to check sharpness, duplicates and room cues.
- Benchmark: Erik published 16 of unit-a's 17 shots in his own order. Report which shots were kept and how the order compares.
- Erik sees: an ordered, labeled gallery page, with dropped shots listed and the reason for each.

**Thu Oct 29. Unit 4: Unit facts, coverage check, and writing.**
- Public unit facts from the existing read-only AppFolio connector (labeled as an existing tool), filtered to an allowlist: beds, baths, square feet, rent, amenities, public address. Facts stay in gitignored `facts/`.
- **Coverage check.** Muse Spark compares the labeled rooms to the room list the facts imply (every bedroom and bathroom, kitchen, living area, front exterior) and flags any missing room or missing hero shot, so the gap is caught before the listing goes up, not after.
- The product reads unit facts from a simple facts file. The AppFolio connector is an optional, pre-existing source that fills that file, labeled as such. The public sample uses a hand-written facts file.
- Muse Spark writes the listing description and social captions from the facts and the curated photos.
- Muse Spark Open, Meta's open-weight model, served through Baseten (partner inference, $100 of Baseten credits, key in the Keychain as BASETEN_API_KEY, model id meta-models/muse-spark-open-1026), runs the same text jobs (description, captions, coverage check) through its own capped client with its own ledger. Both models are measured on the same tasks and the better one is kept per task, with the comparison shown. This makes the project eligible for the Best Build on Meta Open Weight Models bonus. Unit 5's maintenance pass gets the same comparison.
- Every model output from both providers is logged with its task, model, cost and score, so the comparison is a record, not a claim.
- Cost per listing: every run reports what one listing cost, split by model and provider. It goes in the README and the demo.
- Second opinion on safety calls: on the fair housing check, the maintenance pass and the cleanup self-check, Muse Spark and Muse Spark Open judge independently. When they disagree, the item is flagged for a person instead of passing.
- Fair housing check: every description and caption is checked against current HUD advertising guidance (the navigator pulls the guidance into the contract). Wording stays on the unit and its features, never on who should live there, and anything flagged is rewritten. A person still approves before anything is posted.
- Erik sees: the description and captions on the page, every fact matching AppFolio, and the coverage check's verdict.

**Fri Oct 30. Unit 5: Maintenance pass.**
- Muse Spark, using crop and zoom, and SAM 3.1 flag damage, stains and broken items into a separate maintenance list, with a crop of each one.
- Every flagged area becomes a protected zone. Nothing in a protected zone is ever cleaned out of a listing photo.
- The list is a file on the package page. It is never sent anywhere.
- Erik sees: the maintenance list with crops, each one he can check against the photo.

**Sat Oct 31. Unit 6: Tidy with an honesty audit.**
- SAM 3.1 finds only allowlisted clutter (trash bins, boxes, cords, packing plastic) and saves each mask. Muse Spark, using crop and zoom, confirms each candidate is clutter before it is masked.
- Muse Image edits, then only the pixels inside the mask are kept. Outside the mask the tidied photo is pixel-for-pixel the input photo, measured on every photo.
- Sky on exterior shots: SAM 3.1 masks the sky, Muse Image replaces it with a clear sky inside that mask only, labeled "sky replaced" on the page and in the export. Same pixel proof outside the mask.
- A mask that touches a protected zone from unit 5, or covers walls, fixtures, flooring or damage, is refused.
- The package includes each mask as proof that nothing else changed.
- Self-check: after cleanup, Muse Spark compares each tidied photo to its input and confirms only the masked clutter changed, and that nothing removed was damage, a fixture or part of the room. Any disagreement blocks that photo from the package. The pixel measurement stays the binding check.
- MLS photo rules: before this contract is written, the navigator checks Realcomp's current rules on altered photos. Tidied photos can carry an optional "digitally decluttered" note.
- Benchmark: Erik's earlier Gemini cleanups, if `exports/gemini` has files by then (it was empty on Oct 26).
- Erik sees: a before and after page for every tidied photo, with the mask beside it and the measured count of changed pixels outside the mask (must be 0).

**Sun Nov 1. Unit 7: The listing agent. Drop a folder, it works until the listing is done, plus the README.**
- An agent, not a script: it has a written definition of done for a listing (every photo finished, windows pulled, coverage complete or a reshoot list written, description and captions passing the fair housing check, maintenance list written, honesty audit clean, cost recorded). It runs the steps, checks its own results against that definition, and retries a failed step a different way (another bracket for a window, a rewrite for a flagged caption), up to a set number of attempts per step.
- It knows when to stop. A per-listing budget, a maximum number of retries, and a plain handoff for what it cannot fix: the reshoot list, the maintenance list, and any item the two models disagreed on. It never meets a check by inventing content.
- It can be stopped and restarted without losing work, picking up from its run record.
- A progress page shows the agent working: each step, each check, each retry and why, and the cost so far. This is what the demo's live run shows.
- Master for further editing: a 16-bit TIFF of every finished photo, before export sharpening and sizing, so a photographer keeps the latitude to pull shadows and highlights later.
- Export: crop to the listing aspect ratio, output sharpening, sRGB at Erik's MLS size (2096 by 1397 for unit-a), consistent file names. Together with unit 2, this is what lets the README say Lightroom is out of the workflow. The claim lists exactly the steps that shipped, nothing more.
- A drop folder: Erik drops one unit's raw files into a watched folder and the whole pipeline runs with no Terminal, ending in one package page to open. The run measures and shows time from raw files to ready.
- README with setup, how each Meta model is used, and the existing-tool label on the AppFolio connector. The README explains the product in Meta's agent framing:
  - purpose: PRODUCT.md, one unit's raw files to a listing ready to post, with no Lightroom
  - signals: the brackets, their capture data, and the unit facts
  - memory: the per-unit run record (what was kept, dropped, flagged and why); say plainly if this stays thin
  - connectors: the Meta Model API, and the existing read-only AppFolio connector
  - evaluations: the check command, the reviewer, the Lightroom and MLS benchmarks, the coverage check, the honesty audit
  - controls: the $40 cap, the model allowlist, protected zones, the git-hook fence
  - records: the spend ledger, saved masks, the maintenance list, the run log
  Every line has to be true of what shipped.
- **Held-out look test.** Unit 2's look settings were fitted on unit-a. Unit 5 runs them unchanged on Erik's home set and reports the same brightness and color comparison, as the honest test of whether the look generalizes.
- **Baseline, measured.** Erik finishes his home set his usual way (Lightroom, plus Gemini where he would normally use it) and records start and stop times, plus the number of windows he masked by hand. The agent runs on the same raw files. The README reports minutes per photo for each, and how each scales with the number of windows.
- **Working product for judges.** A small public sample set Erik owns outright (3 or 4 bracketed interior sets from his own home, nothing personal in frame, no exterior), attached to a GitHub Release, not committed. One command runs it with the judge's own META_API_KEY. The tool also generates a static before and after gallery, published on GitHub Pages, so judges see real output without running anything. unit-a stays private: benchmarks and testing only, never in the public repo, video, README or X post.
- Builder spend: the navigator records the Meta Billing page's free-credit balance at the end of every unit, and stops the build if Muse Code is on pace to use more than $100 of the $150.
- **Raw versus JPEG, measured** (moves to Nov 2 if unit 7 runs long). Every unit-a NEF carries the camera's own full-size JPEG (6000 by 4000, measured Oct 26). Run the same pipeline twice on the same 17 sets: once from the NEFs, once from JPEG brackets (the embedded camera JPEGs, plus a camera-style JPEG rendered from each NEF at high quality, since the embedded ones are more compressed than a real in-camera JPEG). Measure per photo: clipped highlights in windows, noise in flat shadows and walls, banding in smooth gradients, and detail in textured areas. Show both results side by side on one page, and state in the README which JPEG source each number came from. If Erik shoots a real RAW plus JPEG set before Oct 31, it replaces the simulation as the evidence.
- License, Erik's decision before the repo goes public: source-available (PolyForm Noncommercial or Business Source License) if the organizers confirm it meets the "must be public" rule, otherwise permissive. The public repo stays the hackathon snapshot, public at least through Nov 16. Any work after Nov 4 continues in a separate private repo.
- Full-history hygiene scan of the repo.
- GitHub, with Erik's yes: Claude Code creates `ehill-amera/listing-partner` as a **private** repo, adds it as the remote and pushes `main`. This is the first copy off the Mac. It uses `ehill-amera` through `gh` for this repo only and never changes the active `gh` account (bokanigroup-admin), so Bokani repos are untouched. Steps in `docs/github.md`.
- Erik sees: a raw folder dropped in, and the finished package appearing with no help.

**Mon Nov 2. Buffer, then the stretch goal last.**
- First, finish anything that slipped from units 1 to 7, then raw versus JPEG if it moved here.
- **Cleanup benchmark, measured.** The same 5 photos from Erik's home set, each with one piece of real clutter, go through several general image editors on fal.ai (the current Gemini, OpenAI and other leading editors available there, checked on the day) and through Listing Partner's masked cleanup. Same plain prompt for every model ("remove the [item], change nothing else"), 3 runs each, because results vary run to run. Measured for every output: whether the item is gone, how many pixels changed outside the item's mask, structural similarity outside the mask, whether lines and fixtures moved, whether size and framing were kept, cost and time. Every output is published, best and worst runs alike, whatever the result. Only Erik's own home photos are sent, never unit-a. Spend on fal.ai needs Erik's yes first (estimate a few dollars, checked against fal's prices on the day).
- Only if units 1 to 7 have all shipped by end of day Nov 1: Unit 8, brush touch-up. On the package page Erik paints over anything the automatic tidy missed, and Muse Image removes it inside his brush stroke only, with the same honesty audit and the stroke saved as a record. This replaces Gemini and Lightroom's Remove tool. If it is not shippable by end of Nov 2, it is dropped. It does not move into Nov 3.
- The vertical walkthrough tour moved to after Nov 4 (Oct 26), so the stretch slot goes to the part of Erik's workflow that still needs another app.
- Phone test (ProCamera raw bracketing, verified on ProCamera's own blog) waits until after Nov 4. If Erik shoots a vacancy before then, he captures the phone files and parks them.

**Tue Nov 3. Demo video.** Follow `docs/demo-outline.md`.
- Erik records and edits. The demo shows only hackathon work, with the AppFolio connector labeled as existing.
- Code freeze at end of day, except fixes the demo exposes.

**Wed Nov 4. Submission.**
- Final reviewer pass on `main`. Full-history hygiene scan clean.
- Erik's yes to push the final `main` and make `ehill-amera/listing-partner` public, then submit: repo link, video, working product.
- Target submitted by 3:00 PM ET, six hours ahead of the 9:00 PM ET deadline.

## Not doing

- Bracket-locked cleanup across exposures (cleaning each bracket before the merge). Too much for the time.
- Muse Image extending a photo's edges to make a vertical version. It invents room content, which breaks the honesty rule. Vertical versions are crops only.

## If a unit slips

Units 1 to 6 are the product. Unit 7 is what makes it demoable. If a day is lost, Nov 2's buffer absorbs it and the stretch goal is dropped. If two days are lost, unit 6 narrows to one clutter class (trash bins) before anything else gives, and unit 2's exposure balance narrows to window pulls only. The maintenance pass and the honesty audit do not get cut, because they are what make the tidy step trustworthy.
