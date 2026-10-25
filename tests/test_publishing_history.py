"""Offline regression: publishing history, uncertain outcomes and restart safety."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock

from automation_hub.blogger_draft import (
    DraftCreationError, prepare_blogger_draft, submit_journaled_blogger_draft,
)
from automation_hub.publishing_plan import prepare_publishing_draft
from automation_hub.publishing_history import (
    DuplicatePublishingAttempt, PublishingJournal, PublishingJournalError,
)


class PublishingHistoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.article = self.dir / "article.md"
        self.article.write_text("A regular text post", encoding="utf-8")
        local = prepare_publishing_draft(
            platform="blogger", source_path=self.article,
            title="A test post", description="Only a test",
        )
        self.prepared = prepare_blogger_draft(local, "123456")
        self.path = self.dir / "history.db"
        self.journal = PublishingJournal(self.path)
        self.google = MagicMock()
        self.google.list_blogs.return_value = [{"id": "123456", "name": "Owned"}]
        self.google.create_draft.return_value = {"id": "remote-001", "url": ""}

    def test_persists_real_remote_id_without_storing_content_or_tokens(self):
        result = submit_journaled_blogger_draft(self.google, self.prepared, self.journal)
        self.assertEqual(result.post_id, "remote-001")
        rows = PublishingJournal(self.path).recent()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["state"], "REMOTE_DRAFT")
        self.assertEqual(rows[0]["remote_id"], "remote-001")
        self.assertNotIn("content_html", rows[0])
        self.assertNotIn("A regular text post", repr(rows))
        self.assertNotIn("token", repr(rows))

    def test_rerun_after_app_restart_does_not_submit_duplicate(self):
        submit_journaled_blogger_draft(self.google, self.prepared, self.journal)
        with self.assertRaises(DuplicatePublishingAttempt):
            submit_journaled_blogger_draft(
                self.google, self.prepared, PublishingJournal(self.path))
        self.assertEqual(self.google.create_draft.call_count, 1)

    def test_timeout_records_unknown_and_never_auto_retries(self):
        self.google.create_draft.side_effect = TimeoutError("possible remote write")
        with self.assertRaises(DraftCreationError):
            submit_journaled_blogger_draft(self.google, self.prepared, self.journal)
        self.assertEqual(self.journal.recent()[0]["state"], "OUTCOME_UNKNOWN")
        with self.assertRaises(DuplicatePublishingAttempt):
            submit_journaled_blogger_draft(self.google, self.prepared, self.journal)
        self.assertEqual(self.google.create_draft.call_count, 1)

    def test_wrong_account_is_not_sent_and_marked_conservatively(self):
        self.google.list_blogs.return_value = [{"id": "999999"}]
        with self.assertRaises(DraftCreationError):
            submit_journaled_blogger_draft(self.google, self.prepared, self.journal)
        self.google.create_draft.assert_not_called()
        self.assertEqual(self.journal.recent()[0]["state"], "OUTCOME_UNKNOWN")

    def test_file_change_blocks_before_history_or_api_call(self):
        self.article.write_text("Changed after preview", encoding="utf-8")
        with self.assertRaises(DraftCreationError):
            submit_journaled_blogger_draft(self.google, self.prepared, self.journal)
        self.google.create_draft.assert_not_called()
        self.assertEqual(self.journal.recent(), [])

    def test_journal_failure_must_stop_before_network(self):
        impossible = PublishingJournal(self.dir / "not-a-dir")
        impossible.path.write_text("a regular file", encoding="utf-8")
        impossible = PublishingJournal(impossible.path / "history.db")
        with self.assertRaises((PublishingJournalError, OSError)):
            submit_journaled_blogger_draft(self.google, self.prepared, impossible)
        self.google.list_blogs.assert_not_called()
        self.google.create_draft.assert_not_called()

    def test_pre_existing_pending_blocks_even_if_app_crashed(self):
        from automation_hub.publishing_history import fingerprint_for
        key = fingerprint_for(
            platform="blogger", account_id=self.prepared.blog_id,
            title=self.prepared.title,
            source_sha256=self.prepared.source_sha256,
            html_body=self.prepared.content_html,
        )
        self.journal.reserve(
            fingerprint=key, platform="blogger",
            account_id=self.prepared.blog_id,
            filename=self.article.name, title=self.prepared.title,
        )
        self.assertEqual(self.journal.recent()[0]["state"], "PENDING_REMOTE")
        with self.assertRaises(DuplicatePublishingAttempt):
            submit_journaled_blogger_draft(self.google, self.prepared,
                                           PublishingJournal(self.path))
        self.google.create_draft.assert_not_called()

    def test_invalid_status_never_falsely_marks_success(self):
        from automation_hub.publishing_history import fingerprint_for
        key = fingerprint_for(
            platform="blogger", account_id=self.prepared.blog_id,
            title=self.prepared.title, source_sha256=self.prepared.source_sha256,
            html_body=self.prepared.content_html,
        )
        self.journal.reserve(
            fingerprint=key, platform="blogger", account_id="123456",
            filename="article.md", title="A test post",
        )
        with self.assertRaises(PublishingJournalError):
            self.journal.mark(key, "REMOTE_DRAFT", "")
        self.assertEqual(self.journal.recent()[0]["state"], "PENDING_REMOTE")

    def test_recent_limits_range(self):
        self.assertEqual(self.journal.recent(500), [])


if __name__ == "__main__":
    unittest.main()
