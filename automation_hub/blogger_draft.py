"""Blogger draft creation: explicit approval, scoped account, one remote call.

This is a guarded connector under development. The UI never publishes a post
publicly. Creating a *remote* Blogger draft has a real side effect; all
network-bearing methods must be invoked from deliberate user interactions.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
import hashlib
import html
from pathlib import Path
from typing import Protocol

from .publishing_plan import PublishingDraft, PublishingPlanError


MAX_TEXT_BYTES = 1024 * 1024


class DraftCreationError(RuntimeError):
    """A Blogger remote draft could not be safely created."""


@dataclass(frozen=True)
class PreparedBloggerDraft:
    blog_id: str
    title: str
    content_html: str
    source_path: str
    source_sha256: str


@dataclass(frozen=True)
class RemoteBloggerDraft:
    blog_id: str
    post_id: str
    url: str
    state: str = "REMOTE_DRAFT"


class BloggerDraftConnector(Protocol):
    def list_blogs(self) -> list[dict[str, str]]: ...
    def create_draft(self, blog_id: str, title: str, html_body: str) -> dict: ...


def _read_safe_text(path: Path) -> tuple[bytes, str]:
    # Symlink and size checks bound local loading. Remote filesystems remain
    # outside the intended threat model; a full atomic lock is not possible.
    if path.is_symlink() or not path.is_file():
        raise PublishingPlanError("Select an existing non-link local article")
    size = path.stat().st_size
    if not 0 < size <= MAX_TEXT_BYTES:
        raise PublishingPlanError("Article must be between 1 byte and 1 MB")
    contents = path.read_bytes()
    if not 0 < len(contents) <= MAX_TEXT_BYTES:
        raise PublishingPlanError("Article size changed during reading")
    try:
        return contents, contents.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise PublishingPlanError("Use a UTF-8 text file") from exc


def _safe_html(text: str) -> str:
    # Markdown is intentionally treated as plain text until a vetted renderer
    # exists. Never treat source as trusted HTML, scripts or embed markup.
    paragraphs = [part for part in text.replace("\r\n", "\n").split("\n\n") if part.strip()]
    return "\n".join("<p>" + html.escape(part).replace("\n", "<br>") + "</p>" for part in paragraphs)


def prepare_blogger_draft(draft: PublishingDraft, blog_id: str) -> PreparedBloggerDraft:
    if draft.platform != "blogger" or draft.visibility != "draft":
        raise PublishingPlanError("Only Blogger remote drafts can be prepared")
    if draft.scheduled_at is not None:
        raise PublishingPlanError("Remote scheduling is not implemented")
    if not blog_id.strip().isdigit():
        raise PublishingPlanError("Select a connected Blogger blog")
    source = Path(draft.source_path)
    if source.suffix.lower() not in (".txt", ".md"):
        raise PublishingPlanError(
            "Only UTF-8 .txt/.md are supported for remote drafts; HTML and images need review"
        )
    binary, text = _read_safe_text(source)
    if not text.strip():
        raise PublishingPlanError("Article text is empty")
    if not draft.title.strip() or len(draft.title.strip()) > 200:
        raise PublishingPlanError("Article title is invalid")
    # Explain to customers: the description becomes a paragraph at the start.
    intro = _safe_html(draft.description) if draft.description else ""
    body = _safe_html(text)
    return PreparedBloggerDraft(
        blog_id=blog_id,
        title=draft.title.strip(),
        content_html=(intro + "\n" + body).strip(),
        source_path=str(source),
        source_sha256=hashlib.sha256(binary).hexdigest(),
    )


class DraftPreflightError(DraftCreationError):
    """Definite rejection BEFORE posts.insert; safe to fix and preview again."""


class DraftOutcomeUnknownError(DraftCreationError):
    """The posts.insert request may have reached Blogger. Never auto-retry."""


@dataclass(frozen=True)
class DraftApproval:
    """An explicit, short-lived user confirmation bound to this exact draft."""
    blog_id: str
    title: str
    source_sha256: str
    html_sha256: str
    issued_at_utc: datetime
    confirmed: bool


def issue_draft_approval(prepared: PreparedBloggerDraft, *, confirmed: bool) -> DraftApproval:
    """Called only after the user has answered the specific GUI confirmation."""
    return DraftApproval(
        blog_id=prepared.blog_id, title=prepared.title,
        source_sha256=prepared.source_sha256,
        html_sha256=hashlib.sha256(prepared.content_html.encode("utf-8")).hexdigest(),
        issued_at_utc=datetime.now(timezone.utc), confirmed=confirmed,
    )


def verify_draft_approval(prepared: PreparedBloggerDraft, approval: DraftApproval) -> None:
    if not isinstance(approval, DraftApproval) or not approval.confirmed:
        raise DraftPreflightError("Explicit user approval is required before sending")
    now = datetime.now(timezone.utc)
    if approval.issued_at_utc.tzinfo is None or not (
        timedelta(seconds=0) <= now - approval.issued_at_utc <= timedelta(minutes=5)
    ):
        raise DraftPreflightError("Approval has expired; preview and approve again")
    if (prepared.blog_id != approval.blog_id or
            prepared.title != approval.title or
            prepared.source_sha256 != approval.source_sha256 or
            hashlib.sha256(prepared.content_html.encode("utf-8")).hexdigest()
                != approval.html_sha256):
        raise DraftPreflightError("Draft changed since approval; review again")


def verify_draft_preflight(
    connector: BloggerDraftConnector, prepared: PreparedBloggerDraft,
    approval: DraftApproval,
) -> None:
    """Checks performed BEFORE reserving an attempt; no remote POST is sent."""
    verify_draft_approval(prepared, approval)
    try:
        raw, _ = _read_safe_text(Path(prepared.source_path))
    except (OSError, PublishingPlanError) as exc:
        raise DraftPreflightError("Article is unavailable; review the file again") from exc
    if hashlib.sha256(raw).hexdigest() != prepared.source_sha256:
        raise DraftPreflightError("Article changed after preview; review it again")
    try:
        authorized = connector.list_blogs()
    except Exception as exc:
        raise DraftPreflightError(
            "Blogger account check failed before upload. Check login and network; "
            "nothing was sent"
        ) from exc
    if prepared.blog_id not in {str(x.get("id", "")) for x in authorized}:
        raise DraftPreflightError(
            "Blogger permission denied or blog not found; nothing was sent"
        )


def insert_blogger_draft_once(
    connector: BloggerDraftConnector, prepared: PreparedBloggerDraft,
    approval: DraftApproval,
) -> RemoteBloggerDraft:
    """One posts.insert attempt. Failure can be ambiguous; no automatic replay."""
    verify_draft_approval(prepared, approval)
    try:
        response = connector.create_draft(
            prepared.blog_id, prepared.title, prepared.content_html
        )
    except Exception as exc:
        raise DraftOutcomeUnknownError(
            "Blogger POST result unknown. Check remote drafts before any retry"
        ) from exc
    if not isinstance(response, dict) or not str(response.get("id", "")).strip():
        raise DraftOutcomeUnknownError(
            "Blogger did not confirm a post ID. Check remote drafts before any retry"
        )
    return RemoteBloggerDraft(
        blog_id=prepared.blog_id, post_id=str(response["id"]),
        url=str(response.get("url", "")),
    )


def create_approved_remote_draft(
    connector: BloggerDraftConnector,
    prepared: PreparedBloggerDraft,
    *,
    approval: DraftApproval,
) -> RemoteBloggerDraft:
    """Direct-use path: always requires explicit approval and an authorized blog."""
    verify_draft_preflight(connector, prepared, approval)
    return insert_blogger_draft_once(connector, prepared, approval)


def submit_journaled_blogger_draft(
    connector: BloggerDraftConnector,
    prepared: PreparedBloggerDraft,
    journal: "PublishingJournal",
    *,
    approval: DraftApproval,
) -> RemoteBloggerDraft:
    """Preflight before reservation; classify any later POST uncertainty honestly."""
    from .publishing_history import fingerprint_for, PublishingJournalError

    # Failed OAuth, missing blog or changed article must NOT create a retry lock.
    verify_draft_preflight(connector, prepared, approval)
    key = fingerprint_for(
        platform="blogger", account_id=prepared.blog_id, title=prepared.title,
        source_sha256=prepared.source_sha256, html_body=prepared.content_html,
    )
    journal.reserve(
        fingerprint=key, platform="blogger", account_id=prepared.blog_id,
        filename=Path(prepared.source_path).name, title=prepared.title,
    )
    try:
        result = insert_blogger_draft_once(connector, prepared, approval)
    except Exception:
        # From here posts.insert MAY have happened. Never auto retry.
        try:
            journal.mark(key, "OUTCOME_UNKNOWN")
        except PublishingJournalError:
            # A PENDING_REMOTE row also blocks a duplicate after a crash.
            pass
        raise
    try:
        journal.mark(key, "REMOTE_DRAFT", result.post_id)
    except PublishingJournalError as exc:
        raise DraftCreationError(
            "Blogger confirmed remote draft ID " + result.post_id +
            ", but local history write failed; do NOT resend"
        ) from exc
    return result
