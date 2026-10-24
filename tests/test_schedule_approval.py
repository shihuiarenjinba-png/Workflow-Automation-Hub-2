"""Offline tests: recurring Blogger tasks stop when reviewed content changes."""
from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from automation_hub.models import BloggerLinkJob, ScheduleSpec
from automation_hub.schedule_approval import ScheduleApprovalError, ScheduleApprovalStore


def make_job(**override) -> BloggerLinkJob:
    payload = dict(
        id="scheduled-demo",
        name="Demo", blog_id="123",
        target_text="See here", anchor_text="See here",
        link_url="https://example.com/article", max_posts=5,
    )
    payload.update(override)
    return BloggerLinkJob(**payload)


class ScheduleApprovalTests(unittest.TestCase):
    def test_missing_approval_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertFalse(ScheduleApprovalStore(Path(tmp) / "approvals.json").approved(make_job()))

    def test_authorization_survives_new_store_instance(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "approvals.json"
            ScheduleApprovalStore(path).authorize(make_job())
            self.assertTrue(ScheduleApprovalStore(path).approved(make_job()))

    def test_changed_blog_or_destination_is_not_authorized(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = ScheduleApprovalStore(Path(tmp) / "approvals.json")
            original = make_job()
            store.authorize(original)
            self.assertFalse(store.approved(replace(original, blog_id="different-blog")))
            self.assertFalse(store.approved(replace(original, link_url="https://example.com/new")))
            self.assertFalse(store.approved(replace(original, target_text="Other phrase")))
            self.assertFalse(store.approved(replace(original, max_posts=500)))

    def test_schedule_time_change_is_not_an_article_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = ScheduleApprovalStore(Path(tmp) / "approvals.json")
            original = make_job()
            store.authorize(original)
            alternate = replace(original, schedule=ScheduleSpec(kind="daily", time="19:30"))
            self.assertTrue(store.approved(alternate))

    def test_revoke_removes_approval(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = ScheduleApprovalStore(Path(tmp) / "approvals.json")
            store.authorize(make_job())
            store.revoke("scheduled-demo")
            self.assertFalse(store.approved(make_job()))

    def test_corrupt_approval_file_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "approvals.json"
            path.write_text("{{invalid", encoding="utf-8")
            store = ScheduleApprovalStore(path)
            with self.assertRaises(ScheduleApprovalError):
                store.approved(make_job())
            with self.assertRaises(ScheduleApprovalError):
                store.authorize(make_job())

    def test_file_never_contains_api_tokens_or_post_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "approvals.json"
            ScheduleApprovalStore(path).authorize(make_job())
            content = path.read_text(encoding="utf-8")
            self.assertNotIn("https://example.com/article", content)
            self.assertNotIn("See here", content)
            self.assertIn("scheduled-demo", content)

    def test_failed_atomic_replace_keeps_old_approval(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "approvals.json"
            store = ScheduleApprovalStore(path)
            job = make_job()
            store.authorize(job)
            existing = path.read_bytes()
            with patch("automation_hub.schedule_approval.os.replace", side_effect=OSError("locked")):
                with self.assertRaises(ScheduleApprovalError):
                    store.authorize(replace(job, link_url="https://example.com/changed"))
            self.assertEqual(path.read_bytes(), existing)
            self.assertTrue(store.approved(job))
            self.assertEqual(list(Path(tmp).glob("schedule-approval-*.tmp")), [])


if __name__ == "__main__":
    unittest.main()
