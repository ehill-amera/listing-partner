# Review: contract 04-tidy, branch unit-04-tidy, commit f93deaa

Reviewer agent, Nov 3 2026. The reviewer may not write repo files, so it handed this report back as a message and the builder saved it here word for word.

**Verdict: SHIP.** The gray mark that blocked the last review is gone: home-a 008 now ships untidied with the reason "fill left a mark on the surface". The only tidied home-a photo, 003, shows no mark, smudge or leftover at full resolution. The check command, hooks, $20 cap, hackathon rules, repo hygiene and zero pixels changed outside the mask all hold.

## Checked
1. Check and clean export: ./scripts/check with both keys unset, CHECK OK, 974 passed, banned-strings clean. Clean export of f93deaa: 958 passed, 16 skipped (each needs gitignored photos or .navigator/ evidence), 0 failed.
2. Nothing weakened: no test line deleted since main; scripts/ and .gitignore unchanged. One test changed since 386a564 (80-level cloud), and it now asserts more. The fill check's one-retry case keeps its own test, asserting only the fill check fired.
3. Failing-first holds: 386a564 code with HEAD's tests, the 008 replay fails with "assert True is False" (old code passed the marked fill). The second test fails on importing blotch, which only shows the module is new. Both pass on HEAD.
4. Mark check re-measured: 386a564's shipped 008 fill fails, one dark spot 12.6 levels over 1,893 px at x 5095-5138, y 3001-3063 (last review's spot). Current 008 attempt (rejected.png) fails, 15.4 levels over 4,344 px and 14.5 over 2,670 px. 003 passes, 0% of the fill judged.
5. Pixels and page: sha256 of finished photos match tidy.json; masks only 0/255. 003 (28,900 mask px) and 008 (631,100): 0 pixels changed outside mask, max difference 0, 0 changed on the 1-px ring. Damage under masks 0 (damage list empty). Run started 11 s after the f93deaa commit, tree clean. 008 has no tidied.png or after.jpg; page shows the untidied reason and Mark check line with 3 tries. "Edited: clutter removed" appears once, on 003, with slider and mask-flash button.
6. 003 at full resolution (reviewer's eye, 2x and 3.5x crops, contrast-stretched): soap dispenser and sponge gone, tile pattern and counter edge continue, no spot or remnant; the correctly rejected red bottle is still there. After a blur, fill values stay within the ring's range.
7. Hooks byte-identical to scripts/git-hooks/; core.hooksPath unset; no main-approved or push-approved marker; no remotes; all 13 commits use the noreply email.
8. Meta client unchanged since 386a564. Only meta_client.py and baseten_client.py import an HTTP client. Key read only from META_API_KEY; nothing reads <local path> SPEND_CAP_USD = 20.0 and $1 headroom are constants; allowlist muse-spark-1.3/1.2/1.1, sam-3.1, muse-image-1.0. 24 cap and allowlist tests pass. The retry loop makes at most 3 Muse Image calls per spot; the mark check is local.
9. Ledger: lifetime $6.15281 of $20. Unit-4 guard $3.783781 of $5.00. Less home-a units 2 and 3: $3.252867 (those two amounts taken from the last review, not re-derived). This run: Muse Image 5 calls $0.05, Muse Spark 1 call $0.010682, SAM 3.1 1 call $0.0025. No Baseten calls (ledger last written Nov 2).
10. Hygiene: 82 tracked files, no images, .env, ledger, .navigator/, output/ or inputs/. Image-metadata scan passes. Private banned-string list checked against commit messages since main, tracked file names, contents and branch names: 0 hits. No email, phone, /Users path or address shape in commit messages.

## Notes (not blocking)
1. 003's "no mark" rests on the reviewer's eye and Muse Spark's self-check, not the new check, which judged 0% of 003 (tile) and unit-a 016 (siding).
2. "11 of 300 clean controls" could not be reproduced exactly (no script or seed saved in the repo). The reviewer's own run: 6 of 75 (8%), same range.
3. The page's "Meta spend for this unit: $3.7838" includes home-a units 2 and 3; unit 4 is $3.25. It overstates, never understates.
4. Known limits: unit-a's tidy page predates this code (its 016 measures 0 pixels outside the mask, mark check passes at 0% judged, no leftover bin seen); empty damage list on home-a; fill quality on untidied photos not judged; slider and mask flash checked in page source only; 2 unsettled ledger reservations from Oct 26 (unit 1).

## Hand-off note from the reviewer
The builder's mid-run message said the review had already finished; it had not. At that point only the check command had run. Every check above was finished after that message.
