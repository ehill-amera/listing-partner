# Who built what

Listing Partner was built Oct 26 to Nov 4, 2026, by Erik Hill (solo, Indie track) with three AI roles that never graded their own work.

| Role | Who | What | Where to check |
|---|---|---|---|
| Decides what and whether | Erik Hill | Every scope and ship decision, the test photos, the honesty rule | Contract amendments marked "Erik's decision" |
| Navigator | Claude (Opus 5.5) | PRODUCT.md, AGENTS.md, every contract and amendment, build plan, reviewer prompt | `contracts/`, `PRODUCT.md`, `docs/build-plan.md` |
| Builder, units 1 and 2 | Muse Code, muse-spark-1.3 | Capped Meta client, HDR merge, lens and verticals, windows, exposure, denoise | Every commit up to tag `muse-code-built` (87 commits) |
| Builder, from the unit 2 color fix on | Claude Code, Opus 5.5 | Raw-stage white balance, curation, writing on Muse Spark and Muse Spark Open, scoring, fair housing, Baseten client, tidy | Every commit after `muse-code-built` (51 commits through the unit 4 commit `f93deaa`) |
| Reviewer | Claude Code reviewer agent, fresh context | SHIP or NOT YET on every unit, against the contract | `docs/reviews/` |

## Why the builder changed on Oct 31

Muse Code built on the hackathon's Meta credits, and its own building spend is not capped by the product's spend cap. With credits running low and a rule of no personal money, Erik moved building to Claude Code on his own plan. The product itself still calls Meta's models for every model job.

## Review rounds, by unit

Counted from every saved review report for units 1 to 4; reviews of the publishing step itself are not included. 13 are in [`docs/reviews/`](reviews/README.md); unit 3's SHIP report is withheld there because it names facts of the private test set. Each round reviewed one commit and answered SHIP or NOT YET. Every NOT YET finding was fixed, or settled by an Erik decision written into the contract, before the next round; unit 2's last was accepted as known limits.

| Unit | Rounds | NOT YET | SHIP | How it ended |
|---|---:|---:|---:|---|
| 1. HDR merge and capped Meta client | not saved | not saved | not saved | Reviewed (contract 01 cites its third and fourth reviews), but no report was kept, so none is counted here |
| 2. Window pulls and exposure | 8 | 8 | 0 | After the eighth round, Erik accepted its remaining marks as known limits (listed in the README) and shipped it |
| 3. Curate and write | 3 | 2 | 1 | SHIP on the third round |
| 4. Tidy | 3 | 2 | 1 | SHIP on the third round |
| **Total, saved reports, units 1 to 4** | **14** | **12** | **2** | |

`scripts/measure_docs.py` recounts this table and every commit count above.
