"""The watch folder: a thread that queues a scan every N seconds while the
setting is on. It is shown on the Scan and Jobs pages; the scans it queues
are ordinary jobs, so nothing runs out of sight."""
from __future__ import annotations

import threading
import time
from typing import Callable


class Watcher:
    """Periodic scan scheduler controlled by live settings."""

    def __init__(self, submit_scan: Callable[[str], object], is_enabled: Callable[[], bool],
                 interval: Callable[[], int]):
        self._submit = submit_scan
        self._enabled = is_enabled
        self._interval = interval
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.last_run: float | None = None
        self.next_run: float | None = None

    def start(self) -> None:
        """Start the watcher thread once."""
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, name="watch", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        """Request watcher shutdown and wait briefly for it."""
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None

    def status(self) -> dict:
        """Return status for the UI."""
        now = time.time()
        return {"enabled": self._enabled(), "interval": self._interval(),
                "last_run": self.last_run,
                "next_in": max(0, int(self.next_run - now)) if self.next_run and self._enabled() else None}

    def _run(self) -> None:
        while not self._stop.is_set():
            if self._enabled():
                if self.next_run is None:
                    self.next_run = time.time() + self._interval()
                if time.time() >= self.next_run:
                    self._submit("watch folder: scheduled scan")
                    self.last_run = time.time()
                    self.next_run = time.time() + self._interval()
            else:
                self.next_run = None
            self._stop.wait(1)
