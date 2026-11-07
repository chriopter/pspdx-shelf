"""Jobs: everything the service does that takes longer than a request. One
worker thread runs them one after the other, so two jobs never touch the
library at once; the UI polls their state. Every job ever queued in this
process stays in the list, with its log tail, until the process ends."""
from __future__ import annotations

import dataclasses
import datetime as dt
import logging
import queue
import threading
import traceback
from collections import deque
from typing import Any, Callable

log = logging.getLogger("jobs")

QUEUED, RUNNING, DONE, FAILED, CANCELLED = "queued", "running", "done", "failed", "cancelled"


class Cancelled(Exception):
    """Raised inside a job when the user pressed cancel."""


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclasses.dataclass
class Job:
    """One queued, running, or finished background task."""

    id: int
    kind: str
    title: str
    state: str = QUEUED
    progress: int = 0
    total: int = 0
    message: str = ""
    result: Any = None
    error: str | None = None
    queued_at: str = dataclasses.field(default_factory=_now)
    started_at: str | None = None
    ended_at: str | None = None
    lines: deque = dataclasses.field(default_factory=lambda: deque(maxlen=400))
    cancel_requested: bool = False

    # -- what a job function calls -------------------------------------------
    def log(self, message: str) -> None:
        """Append a message to the job log."""
        self.lines.append(f"{_now()} {message}")
        log.info("job %d %s: %s", self.id, self.kind, message)

    def set_progress(self, progress: int, total: int | None = None, message: str | None = None) -> None:
        """Update job progress and raise if cancellation was requested."""
        self.progress = progress
        if total is not None:
            self.total = total
        if message is not None:
            self.message = message
        if self.cancel_requested:
            raise Cancelled()

    def check_cancel(self) -> None:
        """Raise Cancelled if the user requested cancellation."""
        if self.cancel_requested:
            raise Cancelled()

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable representation for the UI."""
        d = {k: v for k, v in dataclasses.asdict(self).items() if k not in ("lines", "result")}
        d["lines"] = list(self.lines)
        d["percent"] = int(self.progress * 100 / self.total) if self.total else (100 if self.state == DONE else 0)
        d["result"] = self.result if isinstance(self.result, (dict, list, str, int, float, type(None))) else str(self.result)
        return d


class JobManager:
    """Single-worker job queue with in-process job history."""

    def __init__(self):
        self._jobs: dict[int, Job] = {}
        self._order: list[int] = []
        self._queue: queue.Queue = queue.Queue()
        self._lock = threading.Lock()
        self._next = 1
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._run_lock = threading.Lock()
        self.current: Job | None = None

    def start(self) -> None:
        """Start the worker thread once."""
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, name="jobs", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        """Request worker shutdown and wait briefly for it."""
        self._stop.set()
        self._queue.put(None)
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None

    def submit(self, kind: str, title: str, fn: Callable[[Job], Any], *, unique: bool = False) -> Job:
        """Queue fn(job). With unique, a job of the same kind that is queued
        or running is returned instead of queueing another."""
        with self._lock:
            if unique:
                for job_id in self._order:
                    job = self._jobs[job_id]
                    if job.kind == kind and job.state in (QUEUED, RUNNING):
                        return job
            job = Job(id=self._next, kind=kind, title=title)
            self._next += 1
            self._jobs[job.id] = job
            self._order.append(job.id)
        self._queue.put((job, fn))
        log.info("job %d queued: %s", job.id, title)
        return job

    def cancel(self, job_id: int) -> bool:
        """Request cancellation of a queued or running job."""
        job = self._jobs.get(job_id)
        if job is None or job.state not in (QUEUED, RUNNING):
            return False
        job.cancel_requested = True
        if job.state == QUEUED:
            job.state = CANCELLED
            job.ended_at = _now()
            job.log("cancelled before it started")
        return True

    def get(self, job_id: int) -> Job | None:
        """Return a job by id, or None."""
        return self._jobs.get(job_id)

    def all(self) -> list[Job]:
        """Return all jobs, newest first."""
        with self._lock:
            return [self._jobs[i] for i in reversed(self._order)]

    def active(self, kind: str | None = None) -> list[Job]:
        """Return queued or running jobs, optionally filtered by kind."""
        return [j for j in self.all() if j.state in (QUEUED, RUNNING)
                and (kind is None or j.kind == kind)]

    def run_now(self, job: Job, fn: Callable[[Job], Any]) -> Job:
        """Run a job in the calling thread; the tests use it, and so does
        the worker."""
        with self._run_lock:
            if job.state == CANCELLED:
                return job
            job.state = RUNNING
            job.started_at = _now()
            self.current = job
            try:
                job.result = fn(job)
                job.state = DONE
                if job.total and job.progress < job.total:
                    job.progress = job.total
            except Cancelled:
                job.state = CANCELLED
                job.log("cancelled")
            except Exception as exc:  # a job's failure is its own, the worker lives on
                job.state = FAILED
                job.error = f"{type(exc).__name__}: {exc}"
                job.log(f"failed: {job.error}")
                log.error("job %d failed:\n%s", job.id, traceback.format_exc())
            finally:
                job.ended_at = _now()
                self.current = None
        return job

    def _run(self) -> None:
        """Worker loop."""
        while not self._stop.is_set():
            item = self._queue.get()
            if item is None:
                break
            job, fn = item
            self.run_now(job, fn)
