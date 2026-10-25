"""Windows spawn-process and crash-boundary safety tests (offline)."""
from __future__ import annotations
import multiprocessing as mp
import os
from pathlib import Path
import tempfile
import unittest

from automation_hub.publishing_history import (
    PublishingJournal, DuplicatePublishingAttempt,
)

KEY = "a" * 64


def reserve_worker(database: str, trigger: object, report: object) -> None:
    trigger.wait(12)
    try:
        PublishingJournal(Path(database)).reserve(
            fingerprint=KEY, platform="blogger",
            account_id="12345", filename="synthetic.md", title="Concurrent draft",
        )
        report.put("reserved")
    except DuplicatePublishingAttempt:
        report.put("duplicate")
    except Exception as exc:
        report.put("error:" + type(exc).__name__)


def crash_after_reserve(database: str) -> None:
    PublishingJournal(Path(database)).reserve(
        fingerprint=KEY, platform="blogger",
        account_id="12345", filename="synthetic.md", title="Concurrent draft",
    )
    # Simulates abrupt process termination after durable reservation and before POST.
    os._exit(0)


class PublishingInterprocessTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.database = Path(self.temp.name) / "publishing.sqlite3"

    def test_four_processes_only_one_reservation(self):
        ctx = mp.get_context("spawn")
        trigger = ctx.Event()
        report = ctx.Queue()
        workers = [ctx.Process(target=reserve_worker, args=(
            str(self.database), trigger, report,
        )) for _ in range(4)]
        for p in workers:
            p.start()
        try:
            trigger.set()
            results = [report.get(timeout=35) for _ in workers]
            self.assertCountEqual(results, ["reserved", "duplicate", "duplicate", "duplicate"])
        finally:
            for p in workers:
                p.join(timeout=12)
                if p.is_alive():
                    p.terminate()
                    p.join(timeout=5)
            self.assertTrue(all(p.exitcode == 0 for p in workers))
            report.close()
            report.join_thread()
        self.assertEqual(len(PublishingJournal(self.database).recent()), 1)
        self.assertEqual(PublishingJournal(self.database).recent()[0]["state"], "PENDING_REMOTE")

    def test_crash_after_reservation_cannot_duplicate_on_restart(self):
        ctx = mp.get_context("spawn")
        p = ctx.Process(target=crash_after_reserve, args=(str(self.database),))
        p.start()
        p.join(timeout=25)
        if p.is_alive():
            p.terminate()
            p.join()
        self.assertEqual(p.exitcode, 0)
        journal = PublishingJournal(self.database)
        self.assertEqual(journal.recent()[0]["state"], "PENDING_REMOTE")
        with self.assertRaises(DuplicatePublishingAttempt):
            journal.reserve(
                fingerprint=KEY, platform="blogger",
                account_id="12345", filename="synthetic.md", title="Concurrent draft",
            )


if __name__ == "__main__":
    unittest.main()
