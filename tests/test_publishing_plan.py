"""Post preparation is a read-only offline validator, not an uploader."""
import tempfile
import unittest
from pathlib import Path

from automation_hub.publishing_plan import (
    PublishingPlanError, prepare_publishing_draft,
)


class PublishingDraftTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.video = self.base / "movie.mp4"
        self.video.write_bytes(b"synthetic-video-for-metadata-validation")
        self.article = self.base / "article.md"
        self.article.write_text("# Synthetic local article", encoding="utf-8")

    def test_youtube_prepared_as_private_not_uploaded(self):
        plan = prepare_publishing_draft(
            platform="YouTube", source_path=self.video,
            title="Test clip", description="Test", scheduled_at="2026-11-02T10:00:00+09:00"
        )
        self.assertEqual(plan.platform, "youtube")
        self.assertEqual(plan.visibility, "private")
        self.assertEqual(plan.state, "NOT_CONNECTED_NOT_UPLOADED")
        self.assertEqual(plan.preview()["filename"], "movie.mp4")
        self.assertNotIn("source_path", plan.preview())

    def test_blogger_prepared_as_draft_not_published(self):
        plan = prepare_publishing_draft(
            platform="Blogger", source_path=self.article, title="My article",
        )
        self.assertEqual(plan.visibility, "draft")
        self.assertIsNone(plan.scheduled_at)

    def test_reject_wrong_type_or_unsupported_service(self):
        with self.assertRaises(PublishingPlanError):
            prepare_publishing_draft(platform="blogger", source_path=self.video, title="Incorrect")
        with self.assertRaises(PublishingPlanError):
            prepare_publishing_draft(platform="instagram", source_path=self.article, title="Unavailable")

    def test_reject_missing_or_empty_file(self):
        with self.assertRaises(PublishingPlanError):
            prepare_publishing_draft(platform="youtube", source_path=self.base / "missing.mp4", title="No")
        empty = self.base / "empty.mp4"
        empty.touch()
        with self.assertRaises(PublishingPlanError):
            prepare_publishing_draft(platform="youtube", source_path=empty, title="No")

    def test_reject_missing_title_and_naive_schedule(self):
        with self.assertRaises(PublishingPlanError):
            prepare_publishing_draft(platform="blogger", source_path=self.article, title=" ")
        with self.assertRaises(PublishingPlanError):
            prepare_publishing_draft(platform="youtube", source_path=self.video, title="A",
                                     scheduled_at="2026-11-02T10:00:00")

    def test_reject_symbolic_link_if_available(self):
        alias = self.base / "alias.mp4"
        try:
            alias.symlink_to(self.video)
        except (OSError, NotImplementedError):
            self.skipTest("Symlink privileges unavailable in Windows runner")
        with self.assertRaises(PublishingPlanError):
            prepare_publishing_draft(platform="youtube", source_path=alias, title="Linked")

    def test_does_not_change_local_file(self):
        before = self.article.read_bytes()
        plan = prepare_publishing_draft(platform="blogger", source_path=self.article,
                                        title="Original")
        self.assertEqual(self.article.read_bytes(), before)
        self.assertEqual(plan.file_bytes, len(before))


if __name__ == "__main__":
    unittest.main()
