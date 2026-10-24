from __future__ import annotations

import html as html_lib
import json
import os
import re
import tempfile
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, TYPE_CHECKING
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from .audit import AuditLogger
from .locks import JobExecutionLock
from .models import BloggerLinkJob
from .paths import blogger_backup_dir

if TYPE_CHECKING:
    from .google_blogger import GoogleBloggerConnector


class BloggerAutomationError(RuntimeError):
    pass


@dataclass
class LinkInsertionResult:
    html: str
    changed: bool
    reason: str


@dataclass
class JobRunResult:
    scanned: int = 0
    changed: int = 0
    skipped_existing: int = 0
    skipped_no_match: int = 0


def validate_http_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise BloggerAutomationError(
            "link_url must be an absolute http/https URL / link_urlはhttp/httpsの絶対URLで指定してください"
        )
    if parsed.username or parsed.password:
        raise BloggerAutomationError("Credentials are not allowed in link URLs / リンクURLに認証情報は含められません")


class _SafeTextLocator(HTMLParser):
    """Locate plain-text matches without rewriting or normalizing the source HTML."""

    IGNORED = {"a", "script", "style", "code", "pre", "textarea"}

    def __init__(self, source: str, target: str) -> None:
        super().__init__(convert_charrefs=False)
        self.source = source
        self.target = target
        self.ignored_depth = 0
        self.match_start: int | None = None
        self.line_starts = [0]
        for index, char in enumerate(source):
            if char == "\n":
                self.line_starts.append(index + 1)

    def _absolute_position(self) -> int | None:
        line, offset = self.getpos()
        if line < 1 or line > len(self.line_starts):
            return None
        position = self.line_starts[line - 1] + offset
        if not 0 <= position <= len(self.source):
            return None
        return position

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() in self.IGNORED:
            self.ignored_depth += 1

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        return

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in self.IGNORED and self.ignored_depth > 0:
            self.ignored_depth -= 1

    def handle_data(self, data: str) -> None:
        if self.match_start is not None or self.ignored_depth > 0:
            return
        index = data.find(self.target)
        if index < 0:
            return
        start = self._absolute_position()
        if start is None:
            return
        # Do not guess when HTMLParser's view does not map exactly to the raw
        # source. This deliberately favors a safe no-op over changing the wrong
        # bytes in the Blogger post.
        if self.source[start:start + len(data)] != data:
            return
        self.match_start = start + index


def _find_safe_text_match(source: str, target: str) -> int | None:
    locator = _SafeTextLocator(source, target)
    try:
        locator.feed(source)
        locator.close()
    except Exception as exc:
        raise BloggerAutomationError(f"Could not parse Blogger HTML / Blogger HTMLを解析できません: {exc}") from exc
    return locator.match_start


def insert_link_once(html: str, target_text: str, link_url: str, anchor_text: str | None = None) -> LinkInsertionResult:
    if not target_text:
        raise BloggerAutomationError("target_text must not be empty / 検索文字は空にできません")
    validate_http_url(link_url)
    anchor_text = anchor_text or target_text
    source = html or ""

    # BeautifulSoup is used only for read-only duplicate detection. The output
    # HTML is never serialized from the parsed tree, so unrelated Blogger HTML
    # remains byte-for-byte unchanged.
    try:
        soup = BeautifulSoup(source, "html.parser")
    except Exception as exc:
        raise BloggerAutomationError(f"Could not parse Blogger HTML / Blogger HTMLを解析できません: {exc}") from exc
    for anchor in soup.find_all("a", href=True):
        if str(anchor.get("href", "")) == link_url:
            return LinkInsertionResult(source, False, "link_already_present")

    start = _find_safe_text_match(source, target_text)
    if start is None:
        return LinkInsertionResult(source, False, "target_not_found")
    end = start + len(target_text)
    safe_href = html_lib.escape(link_url, quote=True)
    safe_anchor = html_lib.escape(anchor_text, quote=False)
    link = f'<a href="{safe_href}">{safe_anchor}</a>'
    changed = source[:start] + link + source[end:]
    return LinkInsertionResult(changed, True, "inserted")


