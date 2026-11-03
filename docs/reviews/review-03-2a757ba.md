# Review: contract 03 with Amendment Nov 2, branch unit-03-curate-and-write, commit 2a757ba

**NOT YET.** The four earlier findings are fixed and the live run is clean and under budget. But the fair housing screen still misses "adults-only" and "no seniors", the amenity check misses plurals and hyphenated forms of its own groups, and a wrong bath count written in words or ordinals still passes. Both descriptions are also the same fact list repeated.

## State of what was reviewed

- HEAD was 2a757ba and the tree was clean (0 status lines) before the check and at the end of the review.
- No Meta or Baseten call was made. Every test and check ran with both keys unset. Rewrite probes used fake models. Mutants ran in throwaway exports in the scratchpad.
- `.spend/` checksums were the same before and after all of this. No repo file was edited.
- The private folder was opened only by `./scripts/check` itself.

## Findings 1 to 4 of review-03-bc8043b

| # | Verdict | Evidence |
|---|---|---|
| 1. Fair housing list | **FIXED as written.** Holes of the same kind remain: see new finding 1. | I ran `find_phrases`. All 13 old probes now hit. All 9 contract failing examples hit. All 11 allowed phrases return nothing, including "handicapped accessible", "wheelchair accessible", "family room", "master bedroom" and "mature trees". Sources in the file match the amendment, with the memo as background only and "not retrieved". The file says it is a screen, not legal advice, and that a person approves before posting. Removing the "group preferred" pattern fails 6 tests. |
| 2. Facts check and page | **FIXED as written.** Holes remain: see new findings 2 and 3. | `check_facts` with the real unit facts: swapped bed and bath 2 failures, swapped rent and square feet 2, baths equal to bedrooms 1, "sauna, hot tub and rooftop terrace" 3, "detached garage" 1, "Forty feet of frontage" 1, a true text 0. On the page, "Passed the automatic checks" appears 6 times and "passed every check" 0 times. The limits paragraph is present and names the 62 groups. Mutants: turning off the fact-beside lookup fails 33 tests, restoring the old label fails 1, removing the limits sentence fails 1. |
| 3. Rewrite rule | **FIXED.** | Fake-model runs: hard failure plus a reviewer split gave 2 attempts, with the first flag kept true. A disagreement alone gave 1 attempt, status flagged. Hard failure with no split that stays bad gave 2 attempts, status failed. The page shows the first version's flag outside the fold (`listing_page.py:77-82`, read, not clicked). Mutants: old rewrite logic fails 2 tests, dropping the flag fails 1. |
| 4. Report number | **FIXED.** | Case-insensitive whole-word `git grep`: 3 of 4 amenity values at both bc8043b and 2a757ba. All are common words. The report says 3 of 4. |

## New findings, most severe first

1. **The fair housing list still misses plain forms of the classes the amendment names.**
   - Where: `listing_partner/fair_housing.py:40` (gap of two words), `:51-52` (preferred), `:58-62` (negations and "only").
   - How found: I ran 53 phrases through `find_phrases`, hand-picked to break the list. 40 returned nothing, including:
     - **Hyphenated "only":** "adults-only building", "adult-only", "seniors-only". The contract's own example is "adults only".
     - **Negations:** "no seniors", "no students", "no teens", "no toddlers", "no child", "no pets or children", "kids not allowed", "children not allowed", "unsuitable for children", "not appropriate for children", "not recommended for children".
     - **Preferred:** "adults strongly preferred", "seniors strongly preferred", "preference will be given to seniors", "preferred tenants: adults", "gentleman preferred", "lady preferred".
     - **Adjectives before the group:** "perfect for a busy working couple", "best suited to a busy working family", "ideal for a small quiet family". The gap allows two words, and these use three.
     - **Other wording:** "good for families", "families welcome", "kid-friendly", "professionals only", "english only".
   - No live text is affected, and the two model reviews sit behind the list. An exhaustive list is not achievable, and the file says so.
   - To pass, with failing-first tests:
     - accept a hyphen in the "only" patterns;
     - cover negations across all age and family groups, plus "X not allowed" and "unsuitable for";
     - allow an adverb before "preferred" and "preference ... given to";
     - widen the gap to at least three words;
     - add "good for", "welcome" and "-friendly" for the listed groups.

