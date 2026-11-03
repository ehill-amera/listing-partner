# Review: contract 03, branch unit-03-curate-and-write, commit bc8043b

**NOT YET.** The live run on this commit is clean and within budget, but the fair housing list and the facts check miss things the contract says they must catch, and the page says "Passed every check" without saying so.

## State of what was reviewed

- HEAD is bc8043b and the tree was clean at the start and at the end of the review.
- No Meta or Baseten call was made. Every check and test ran with both keys unset. The one rewrite probe used fake models and no client.
- `.spend/` ledger checksums were the same before and after `./scripts/check`.
- Mutation tests and the rewrite probe ran in a throwaway export in the scratchpad. No repo file was edited.

## Check command (measured)

- `./scripts/check`: **exit 0, CHECK OK, 366 passed**, banned-strings scan clean, ruff clean.
- Clean export without photos (`git archive`, package confirmed imported from the export): **357 passed, 9 skipped, 0 failed**. All 9 skips printed a reason under `-rs`.
- Branch diff of `scripts/check`: one line changed, adding `-u BASETEN_API_KEY` to the pytest call. That is stricter, not weaker.
- `tests/test_check.py` only gained a test. `.gitignore` changed only for the navigator-accepted sample exception, and `scripts/check` still confirms `facts/` is ignored.
- No check was weakened, skipped or deleted. Hook sources and the banned-scan script are unchanged on the branch.

## Required check: unit-a facts in tracked files

`facts/unit-a.json` **is present on disk** and is **not tracked**. 0 paths under `facts/` are tracked at bc8043b.

I compared every non-null value in the file (12 values, with comma forms for large numbers) against the tree at bc8043b using a case-insensitive whole-word `git grep`.

| Field | Result |
|---|---|
| Rent, square feet, city (all forms) | **0 tracked files. PASS.** |
| Source text | 0 tracked files. PASS. |
| Amenities, 3 of 4 values | Match as common words only: `listing_partner/scoring.py`, `listing_partner/sample_data/facts_sample.json`, `tests/test_scoring.py`, `tests/test_run_listing.py`, `tests/test_writing.py`, `tests/test_fair_housing.py`. These are the general amenity vocabulary, the fictional sample and test strings, not unit data. PASS with that caveat. |
| Amenities, the 4th value | 0 tracked files. PASS. |
| State | 1 file, `listing_partner/sample_data/facts_sample.json`. A common two-letter value in the fictional sample. PASS. |
| Bed and bath counts | Too short to be meaningful: 51 and 63 files, all ordinary uses of a small number. Not a usable signal. |
| Unit slug | 22 files. The slug is the name AGENTS.md permits. Not a leak. |

- Commit messages since `main`: 0 fact-value hits.
- Full branch diff history: rent, square feet and city 0 hits. The only hits are the slug and the same common amenity words.

## Contract items

| # | Criterion | Result | What I observed |
|---|---|---|---|
| 1 | Check and clean-export pytest | PASS | See above. |
| 2 | Both clients refuse at caps, on corrupt ledgers and off-allowlist; Baseten key only from its variable | PASS | Named tests exist for both clients. Seven mutants of `baseten_client.py` (no cap refusal, no ceiling refusal, cap changed and env-readable, corrupt line ignored, no allowlist, no key refusal, length cutoff accepted) each failed at least one test. The only key read is `os.environ.get(KEY_ENV_VAR)`. Meta client tests were read and run, not mutated. |
| 3 | Kept plus dropped equals 17 | PASS | `curation.json`: 14 kept with positions, 3 dropped with reasons. 17 JPEGs in `finished/`, none modified on or after Nov 2, so unit 2's finish was not re-run. |
| 4 | Benchmark reported | PASS | Reran the MLS match from the local files: 16 published shots, all matched by capture time. Hand calculation among the 13 kept by both: 9 in a different position, rank correlation 0.7143. Kept here only: 1. Published but dropped here: 3. Matches the page. |
| 5 | Coverage lists every required room | PASS | 7 of 7 found, 0 missing. Code is deterministic, one row per required room. |
| 6 | All jobs on both models, logged | PASS | 16 log rows: 2 descriptions, 2 caption calls (6 texts in all), 12 reviews (6 times 2). Prompt hashes are identical across models for the description and caption jobs. Log costs per provider match the page; Baseten log total $0.040947 matches its ledger. Review rows carry verdicts and no `checks` field, since no text checks apply to a review. |
| 7 | No shipped text with an invented number, amenity or listed phrase; disagreements flagged | **PASS for this run; see findings 1 and 2** | I read all 6 texts myself. Every digit run is a facts value, no amenity outside the facts, 0 list hits. Words 137 and 126. Captions: 148 and 146 characters before hashtags with 4 and 3 hashtags; video 133 and 117. All 12 reviews PASS, 0 disagreements. The disagreement path ran only with fake models. |
| 8 | Spend under budget | PASS | Recomputed from both ledgers. Meta unit spend **$0.28227 of $3.00** (includes the stopped first run, $0.123369). Baseten **$0.040947 of $10.00**. Lifetime: Meta $1.74029, Baseten $0.040947. |
| 9 | No facts, address, unit number or banned string in tracked files; `facts/` ignored | PASS, with the limit below | Required check above. Address-pattern search: 0 in tracked files and 0 in messages. Banned scan clean through `./scripts/check`. |
| 10 | Page shows cost split by provider and model | PASS | Meta Muse Spark 26 calls $0.1589; Meta SAM 3.1 0 calls $0.0000; Baseten Muse Spark Open 8 calls $0.0409; total $0.1998. Earlier SAM 3.1 spend, $0.2675, is shown apart. All match the ledgers. |
| 11 | Report numbers from the final run; no verdicts on quality | PASS except finding 4 | Run started 08:38:07 UTC, seconds after the 03:38:05 local commit of bc8043b. I saw no quality verdicts in the report. |

