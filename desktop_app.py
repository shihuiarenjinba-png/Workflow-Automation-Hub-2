from __future__ import annotations

import argparse
import sys
from pathlib import Path

from automation_hub.audit import AuditLogger
from automation_hub.i18n import tr
from automation_hub.settings import SettingsStore


def main() -> int:
    parser = argparse.ArgumentParser(description="Workflow Automation Hub / ワークフロー自動化ハブ")
    parser.add_argument("--run-job", help="Run a saved Blogger job / 保存済みBloggerジョブを実行")
    parser.add_argument("--dry-run", action="store_true", help="Preview only / 変更せず確認のみ")
    parser.add_argument("--self-test", action="store_true", help="Run local package diagnostics / ローカル自己診断")
    parser.add_argument(
        "--diagnose",
        nargs="?",
        const="support_report.txt",
        metavar="OUTPUT",
        help="Write a privacy-safe support report / 秘密情報を含まないサポートレポートを出力",
    )
    args = parser.parse_args()

    if args.self_test:
        from automation_hub.selftest import format_self_test, run_self_test
        try:
            print(format_self_test(run_self_test()))
            return 0
        except Exception as exc:
            print(f"SELF-TEST ERROR: {exc}", file=sys.stderr)
            return 2

    if args.diagnose is not None:
        from automation_hub.diagnostics import write_diagnostics
        try:
            report = write_diagnostics(Path(args.diagnose))
            print("Support report written.")
            return 0 if report.get("overall_ok") else 3
        except Exception as exc:
            print(f"DIAGNOSTICS ERROR: {type(exc).__name__}", file=sys.stderr)
            return 4

    locale = str(SettingsStore().load().get("locale", "ja"))
    if args.run_job:
        from automation_hub.runner import run_saved_job
        audit = AuditLogger()
        try:
            result = run_saved_job(args.run_job, dry_run=args.dry_run)
            message = tr(locale, "dry_result" if args.dry_run else "run_result", scanned=result.scanned, changed=result.changed)
            audit.write("scheduled_job_ok", job_id=args.run_job, dry_run=args.dry_run, scanned=result.scanned, changed=result.changed)
            print(message)
            return 0
        except Exception as exc:
            audit.write("scheduled_job_error", job_id=args.run_job, dry_run=args.dry_run, error=type(exc).__name__, detail=str(exc)[:1000])
            print(f"{tr(locale, 'status_error')}: {exc}", file=sys.stderr)
            return 1

    from automation_hub.gui import launch_gui
    launch_gui()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
