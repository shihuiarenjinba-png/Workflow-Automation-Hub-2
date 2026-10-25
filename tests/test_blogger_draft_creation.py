"""All Blogger posting tests are offline; no real OAuth/API calls occur."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from automation_hub.blogger_draft import (
    DraftCreationError, DraftPreflightError, DraftOutcomeUnknownError,
    issue_draft_approval, create_approved_remote_draft, prepare_blogger_draft,
)
from automation_hub.google_blogger import GoogleBloggerConnector, GoogleBloggerError
from automation_hub.publishing_plan import PublishingPlanError, prepare_publishing_draft


class DraftCreationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.source = Path(self.temp.name) / "article.md"
        self.source.write_text("First paragraph\n\n<script>attack</script> & text", encoding="utf-8")
        self.plan = prepare_publishing_draft(
            platform="blogger", source_path=self.source,
            title="My article", description="Intro text",
        )
        self.draft = prepare_blogger_draft(self.plan, "1234567")
        self.connector = MagicMock()
        self.connector.list_blogs.return_value = [{"id": "1234567", "name": "Test"}]
        self.connector.create_draft.return_value = {"id": "post-100", "url": ""}

    def test_renders_text_as_escaped_html_not_script(self):
        self.assertIn("&lt;script&gt;attack&lt;/script&gt;", self.draft.content_html)
        self.assertNotIn("<script>", self.draft.content_html)
        self.assertIn("<p>Intro text</p>", self.draft.content_html)

    def test_reviewed_draft_creates_exactly_one_remote_draft(self):
        outcome = create_approved_remote_draft(
            self.connector, self.draft, approval=issue_draft_approval(self.draft, confirmed=True),
        )
        self.assertEqual(outcome.state, "REMOTE_DRAFT")
        self.assertEqual(outcome.post_id, "post-100")
        self.connector.create_draft.assert_called_once_with(
            "1234567", "My article", self.draft.content_html,
        )

    def test_without_approval_or_changed_approval_never_calls_api(self):
        from dataclasses import replace
        valid = issue_draft_approval(self.draft, confirmed=True)
        cases = [issue_draft_approval(self.draft, confirmed=False),
                 replace(valid, source_sha256="invalid"),
                 replace(valid, title="different article")]
        for approval in cases:
            with self.assertRaises(DraftPreflightError):
                create_approved_remote_draft(
                    self.connector, self.draft, approval=approval,
                )
        self.connector.list_blogs.assert_not_called()
        self.connector.create_draft.assert_not_called()

    def test_local_file_modified_after_preview_blocks_remote_write(self):
        self.source.write_text("changed text", encoding="utf-8")
        with self.assertRaises(DraftCreationError):
            create_approved_remote_draft(
                self.connector, self.draft, approval=issue_draft_approval(self.draft, confirmed=True),
            )
        self.connector.list_blogs.assert_not_called()

    def test_other_blog_not_accessible_blocks_remote_write(self):
        self.connector.list_blogs.return_value = [{"id": "999", "name": "Different"}]
        with self.assertRaises(DraftCreationError):
            create_approved_remote_draft(
                self.connector, self.draft, approval=issue_draft_approval(self.draft, confirmed=True),
            )
        self.connector.create_draft.assert_not_called()

    def test_timeout_must_not_be_retried_automatically(self):
        self.connector.create_draft.side_effect = TimeoutError("connection timed out")
        with self.assertRaises(DraftOutcomeUnknownError):
            create_approved_remote_draft(
                self.connector, self.draft, approval=issue_draft_approval(self.draft, confirmed=True),
            )
        self.assertEqual(self.connector.create_draft.call_count, 1)

    def test_html_upload_and_youtube_upload_do_not_implicitly_work(self):
        html = Path(self.temp.name) / "article.html"
        html.write_text("<h1>HTML not reviewed</h1>", encoding="utf-8")
        plan = prepare_publishing_draft(
            platform="blogger", source_path=html, title="HTML")
        with self.assertRaises(PublishingPlanError):
            prepare_blogger_draft(plan, "1234567")
        with self.assertRaises(PublishingPlanError):
            prepare_blogger_draft(self.plan, "not-a-blog-id")

    def test_blogger_connector_calls_exact_draft_api_without_retries(self):
        connector = GoogleBloggerConnector.__new__(GoogleBloggerConnector)
        service = MagicMock()
        connector._service = MagicMock(return_value=service)
        service.posts.return_value.insert.return_value.execute.return_value = {
            "id": "new-post-id"}
        result = connector.create_draft("1234567", "title", "<p>safe</p>")
        self.assertEqual(result["id"], "new-post-id")
        service.posts.return_value.insert.assert_called_once_with(
            blogId="1234567", isDraft=True,
            body={"kind": "blogger#post", "title": "title",
                  "content": "<p>safe</p>"})
        service.posts.return_value.insert.return_value.execute.assert_called_once_with(
            num_retries=0)

    def test_connector_requires_remote_id_for_confirmation(self):
        connector = GoogleBloggerConnector.__new__(GoogleBloggerConnector)
        service = MagicMock()
        connector._service = MagicMock(return_value=service)
        service.posts.return_value.insert.return_value.execute.return_value = {}
        with self.assertRaises(GoogleBloggerError):
            connector.create_draft("1234567", "title", "<p>ok</p>")


if __name__ == "__main__":
    unittest.main()
