# Provenance: what was built during the hackathon, and how

Meta Global AI Developer Hackathon, Indie track, solo. Kickoff Mon Oct 26, 2026, 12:00 PM ET. Submission due Wed Nov 4, 2026, 9:00 PM ET.

## Built during the hackathon

Everything in this repository. The first commit was made Oct 26, 2026 at 12:37 PM ET, after kickoff, and every commit's date is in the git history. No code was copied in from any earlier project.

One disclosure: the planning documents (PRODUCT.md, AGENTS.md, the first contract, the reviewer instructions) and the git safety hooks in `scripts/git-hooks/` were written the morning of Oct 26, before the noon kickoff, and committed after it. They are planning notes and repo guardrails, not product code. All product code was written after kickoff.

## Existing tools plugged in, not built here

- **AppFolio read-only connector.** Built before the hackathon. Listing Partner reads public unit facts from it (beds, baths, square feet, rent, amenities, public address). It is not part of this repository and is not presented as hackathon work.

## Meta models the product uses

Every model call the product makes goes to Meta's models through the Meta Model API, through one spend-capped function (`listing_partner/meta_client.py`):
- Muse Spark: curation, room labels, coverage check, maintenance pass, honesty self-check, listing description and captions.
- SAM 3.1: clutter masks and maintenance-pass regions.
- Muse Image: removing clutter inside the saved masks only.

The product calls no other model provider.

## Development tools

- **Muse Code** (Meta's coding agent) wrote the product code.
- **Claude Code** ran a fixed, read-only review at the end of each unit (`.claude/agents/reviewer.md`). It reads and runs tests. It never writes product code.
- **Claude** (Anthropic) helped plan the build and write the contracts in `contracts/` and the documents in `docs/`.

The official Participant Guide places no restriction on development tools. This section discloses them so judges can see exactly who and what built each part.

## Test photos

All photos are Bokani Property Management Group's own, shot by Erik Hill. Only public listing facts and these photos are ever sent to Meta. No tenant, applicant or owner data.
