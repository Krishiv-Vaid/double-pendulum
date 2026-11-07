"""Background jobs for expensive experiments (maps, Lyapunov scans, sweeps...).

Each job runs in its own daemon thread. A job function receives a
:class:`JobContext` with ``progress(fraction, partial=None)`` and
``cancelled()``; it should poll ``cancelled()`` and raise
:class:`InterruptedError` to stop. Finished jobs are kept for ``ttl`` seconds.
The number of concurrently *running* jobs is bounded so that a browser tab
cannot fork-bomb the machine.
"""

from __future__ import annotations

import threading
import time
import traceback
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any


class JobLimitError(RuntimeError):
    pass


@dataclass
class Job:
    id: str
    kind: str
    status: str = "running"  # running | done | error | cancelled
    progress: float = 0.0
    message: str = ""
    result: Any = None
    partial: Any = None
    created: float = field(default_factory=time.time)
    finished: float | None = None
    _cancel: threading.Event = field(default_factory=threading.Event, repr=False)

    def info(self, include_partial: bool = False) -> dict:
        d = {
            "id": self.id,
            "kind": self.kind,
            "status": self.status,
            "progress": round(float(self.progress), 4),
            "message": self.message,
            "elapsed_s": round((self.finished or time.time()) - self.created, 3),
        }
        if self.status == "done":
            d["result"] = self.result
        elif include_partial and self.partial is not None:
            d["partial"] = self.partial
        return d


class JobContext:
    def __init__(self, job: Job):
        self._job = job

    def progress(self, fraction: float, partial: Any = None, message: str | None = None) -> None:
        self._job.progress = max(0.0, min(1.0, float(fraction)))
        if partial is not None:
            self._job.partial = partial
        if message is not None:
            self._job.message = message

    def cancelled(self) -> bool:
        return self._job._cancel.is_set()

    def check(self) -> None:
        if self.cancelled():
            raise InterruptedError("cancelled")


class JobManager:
    def __init__(self, max_running: int = 3, ttl: float = 900.0):
        self.max_running = max_running
        self.ttl = ttl
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    def _gc(self) -> None:
        now = time.time()
        for jid in [j.id for j in self._jobs.values() if j.finished and now - j.finished > self.ttl]:
            del self._jobs[jid]

    def running(self) -> int:
        return sum(1 for j in self._jobs.values() if j.status == "running")

    def submit(self, kind: str, fn: Callable[[JobContext], Any]) -> Job:
        with self._lock:
            self._gc()
            if self.running() >= self.max_running:
                raise JobLimitError(f"too many running jobs (limit {self.max_running}); cancel one or wait")
            job = Job(id=uuid.uuid4().hex[:12], kind=kind)
            self._jobs[job.id] = job
        ctx = JobContext(job)

        def run():
            try:
                job.result = fn(ctx)
                job.status = "cancelled" if ctx.cancelled() else "done"
                job.progress = 1.0 if job.status == "done" else job.progress
            except InterruptedError:
                job.status = "cancelled"
                job.message = "cancelled"
            except Exception as e:  # reported to the client, never swallowed
                job.status = "error"
                job.message = f"{type(e).__name__}: {e}"
                traceback.print_exc()
            finally:
                job.finished = time.time()
                job.partial = None

        threading.Thread(target=run, name=f"job-{kind}-{job.id}", daemon=True).start()
        return job

    def get(self, jid: str) -> Job | None:
        return self._jobs.get(jid)

    def cancel(self, jid: str) -> bool:
        job = self._jobs.get(jid)
        if job is None:
            return False
        job._cancel.set()
        return True

    def list(self) -> list[dict]:
        return [j.info() | {"result": None} for j in sorted(self._jobs.values(), key=lambda j: j.created)]

    def wait(self, jid: str, timeout: float = 60.0) -> Job:
        """Block until a job finishes (used by tests)."""
        t0 = time.time()
        job = self._jobs[jid]
        while job.status == "running":
            if time.time() - t0 > timeout:
                raise TimeoutError(jid)
            time.sleep(0.02)
        return job
