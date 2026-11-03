# Reviewer verdict — contract 02 (window pulls and exposure)

Verdict: NOT YET
Commit reviewed: b99903e9e8deee497aca509c163da2fc48730480 (HEAD of unit-02-window-pulls, clean tree)
Reviewed: 2026-10-29, ~23:00 EDT

## Findings, most severe first

1. Window pull damages windows in every interior opened (003, 004, 007, 009). SAM mask covers whole window incl. frames/blinds; pull_window fills it from a darker bracket with a darken-only gain. White frames/mullions/blinds turn dark brown; dark smear into trim and sill. Breaks A ("mask covers glass only; frames, sills and trim stay from the merge"), B ("no halos, no hard edges, no dark outline on the frame"), the observable criterion, and the honesty rule. To pass: pull touches glass only (narrow mask to glass or keep frame pixels from the merge); view reads naturally; frames keep real color.
2. Criterion 4 measured on grayscale luminance, contract says "250 of 255 on any channel" (finish_tail in run_finish.py, CLIP_LEVEL in checks.py). Measured any-channel: 013 goes 0 -> 878 inside confirmed windows; contract says 013 must not gain any. Other 9 window photos still drop (e.g. 004: 410,345 -> 765). 013's "windows" are facade glass seen from outside (one on the neighbor's house); probably should be rejected under A's "view to the outdoors" rule. To pass: measure any channel; 013, 014, 017 gain zero.
3. Criterion 12: checks with nothing to measure show PASS. "PASS highlights 0.0000 -> 0.0000" on 002, 008, 012, 015, 016 (0 window pixels); "PASS outside: 0 pixels changed" with no mask; "PASS straightness 289 -> 289" on all 17 (before and after identical by construction). check_highlights(0, 0) returns True; test_empty_checks_report_not_measured_never_pass has no highlights/outside cases. To pass: NOT MEASURED, with tests for each.
4. Criterion 10 not shown. straight_before is taken after lens correction, so identical to after on all 17. Reviewer's own measure (line_measure on middle frame before/after correct_distortion): improves on 14 (e.g. 004: 239 -> 352); 001, 009, 012 fit strength 0, no improvement, but contract says "every photo with a lens profile match." Only rotation implemented; contract also asks for perspective. Reviewer's length-weighted median of near-vertical segments puts 001 0.80, 010 0.62, 012 0.66, 014 0.61, 015 0.75 degrees (over 0.5); builder's dominant-angle reading reports <=0.11 on all. Reviewer says its method is rough: a disagreement to resolve, not proof. To pass: report lens straightness per photo before vs after on the same frame; fix or honestly name 001/009/012; measure verticals across the lines.
5. "Tuned once, then frozen" is untrue. After ea11545 "freeze it", shared look constants changed in 3093bab, 496a0e1, 4c178c7, b99903e, each naming a set that missed its MLS twin. Reviewer re-measured the 16 comparisons: all pass, thinnest 004 at 14.1% vs 15% limit. To pass: report states the constants were fitted on these same 16 photos. Whether repeated tuning is acceptable is a contract question for the navigator.
6. Spend understated: page and report say $1.0325; ledger shows $1.1403 for unit 2's 206 calls on Oct 29 (incl. two unsettled reservations at estimate). Still under $2.00, criterion 8 holds. To pass: show the real total.
7. Visible purple cast on floors near windows in 003, 007, 009 (seen in review images, not in per-photo color averages). Works against "walls look their true color."

Contract problem (not builder defect): A2 asks the merge be scored on brightness against the MLS photo, which criterion 11 forbids. Builder followed 11 (right call). Navigator should fix A2.

## Verified sound
- ./scripts/check (META_API_KEY unset): 154 tests, CHECK OK. Only loosening: sk- pattern now needs 20+ chars, own commit with reason. Installed hooks byte-identical to scripts/git-hooks/.
- Hygiene: 10 banned-string entries, zero hits everywhere; 25 commits all noreply email; no remote; no raw photos/outputs/ledger/.navigator tracked; 153 output images, none with GPS/serial.
- Cap $40 constant, $39 reservation ceiling, refusal tests present; first-party allowlist; urllib only in meta_client.py; key only from META_API_KEY; AppFolio labeled existing tool. Worst reserve-to-bill ratio 2.0, none under 1.
- Reproduced from saved masks, no Meta calls: 17/17 finished; 18 masks; 15 rejections with reasons; 0 pixels changed outside masks on all 17; noise drops on all 17; edge ratio 0.946-1.021; shipped files match HEAD within JPEG error (0.9-2.4 levels); processing never reads the MLS twin.
