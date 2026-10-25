"""Offline classification and redaction checks for Blogger safe preflight."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock
import tempfile
import unittest

from automation_hub.blogger_draft import (
    DraftAuthenticationError, DraftPermissionError, DraftConnectionError,
    issue_draft_approval, prepare_blogger_draft, submit_journaled_blogger_draft,
)
from automation_hub.publishing_history import PublishingJournal
from automation_hub.publishing_plan import prepare_publishing_draft


class HttpFailure(Exception):
    def __init__(self, code: int, secret: str):
        super().__init__("secret-not-for-user: " + secret)
        self.resp = SimpleNamespace(status=code)


class PreflightFailureClasses(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.src = Path(self.tmp.name) / "post.md"
        self.secret = "unique-SUPER-SECRET-token-2026"
        self.src.write_text("Harmless article body", encoding="utf-8")
        plan = prepare_publishing_draft(
            platform="blogger", source_path=self.src, title="Test",
        )
        self.prepared = prepare_blogger_draft(plan, "1234567")
        self.approval = issue_draft_approval(self.prepared, confirmed=True)
        self.api = MagicMock()
        self.journal = PublishingJournal(Path(self.tmp.name) / "attempts.db")

    def _attempt(self):
        return submit_journaled_blogger_draft(
            self.api, self.prepared, self.journal, approval=self.approval,
        )

    def test_expired_google_login_does_not_send_or_save_uncertain(self):
        self.api.list_blogs.side_effect = HttpFailure(401, self.secret)
        with self.assertRaises(DraftAuthenticationError) as caught:
            self._attempt()
        self.assertNotIn(self.secret, str(caught.exception))
        self.assertEqual(self.journal.recent(), [])
        self.api.create_draft.assert_not_called()

    def test_google_denied_permission_does_not_block_valid_retry(self):
        self.api.list_blogs.side_effect = HttpFailure(403, self.secret)
        with self.assertRaises(DraftPermissionError) as caught:
            self._attempt()
        self.assertNotIn(self.secret, str(caught.exception))
        self.api.create_draft.assert_not_called()
        self.api.list_blogs.side_effect = None
        self.api.list_blogs.return_value = [{"id": "1234567"}]
        self.api.create_draft.return_value = {"id": "test-post-id"}
        self._attempt()
        self.api.create_draft.assert_called_once()

    def test_network_failed_does_not_create_remote_result(self):
        self.api.list_blogs.side_effect = ConnectionError(self.secret)
        with self.assertRaises(DraftConnectionError) as caught:
            self._attempt()
        self.assertNotIn(self.secret, str(caught.exception))
        self.assertEqual(self.journal.recent(), [])
        self.api.create_draft.assert_not_called()

    def test_source_secrets_do_not_reach_history(self):
        # Histories store filenames and user-facing titles, not tokens or body.
        self.api.list_blogs.return_value = [{"id": "1234567"}]
        self.api.create_draft.return_value = {"id": "post123"}
        self._attempt()
        data = (Path(self.tmp.name) / "attempts.db").read_bytes()
        self.assertNotIn(self.secret.encode(), data)
        self.assertNotIn(b"Harmless article body", data)


if __name__ == "__main__":
    unittest.main()
