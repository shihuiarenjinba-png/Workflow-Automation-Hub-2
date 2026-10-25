# Hub -2: market-informed UX and Microsoft Store readiness (2026-10-25)

**Purpose:** A consumer Windows app that selects a file, selects a supported
channel, connects an authorized account, reviews the content, and sends a draft
or permitted upload with clear history. This is a working-branch QA plan, not
a declaration that Store certification requirements have been met.

## Competitive patterns to learn from (not copy code, assets or branding)

- **Buffer**: distinct draft / approval / calendar states and selected accounts.
  Implement true local-vs-remote state before implementing approval teams.
  Official: https://support.buffer.com/articles/managing-and-approving-draft-posts-57li7M8tDA
- **Metricool**: composer preview, media library, network-specific metadata,
  CSV import, calendar filters. Begin with a readable one-file preview and
  visible actual destination. No unimplemented service advertised.
  Official: https://metricool.com/planner/
- **Publer**: CSV bulk import, preview and channel-specific posting.
  CSV bulk import and queue are future phases and must validate each row
  before any side effects. No claims of batch scheduling yet.
  Official: https://publer.com/help/en/article/how-to-schedule-in-bulk-using-a-csv-file-3yvwt
- **Zapier**: visible run history, manual replay with step/status details.
  Never blindly replay a potentially successful Blogger POST.
  Official: https://help.zapier.com/hc/en-us/articles/19220226086797-What-is-replay

## Implemented on this branch

- Google Blogger API remote draft remains explicitly opt-in. Title, local
  UTF-8 .txt/.md file, selected authorized Blogger blog and content fingerprint
  are verified before any Google API write.
- **Local SQLite publishing history** tracks:
  - `PENDING_REMOTE`: a request may be in progress or the app terminated.
  - `REMOTE_DRAFT`: Blogger confirmed a remote post ID.
  - `OUTCOME_UNKNOWN`: failure/timeout may still have created a remote draft.
- A duplicate key is based on platform, authorized blog ID, article content,
  file SHA-256 and title. Unique SQLite key blocks double submission
  after restart and across processes. No automatic retries for mutation.
- The history window reads actual records; it never invents published posts.
- History never stores OAuth tokens, article body, passwords or client secrets.
  Article title, source filename, connected blog ID and confirmed post ID are
  retained locally; explain this to users in the eventual privacy notice.
- OAuth credentials already use local DPAPI in the existing connector.

## Still NOT implemented

- YouTube OAuth/video upload, true scheduled publishing, multi-account calendar,
  CSV queue, post approval teams, media library, public Blogger publishing,
  image hosting / Markdown rendering, conflict-free remote reconciliation.
- More reliable error categorization, account linking improvements,
  cross-process lifetime tests and consent verification remain QA gates.
- Browser -2 screenshot capture is not a social publishing feature.

## Microsoft Store and customer-sales gate (all HOLD unless marked)

- [ ] Confirm Store listing product name, unique -2 Store ID, Package Identity,
  Publisher, version and PFN **from Partner Center**; do not guess or copy
  existing regular Hub values.
- [ ] Produce correctly branded, legally usable icon and in-app images. Audit
  Google, YouTube, Blogger marks (referential naming only), and all third-party
  code / licence / NOTICE obligations. No copied competitor graphics.
- [ ] Provide a **real** public privacy policy URL covering selected files,
  OAuth scopes, account/data access, local SQLite history, logging, data
  retention and deletion, user consent and support.
  Microsoft does not supply a privacy policy on the developer's behalf.
- [ ] Provide usable customer support contact, help page, version/about
  information, limits of offline vs online and internet requirements.
- [ ] Create accurate JP and EN Store listing text with only actually
  implemented features and real app images. For MSIX, Microsoft requires
  **at least one Store screenshot** and recommends four or more.
  Desktop screenshot must be at least **1366×768** (PNG) according to
  current Windows documentation; 1024×768 is an in-app usability QA size,
  not an acceptable Store screenshot size.
- [ ] Windows 11 manual QA at 1024×768 and 1280×720 with 125/150% scaling,
  keyboard navigation, focus order, visible status, proper error recovery.
- [ ] Controlled live Blogger QA using the user's expressly authorized
  **test blog** and test Google OAuth project, remote draft only. Test
  permission denial, expired token, network loss and post-ID reconciliation.
- [ ] YouTube feature marketing remains disabled until videos.insert private
  upload and real authenticated QA pass; review API verification/audit/privacy.
- [ ] Verify signing, unsigned QA MSIX identity, EXE equivalence and hashes,
  WACK and Store upload checks independently; don't turn CI success into
  certification success.
- [ ] Separate user authorization before real publishing, OAuth login,
  Partner Center submission or publication.

## Manual verification / owner handoff

On the working PR: confirm screenshot evidence, review read-only history and
user-facing warning text. Never assume a successful local preview means an
account is connected or a remote blog draft exists.

Microsoft official references:
- https://learn.microsoft.com/en-us/windows/apps/publish/publish-your-app/msix/support-info
- https://learn.microsoft.com/en-us/windows/apps/publish/publish-your-app/msix/add-and-edit-store-listing-info
- https://learn.microsoft.com/en-us/windows/apps/publish/publish-your-app/screenshots-and-images
- https://developers.google.com/blogger/docs/3.0/reference/posts/insert
