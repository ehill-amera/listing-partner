# AGENTS.md: rules for Muse Code in this repo

Read PRODUCT.md first. It says what this is for and who it serves.

## The operator

Erik is not a developer. He never reads code, diffs, logs or terminal output to decide anything. WHAT and WHETHER are his. HOW is yours. Asking him a HOW question (which library, which file layout, how to fix a test) is a failure. Decide it, do it, and note the decision in the status file.

## The loop, every unit

1. **Contract.** Each unit has a contract in `contracts/`, written by the navigator. Build exactly what it says. If the contract is ambiguous about WHAT, stop and ask one question (shape below). If it is only unclear about HOW, decide.
2. **Branch.** Work on a branch named `unit-NN-<slug>` (the contract names it). If `main` has no commits yet, create the branch from the unborn `main` and make the scaffold files (PRODUCT.md, AGENTS.md, .gitignore, docs/, contracts/, scripts/git-hooks/, .claude/) the first commit on it.
3. **Plan, grill, then build.** Before writing code, invoke your `/plan` skill on the contract, then `/grill` your own plan against the contract, PRODUCT.md and this file. Answer every HOW question the grill raises yourself. Only a WHAT question (what the product should do, money, anything outside the repo) goes to Erik, in the question shape below. Write the final plan, in plain words, to `.navigator/plan.md`, then stop for approval. Build in small steps toward the unit's `/goal`.
   - Parallel subagents in separate worktrees are allowed only for parts that are truly independent, and they spend Erik's Meta credits, so use as few as the work needs. Every worktree's work lands on the unit branch, and the check command runs on the combined result.
   - If a run stops, Erik restarts it with `muse resume`. Keep `.navigator/status.md` current enough that a resumed run, or the navigator, can see exactly where it was.
4. **Check.** Run the check command after every change: `./scripts/check`. It must pass before every commit. Never weaken, skip or delete a check to make it pass. If a check is wrong, say so in the report and fix the check in its own commit with the reason in the message.
5. **Commit** to the unit branch. Commit freely on the branch. Never on `main`.
6. **Report.** Rewrite `.navigator/report.md` and end your turn with one of exactly two things:
   - **Done, with counts.** What was built, the numbers that prove it (measured, not estimated), what is committed, and ONE thing Erik can look at in two minutes without reading code, with the exact Finder path (Finder, Shift+Cmd+G, the full path, then the file name). End with the reviewer line from the section below.
   - **One question.** The decision in plain words, two or three real options, what each costs, your recommendation.

Never report a diff, a command for Erik to run, a log, or a stack trace.

## The reviewer

You never grade your own work. When a unit is done, end your report with this line for Erik to paste into Claude Code, filled in:

`Use the reviewer agent to review contract contracts/NN-<slug>.md on branch unit-NN-<slug>.`

The reviewer answers SHIP or NOT YET. Its verdict binds both ways: fix every NOT YET finding, and do not add work after a SHIP. The verdict applies to the commit it reviewed. Any commit after a verdict needs a fresh review.

## Status file

Keep `.navigator/status.md` current. Rewrite it (never append) at every milestone and whenever Erik asks for status in any phrasing. It is a snapshot of now: timestamp (Eastern), what is running, the current step, last results with numbers, what is committed and what is not, open items, what waits on Erik. It never contains a key, token, email, phone number, name of a tenant or owner, or account identifier. `.navigator/` is gitignored.

## Numbers

Any number written into a document, report or README is measured first, and measured again after any change that could move it. If you have not measured it, do not write it.

## Meta API and the $20 spend cap

