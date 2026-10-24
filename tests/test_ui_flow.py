from __future__ import annotations

from dataclasses import replace
import unittest

from automation_hub.models import BloggerLinkJob
from automation_hub.ui_flow import home_progress, job_revision, live_run_ready, needs_save


def make_job(**fields) -> BloggerLinkJob:
    options = dict(
        id="sample",
        name="Sample rule",
        blog_id="123",
        target_text="Learn more",
        link_url="https://example.com/guide",
        anchor_text="Learn more",
        max_posts=5,
        enabled=True,
    )
    options.update(fields)
    return BloggerLinkJob(**options)


class FirstRunSafeFlowTests(unittest.TestCase):
    def test_identical_job_digest_is_stable(self) -> None:
        self.assertEqual(job_revision(make_job()), job_revision(make_job()))
        self.assertEqual(len(job_revision(make_job())), 64)

    def test_edited_url_requires_save(self) -> None:
        saved = make_job()
        edited = replace(saved, link_url="https://example.com/other")
        self.assertTrue(needs_save(saved, edited))
        self.assertFalse(needs_save(saved, replace(saved)))

    def test_schedule_time_only_does_not_invalidate_content_preview(self) -> None:
        from automation_hub.models import ScheduleSpec

        original = make_job()
        updated_schedule = replace(
            original,
            schedule=ScheduleSpec(kind="daily", time="09:15"),
        )
        self.assertEqual(job_revision(original), job_revision(updated_schedule))
        self.assertTrue(needs_save(original, updated_schedule) is False)

    def test_blog_change_always_invalidates_preview(self) -> None:
        original = make_job()
        switched = replace(original, blog_id="another-blog")
        self.assertNotEqual(job_revision(original), job_revision(switched))

    def test_different_job_rejects_other_job_preview(self) -> None:
        original = make_job()
        alternative = make_job(id="another")
        self.assertNotEqual(job_revision(original), job_revision(alternative))
        ready, reason = live_run_ready(
            job=alternative, edited=alternative,
            preview_revision=job_revision(original), busy=False
        )
        self.assertFalse(ready)
        self.assertEqual(reason, "preview_required")

    def test_live_requires_preview(self) -> None:
        job = make_job()
        ready, reason = live_run_ready(job=job, edited=job, preview_revision=None, busy=False)
        self.assertFalse(ready)
        self.assertEqual(reason, "preview_required")

    def test_live_requires_exact_saved_revision(self) -> None:
        old = make_job()
        updated = make_job(target_text="New words")
        ready, reason = live_run_ready(
            job=updated, edited=updated,
            preview_revision=job_revision(old), busy=False
        )
        self.assertFalse(ready)
        self.assertEqual(reason, "preview_required")

    def test_unsaved_edits_block_even_with_old_preview(self) -> None:
        original = make_job()
        edited = replace(original, max_posts=100)
        ready, reason = live_run_ready(
            job=original, edited=edited,
            preview_revision=job_revision(original), busy=False
        )
        self.assertFalse(ready)
        self.assertEqual(reason, "unsaved")

    def test_busy_operation_blocks_execution(self) -> None:
        job = make_job()
        ready, reason = live_run_ready(
            job=job, edited=job,
            preview_revision=job_revision(job), busy=True
        )
        self.assertFalse(ready)
        self.assertEqual(reason, "busy")

    def test_previewed_unchanged_rule_is_ready(self) -> None:
        job = make_job()
        ready, reason = live_run_ready(
            job=job, edited=replace(job),
            preview_revision=job_revision(job), busy=False
        )
        self.assertTrue(ready)
        self.assertEqual(reason, "ready")

    def test_missing_client_reports_setup_needed(self) -> None:
        self.assertEqual(home_progress(False, False, 0)[0], "config_missing")

    def test_token_presence_is_not_api_confirmation(self) -> None:
        self.assertEqual(home_progress(True, True, 2), ("auth_present", "jobs_ready", "preview_required"))

    def test_job_file_error_not_reported_as_empty(self) -> None:
        self.assertEqual(home_progress(True, False, None)[1], "jobs_error")

    def test_zero_jobs_is_distinct_from_error(self) -> None:
        self.assertEqual(home_progress(True, False, 0)[1], "jobs_missing")


if __name__ == "__main__":
    unittest.main()