2. **The amenity check misses plurals and hyphenated forms of its own known groups, so the page's limits line is wrong.**
   - Where: `listing_partner/scoring.py:159`. `_has` needs an exact term with no hyphen or word character on either side.
   - How found: `check_facts` with the real facts returned 0 failures for "private patios", "balconies", "decks", "resort pools and saunas", "front and rear porches", "new dishwashers", "stainless-steel appliances", "fully-furnished", "air-conditioning" and "pool-side". None of these is in the unit's facts.
   - The amendment says a text naming an amenity group not in the facts fails. The page tells Erik only amenities outside the groups go undetected, and these are inside them.
   - To pass: match plural and hyphen forms for every group, with failing-first tests.

3. **Numbers and pet or garage claims that contradict the facts still pass.**
   - Where: `listing_partner/scoring.py:251-252` (a bare "one" is skipped), `:56` (reach stops at "and"), `:263-271` (presence-only amenity match).
   - How found, with `check_facts`, 0 failures each:
     - "one and a half baths" and "one and a half bedrooms", with the real facts. The digit form of a wrong bath count does fail;
     - "a second bathroom" and "a half bath", with the real facts. The page's example "second floor" does not tell a reader that a bath count can slip through;
     - with test facts of `pet_policy: "No pets allowed"`, "pets welcome" and "pet-friendly" pass;
     - with test amenities of `["no garage"]`, "garage" passes.
   - unit-a's pet policy is empty, so this run is unaffected. "No pets" will be common across other units.
   - To pass:
     - "and a half" after a number word counts as that value next to the noun;
     - ordinal and half wording next to bed or bath fails, or the page names it plainly as unseen;
     - a negated fact does not count as the amenity being present.

4. **Both descriptions read as the same fact list repeated, which misses the contract's "the words that sell the unit". This is my judgment, as criterion 11 assigns it, not a measurement failure.**
   - Where: `output/unit-a/writing/log.jsonl`. The likely cause is `listing_partner/writing.py:13-18` ("Use only these facts") with a 120-word floor and only 4 amenities.
   - How found: I read both and counted. Muse Spark Open states the square feet, bedroom count, city and each amenity 5 times, and the rent 4 times, in 137 words. Muse Spark states each 3 times, in exactly 120 words.
   - The first run at bc8043b repeated less (square feet and rent twice each), so this varies run to run.
   - The observable criterion asks Erik to pick the one he would post. A renter or judge sees this first.
   - To pass: the prompt says to state each fact once and describe the rooms photographed without inventing anything, then one fresh live writing run. The last run's writing cost was $0.059 at Meta and $0.059 at Baseten.

## Contract items

| # | Criterion | Result | What I did |
|---|---|---|---|
| 1 | Check and clean export | PASS | See check results below. |
| 2 | Clients refuse at caps, on corrupt ledgers, off allowlist | PASS | Named tests read and run for both clients. Neither client changed since bc8043b, per `git diff`. Key read only at `baseten_client.py:179` and `meta_client.py:313`. I did not re-mutate them at this commit. |
| 3 | Kept plus dropped equals 17 | PASS | 14 kept, 3 dropped (003, 007, 013), each with a reason. Saved curation differs from the pre-backfill copy only in `photos` and `cost`. All 17 hashes match the files. Newest photo is Nov 1, so the finish was not re-run. |
| 4 | Benchmark reported | PASS | Page and summary agree: 13 both, 1 here only, 3 published but dropped, 9 in a different position, 0.7143. I did not rerun the MLS match at this commit. The kept and dropped lists are unchanged from the earlier curation. |
| 5 | Coverage | PASS | Reran `check_coverage`: 7 of 7 found, 0 missing, one row per required room. |
| 6 | All jobs on both models, logged | PASS | 16 rows and 16 unique request ids: 2 descriptions, 2 caption calls (6 texts), 12 reviews. Prompt hashes are identical across models for each job. |
| 7 | No shipped text with invented number, amenity or listed phrase; disagreements flagged | PASS for this run; the check behind it has holes (new findings 1 to 3) | I read all 6 texts. Rerun checks: 0 facts failures, 0 list hits. 12 of 12 reviews PASS, 0 disagreements. The disagreement path has run only with fake models. |
| 8 | Spend under budget | PASS | From ledgers: Meta $0.443076 of $3.00, Baseten $0.157042 of $10.00. Lifetime Meta $1.901096, Baseten $0.157042. 0 open reservations since Nov 2. |
| 9 | No facts, address, unit number, banned string tracked | PASS, limit below | Rent, square feet and city: 0 in the tree, 0 in commit messages, 0 in the branch diff. Address pattern: 0 in the tree and messages. Banned scan clean through the check. `facts/unit-a.json` and other `facts/` files are ignored. Nothing tracked under `facts/`. |
| 10 | Cost split by provider and model | PASS | Muse Spark 8 calls $0.0592, SAM 3.1 0 calls, Muse Spark Open 8 calls $0.0588, saved curation row 18 calls $0.0976, total $0.2157. Matches the ledgers. |
| 11 | Report numbers from final run, no quality verdicts | PASS with a noted exception | Run started 10:11:55 UTC, right after the 2a757ba commit. Curation numbers come from an earlier run, disclosed in the report and on the page as a saved row. The thrown-out run is disclosed. No quality verdicts in the report. |

