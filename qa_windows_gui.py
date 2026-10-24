"""Windows hosted-runner Tk screenshots for consumer Hub -2; entirely offline.

Google, Blogger and Windows task scheduler are replaced by mocks.
All jobs and settings are synthetic and held in a disposable directory.
"""
from __future__ import annotations

import argparse
import json
import tempfile
import time
import tkinter as tk
from pathlib import Path
from unittest.mock import MagicMock, patch
from PIL import ImageGrab

from automation_hub import gui as gui_module
from automation_hub.jobs import JobStore
from automation_hub.settings import SettingsStore
from automation_hub.schedule_approval import ScheduleApprovalStore
from automation_hub.models import BloggerLinkJob


def screenshot(root, directory, name):
    root.deiconify()
    root.lift()
    root.focus_force()
    root.update()
    time.sleep(.25)
    root.update()
    x, y, w, h = root.winfo_rootx(), root.winfo_rooty(), root.winfo_width(), root.winfo_height()
    if w < 800 or h < 550:
        raise AssertionError(f"GUI display unexpectedly small: {w}x{h}")
    image = ImageGrab.grab(bbox=(x, y, x+w, y+h))
    file = directory / name
    image.save(file)
    if file.stat().st_size < 4500:
        raise AssertionError(f"Empty screenshot: {name}")
    return {"file": name, "actual_resolution": [w, h], "bytes": file.stat().st_size}


def main(out):
    out.mkdir(parents=True, exist_ok=True)
    checks=[]
    with tempfile.TemporaryDirectory(prefix="hub-v2-gui-qa-") as temp:
        directory=Path(temp)
        settings = SettingsStore(directory / "settings.json")
        jobs = JobStore(directory / "jobs.json")
        approvals = ScheduleApprovalStore(directory / "approvals.json")
        google = MagicMock()
        google.has_client_config.return_value=False
        google.has_token.return_value=False
        scheduler = MagicMock()
        root=tk.Tk()
        try:
            root.withdraw()
            with patch.object(gui_module,"SettingsStore",return_value=settings), \
                 patch.object(gui_module,"JobStore",return_value=jobs), \
                 patch.object(gui_module,"ScheduleApprovalStore",return_value=approvals), \
                 patch.object(gui_module,"GoogleBloggerConnector",return_value=google), \
                 patch.object(gui_module,"WindowsTaskScheduler",return_value=scheduler):
                app=gui_module.AutomationHubGUI(root)
            root.geometry("1024x768+30+30")
            root.deiconify()
            root.update()
            if app.notebook.index("end") != 6:
                raise AssertionError("Expected five functional tabs")
            if app.home_saved_jobs.get(0) != "まだ登録がありません":
                raise AssertionError("UI invents a job or fails to show empty state")
            checks.append({"case":"japanese_empty_home","requested":[1024,768],
                           **screenshot(root,out,"hub-v2-ja-home-1024x768.png")})

            synthetic=BloggerLinkJob(
                id="qa-record",name="QAのサンプル作業",blog_id="offline-blog",
                target_text="Example",anchor_text="Example",
                link_url="https://example.com/demo",max_posts=2,
            )
            jobs.upsert(synthetic)
            app.refresh_jobs()
            root.update()
            shown=app.home_saved_jobs.get(0)
            if shown != "QAのサンプル作業 — 有効":
                raise AssertionError(f"Actual stored job not reflected: {shown!r}")
            checks.append({"case":"saved_job_is_real_synthetic_state","passed":True})
            checks.append({"case":"japanese_home_with_saved_job","requested":[1024,768],
                           **screenshot(root,out,"hub-v2-ja-saved-1024x768.png")})

            # Offline post preparation. Never use OAuth or perform remote mutations.
            local_article = directory / "post.md"
            local_article.write_text("# Synthetic article", encoding="utf-8")
            app.compose_platform.set("Blogger")
            app.compose_file.set(str(local_article))
            app.compose_title.set("QA 投稿確認")
            app._preview_compose_plan()
            if "ローカル確認のみ" not in app.compose_preview_status.get():
                raise AssertionError("Composer must say there was no upload")
            app.notebook.select(app.compose_tab)
            root.update()
            checks.append({"case":"ja_content_prep_no_upload",
                           **screenshot(root,out,"hub-v2-ja-content-preview.png")})
            local_video = directory / "test.mp4"
            local_video.write_bytes(b"synthetic-video-bytes")
            app.compose_platform.set("YouTube")
            app.compose_file.set(str(local_video))
            app.compose_title.set("Video example")
            app._preview_compose_plan()
            if "非公開" not in app.compose_preview_status.get():
                raise AssertionError("Video must default to private in draft preview")
            checks.append({"case":"youtube_local_only", "passed": True})
            app.notebook.select(app.jobs_tab)
            root.update()
            checks.append({"case":"japanese_job_editor","requested":[1024,768],
                           **screenshot(root,out,"hub-v2-ja-jobs-1024x768.png")})

            app.locale="en"
            app.build_ui()
            root.geometry("1280x720+30+30")
            root.update()
            if app.notebook.index("end") != 6:
                raise AssertionError("Language change removed tabs")
            checks.append({"case":"english_home","requested":[1280,720],
                           **screenshot(root,out,"hub-v2-en-home-requested1280x720.png")})
            app.notebook.select(app.jobs_tab)
            root.update()
            checks.append({"case":"english_job_editor","requested":[1280,720],
                           **screenshot(root,out,"hub-v2-en-jobs-requested1280x720.png")})
            google.authenticate.assert_not_called()
            google.list_blogs.assert_not_called()
            scheduler.register.assert_not_called()
            checks.append({"case":"no_remote_auth_mutation_or_scheduler_registration","passed":True})
        finally:
            root.destroy()
    report={"product":"Workflow Automation Hub -2",
            "scope":"ephemeral Windows GUI smoke, mocked integrations",
            "human_real_machine_QA":False, "live_google":False, "blogger_mutation":False,
            "store_msix_installed":False, "checks":checks}
    (out/"gui_qa_report.json").write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print("HUB-V2-GUI-QA PASS: "+json.dumps(report,ensure_ascii=False))


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--output",type=Path,default=Path("gui-review-evidence"))
    args=parser.parse_args()
    main(args.output)
