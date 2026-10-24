# -2 製品方針変更：複数サービスへのコンテンツ自動投稿基盤

2026-10-24 — user-intent correction / **DESIGN & QA ONLY, NOT LIVE POSTING**

## Purpose (user's intended product)
One beginner-friendly Windows app that selects local files, prepares posts for Blogger / YouTube and ultimately other supported services, connects accounts with official OAuth, previews exactly what will be posted, schedules or executes, and shows history/retries. Users should NOT be forced to operate Folder -2, Browser -2, and Hub -2 together to accomplish a post.

**Screenshots are NOT the main selling point.** Browser screenshots/recording are secondary diagnostics, not an upload solution.

## Truthful current state
- `Workflow-Automation-Hub-2`: existing live engine is for **Blogger link insertion in existing posts**, not general article publishing.
- New `automation_hub/publishing_plan.py`: **OFFLINE** file and metadata validator for Blogger articles and YouTube videos, defaults to Blogger **draft** / YouTube **private**, without any network, account sign-in, upload, remote draft, scheduling or persistent queue.
- UI new tab "投稿の準備（試作）" allows local-only preview. Clearly says actual publishing is unavailable. It must not display fake connected accounts, queued jobs, completed uploads or public publication.
- `Browser-Automation-Runner-2`: Playwright click/fill/download/screenshot runner. **Not an uploader** and not needed for Google APIs. Do not infer that it publishes to YouTube/Blogger.
- `Folder-Automation-Engine-2`: independent local file organizer, optional producer of inputs for the publishing app, not mandatory.

## UX target, one app and one process
1. Choose destination card **YouTube** / **Blogger** (others visible only when actually integrated; disabled otherwise).
2. Connect an account using Google OAuth 2.0 (the consent page is provided by Google). Support least-privilege scopes, token revocation, expired-login handling and account/channel verification; never ask users for passwords.
3. Pick source file(s): video for YouTube, article content for Blogger; show allowed formats, size, missing-file and rights checks.
4. Enter title, description and platform-required metadata. Blogger may need HTML body conversion and hosted images; YouTube needs audience / child-directed status, privacy, and relevant platform fields. Never silently publish publicly.
5. Show an actionable preview: target service/account, filenames, privacy/draft settings, scheduled time in local timezone, operation and side-effect warnings.
6. Publish only with explicit approval. API implementations must use service-native upload/post endpoints, not mimic site UI where an official API exists.
7. Durable job state with persistent IDs: DRAFT → READY → AWAITING_USER_APPROVAL → UPLOADING → REMOTE_DRAFT/PRIVATE/POSTED/FAILED. An upload timeout must not cause duplicate posts: reconcile remote post/video ID before retry.
8. Show true result URL/ID, error reason, safe retry and cancellation boundaries. Never represent a local preview or browser screenshot as successful publication.

## Integration requirements and gates

### Blogger (P0 first)
- Official Blogger API v3 `posts.insert` for draft creation, `posts.publish` for publication. Requires user OAuth scope `https://www.googleapis.com/auth/blogger`.
- Existing **Blogger link insertion** is a separate capability; don't assume it creates new articles.
- Article conversion and images must be implemented and validated; don't promise that local image files are automatically hosted. Start with safe text/HTML article draft only.
- E2E QA: test account / draft only, with action-time authorization; prevent accidental public posts.

### YouTube (P0 after Blogger draft)
- Official YouTube Data API v3 `videos.insert`; uploads user-selected video with user OAuth, minimum `youtube.upload` scope where applicable.
- Support resumable uploads, interruptions, progress, quota/error handling, duplicate prevention, thumbnail/metadata validation and user-visible privacy.
- Developer documentation as of October 2026 conflicts on whether **unverified API projects** must always upload as private. Do not rely on a categorical assumption. Confirm actual project/API audit and test account before selling a "public auto-upload" promise.
- API project and public OAuth verification/audit may be required. API quotas are project-specific and change. Check current Cloud Console, not a hard-coded fixed sales promise.

### Other services (P1, never advertise before supported)
- Plug-in/adapter per platform, with dedicated authorization, data formats, rate limits, publishing permissions, status mappings, and platform policy checks.
- Browser fallback only for an explicitly authorized, permitted site that has no suitable API; do not automate Google login screens or capture user passwords.

## Privacy/safety
- Keep tokens out of logs/config exports, restrict storage (Windows Credential Manager/DPAPI where appropriate), let user revoke, no secrets in GitHub workflows or artifact.
- Safe mode first, no remote writes during initial UI QA. No uploading to personal accounts without explicit user authorization.
- Scheduled posts depend on online Windows machine or supported cloud scheduling; explain PC-offline limitations before enabling scheduling.
- Distinguish **local draft** vs **remote draft** vs **published** with different status labels.

## Acceptance / rollout
- Stage A (current branch): offline file selection + truthful preview + tests + GUI screenshots.
- Stage B: first-party Blogger OAuth and remote draft creation, E2E on controlled test blog after authorization, then explicit publish step.
- Stage C: YouTube OAuth, private video resumable upload on test channel, correct remote video ID and progress, then verification / policy review for public uploads.
- Stage D: local queue/scheduling, durable state and reconciliation, exception UX and real Windows GUI QA.
- Stage E: independent -2 Microsoft Store Identity/PFN/version verification, QA_UNSIGNED MSIX, WACK, privacy/rights audit, then user-approved Store submission.
- **No main/release change; no existing Store Identity copied; no Store upload or publication.**

Official API sources:
- https://developers.google.com/blogger/docs/3.0/reference/posts/insert
- https://developers.google.com/blogger/docs/3.0/reference/posts/publish
- https://developers.google.com/youtube/data/reference/rest/v3/videos/insert
- https://developers.google.com/youtube/data/guides/auth/installed-apps
- https://developers.google.com/identity/protocols/oauth2/production-readiness/sensitive-scope-verification
