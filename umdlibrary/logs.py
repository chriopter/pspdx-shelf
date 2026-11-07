"""The service log: a file in the data volume, and a ring buffer of the last
lines so the Logs page has them without reading the file back."""
from __future__ import annotations

import collections
import logging
import threading

FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"


class RingHandler(logging.Handler):
    """Logging handler that keeps a bounded in-memory tail."""

    def __init__(self, capacity: int = 5000):
        """Create a ring buffer with capacity lines."""
        super().__init__()
        self.lines: collections.deque[str] = collections.deque(maxlen=capacity)
        self._lock = threading.Lock()

    def emit(self, record: logging.LogRecord) -> None:
        """Append one formatted log record."""
        line = self.format(record)
        with self._lock:
            self.lines.append(line)

    def tail(self, n: int) -> list[str]:
        """Return the last n formatted log lines."""
        with self._lock:
            lines = list(self.lines)
        return lines[-n:]


def setup(path: str | None, level: int = logging.INFO) -> RingHandler:
    """Configure root logging to stream, optional file, and ring buffer."""
    root = logging.getLogger()
    root.setLevel(level)
    formatter = logging.Formatter(FORMAT, "%Y-%m-%d %H:%M:%S")
    ring = RingHandler()
    ring.setFormatter(formatter)
    root.addHandler(ring)
    stream = logging.StreamHandler()
    stream.setFormatter(formatter)
    root.addHandler(stream)
    if path:
        file_handler = logging.FileHandler(path, encoding="utf-8")
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)
    # werkzeug logs every request at INFO; that is noise next to the jobs.
    logging.getLogger("werkzeug").setLevel(logging.WARNING)
    return ring
