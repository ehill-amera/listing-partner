# GitHub for listing-partner

Owner: `ehill-amera` (Erik's personal account). Never the Bokani organization.

## Already set (Oct 26, 2026, local git config, not committed)

- Commits use `Erik Hill` and the `ehill-amera` private GitHub email.
- This repo's credential helper asks `gh` for the `ehill-amera` token (`gh auth token --user ehill-amera`). The active `gh` account stays `bokanigroup-admin`, so Erik's other repos are unaffected.
- No remote. The `pre-push` hook refuses every push unless `.git/push-approved` exists.

## When the build plan calls for it (unit 6, Nov 1), only after Erik's yes

Done by Claude Code, never Muse Code:
1. Confirm `gh auth status` shows `ehill-amera` signed in, and that `gh auth token --user ehill-amera` works on this `gh` version. Do not switch the active account.
2. Run the full-history hygiene scan. It must be clean before anything leaves the Mac.
3. Create the repo as private with the `ehill-amera` token for this one command only (`GH_TOKEN` set inline), named `listing-partner`.
4. Add it as `origin`, create `.git/push-approved`, push `main`, delete `.git/push-approved`.
5. Confirm `gh auth status` still shows `bokanigroup-admin` as active.

## Nov 4, only after Erik's yes

Final full-history scan, push `main` the same way, then make the repo public with the `ehill-amera` token.
