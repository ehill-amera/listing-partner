# Contract 03: Curate, check coverage, and write the listing (Muse Spark and Muse Spark Open)

Branch: `unit-03-curate-and-write`, cut from `main` after unit 2 ships.
Builder: Claude Code (Opus 5.5). Reviewer: the fixed reviewer agent, fresh context.
Target: Mon Nov 2, 2026.
Meta budget for this unit: **$3.00**, inside the $20 project cap. Baseten budget for this unit: **$10.00**, inside a hard Baseten cap of **$80** (the free credit is $100).

Read PRODUCT.md and AGENTS.md first. This unit merges the old units 3 and 4 of the build plan, because the schedule slipped.

## Why

Judges and renters see this part first: which photos made the cut, in what order, with what labels, and the words that sell the unit. It is also where Meta's open-weight model earns its place, by doing the same writing jobs as Muse Spark side by side, scored on the same checks.

## Inputs

- The 17 finished photos in `output/unit-a/finished/` from unit 2. Never re-run unit 2's finish in this unit.
- Unit facts in `facts/unit-a.json` (gitignored). The navigator fills it from Bokani's existing read-only AppFolio connector before the live run: beds, baths, square feet, rent, deposit if public, available date, amenities, pet policy, property type, city and state only. No street address, no unit number, no names, no tenant, owner or applicant data. If the file is missing, stop and say so.
- `facts/sample.json` (committed): a hand-written, clearly fictional sample unit with the same fields, used by tests and by anyone running the public repo. It is labeled as sample data in the file.
- The AppFolio connector existed before the hackathon. Any code or doc that mentions it says so. This unit adds no AppFolio code: the facts file is the interface.

## Build

### A. A second capped client for Baseten

- `listing_partner/baseten_client.py`: the only place that talks to Baseten. OpenAI-compatible endpoint `https://inference.baseten.co/v1`, model `meta-models/muse-spark-open-1026` only (allowlist of one), key read only from the `BASETEN_API_KEY` environment variable.
- Same safety shape as `meta_client.py`: its own append-only ledger `.spend/baseten-ledger.jsonl`, reservations at about 2x the worst case before each call, settled after, fail-closed on a corrupt or unreadable ledger, hard cap constant `BASETEN_CAP_USD = 80.0` with $1 headroom, refusal tests for every case. Prices come from Baseten's published per-token price for this model; the navigator confirms the price in the report before the live run.
- Network: `inference.baseten.co` is the only new address. Erik approves it when asked.

### B. Curate with Muse Spark (vision)

- For each finished photo, Muse Spark (through `meta_client.py`) labels the room (one of a fixed list: front exterior, rear exterior, living room, dining area, kitchen, bedroom, bathroom, laundry, hallway, stairs, basement, garage, yard, other) and rates it for listing use (sharpness, framing, duplicate of another shot). It may ask for a crop or zoom, reusing the pattern in `segment.py`, and every round goes through the capped client.
- Duplicates: when two shots show the same view, keep the better one and give the reason.
- Order: walkthrough order, front exterior first, then the path a renter would walk, then rear exterior and yard.
- Benchmark: Erik published 16 of unit-a's 17 shots in his own order (the MLS photo numbers). Report which shots were kept or dropped against his, and how far the order differs (number of shots in a different position, and a rank correlation).

### C. Coverage check

- From the facts, build the list of rooms the listing must show: each bedroom and bathroom the facts count, kitchen, a living area, front exterior.
- Compare to the kept, labeled photos. Report every missing room and every room with no strong shot, in plain words. This is deterministic code, not a model call.

### D. Write, twice

For each of three text jobs, both Muse Spark (Meta) and Muse Spark Open (Baseten) get the same prompt and the same inputs (the facts file and the room labels, never the photos for Muse Spark Open unless the navigator confirms it accepts images):
1. Listing description, 120 to 220 words.
2. Social captions: one for Instagram and Facebook (under 300 characters plus up to 5 hashtags) and one for a short video post (under 150 characters).
3. Fair housing review of every description and caption from both models (each model reviews all of them).

### E. Score both, the same way