**Observable criterion.**
- I opened `<local path>` as HTML text and looked at the 17 photos in a labeled contact sheet I built from the same files. I did not click the toggle in a browser. I read its markup and CSS.
- All 14 kept labels and 3 dropped labels matched what the photos show, and the order runs front exterior, through the home, to rear exterior.
- Whether the walkthrough order and the 3 dropped photos suit him is Erik's call. His published set included those 3.
- Description A and B and the model-name toggle are present, and names are hidden by default. The cost table is at the bottom.
- Note for Erik: one amenity value in the facts file may not match what the photos appear to show. I cannot confirm this from photos. He should compare it to what he knows of the unit. I could not verify the facts file against the source connector.

**Contract build items.** Prompts, room list, rewrite-once, tie rule, and the A/B shuffle with toggle all read as specified, except finding 3. The Baseten price in the code ($1.25 / $0.15 / $4.25 per million tokens) is **unverified by me**, because I made no network call. The report says the source pages name the model without the `-1026` suffix, and that no invoice has been compared.

## Hackathon rules

- **Clients:** the only HTTP clients are in `meta_client.py` and `baseten_client.py`. No other provider or network path turned up in `listing_partner/` or `scripts/`.
- **Keys:** read only from `META_API_KEY` and `BASETEN_API_KEY`. Nothing reads Muse Code's credentials.
- **Baseten:** text only. Muse Spark Open receives prompts built from `prompt_facts`, which excludes `source` and `unit`.
- **Facts file:** `load_facts` refuses fields outside the allowed list. The file holds only allowed keys.
- **Provenance:** the AppFolio connector is labeled pre-existing wherever this branch mentions it, and on the page. This unit adds no AppFolio code.

## Public repo hygiene

- No key, email or phone pattern in tracked files (through the check) or in the branch history. The only email-shaped hits in history are 12 `@pytest` decorator lines.
- No images, raw files, ledgers, outputs or `.navigator/` files are tracked or were ever added on the branch.
- `.gitignore` covers `.env`, `inputs`, `output`, `.spend`, `.navigator`, `local`, `.muse` and `facts`.
- All 4 installed hooks are byte-identical to `scripts/git-hooks/`. `core.hooksPath` is not set. 0 remotes.
- All branch commits use the private no-reply email form for the expected account.

**Not verified:** banned strings against commit messages and per-commit history. `banned_scan.sh` covers only current tracked names and contents, and my instructions forbid opening the list directly. The commit-msg and pre-commit hooks are installed and identical, which is indirect evidence only. The address-pattern search above found nothing.

## Photo honesty rules

Out of scope for this unit: no tidying exists and no photo is edited. Not measured.

## Numbers in prose

No README or docs changed on this branch. Numbers in `.navigator/report.md` that I reproduced:

- 366 and 357/9 test counts
- 14/3 curation split, and 13, 1, 3, 9 and 0.7143 for the benchmark
- 7 of 7 coverage
- 16 logged calls and every cost
- $0.1234 stopped run
- 47 amenity groups
- thinnest reservations 2.80 (measured 2.7959) and 3.93

Not reproduced: see finding 4. Also unverified: "a separate look-based match agreed on 15 of 16" and the 0.264 score, which I did not rerun.

