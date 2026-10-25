# CODE OWNER HANDOFF — Hub -2 P0 repair (2026-10-25)

**Status: HOLD. Work was committed on GitHub, NOT in portfolio-audit.**

## GitHub source
- Repo: https://github.com/shihuiarenjinba-png/Workflow-Automation-Hub-2
- Original branch: codex/publishing-history-sale-gates-20261025
- Verified original HEAD: 0e5e21e5167868b301104da46e9da1d359a21717
- New branch: codex/hub-v2-p0-qa-security-20261025
- Draft PR #7: https://github.com/shihuiarenjinba-png/Workflow-Automation-Hub-2/pull/7
- Main/release and unrelated portfolio-audit remain untouched. NO live Google authorization, posting, MSIX submission or merge.

## P0 code fixes
1. Lower-layer explicit approval: GUI creates DraftApproval only after answer YES; bound to blog ID, title, source SHA256, HTML SHA256 and 5-minute time window. submit_journaled_blogger_draft and insert_blogger_draft_once validate it, removing approved=True hardcoding. This is protection against accidental call-site bypass, not an unforgeable security boundary.
2. Pre-POST errors: file mismatch, Blogger auth failure, inaccessible blog and network errors are classified BEFORE SQLite reservation, so do not generate OUTCOME_UNKNOWN locks. OAuth 401 and permission 403 have distinct exceptions. Once posts.insert is attempted, timeouts or missing post IDs conservatively remain OUTCOME_UNKNOWN, without auto retry.
3. Spawn-process race test verifies exactly one of four simultaneous reservations succeeds. Crash-boundary test kills a separate process after durable reserve; next attempt is still blocked.
4. GUI QA now checks requested dimensions versus measured viewport; mismatch outputs explicit gui_size_acceptance=FAIL in JSON, screenshot evidence, and nonzero Actions step. This is an intentional failed release gate, not a regression to paper over.
5. Hosted Actions updated to checkout@v5, setup-python@v6, upload-artifact@v6 for Node24; upload-artifact@v5 was verified to still warn.

## Last checked Windows runs
- Hub: https://github.com/shihuiarenjinba-png/Workflow-Automation-Hub-2/actions/runs/40205671397
- Hub: 134 Python tests PASS; QA_UNSIGNED EXE build and packaged self-test PASS.
- Hub QA EXE SHA256: 1df25ce7c45b0231ca5c093481be74c9ccb2d888e5a953400de678ed87f030ba
- Hub overall Actions FAIL because strict GUI acceptance identified mismatch.
- 1024×768 requested / 1024×749 measured; 1280×720 requested / 1028×720 measured.
- The GUI evidence and unsigned EXE artifacts were still uploaded in the failed run.
- Folder Node24 update: https://github.com/shihuiarenjinba-png/Folder-Automation-Engine-2/pull/4 ; run https://github.com/shihuiarenjinba-png/Folder-Automation-Engine-2/actions/runs/40205524925 succeeded.
- Browser Node24 update: https://github.com/shihuiarenjinba-png/Browser-Automation-Runner-2/pull/5 ; run https://github.com/shihuiarenjinba-png/Browser-Automation-Runner-2/actions/runs/40205532845 succeeded.

## Remaining HOLD
- Re-run strict GUI acceptance at real 1024×768 and 1280×720 on a Windows desktop with adequate display, including 125%/150% DPI and keyboard navigation.
- Perform actual Google OAuth onboarding, remote token revocation and deliberately approved TEST Blogger blog remote draft E2E; no live Google account access in this repair.
- Remote post-ID reconciliation, audit all app logs for secrets (not only SQLite rows), accurate network classification and persistent job recovery need deeper QA.
- YouTube video upload, Store Identity/Publisher/PFN, signed MSIX, WACK, live install QA and Partner Center listing/submission are NOT complete.
- No PR merge, release GO or real service publication without explicit approval.