Deterministic checks on every description and caption, from both models:
- **Facts:** every number and every amenity in the text appears in the facts file. Anything invented fails.
- **Fair housing words:** no word or phrase describing who should or should not live there, from a fixed list in `listing_partner/fair_housing.py` built from 42 U.S.C. 3604(c), 24 CFR 100.75, and HUD's 1995 advertising guidance (the Achtenberg memo). Examples of what fails: words about family status (no kids, adults only, perfect for couples, ideal for a single professional), religion, race, color, national origin, sex, disability (no wheelchairs, must be able to climb stairs, able-bodied), and age-based steering (mature, young professionals). Describing the property stays fine (family room, master bedroom per HUD's guidance, walk-in closet, near a park, wheelchair ramp). The list and its sources are in the file, with tests.
- **Length:** within the limits above.
- **Second opinion:** each model's fair housing review of each text. When the two models disagree on a text, the text is flagged for a person, never passed.
- A text that fails any check is rewritten once by the same model with the failure named, then rechecked. A text that still fails is shown as failed, not hidden.

The better model per job is chosen by: fewer failed checks first, then lower cost. Ties are shown as ties. Every output, from both providers, is logged to `output/unit-a/writing/log.jsonl` with job, model, provider, prompt hash, cost, checks and verdicts.

### F. The listing page

`output/unit-a/listing.html`:
- The kept photos in order, each with its room label; dropped shots below with the reason for each.
- The facts (from the facts file) and the coverage check verdict.
- For each text job, the two models' outputs side by side, labeled "A" and "B" in a random order with the model names behind a "show which model" toggle, so Erik can pick without bias. His pick is not stored by the page; he says it to the navigator.
- Every check result per text, and any flag for a person.
- Cost per listing for this run, split by provider and model (Meta: Muse Spark, SAM 3.1; Baseten: Muse Spark Open), from the two ledgers.

## Acceptance criteria

1. `./scripts/check` passes on the final commit, and pytest passes on a clean export without photos (skips print their reason).
2. Both clients refuse at their caps, on corrupt ledgers, and on any model not on their allowlist, with a named test for each. The Baseten key is read only from `BASETEN_API_KEY`.
3. Every finished photo is either kept with a label and a position, or dropped with a reason. Kept plus dropped equals 17.
4. The benchmark against Erik's MLS selection and order is reported with numbers.
5. The coverage check lists every room the facts require and says found or missing for each.
6. All three text jobs ran on both models. Every output is in the log with its cost and checks.
7. No shipped description or caption contains a number or amenity that is not in the facts file, or a phrase on the fair housing list. Any text the two models disagree on is flagged for a person on the page.
8. Meta spend for this unit is under $3.00 and Baseten spend under $10.00, each from its own ledger.
9. No tracked file contains facts from `facts/unit-a.json`, a street address, a unit number, or any banned string. `facts/` stays gitignored except `facts/sample.json`.
10. The page shows cost per listing split by provider and model.
11. Report numbers come from the final run only. No visual or quality verdicts in the report; the reviewer and Erik judge the writing.

## Observable criterion (Erik, two minutes, no code)

Finder, Shift+Cmd+G, `~/projects/listing-partner/output/unit-a`, then open `listing.html`. The photos run in an order you would walk a renter through, each with a room label you agree with. Read description A and description B and pick the one you would post. Every number in it matches the unit. The cost per listing at the bottom is in cents or a few dollars, split between Meta and Baseten.

## Out of scope

Tidying (SAM 3.1 plus Muse Image), the maintenance list, export sizing and naming, the agent and drop folder, posting anywhere, scheduling, and any change to unit 2's finish.

## Amendment, Nov 2 (navigator, after the first review)

- **Fair housing source:** the HUD 1995 advertising memo's text could not be retrieved from hud.gov during the build, so the list is built from 42 U.S.C. 3604(c) and 24 CFR 100.75 (which itself gives examples), with the memo cited as background only. The list must catch "preferred" and "preference" wording ("adults preferred", "seniors preferred"), an adjective before a group ("perfect for a young family", "best suited to a couple"), and negations ("no young children", "not for kids"). Describing the property's features stays fine, including "handicapped accessible" and "wheelchair accessible". The file says the list is a screen, not legal advice, and a person approves before posting.
- **Facts check:** each bed, bath, rent and square-foot number is checked against the fact it sits next to, not against a shared set of numbers, and number words are covered. Amenities are checked against the fixed list of known amenity groups, and a text naming an amenity group not in the facts fails. The page states plainly that an amenity outside the known groups cannot be detected, and labels a passing text "passed the automatic checks", not "passed every check".
- **Rewrite rule:** a text with any hard failure is rewritten once even when the reviewers also disagree; the original's flag stays visible.
