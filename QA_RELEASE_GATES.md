# Workflow Automation Hub -2 — independent Windows QA

- Source target base `23d7cc2b7a08b33d8fa512cae859bca92f7dff4c`
- Separate AppData and Windows task prefix from regular Hub.
- This target repo contains no regular-product Store manifests or Store ID.
- Windows QA only: unit tests, EXE self-diagnostics, QA_UNSIGNED EXE package and source provenance.
- Current integrated API scope: Blogger links only. Google OAuth login, Blogger writes and scheduled task registration are excluded from QA actions.
- Manual UX, third-party compliance and any official Google permissions are HOLD.
- New -2 Store ID / Identity / Publisher / PFN / Version all UNKNOWN; no Store MSIX packaging until verified.
- No main/release merge, signature, submission or publication.
