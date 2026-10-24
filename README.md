# Workflow Automation Hub -2

Consumer UI, separate product from the regular Workflow Automation Hub.

## Intended product direction: cross-platform content publishing

The owner's intended consumer experience is **select local content → connect account
with official OAuth → choose destination → preview → schedule/publish → show true results**.
Screenshot saving in Browser -2 is not the core product. The unified implementation
and release requirements are in [CONTENT_PUBLISHING_V2_PLAN.md](CONTENT_PUBLISHING_V2_PLAN.md).

The **Prepare post** tab validates Blogger article files and YouTube video files
locally. An experimental Blogger-only button can create one **REMOTE DRAFT** using
the already configured Google OAuth Desktop client, verified blog selection, a
matching file fingerprint and explicit user approval. Existing Blogger link
insertion remains a separate feature. No live Blogger test has been authorized
or executed; this feature is NOT production-qualified yet.

**No YouTube upload, remote scheduling, Blogger public publication or universal
social-media integrations are implemented.** Only UTF-8 .txt/.md article files
can create remote Blogger drafts; .html can be previewed locally but cannot be
sent until vetted conversion is implemented. Markdown formatting is treated as
escaped plain text. The description becomes a first paragraph. All general
upload/publication marketing claims remain HOLD.

## Actual implemented scope
The current app manages **Google Blogger link-insertion jobs only**. It is not an arbitrary website/API automation hub, and does not generate blog articles. Users need their own Google OAuth Desktop client before live Blogger connection. Google login/remote mutation is NOT part of this QA.

Consumer -2 home screen shows only real saved Blogger jobs, not synthetic demo jobs. Missing and corrupt job records are distinguished.

## Isolation and provenance
- Ported exact source from `shihuiarenjinba-png/workflow-automation-hub` commit `a4bd0419e66b1dfaa6208564dd07d07ab2cd662b` (2026-10-24).
- Root app storage namespace: `WorkflowAutomationHub2`, separate from old product.
- Windows task name prefix: `WorkflowAutomationHub2_`, separate from old product.
- QA-only source branch `codex/consumer-v2-initial-20261024`. No main/release changes.
- Windows workflow builds a QA_UNSIGNED **EXE only**; no MSIX, Store submission or signing.

## HOLD before sale
- Google OAuth consent, verification, live API permissions, and technical-user credential setup simplification
- Third-party licence and notice audit
- Real Windows GUI at 1024x768 / 1280x720, JP/EN, restart/restore, no accidental remote mutations
- Independent -2 Partner Center Store ID / Package Identity / Publisher / PFN / Version (all UNKNOWN)
- Store listing assets, MSIX QA, certification and explicit submission approval

## Local checks
```powershell
python -m pip install --require-hashes -r requirements-lock.txt
python -m unittest discover -s tests -v
python desktop_app.py --self-test
```
