"""Blogger draft creation: explicit approval, scoped account, one remote call.

This is a guarded connector under development. The UI never publishes a post
publicly. Creating a *remote* Blogger draft has a real side effect; all
network-bearing methods must be invoked from deliberate user interactions.
"""
from __future__ import annotations

from dataclasses import dataclass
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


def create_approved_remote_draft(
    connector: BloggerDraftConnector,
    prepared: PreparedBloggerDraft,
    *,
    approved: bool,
    expected_sha256: str,
) -> RemoteBloggerDraft:
    """Exactly one insert, no automatic retry if the remote outcome is unknown."""
    if not approved or not expected_sha256 or expected_sha256 != prepared.source_sha256:
        raise DraftCreationError("Review and explicitly approve the unchanged article first")
    source = Path(prepared.source_path)
    raw, _ = _read_safe_text(source)
    if hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise DraftCreationError("File changed after preview; review it again")

    # Always re-validate the currently authorized blog before a remote write.
    if prepared.blog_id not in {str(x.get("id", "")) for x in connector.list_blogs()}:
        raise DraftCreationError("Selected blog is not accessible in the connected account")
    try:
        response = connector.create_draft(prepared.blog_id, prepared.title, prepared.content_html)
    except Exception as exc:
        # We cannot determine whether a timed-out POST succeeded; don't retry.
        raise DraftCreationError(
            "Draft result uncertain. Check Blogger before trying again; automatic retry disabled"
        ) from exc
    if not isinstance(response, dict) or not str(response.get("id", "")).strip():
        raise DraftCreationError(
            "Blogger did not return a post ID. Check Blogger before attempting another upload"
        )
    return RemoteBloggerDraft(
        blog_id=prepared.blog_id,
        post_id=str(response["id"]),
        url=str(response.get("url", "")),
    )
