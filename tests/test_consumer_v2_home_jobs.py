"""Home dashboard reads only actual saved Blogger jobs; no sample automation."""
from __future__ import annotations
import unittest
from pathlib import Path
from types import SimpleNamespace
from automation_hub.gui import AutomationHubGUI
from automation_hub.jobs import JobStoreError
from automation_hub.models import BloggerLinkJob

class Variable:
    def __init__(self):
        self.value = ""
    def set(self, value):
        self.value = value

class ListStub:
    def __init__(self):
        self.values = []
    def delete(self, start, end):
        self.values = []
    def insert(self, pos, value):
        self.values.append(value)

def model_for(jobs):
    listed = ListStub()
    return SimpleNamespace(
        locale="ja", home_connection_status=Variable(),
        home_jobs_status=Variable(), home_preview_status=Variable(),
        home_saved_jobs=listed, google_verified=False,
        selected_job_id=None, preview_revision=None,
        job_store=SimpleNamespace(load_all=lambda: jobs),
        google=SimpleNamespace(has_client_config=lambda: False, has_token=lambda: False),
        t=lambda key, **kwargs: key,
    )

class ConsumerHomeJobsTests(unittest.TestCase):
    def test_only_saved_jobs_appear(self):
        job = BloggerLinkJob(
            id="j1", name="記事のリンク確認", blog_id="123",
            target_text="X", anchor_text="X",
            link_url="https://example.com",
        )
        model = model_for([job])
        AutomationHubGUI._refresh_home_status(model)
        self.assertEqual(model.home_saved_jobs.values, ["記事のリンク確認 — 有効"])

    def test_no_demo_job_when_unconfigured(self):
        model = model_for([])
        AutomationHubGUI._refresh_home_status(model)
        self.assertEqual(model.home_saved_jobs.values, ["まだ登録がありません"])

    def test_corrupt_job_store_is_error_not_empty(self):
        model = model_for([])
        def corrupted():
            raise JobStoreError("corrupt jobs.json")
        model.job_store.load_all = corrupted
        AutomationHubGUI._refresh_home_status(model)
        self.assertEqual(model.home_saved_jobs.values, ["読み込み失敗"])
        self.assertEqual(model.home_jobs_status.value, "home_state_jobs_error")

if __name__ == "__main__":
    unittest.main()
