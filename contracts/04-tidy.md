# Contract 04: Honest tidy with SAM 3.1 and Muse Image, plus the damage list

Branch: `unit-04-tidy`, cut from `main` after unit 3 ships.
Builder: Claude Code (Opus 5.5). Reviewer: the fixed reviewer agent, fresh context.
Target: Tue Nov 3, 2026, morning.
Meta budget for this unit: **$5.00**, inside the $20 project cap.

Read PRODUCT.md (the honesty rule, in Erik's words) and AGENTS.md first.

## Why

The demo opens on messy versus clean. This is the most visible use of Meta's image models, and the place where the honesty rule matters most: a renter must see the property as it would look after a quick physical cleanup, never a repaired or altered property.

## Inputs

- Finished photos from unit 2 (`output/<set>/finished/`). Development and tests use unit-a. The public demo set (Erik's own home, interiors only) arrives as raw brackets later and runs through units 2 to 4 unchanged; the code must take any set name.
- Unit 3's curation results, so only kept photos are tidied.

## Build

### A. Damage list first (Muse Spark)

- Muse Spark looks at each kept photo (crop and zoom allowed, through the capped client) and lists visible damage, stains, broken or missing items, with a box and a plain-words note for each.
- Every damage box becomes a protected zone. The damage list is a file on the page. It is never sent anywhere.

### B. Find the clutter (SAM 3.1)

- SAM 3.1, through the capped client, segments carry-out clutter with a fixed list of text prompts: trash bin, cardboard box, plastic bag, packing material, loose cable or cord, hose, laundry basket, cleaning supplies, shoes, bucket, ladder, paint can, tools. Nothing else is ever a tidy target.
- Muse Spark confirms or rejects each candidate with its reason, rejecting anything that is a fixture, part of the building, furniture that conveys, or damage.
- Each confirmed mask is grown by a small fixed margin for shadows, and any mask pixel that touches a protected damage zone is removed from the mask. A candidate that overlaps damage is listed as "left in place: overlaps damage".

### C. Remove only inside the mask (Muse Image)

- Muse Image (`muse-image-1.0`, through the capped client) fills the masked area. The result is composited back so that only masked pixels come from Muse Image. Every pixel outside the final mask is copied from the finished photo, so "outside unchanged" is true by construction and measured anyway.
- No edge extension, no added objects, no sky replacement in this unit.
- If Muse Image fails or the self-check fails, the photo ships untidied, with the reason on the page.

### D. Self-check (Muse Spark)

- Muse Spark compares a crop of each tidied area before and after: the item is gone, nothing that is part of the property changed, no damage was softened. Its verdict is shown. The pixel measurement is the binding one when they disagree, and a disagreement ships the untidied photo.

### E. The page

`output/<set>/tidy.html`: for each tidied photo, a before and after slider, a button that flashes the mask for one second, the list of items removed and items left in place with reasons, the self-check verdict, and the damage list with crops. Every tidied photo carries the label "Edited: clutter removed". The untidied photo is always kept beside it.

## Acceptance criteria

1. `./scripts/check` passes on the final commit, and pytest passes on a clean export without photos.
2. Outside the final mask, the tidied photo matches the finished photo exactly, measured on every tidied photo.
3. No damage box overlaps a final mask, measured.
4. Every removed item is on the fixed clutter list and confirmed by Muse Spark with its reason. Every rejection and every "left in place" carries a reason.
5. Every tidied photo has a self-check verdict, and any disagreement with the pixel measurement ships the untidied photo.
6. Meta spend for this unit is under $5.00, from the ledger.
7. The page shows the slider, the mask flash, the lists and the "Edited: clutter removed" label for every tidied photo.
8. Measured numbers only in the report, no visual verdicts. A set with nothing to tidy reports "nothing to tidy", not a failure.

## Observable criterion (Erik, two minutes, no code)

Finder, Shift+Cmd+G, `~/projects/listing-partner/output/unit-a`, then open `tidy.html`. Drag the slider on any tidied photo: only the listed clutter disappears. Press the mask button: the flash covers only that clutter. The damage list shows anything you would want a maintenance coordinator to see, and none of it was removed.

## Out of scope

Sky replacement, brush touch-up, virtual staging, export sizing and naming, the agent and drop folder, posting anywhere.
