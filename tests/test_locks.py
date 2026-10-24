import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from automation_hub.locks import JobAlreadyRunningError, JobExecutionLock


class LockTests(unittest.TestCase):
    def test_prevents_duplicate_execution(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            first = JobExecutionLock('job-1', root=root)
            second = JobExecutionLock('job-1', root=root)
            first.acquire()
            try:
                with self.assertRaises(JobAlreadyRunningError):
                    second.acquire()
            finally:
                first.release()
            second.acquire()
            second.release()

    def test_stale_lock_requires_a_proven_dead_pid(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            path = root / "job-1.lock"
            path.write_text(json.dumps({"pid": 12345, "job_id": "job-1"}), encoding="utf-8")
            old = time.time() - 120
            os.utime(path, (old, old))
            with patch("automation_hub.locks._pid_alive", return_value=False):
                lock = JobExecutionLock("job-1", root=root, stale_seconds=60)
                lock.acquire()
                lock.release()

    def test_old_lock_held_by_live_pid_never_deleted(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            path = root / "job-1.lock"
            original = json.dumps({"pid": os.getpid(), "job_id": "job-1"})
            path.write_text(original, encoding="utf-8")
            old = time.time() - 36000
            os.utime(path, (old, old))
            lock = JobExecutionLock("job-1", root=root, stale_seconds=60)
            with patch("automation_hub.locks._pid_alive", return_value=True):
                with self.assertRaises(JobAlreadyRunningError):
                    lock.acquire()
            self.assertEqual(path.read_text(encoding="utf-8"), original)

    def test_malformed_old_lock_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            path = root / "job-1.lock"
            path.write_text("stale", encoding="utf-8")
            old = time.time() - 120
            os.utime(path, (old, old))
            with self.assertRaises(JobAlreadyRunningError):
                JobExecutionLock("job-1", root=root, stale_seconds=60).acquire()
            self.assertEqual(path.read_text(encoding="utf-8"), "stale")

    def test_old_lock_with_uncertain_process_status_is_not_reclaimed(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            path = root / "job-1.lock"
            path.write_text(json.dumps({"pid": 12345}), encoding="utf-8")
            old = time.time() - 120
            os.utime(path, (old, old))
            with patch("automation_hub.locks._pid_alive", return_value=None):
                with self.assertRaises(JobAlreadyRunningError):
                    JobExecutionLock("job-1", root=root, stale_seconds=60).acquire()

    def test_release_does_not_delete_replaced_lock(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            lock = JobExecutionLock("job-1", root=root)
            lock.acquire()
            replacement = json.dumps({"pid": 9999, "nonce": "owned-by-other"})
            lock.path.write_text(replacement, encoding="utf-8")
            lock.release()
            self.assertEqual(lock.path.read_text(encoding="utf-8"), replacement)


if __name__ == '__main__':
    unittest.main()