## Findings

1. **The fair housing list misses common discriminatory wording, and it was not built from a source the contract names.**
   - Where: `listing_partner/fair_housing.py`.
   - How found: all 9 of the contract's own failing examples and all 5 of its allowed examples behave correctly, so the existing tests pass. I then ran other phrasings through `find_phrases`. These returned no hit: "adults preferred", "men preferred", "woman preferred", "seniors preferred", "perfect for a young family", "perfect for a growing family", "best suited to a couple", "suited to a single person", "no young children", "not for kids", "female roommate wanted", "single person only", "english speakers preferred".
   - The statute's own word is "preference", yet no pattern covers "preferred" on its own. An adjective before the group also defeats the "perfect for" pattern.
   - In the other direction, "handicapped accessible" fails even though it describes the property, which the contract says stays fine.
   - The file itself says the HUD 1995 memo's text could not be retrieved and its examples were not checked. The contract requires the list to be built from it.
   - No live text was affected, and both models also review each text. But this is the deterministic check a public listing relies on.
   - To pass: add "preferred" and adjective-before-group patterns, narrow the "handicapped" pattern, with tests that fail first for each. Then check the list against the memo's text. If the memo truly cannot be obtained, the navigator has to change that contract line. The builder cannot waive it.

2. **The facts check passes wrong numbers and invented amenities, and the page says "Passed every check" with no statement of those limits.**
   - Where: `listing_partner/scoring.py`, `listing_partner/listing_page.py`.
   - How found: I ran probe strings through `check_facts` with the real facts file. All returned no failure:
     - a text swapping the bedroom and bathroom counts and swapping the rent and square-foot values
     - a text claiming as many baths as the unit has bedrooms
     - "sauna, hot tub and rooftop terrace"
     - "detached garage"
     - "Forty feet of frontage" (forty, sixty, fifteen and other number words are not on the list)
   - The contract says "Anything invented fails", and its observable criterion says every number matches the unit. Numbers are only checked against one shared set, so a real number attached to the wrong thing passes.
   - The comment at `scoring.py` lines 30 to 32 says the page and report state the check's reach. The report does; **the page does not**. I searched `listing_page.py` and read the page text, and it has no such line.
   - An exhaustive amenity list is not achievable by deterministic code, so that part of the contract's wording needs a stated limit rather than a perfect check. The rest is fixable.
   - To pass: tie bed, bath, rent and square-foot numbers to what they sit next to; complete the number words; add a page line saying what the amenity check cannot see, and label the passing result accordingly.

3. **A text with a failed check and a reviewer disagreement is never rewritten.**
   - Where: `needs_rewrite` in `listing_partner/writing.py`, lines 168 to 170.
   - How found: I read the code, then ran `run_writing` with fake models. A description with an invented number plus a reviewer split came back with 1 attempt, status failed.
   - The contract says a text that fails any check is rewritten once. The failed text is shown, not hidden, so nothing unsafe ships. But the model never got its one chance, and that counts against it in the comparison. `tests/test_writing.py` has no case for this.
   - To pass: rewrite when a hard failure exists, keep the flag on the original visible, and add a test that fails first.

4. **One number in the report does not reproduce.**
   - Where: `.navigator/report.md`, line 79, says 2 of the 4 unit-a amenity values appear in tracked files.
   - How found: case-insensitive whole-word `git grep` at bc8043b finds 3 of 4.
   - All are common words, so this is not a leak, but the number is wrong.
   - To pass: measure again and correct it.

## Contract problems, not builder defects

- **Baseten against the written hard rule.** `PRODUCT.md`, and the reviewer brief's rule 3, say every model call goes through the Meta Model API through one capped function. Contract 03 requires a second path through Baseten, and the builder followed the contract. I am not counting this against the builder. `PRODUCT.md` still contradicts the code in a repo judges will read. I cannot verify from here whether the hackathon rules accept Muse Spark Open on Baseten. That is Erik's and the navigator's decision, and `PRODUCT.md` should be updated before the repo goes public.
- **Sample facts path.** Accepted by navigator decision as instructed. Not raised as a finding.

## Files

- `contracts/03-curate-and-write.md`
- `listing_partner/fair_housing.py`
- `listing_partner/scoring.py`
- `listing_partner/writing.py`
- `listing_partner/listing_page.py`
- `.navigator/report.md`
- `output/unit-a/listing.html`

**Verdict: NOT YET.** Findings 1 to 4 above, in order of severity. Any fix commit needs a fresh review.
