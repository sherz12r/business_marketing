"""Cross-process guard that allows only one outreach automation at a time."""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

from app_paths import get_app_dir


LOCK_PATH = Path(get_app_dir()) / "data" / "runtime" / "automation.lock"


class AutomationLock:
    def __init__(self, path=LOCK_PATH):
        self.path = Path(path)
        self.handle = None

    def acquire(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.path.open("a+", encoding="utf-8")
        try:
            handle.seek(0, os.SEEK_END)
            if handle.tell() == 0:
                handle.write(" ")
                handle.flush()
            handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (OSError, BlockingIOError):
            handle.close()
            return False

        self.handle = handle
        handle.seek(0)
        handle.truncate()
        handle.write(json.dumps({
            "pid": os.getpid(),
            "started_at": datetime.now().isoformat(timespec="seconds"),
        }))
        handle.flush()
        return True

    def release(self):
        handle = self.handle
        self.handle = None
        if not handle:
            return
        try:
            handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()

    def __enter__(self):
        return self if self.acquire() else None

    def __exit__(self, _exc_type, _exc, _traceback):
        self.release()


def automation_running():
    """Return whether another process currently owns the automation lock."""
    probe = AutomationLock()
    if not probe.acquire():
        return True
    probe.release()
    return False