**Amendment.** Each stated example behaves as required. Its facts-check and fair housing classes are incomplete: new findings 1 to 3.

**Build items.** Budgets, the A/B shuffle per job, tie rule, log fields and the room list read as specified. Review rows carry verdicts and no `checks` field, since no text checks apply to a review.

**Observable criterion.**
- I read `output/unit-a/listing.html` as HTML and text. 17 images, in order. A, B and the toggle markup are present, and names are hidden by CSS. I did not click the toggle in a browser.
- I looked at the 17 finished photos in a labeled contact sheet I built. All 17 labels match what the photos show, and the order runs front exterior, through the home, to rear exterior.
- The table row for this cost is labeled "Total this run" and includes $0.0976 of earlier curation. The row above it names that amount, so I did not count it as a finding.
- Still for Erik: the flooring amenity in the facts should be compared with what he knows of the unit. I cannot settle this from photos. Both descriptions repeat it.

## Hackathon rules

- **Other paths:** a search of `listing_partner/` and `scripts/` found HTTP only in the two clients and no other provider. Meta allowlist is three Muse Spark versions, SAM 3.1 and Muse Image, with no Contributor models. Baseten is treated as settled per the navigator.
- **Cap:** the Meta client is unchanged except for a stricter cut-off reply check. Named refusal tests exist and pass.
- **Data sent:** `load_facts` refuses extra fields. `prompt_facts` excludes `source` and `unit`. Baseten gets text only.
- **Provenance:** every AppFolio mention on this branch's code and page says existing or pre-hackathon.
- **PRODUCT.md:** Meta-only wording not raised, per the navigator.

## Public repo hygiene

- No key or phone pattern in branch history. The only email-shaped added lines are `@pytest` decorators (22).
- No image, ledger, output or `.navigator/` file is tracked.
- All listed `.gitignore` entries still apply.
- All 4 hooks are byte-identical to `scripts/git-hooks/`, `core.hooksPath` is unset, and there are 0 remotes.
- All 14 commits use the expected private no-reply address.
- `scripts/check` diff is one stricter line. `tests/test_check.py` only gained a test. No check was weakened, skipped or deleted.

**Photo honesty rules:** no tidying exists in this unit, so nothing was measured.

## Check results (measured)

- `./scripts/check` on 2a757ba: **exit 0, CHECK OK, 461 passed**, ruff clean, banned scan clean.
- Clean `git archive` export, package confirmed imported from the export: **452 passed, 9 skipped, 0 failed**. All skips print a reason.

## Numbers in prose

No README or docs changed. Reproduced from `.navigator/report.md`:
- 461 and 452/9;
- 14/3 and all benchmark numbers; 7 of 7;
- 62 groups; 16 calls; 6 texts; 12 reviews; 0 rewrites;
- word and character counts (120, 137; 146, 133; 121, 117; 3 hashtags each);
- all job costs; thrown-out run $0.101563 and $0.057284; ledger totals; thinnest reservations 2.43 and 3.06;
- 18 curation calls, $0.097619: curation is the 45-call first-run window less the stopped run and writing;
- 3 of 4 amenity values; all 5 facts probes.

Partly reproduced, no effect on the code: "55 failed, 90 passed". Tests at 38e9b86 on code at bc8043b give **55 failed, 94 passed**. The evidence file does say 55 and 90, so it was likely a different test selection. The builder should say which tests produced it.

The `USD` (6/4) and reuse (5) failing-first counts are read from evidence files only. Not rerun.

**Not verified:**
- Banned strings against commit messages and per-commit history. `banned_scan.sh` covers the current tree only, and I am barred from opening the list. Hooks being installed is indirect evidence.
- The Baseten price, as no network was used.
- The facts file against the connector.

## Files

- `listing_partner/fair_housing.py`
- `listing_partner/scoring.py`
- `listing_partner/writing.py`
- `output/unit-a/listing.html`
- `.navigator/report.md`

**Verdict: NOT YET.** Fix new findings 1 to 4, in that order. Changes to the checks and the prompt need a fresh writing run, and any new commit needs a fresh review.