def _safe_component(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]", "_", value)[:100]
    return cleaned or "unknown"


def _write_backup(job: BloggerLinkJob, post: dict[str, Any], original_content: str, backup_root: Path) -> Path:
    backup_root.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ")
    post_id = str(post.get("id", "unknown"))
    filename = f"{_safe_component(job.id)}_{_safe_component(job.blog_id)}_{_safe_component(post_id)}_{timestamp}.json"
    path = backup_root / filename
    payload = {
        "backup_version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "job_id": job.id,
        "blog_id": job.blog_id,
        "post_id": post_id,
        "title": str(post.get("title", "")),
        "url": str(post.get("url", "")),
        "published": str(post.get("published", "")),
        "updated": str(post.get("updated", "")),
        "original_content": original_content,
    }
    content = json.dumps(payload, ensure_ascii=False, indent=2)
    fd, temp_name = tempfile.mkstemp(prefix=filename + ".", suffix=".tmp", dir=backup_root)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(content)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)
    return path


def _run_link_job_inner(
    connector: "GoogleBloggerConnector",
    job: BloggerLinkJob,
    *,
    dry_run: bool,
    audit: AuditLogger,
    backup_root: Path | None,
) -> JobRunResult:
    result = JobRunResult()
    audit.write("blogger_job_start", job_id=job.id, dry_run=dry_run, blog_id=job.blog_id)
    posts = connector.list_posts(job.blog_id, status=job.status, max_posts=job.max_posts)
    for post in posts:
        result.scanned += 1
        post_id = str(post.get("id", ""))
        if not post_id:
            raise BloggerAutomationError("Blogger API returned a post without id / Blogger APIが記事IDなしの応答を返しました")
        content = str(post.get("content", ""))
        insertion = insert_link_once(content, job.target_text, job.link_url, job.anchor_text)
        if insertion.reason == "link_already_present":
            result.skipped_existing += 1
            continue
        if not insertion.changed:
            result.skipped_no_match += 1
            continue

        backup_path: Path | None = None
        if not dry_run:
            backup_path = _write_backup(job, post, content, backup_root or blogger_backup_dir())
            audit.write(
                "blogger_post_patch_start",
                job_id=job.id,
                post_id=post_id,
                backup_path=str(backup_path),
            )
            try:
                connector.patch_post_content(job.blog_id, post_id, insertion.html)
            except Exception as exc:
                audit.write(
                    "blogger_post_error",
                    job_id=job.id,
                    post_id=post_id,
                    error=type(exc).__name__,
                    detail=str(exc)[:1000],
                    backup_path=str(backup_path),
                )
                raise

        result.changed += 1
        audit.write(
            "blogger_post_change",
            job_id=job.id,
            post_id=post_id,
            dry_run=dry_run,
            backup_path=str(backup_path) if backup_path else "",
        )
    audit.write(
        "blogger_job_finish",
        job_id=job.id,
        dry_run=dry_run,
        scanned=result.scanned,
        changed=result.changed,
        skipped_existing=result.skipped_existing,
        skipped_no_match=result.skipped_no_match,
    )
    return result


def run_link_job(
    connector: "GoogleBloggerConnector",
    job: BloggerLinkJob,
    *,
    dry_run: bool,
    audit: AuditLogger | None = None,
    backup_root: Path | None = None,
    execution_lock: AbstractContextManager[Any] | None = None,
) -> JobRunResult:
    audit = audit or AuditLogger()
    lock = execution_lock or JobExecutionLock(job.id)
    with lock:
        return _run_link_job_inner(
            connector,
            job,
            dry_run=dry_run,
            audit=audit,
            backup_root=backup_root,
        )
