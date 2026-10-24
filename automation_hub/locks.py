from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path

from .models import validate_job_id
from .paths import job_lock_dir


class JobAlreadyRunningError(RuntimeError):
    pass


def _pid_alive(pid: int) -> bool | None:
    """True alive, False proven exited, None if inaccessible/unknown.

    Never use os.kill(pid, 0) on Windows: Python implements this differently
    from Unix and it may terminate a process.
    """
    if not isinstance(pid, int) or pid < 1:
        return None
    if os.name == "nt":
        try:
            import ctypes
            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
            kernel.OpenProcess.restype = ctypes.c_void_p
            kernel.GetExitCodeProcess.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
            kernel.GetExitCodeProcess.restype = ctypes.c_int
            kernel.CloseHandle.argtypes = [ctypes.c_void_p]
            kernel.CloseHandle.restype = ctypes.c_int
            handle = kernel.OpenProcess(0x1000, 0, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
            if not handle:
                return False if ctypes.get_last_error() == 87 else None
            try:
                exit_code = ctypes.c_ulong()
                if not kernel.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                    return None
                return exit_code.value == 259  # STILL_ACTIVE
            finally:
                kernel.CloseHandle(handle)
        except (AttributeError, OSError, ValueError):
            return None
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return None
    return True


class JobExecutionLock:
    def __init__(self, job_id: str, *, root: Path | None = None,
                 stale_seconds: int = 6 * 60 * 60) -> None:
        self.job_id = validate_job_id(job_id)
        self.root = root or job_lock_dir()
        self.stale_seconds = max(int(stale_seconds), 60)
        self.path = self.root / f"{self.job_id}.lock"
        self.acquired = False
        self._nonce: str | None = None

    def _remove_if_stale(self) -> None:
        """Remove only when stale AND a recorded owner PID is proven exited."""
        try:
            info = self.path.stat()
            if time.time() - info.st_mtime <= self.stale_seconds:
                return
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(data, dict) or not isinstance(data.get("pid"), int):
                return
            if _pid_alive(data["pid"]) is not False:
                return
            # A different process must not have replaced this file meanwhile.
            again = self.path.stat()
            if (info.st_ino, info.st_dev, info.st_mtime_ns, info.st_size) != (
                    again.st_ino, again.st_dev, again.st_mtime_ns, again.st_size):
                return
            self.path.unlink()
        except (OSError, UnicodeError, ValueError, TypeError):
            return

    def acquire(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self._remove_if_stale()
        flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
        try:
            fd = os.open(self.path, flags, 0o600)
        except FileExistsError as exc:
            raise JobAlreadyRunningError(
                f"Job is already running: {self.job_id} / ジョブはすでに実行中です: {self.job_id}"
            ) from exc
        try:
            nonce = uuid.uuid4().hex
            payload = json.dumps({
                "pid": os.getpid(), "created_at": time.time(),
                "job_id": self.job_id, "nonce": nonce,
            })
            os.write(fd, payload.encode("utf-8"))
            os.fsync(fd)
            self._nonce = nonce
            self.acquired = True
        finally:
            os.close(fd)

    def release(self) -> None:
        if not self.acquired:
            return
        try:
            try:
                record = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, ValueError):
                return
            if (isinstance(record, dict)
                    and record.get("nonce") == self._nonce
                    and record.get("pid") == os.getpid()):
                try:
                    self.path.unlink()
                except FileNotFoundError:
                    pass
        finally:
            self.acquired = False
            self._nonce = None

    def __enter__(self) -> "JobExecutionLock":
        self.acquire()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.release()
