"""Real Windows Tk tests; all Blogger API calls are mocks, never live."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import sys
import tempfile
import tkinter as tk
import unittest
from unittest.mock import MagicMock, patch

from automation_hub import gui as gui_module
from automation_hub.jobs import JobStore
from automation_hub.settings import SettingsStore
from automation_hub.schedule_approval import ScheduleApprovalStore


@unittest.skipUnless(sys.platform == "win32", "Tk Windows GUI validation")
class BloggerDraftGuiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name)
        self.article = base / "article.txt"
        self.article.write_text("Test article", encoding="utf-8")
        self.google = MagicMock()
        self.google.has_client_config.return_value = False
        self.google.has_token.return_value = False
        self.root = tk.Tk()
        self.root.withdraw()
        self.addCleanup(self.root.destroy)
        with patch.object(gui_module, "SettingsStore", return_value=SettingsStore(base / "settings.json")), \
             patch.object(gui_module, "JobStore", return_value=JobStore(base / "jobs.json")), \
             patch.object(gui_module, "ScheduleApprovalStore", return_value=ScheduleApprovalStore(base / "approval.json")), \
             patch.object(gui_module, "GoogleBloggerConnector", return_value=self.google), \
             patch.object(gui_module, "WindowsTaskScheduler", return_value=MagicMock()):
            self.app = gui_module.AutomationHubGUI(self.root)
        self.app.compose_platform.set("Blogger")
        self.app.compose_file.set(str(self.article))
        self.app.compose_title.set("Offline test")
        self.app._set_blogs([{"id": "1234567", "name": "Owned test", "url": "https://example.com"}])
        self.app.compose_blog.set(next(iter(self.app.blog_display_to_id)))

    def test_no_google_verification_means_no_remote_draft(self):
        self.app._preview_compose_plan()
        with patch.object(gui_module.messagebox, "showwarning"):
            self.app._submit_compose_blogger_draft()
        self.google.create_draft.assert_not_called()

    def test_review_then_explicit_confirmation_single_remote_draft(self):
        self.app.google_verified = True
        self.app._preview_compose_plan()
        self.assertIsNotNone(self.app.compose_review)
        self.google.list_blogs.return_value = [{"id": "1234567", "name": "Owned test"}]
        self.google.create_draft.return_value = {"id": "post-321"}
        self.app.run_async = lambda work, on_done: on_done(work())
        with patch.object(gui_module.messagebox, "askyesno", return_value=True):
            self.app._submit_compose_blogger_draft()
        self.google.create_draft.assert_called_once()
        self.assertIn("post-321", self.app.compose_preview_status.get())
        # A repeated click cannot submit again until an explicit new preview.
        with patch.object(gui_module.messagebox, "showwarning"):
            self.app._submit_compose_blogger_draft()
        self.google.create_draft.assert_called_once()

    def test_modified_title_after_preview_requires_new_review(self):
        self.app.google_verified = True
        self.app._preview_compose_plan()
        self.app.compose_title.set("Unexpected new title")
        with patch.object(gui_module.messagebox, "showwarning"):
            self.app._submit_compose_blogger_draft()
        self.google.create_draft.assert_not_called()

    def test_user_declines_remote_creation(self):
        self.app.google_verified = True
        self.app._preview_compose_plan()
        with patch.object(gui_module.messagebox, "askyesno", return_value=False):
            self.app._submit_compose_blogger_draft()
        self.google.create_draft.assert_not_called()


if __name__ == "__main__":
    unittest.main()
