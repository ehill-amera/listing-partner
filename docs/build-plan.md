# Build plan: Oct 26 to Nov 4, 2026

Submission due **Wed Nov 4, 9:00 PM ET**: public repo, three minute demo video, working product.

Core pipeline first. Each unit ends with the reviewer's SHIP and Erik's look at the running thing before it merges. The navigator writes each unit's contract before the unit starts, so only contract 01 exists today. Test unit for every unit: `unit-a` (paths in `local/test-sets.md`).

How every unit runs in Muse Code: one kickoff that sets the unit's `/goal`, then `/plan` and `/grill` before any code, with the plan written to `.navigator/plan.md`. Erik approves the plan, Muse Code builds toward the goal, and the reviewer runs at the end.

Muse Spark image tools: wherever Muse Spark judges photos (curation, clutter detection, the maintenance pass, the honesty audit), it gets crop and zoom tools so it can inspect parts of a photo up close instead of judging the whole frame at once. Meta reports this lifts its image results by more than 10 points. Every tool call goes through the capped client and counts toward the $100.

## Units

**Mon Oct 26. Setup.** Done by the navigator. PRODUCT.md, AGENTS.md, the reviewer, .gitignore, git-hook fence, this plan, the demo outline, contract 01. No Meta calls.

**Tue Oct 27. Unit 1: HDR merge and the spend-capped Meta client.** Starts when Meta credits land.
- unit-a's 86 NEFs become one merged photo per bracket set.
- The single capped Meta function, with the $100 cap proven by tests and one tiny live call.
- The check command and the public-hygiene scan.
- Erik sees: a review page with each merge beside the darkest and brightest bracket, Lightroom's merge of the same set, and his finished MLS photo of the same shot.

**Wed Oct 28. Unit 2: Curate with Muse Spark.**
- Drop weak and duplicate shots, label each room, put the best in walkthrough order. Muse Spark uses crop and zoom to check sharpness, duplicates and room cues.
- Benchmark: Erik published 16 of unit-a's 17 shots in his own order. Report which shots were kept and how the order compares.
- Erik sees: an ordered, labeled gallery page, with dropped shots listed and the reason for each.

**Thu Oct 29. Unit 3: Unit facts, coverage check, and writing.**
- Public unit facts from the existing read-only AppFolio connector (labeled as an existing tool), filtered to an allowlist: beds, baths, square feet, rent, amenities, public address. Facts stay in gitignored `facts/`.
- **Coverage check.** Muse Spark compares the labeled rooms to the room list the facts imply (every bedroom and bathroom, kitchen, living area, front exterior) and flags any missing room or missing hero shot, so the gap is caught before the listing goes up, not after.
- Muse Spark writes the listing description and social captions from the facts and the curated photos.
- Erik sees: the description and captions on the page, every fact matching AppFolio, and the coverage check's verdict.

**Fri Oct 30. Unit 4: Maintenance pass.**
- Muse Spark, using crop and zoom, and SAM 3.1 flag damage, stains and broken items into a separate maintenance list, with a crop of each one.
- Every flagged area becomes a protected zone. Nothing in a protected zone is ever cleaned out of a listing photo.
- The list is a file on the package page. It is never sent anywhere.
- Erik sees: the maintenance list with crops, each one he can check against the photo.

**Sat Oct 31. Unit 5: Tidy with an honesty audit.**
- SAM 3.1 finds only allowlisted clutter (trash bins, boxes, cords, hoses, packing plastic) and saves each mask. Muse Spark, using crop and zoom, confirms each candidate is clutter before it is masked.
- Muse Image edits, then only the pixels inside the mask are kept. Outside the mask the tidied photo is pixel-for-pixel the merged photo, measured on every photo.
- A mask that touches a protected zone from unit 4, or covers walls, fixtures, flooring or damage, is refused.
- The package includes each mask as proof that nothing else changed.
- Self-check: after cleanup, Muse Spark compares each tidied photo to the merged original and confirms only the masked clutter changed, and that nothing removed was damage, a fixture or part of the room. Any disagreement blocks that photo from the package. The pixel measurement stays the binding check.
- Benchmark: Erik's earlier Gemini cleanups, if `exports/gemini` has files by then (it was empty on Oct 26).
- Erik sees: a before and after page for every tidied photo, with the mask beside it and the measured count of changed pixels outside the mask (must be 0).

**Sun Nov 1. Unit 6: One command, end to end, and the README.**
- One bracket folder in, one listing package out, one page to open. The run measures and shows time from raw files to ready.
- README with setup, how each Meta model is used, and the existing-tool label on the AppFolio connector. The README explains the product in Meta's agent framing:
  - purpose: PRODUCT.md, one unit's brackets to a listing ready to post
  - signals: the brackets, their capture data, and the unit facts
  - memory: the per-unit run record (what was kept, dropped, flagged and why); say plainly if this stays thin
  - connectors: the Meta Model API, and the existing read-only AppFolio connector
  - evaluations: the check command, the reviewer, the Lightroom and MLS benchmarks, the coverage check, the honesty audit
  - controls: the $100 cap, the model allowlist, protected zones, the git-hook fence
  - records: the spend ledger, saved masks, the maintenance list, the run log
  Every line has to be true of what shipped.
- Full-history hygiene scan of the repo.
- GitHub, with Erik's yes: Claude Code creates `ehill-amera/listing-partner` as a **private** repo, adds it as the remote and pushes `main`. This is the first copy off the Mac. It uses `ehill-amera` through `gh` for this repo only and never changes the active `gh` account (bokanigroup-admin), so Bokani repos are untouched. Steps in `docs/github.md`.
- Erik sees: the whole unit-a run start to finish with no help.

**Mon Nov 2. Buffer, then the stretch goal last.**
- First, finish anything that slipped from units 1 to 6.
- Only if units 1 to 6 have all shipped by end of day Nov 1: Unit 7, a vertical walkthrough tour from Erik's real footage, with SAM 3.1 keeping each room framed by cropping only. If it is not shippable by end of Nov 2, it is dropped. It does not move into Nov 3.

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

Units 1 to 5 are the product. Unit 6 is what makes it demoable. If a day is lost, Nov 2's buffer absorbs it and the stretch goal is dropped. If two days are lost, unit 5 narrows to one clutter class (trash bins) before anything else gives. The maintenance pass and the honesty audit do not get cut, because they are what make the tidy step trustworthy.