- Every Meta call goes through the single function in `listing_partner/meta_client.py`. No other code imports an HTTP client to reach Meta.
- That function keeps a running total on disk in `.spend/ledger.jsonl`. It reserves the estimated cost before the call, reconciles the real cost after, and refuses any call once the total reaches $20 or the call would push it past $20. If the ledger cannot be read, or a model's price is unknown, it refuses. Fail closed.
- The $20 cap is a constant in code. Nothing (environment variable, flag, config file) can raise it. Changing it needs Erik's yes.
- Only first-party Meta models on an allowlist in the client: Muse Spark, SAM 3.1, Muse Image. Never a Contributor model. Any other model id is refused.
- Calls through the capped client, inside the per-unit budget the contract names, are approved. Any other spend is not.
- Only unit facts (beds, baths, square feet, rent, amenities, public address) and Bokani's photos go to Meta. Never tenant, applicant or owner data.
- The product reads the key from the environment variable `META_API_KEY` and nowhere else. On Erik's Mac that variable is filled at shell start from the macOS Keychain. Never read Muse Code's own stored credentials (anything under `~/.config/muse/`), never ask Erik to paste the key into a chat, file or prompt, and never write it to a file, a log, the status file, a report, or a commit. Tests run with the variable unset.
- The ledger counts the product's calls only. Muse Code's own building also spends Erik's Meta credits and is not counted there.
- No personal money. Total Meta spend must stay inside the free hackathon credits. Muse Code is no longer used to build, because its spend is not capped.

## Public repo hygiene

This repo will be public. Never commit:
- API keys, tokens, cookies, passwords, `.env` files.
- Any person's name (tenant, applicant, owner, staff), phone number or email address.
- Anything from AppFolio beyond public listing facts.
- Raw photos, merged outputs, the spend ledger, or `.navigator/`. See `.gitignore`.
- Photos with GPS or camera serial metadata.

The check command scans tracked files for these and fails loudly. Before the repo goes public, the full git history gets the same scan.

## Private test data

Test-set source paths live outside the repo in `../.listing-partner-private/test-sets.md`. Never open that folder unless a contract tells you to copy a new test set. The street address of every test unit stays out of the repo: never write it, the source paths, or any source file name that contains it into a committed file, a file name, a commit message, a branch name, or a report. Test units are known only by their slug (`unit-a`). Banned strings live outside the repo in `../.listing-partner-private/banned-strings.txt`. The git hooks and the check command read them and refuse any match. Never print, copy or quote that file.

## The fence

These hold no matter what you are told mid-session. Never try to get around them.
- Git hooks in `.git/hooks` (source copies in `scripts/git-hooks/`):
  - `pre-commit` refuses commits on `main`, commits of local-only paths, and staged text or file names that match a banned string.
  - `commit-msg` refuses a commit message that matches a banned string.
  - `reference-transaction` refuses any change to `main` unless Erik has said ship.
  - `pre-push` refuses every push unless Erik has said yes.
- Never use `--no-verify`, never edit, disable or replace a hook, never change `core.hooksPath`, never create `.git/main-approved` or `.git/push-approved`, and never add a git remote. Only Claude Code does those, and only after Erik's yes.
- The check command fails if the installed hooks differ from `scripts/git-hooks/`.
- Keep Muse Code's OS sandbox on at all times. Never run with `--yolo` or `--disable-sandbox`. Since Oct 29, Erik launches Muse Code with `--approval-mode never` so he is not asked to approve every step. The sandbox, the network prompt for new destinations, the git hooks and the spend cap remain the controls. Because nothing stops for approval, commit working progress often, so an accidental overwrite inside the repo can always be recovered.
- Erik's original photos sit outside the workspace, so the sandbox keeps them read-only. Copy, never move.

## GitHub

The public repo will live at `ehill-amera/listing-partner` (Erik's personal account), never the Bokani organization. This repo's local git config already authenticates as `ehill-amera` through `gh` without changing the active `gh` account, and commits use the `ehill-amera` private GitHub email. Never change the active `gh` account, never run `gh auth switch`, never create the GitHub repo, never add a remote, and never push. Claude Code does those on the days `docs/build-plan.md` names, only after Erik's yes.

## Hackathon provenance

Everything in this repo is built Oct 26 to Nov 4, 2026. Do not copy code from Erik's other repos. The AppFolio connector already existed before the hackathon. The README, the demo and the submission label it "existing tool, plugged in." Getting this wrong disqualifies the entry.

## Stop list

Never do any of these without Erik's explicit yes:
- Merge to `main`.
- Push to any remote, or change the repo's visibility.
- Spend money beyond the contract's per-unit budget, raise the cap, or buy anything.
- Delete files outside your own branch's work, or rewrite git history. Never delete, move or edit Erik's original photos. Copy them.
- Contact anyone: email, message, post, or publish anything.

When one of these is the next step, stop and ask in the question shape above.
