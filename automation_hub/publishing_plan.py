"""Offline-only posting draft validation. No OAuth, browser, network or upload.

This module prepares a candidate publishing plan for the future Blogger/YouTube
connectors. Producing a plan does NOT mean the content was uploaded, scheduled
or authorized. The public posting action must never be enabled from this module.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

BLOGGER_EXTENSIONS = frozenset({".txt", ".md", ".html", ".htm"})
YOUTUBE_EXTENSIONS = frozenset({".mp4", ".mov", ".m4v", ".webm"})
MAX_TITLE = {"blogger": 200, "youtube": 100}
MAX_DESCRIPTION = 5000


class PublishingPlanError(ValueError):
    """Local validation failed before any external operation."""


@dataclass(frozen=True)
class PublishingDraft:
    platform: str
    source_path: str
    filename: str
    file_bytes: int
    title: str
    description: str
    visibility: str
    scheduled_at: str | None
    state: str = "NOT_CONNECTED_NOT_UPLOADED"

    def preview(self) -> dict[str, str | int | None]:
        """Return only file metadata, never content or credentials."""
        return {
            "platform": self.platform,
            "filename": self.filename,
            "file_bytes": self.file_bytes,
            "title": self.title,
            "description": self.description,
            "visibility": self.visibility,
            "scheduled_at": self.scheduled_at,
            "state": self.state,
        }


def prepare_publishing_draft(
    *,
    platform: str,
    source_path: str | Path,
    title: str,
    description: str = "",
    scheduled_at: str | None = None,
) -> PublishingDraft:
    """Strict, local-only file/metadata check for a future publishing UI.

    Intentionally limits output visibility to Blogger 'draft' and YouTube
    'private'. Posting, OAuth and scheduling are NOT implemented.
    """
    normalized = platform.strip().lower()
    if normalized not in ("blogger", "youtube"):
        raise PublishingPlanError("Select Blogger or YouTube / BloggerかYouTubeを選択してください")
    p = Path(source_path).expanduser()
    if p.is_symlink():
        raise PublishingPlanError("Symbolic-link files are not supported")
    if not p.is_file():
        raise PublishingPlanError("The source file does not exist / ファイルが見つかりません")
    accepted = BLOGGER_EXTENSIONS if normalized == "blogger" else YOUTUBE_EXTENSIONS
    if p.suffix.lower() not in accepted:
        raise PublishingPlanError("File type is not supported for this destination")
    size = p.stat().st_size
    if size <= 0:
        raise PublishingPlanError("Empty files cannot be posted")
    if len(title.strip()) == 0 or len(title.strip()) > MAX_TITLE[normalized]:
        raise PublishingPlanError("Title is missing or too long")
    if len(description) > MAX_DESCRIPTION:
        raise PublishingPlanError("Description is too long")
    if scheduled_at is not None:
        try:
            at = datetime.fromisoformat(scheduled_at)
        except ValueError as exc:
            raise PublishingPlanError("Invalid scheduled date/time") from exc
        if at.tzinfo is None or at.utcoffset() is None:
            raise PublishingPlanError("Schedule must include an explicit timezone")
    return PublishingDraft(
        platform=normalized,
        source_path=str(p.resolve()),
        filename=p.name,
        file_bytes=size,
        title=title.strip(),
        description=description,
        visibility="draft" if normalized == "blogger" else "private",
        scheduled_at=scheduled_at,
    )
