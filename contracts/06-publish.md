# Contract 06: publish (navigator, Nov 3)

Saved by the builder from the navigator's message, word for word below the line. Branch: `unit-06-publish`, cut from `main`.

---

You are the builder for this repo. Read AGENTS.md and docs/github.md. Work on a new branch unit-06-publish cut from main. Erik's yes is given for everything below except making the repo public.

1. README.md: replace it with .navigator/README-draft.md, filling every MEASURE_ token from real files only (picks from output/home-a/listing_summary.json, pixels outside masks from output/home-a/tidy.json, cost per listing for home-a split by provider and model from both ledgers, commit counts from the muse-code-built tag, the run command from step 3, and a Known limits section merging the existing unit 2 limits with units 3 and 4's). The README must never mention unit-a, its photos, its city or its facts; call it "a private test set" if needed.
2. docs/who-built-what.md from .navigator/who-built-what-draft.md, with MEASURE tokens filled and a review-rounds table per unit (count of NOT YET and SHIP from .navigator/review-*.md). LICENSE from .navigator/LICENSE-draft as is.
3. A one-command run: scripts/run <set-name> runs units 2, 3 and 4 end to end on inputs/<set-name>/raw and facts/<set-name>.json, one set at a time, and prints where the pages are. Test it with a dry run that makes no model calls.
4. On review-finish.html, show each set's raw bracket frames as a small strip above its finished photo (for the video hook), then re-render home-a's page with no model calls.
5. docs/reviews/: copy every .navigator/review-*.md, scrubbing local machine paths, usernames and anything on the banned list, and add an index. Include the unit-a reviews only if no unit-a address, city or facts value appears after scrubbing.
6. Run the full-history hygiene scan (banned strings, keys, tokens, emails, phone numbers, facts values, image metadata) over every commit and every file. It must be clean.
7. Use the reviewer agent to review this branch for hackathon rules, hygiene and that every number in README and docs is measured; it writes .navigator/review-06.md and must not edit files or call any model.
8. Only on SHIP: approved fast-forward of main as before, then follow docs/github.md to create listing-partner on ehill-amera as PRIVATE, add origin, push main with the push approval file created and deleted around the push, and confirm gh's active account is unchanged. Do not make it public.

Never use --no-verify. Report "done, with counts", including the review verdict, main commit, and the private repo URL.
