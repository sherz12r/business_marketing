"""
Daily session logs under logs/ — only the last 7 days are kept.
"""

import io
import os
import sys
from datetime import datetime, timedelta


def ensure_stdio():
    """Windowed .exe builds have no console; stdout/stderr may be None."""
    if sys.stdout is None:
        sys.stdout = io.StringIO()
    if sys.stderr is None:
        sys.stderr = io.StringIO()

LOG_DIR = "logs"
RETENTION_DAYS = 7
PREFIX = "Marketing_"


def _log_dir(base_dir: str) -> str:
    return os.path.join(base_dir, LOG_DIR)


def prune_old_logs(base_dir: str = ".", retention_days: int = RETENTION_DAYS) -> None:
    directory = _log_dir(base_dir)
    if not os.path.isdir(directory):
        return

    cutoff = datetime.now().date() - timedelta(days=retention_days - 1)
    for name in os.listdir(directory):
        if not name.startswith(PREFIX):
            continue
        if not name.endswith(".log"):
            continue
        stem = name[len(PREFIX):-4]
        # stem = name[:-4]
        try:
            file_date = datetime.strptime(stem, "%Y-%m-%d").date()
        except ValueError:
            continue
        if file_date < cutoff:
            try:
                os.remove(os.path.join(directory, name))
            except OSError:
                pass


def today_log_path(base_dir: str = ".") -> str:
    directory = _log_dir(base_dir)
    os.makedirs(directory, exist_ok=True)
    prune_old_logs(base_dir)
    return os.path.join(directory, f"{PREFIX}{datetime.now():%Y-%m-%d}.log")


class _Tee:
    def __init__(self, stream, file_handle, on_line=None):
        self._stream = stream
        self._file = file_handle
        self._on_line = on_line
        self._buffer = ""

    def write(self, data):
        if not data:
            return
        if self._stream is not None:
            self._stream.write(data)
        self._file.write(data)
        self._file.flush()

        if self._on_line:
            self._buffer += data
            while "\n" in self._buffer:
                line, self._buffer = self._buffer.split("\n", 1)
                if line.strip():
                    self._on_line(line)

    def flush(self):
        if self._stream is not None:
            self._stream.flush()
        self._file.flush()
        if self._buffer.strip() and self._on_line:
            self._on_line(self._buffer.rstrip())
            self._buffer = ""

    def isatty(self):
        return getattr(self._stream, "isatty", lambda: False)()


class SessionLog:
    """Redirect stdout/stderr to today's log file (and optional GUI callback)."""

    def __init__(self, base_dir: str = ".", on_line=None):
        self._base_dir = base_dir
        self._on_line = on_line
        self._file = None
        self._orig_stdout = None
        self._orig_stderr = None
        self.path = None

    def __enter__(self):
        ensure_stdio()
        self.path = today_log_path(self._base_dir)
        self._file = open(self.path, "a", encoding="utf-8")
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self._file.write(f"\n--- Automation started {stamp} ---\n")
        self._file.flush()

        self._orig_stdout = sys.stdout
        self._orig_stderr = sys.stderr
        sys.stdout = _Tee(self._orig_stdout, self._file, self._on_line)
        sys.stderr = _Tee(self._orig_stderr, self._file, self._on_line)
        return self

    def __exit__(self, exc_val):
        if self._file:
            stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            if exc_val:
                self._file.write(f"\n--- Automation ended with error {stamp}: {exc_val} ---\n")
            else:
                self._file.write(f"\n--- Automation ended {stamp} ---\n")
            self._file.flush()

        sys.stdout = self._orig_stdout
        sys.stderr = self._orig_stderr

        if self._file:
            self._file.close()
            self._file = None
        return False


def append_log_line(message: str, base_dir: str = ".") -> str:
    """Append one line to today's log; returns the log file path."""
    path = today_log_path(base_dir)
    stamp = datetime.now().strftime("%H:%M:%S")
    with open(path, "a", encoding="utf-8") as f:
        f.write(f"[{stamp}] {message}\n")
    return path