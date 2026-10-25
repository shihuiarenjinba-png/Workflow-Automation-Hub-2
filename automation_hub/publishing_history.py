"""Durable, credential-free publishing history and duplicate prevention.

A single local SQLite database records *attempted* remote draft creations.
It must be written BEFORE a request is sent. Interrupted requests remain
ambiguous, not "failed": users must inspect Blogger before any new attempt.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3

from .paths import app_data_dir


class PublishingJournalError(RuntimeError):
    pass


class DuplicatePublishingAttempt(PublishingJournalError):
    pass


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def fingerprint_for(*, platform: str, account_id: str, title: str,
                    source_sha256: str, html_body: str) -> str:
    """Same content and destination must not be resent implicitly."""
    data = [platform, account_id, title, source_sha256,
            hashlib.sha256(html_body.encode("utf-8")).hexdigest()]
    return hashlib.sha256(json.dumps(data, ensure_ascii=False,
                                     separators=(",", ":")).encode("utf-8")).hexdigest()


class PublishingJournal:
    """SQLite UNIQUE key stops duplicate attempts across app restarts/processes."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path if path is not None else app_data_dir() / "publishing_history.sqlite3"

    def _connect(self) -> sqlite3.Connection:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            cx = sqlite3.connect(self.path, timeout=12)
            cx.execute("PRAGMA busy_timeout = 12000")
            cx.execute("""
                CREATE TABLE IF NOT EXISTS publication_attempts (
                    fingerprint TEXT PRIMARY KEY,
                    platform TEXT NOT NULL,
                    account_id TEXT NOT NULL,
                    filename TEXT NOT NULL,
                    title TEXT NOT NULL,
                    state TEXT NOT NULL CHECK (state IN (
                        'PENDING_REMOTE','REMOTE_DRAFT','OUTCOME_UNKNOWN')),
                    remote_id TEXT NOT NULL DEFAULT '',
                    created_utc TEXT NOT NULL,
                    updated_utc TEXT NOT NULL
                )
            """)
            cx.commit()
            return cx
        except sqlite3.Error as exc:
            raise PublishingJournalError("Cannot access local publishing history") from exc

    def reserve(self, *, fingerprint: str, platform: str, account_id: str,
                filename: str, title: str) -> None:
        if len(fingerprint) != 64 or platform != "blogger" or not account_id.isdigit():
            raise PublishingJournalError("Invalid publishing attempt")
        if not filename or len(filename) > 260 or not title or len(title) > 200:
            raise PublishingJournalError("Invalid publishing metadata")
        cx = self._connect()
        try:
            with cx:
                now = _timestamp()
                cx.execute("""
                    INSERT INTO publication_attempts(
                        fingerprint,platform,account_id,filename,title,state,
                        remote_id,created_utc,updated_utc
                    ) VALUES(?,?,?,?,?,'PENDING_REMOTE','',?,?)
                """, (fingerprint, platform, account_id, filename, title, now, now))
        except sqlite3.IntegrityError as exc:
            raise DuplicatePublishingAttempt(
                "This file and title have already been attempted for the selected blog. "
                "Check Blogger and the publishing history before any new attempt."
            ) from exc
        except sqlite3.Error as exc:
            raise PublishingJournalError("Could not safely record attempt; no upload started") from exc
        finally:
            cx.close()

    def mark(self, fingerprint: str, state: str, remote_id: str = "") -> None:
        if state not in ("REMOTE_DRAFT", "OUTCOME_UNKNOWN"):
            raise PublishingJournalError("Unsupported publishing status")
        if state == "REMOTE_DRAFT" and not remote_id.strip():
            raise PublishingJournalError("A verified Blogger post ID is required")
        cx = self._connect()
        try:
            with cx:
                cur = cx.execute("""
                    UPDATE publication_attempts
                    SET state=?, remote_id=?, updated_utc=?
                    WHERE fingerprint=? AND state='PENDING_REMOTE'
                """, (state, remote_id if state == "REMOTE_DRAFT" else "", _timestamp(), fingerprint))
                if cur.rowcount != 1:
                    raise PublishingJournalError("Publishing history state was not pending")
        except sqlite3.Error as exc:
            raise PublishingJournalError("Cannot update publishing attempt history") from exc
        finally:
            cx.close()

    def recent(self, limit: int = 30) -> list[dict[str, str]]:
        n = max(1, min(int(limit), 100))
        cx = self._connect()
        try:
            rows = cx.execute("""
                SELECT platform,account_id,filename,title,state,remote_id,
                       created_utc,updated_utc
                FROM publication_attempts ORDER BY created_utc DESC, rowid DESC LIMIT ?
            """, (n,)).fetchall()
            keys = ("platform","account_id","filename","title","state",
                    "remote_id","created_utc","updated_utc")
            # Do not expose or persist OAuth secrets or the article body.
            return [dict(zip(keys, row)) for row in rows]
        except sqlite3.Error as exc:
            raise PublishingJournalError("Could not read publishing history") from exc
        finally:
            cx.close()
