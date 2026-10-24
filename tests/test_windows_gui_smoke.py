"""Real Tkinter widget smoke tests on Windows CI, with zero network access.

Only the GUI is real. Credentials, Blogger, schedules and filesystem state are
test doubles. Tests never patch or publish a real Blogger post.
"""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
import sys
import tempfile
import tkinter as tk
from tkinter import ttk
import unittest
from unittest.mock import MagicMock, patch

from automation_hub import gui as gui_module
from automation_hub.jobs import JobStore
from automation_hub.models import BloggerLinkJob
from automation_hub.schedule_approval import ScheduleApprovalStore
from automation_hub.settings import SettingsStore


@unittest.skipUnless(sys.platform == "win32", "Real Windows Tkinter test")
class WindowsGuiSmokeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        parent = Path(self.tmp.name)
        self.jobs = JobStore(parent / "jobs.json")
        self.settings = SettingsStore(parent / "settings.json")
        self.approvals = ScheduleApprovalStore(parent / "schedule_approvals.json")
        self.google = MagicMock()
        self.google.has_client_config.return_value = False
        self.google.has_token.return_value = False
        self.scheduler = MagicMock()
        self.root = tk.Tk()
        self.addCleanup(self._close_tk)
        self.root.withdraw()
        self.msg_info = patch.object(gui_module.messagebox, "showinfo")
        self.msg_warning = patch.object(gui_module.messagebox, "showwarning")
        self.msg_error = patch.object(gui_module.messagebox, "showerror")
        self.msg_yesno = patch.object(gui_module.messagebox, "askyesno", return_value=True)
        for obj in (self.msg_info, self.msg_warning, self.msg_error, self.msg_yesno):
            obj.start()
            self.addCleanup(obj.stop)

        with patch.object(gui_module, "SettingsStore", return_value=self.settings), \
             patch.object(gui_module, "JobStore", return_value=self.jobs), \
             patch.object(gui_module, "ScheduleApprovalStore", return_value=self.approvals), \
             patch.object(gui_module, "GoogleBloggerConnector", return_value=self.google), \
             patch.object(gui_module, "WindowsTaskScheduler", return_value=self.scheduler):
            self.app = gui_module.AutomationHubGUI(self.root)
        self.root.update_idletasks()

    def _close_tk(self) -> None:
        if self.root.winfo_exists():
            self.root.destroy()

    def _saved_job(self, name: str = "Link my post") -> BloggerLinkJob:
        job = BloggerLinkJob(
            id="test-rule",
            name=name,
            blog_id="test-blog",
            target_text="Product list",
            anchor_text="Product list",
            link_url="https://example.com/products",
            max_posts=5,
        )
        self.jobs.upsert(job)
        self.app.refresh_jobs()
        self.app.selected_job_id = job.id
        self.app.load_job(job.id)
        return job

    @staticmethod
    def _buttons(widget: tk.Misc) -> list[ttk.Button]:
        found: list[ttk.Button] = []
        for child in widget.winfo_children():
            if isinstance(child, ttk.Button):
                found.append(child)
            found.extend(WindowsGuiSmokeTests._buttons(child))
        return found

    def _sync_run(self, operation, on_success):
        on_success(operation())

    def test_home_explains_product_and_navigates_to_real_tabs(self) -> None:
        self.assertEqual(self.app.notebook.index("end"), 5)
        self.assertIn("はじめに", self.app.notebook.tab(0, "text"))
        self.assertIn("Blogger", self.app.t("home_what"))
        buttons = self._buttons(self.app.home_tab)
        self.assertEqual(len(buttons), 5)
        for button, expected_tab in zip(
            buttons, (self.app.google_tab, self.app.jobs_tab, self.app.jobs_tab,
                      self.app.jobs_tab, self.app.schedule_tab)
        ):
            button.invoke()
            self.assertEqual(self.app.notebook.select(), str(expected_tab))

    def test_consumer_home_shows_only_real_saved_jobs(self) -> None:
        self.assertEqual(self.app.home_saved_jobs.get(0), "まだ登録がありません")
        job = self._saved_job(name="自分のBlogger作業")
        self.assertEqual(self.app.home_saved_jobs.get(0), "自分のBlogger作業 — 有効")
        self.assertEqual(self.app.home_saved_jobs.size(), 1)
        self.assertEqual(self.app.job_store.get(job.id).name, "自分のBlogger作業")

    def test_unsaved_edit_blocks_live_and_switch_prompts(self) -> None:
        old = self._saved_job()
        other = replace(old, id="other", name="Another rule")
        self.jobs.upsert(other)
        self.app.refresh_jobs()
        self.app.link_var.set("https://example.com/unsaved")
        with patch.object(gui_module, "run_link_job") as call:
            self.app.run_job(False)
            call.assert_not_called()
        gui_module.messagebox.showwarning.assert_called()
        gui_module.messagebox.askyesno.return_value = False
        index = self.app.job_row_ids.index(other.id)
        self.app.jobs_list.selection_clear(0, "end")
        self.app.jobs_list.selection_set(index)
        self.app.on_job_select()
        self.assertEqual(self.app.selected_job_id, old.id)
        self.assertEqual(self.app.link_var.get(), "https://example.com/unsaved")

    def test_preview_then_live_once_uses_saved_rule(self) -> None:
        job = self._saved_job()
        remote = MagicMock(return_value=SimpleNamespace(scanned=2, changed=1))
        with patch.object(gui_module, "run_link_job", remote), \
             patch.object(self.app, "run_async", side_effect=self._sync_run):
            self.app.run_job(False)  # must refuse without preview
            remote.assert_not_called()
            self.app.run_job(True)  # simulated, no real API call
            self.assertIsNotNone(self.app.preview_revision)
            self.app.run_job(False)
            self.assertIsNone(self.app.preview_revision)
            self.app.run_job(False)  # must demand fresh preview
        self.assertEqual(remote.call_count, 2)
        self.assertEqual([x.kwargs["dry_run"] for x in remote.call_args_list], [True, False])
        self.assertEqual(remote.call_args_list[-1].args[1].id, job.id)

    def test_duplicate_display_names_keep_distinct_internal_job_ids(self) -> None:
        first = self._saved_job(name="Same name")
        second = replace(first, id="another-id")
        self.jobs.upsert(second)
        self.app.refresh_jobs()
        self.assertEqual(self.app.jobs_list.get(0), "Same name (1/2)")
        self.assertEqual(self.app.jobs_list.get(1), "Same name (2/2)")
        self.assertEqual(self.app.job_row_ids, [first.id, second.id])
        self.app.jobs_list.selection_clear(0, "end")
        self.app.jobs_list.selection_set(1)
        self.app.on_job_select()
        self.assertEqual(self.app.selected_job_id, second.id)

    def test_locale_change_preserves_current_unsaved_edits(self) -> None:
        job = self._saved_job()
        self.app.notebook.select(self.app.jobs_tab)
        self.app.target_var.set("unsaved custom target")
        self.app.link_var.set("https://example.com/unsaved")
        self.app.language_var.set("English")
        self.app.on_language_change()
        self.assertEqual(self.app.notebook.tab(self.app.notebook.select(), "text"), "2 Link Rules & Run")
        self.assertEqual(self.app.selected_job_id, job.id)
        self.assertEqual(self.app.target_var.get(), "unsaved custom target")
        self.assertEqual(self.app.link_var.get(), "https://example.com/unsaved")
        self.app.language_var.set("日本語")
        self.app.on_language_change()
        self.assertEqual(self.app.target_var.get(), "unsaved custom target")

    def test_schedule_registration_needs_preview_and_approval(self) -> None:
        job = self._saved_job()
        with patch.object(gui_module, "run_link_job", return_value=SimpleNamespace(scanned=1, changed=1)), \
             patch.object(self.app, "run_async", side_effect=self._sync_run):
            self.app.register_schedule()
            self.scheduler.register.assert_not_called()
            self.app.run_job(True)
            self.app.register_schedule()
        self.scheduler.register.assert_called_once()
        self.assertTrue(self.approvals.approved(job))
        # A changed rule is refused by the persisted approval gate even after
        # closing the UI; no credential/network is involved.
        self.jobs.upsert(replace(job, link_url="https://example.com/changed"))
        self.assertFalse(self.approvals.approved(self.jobs.get(job.id)))

    def test_failed_google_connection_does_not_show_connected(self) -> None:
        self.app.google_verified = True
        self.app._checked_google_result(SimpleNamespace(ok=False, blogs=[], detail="offline"))
        self.assertFalse(self.app.google_verified)
        self.assertNotIn(self.app.t("home_state_api_verified"), self.app.home_connection_status.get())
        gui_module.messagebox.showerror.assert_called_once()

    def test_successful_google_connection_is_displayed_as_verified(self) -> None:
        self.app._checked_google_result(SimpleNamespace(
            ok=True, blogs=[{"id": "test-blog", "name": "Demo", "url": "https://example.blogspot.com"}]
        ))
        self.assertTrue(self.app.google_verified)
        self.assertIn(self.app.t("home_state_api_verified"), self.app.home_connection_status.get())
        self.assertEqual(len(self.app.blog_display_to_id), 1)

    def test_task_delete_failure_keeps_saved_rule_and_reports_error(self) -> None:
        job = self._saved_job()
        self.scheduler.unregister.side_effect = OSError("simulated Windows task error")
        self.app.delete_job()
        self.assertEqual(self.jobs.get(job.id).id, job.id)
        self.assertEqual(self.app.selected_job_id, job.id)
        gui_module.messagebox.showerror.assert_called_once()

    def test_delete_success_removes_rule_and_schedule_approval(self) -> None:
        job = self._saved_job()
        self.approvals.authorize(job)
        self.app.delete_job()
        self.scheduler.unregister.assert_called_once_with(job.id)
        self.assertFalse(self.approvals.approved(job))
        with self.assertRaises(KeyError):
            self.jobs.get(job.id)

    def test_primary_actions_are_grouped_in_two_rows(self) -> None:
        actions = {
            button.cget("text"): button
            for button in self._buttons(self.app.jobs_tab)
        }
        expected_rows = {
            "save_job": 0, "run_dry": 0,
            "run_now": 1, "delete_job": 1,
        }
        for key, expected_row in expected_rows.items():
            with self.subTest(key=key):
                button = actions[self.app.t(key)]
                self.assertEqual(int(button.grid_info()["row"]), expected_row)
        scheduled = {
            button.cget("text"): button
            for button in self._buttons(self.app.schedule_tab)
        }
        for key, expected in (
            ("save", 0), ("test_scheduler", 0),
            ("register_schedule", 1), ("remove_schedule", 1),
        ):
            with self.subTest(key=key):
                self.assertEqual(
                    int(scheduled[self.app.t(key)].grid_info()["row"]), expected
                )

    def test_failed_live_write_consumes_preview_and_needs_new_dry_run(self) -> None:
        self._saved_job()
        attempts = []
        error = OSError("response lost after remote post update")

        def simulated_async(operation, on_success):
            try:
                on_success(operation())
            except OSError:
                # Mirrors the worker path: the failure has no success callback.
                attempts.append("uncertain")

        def remote(_connector, _job, *, dry_run):
            attempts.append("preview" if dry_run else "write")
            if not dry_run:
                raise error
            return SimpleNamespace(scanned=2, changed=1)

        with patch.object(gui_module, "run_link_job", side_effect=remote), \
             patch.object(self.app, "run_async", side_effect=simulated_async):
            self.app.run_job(True)
            self.assertIsNotNone(self.app.preview_revision)
            self.app.run_job(False)
            self.assertIsNone(self.app.preview_revision)
            self.app.run_job(False)
        self.assertEqual(attempts, ["preview", "write", "uncertain"])
        gui_module.messagebox.showwarning.assert_called()

    def test_cancelled_live_confirmation_keeps_preview_without_writing(self) -> None:
        self._saved_job()
        with patch.object(gui_module, "run_link_job", return_value=SimpleNamespace(scanned=1, changed=1)), \
             patch.object(self.app, "run_async", side_effect=self._sync_run):
            self.app.run_job(True)
            approved = self.app.preview_revision
            gui_module.messagebox.askyesno.return_value = False
            self.app.run_job(False)
            self.assertEqual(self.app.preview_revision, approved)

    def test_busy_worker_blocks_edits_deletion_and_locale_switch(self) -> None:
        original = self._saved_job()
        self.app._set_busy(True)
        try:
            self.app.link_var.set("https://example.com/unsaved-change")
            self.app.save_job()
            self.app.delete_job()
            self.app.new_job()
            self.assertEqual(self.jobs.get(original.id).link_url, original.link_url)
            self.assertEqual(self.app.selected_job_id, original.id)
            self.assertEqual(self.app.link_var.get(), "https://example.com/unsaved-change")
            self.app.language_var.set("English")
            self.app.on_language_change()
            self.assertEqual(self.app.locale, "ja")
            self.assertEqual(self.app.language_var.get(), "日本語")
            self.assertIn(self.app.t("busy_processing"), self.app.operation_status.get())
        finally:
            self.app._set_busy(False)
        self.assertEqual(self.app.operation_status.get(), "")
        self.assertGreaterEqual(gui_module.messagebox.showinfo.call_count, 4)

    def test_high_dpi_editor_can_scroll_to_the_last_section(self) -> None:
        self._saved_job()
        old_scale = float(self.root.tk.call("tk", "scaling"))
        try:
            self.root.tk.call("tk", "scaling", old_scale * 1.5)
            self.app.build_ui()
            self.app.load_job("test-rule")
            self.app.notebook.select(self.app.jobs_tab)
            self.root.update_idletasks()
            self.app.job_canvas.yview_moveto(1.0)
            self.root.update_idletasks()
            self.assertAlmostEqual(self.app.job_canvas.yview()[1], 1.0, places=2)
            self.assertGreater(self.app.job_scrollbar.winfo_exists(), 0)
        finally:
            self.root.tk.call("tk", "scaling", old_scale)

    def test_layout_widgets_exist_at_three_scaling_factors(self) -> None:
        # This checks real geometry computation, not visual legibility, colors,
        # clipping in a physical monitor, or 100-150% Windows display scaling.
        before = float(self.root.tk.call("tk", "scaling"))
        try:
            for factor in (1.0, 1.25, 1.5):
                self.root.tk.call("tk", "scaling", factor)
                self.root.update_idletasks()
                self.assertGreater(self.app.notebook.winfo_reqwidth(), 200)
                self.assertGreater(self.app.jobs_list.winfo_reqheight(), 20)
                self.assertGreater(self.app.home_tab.winfo_reqheight(), 100)
        finally:
            self.root.tk.call("tk", "scaling", before)


if __name__ == "__main__":
    unittest.main()
