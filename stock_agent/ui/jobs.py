"""Run one collection or weekly job and keep its printed lines."""

from __future__ import annotations

import sys
import threading
import time
from typing import Callable

WEEKLY_NOTE = "A full weekly run takes about an hour."
_KINDS = {"collect", "weekly"}
Runner = Callable[[str], None]


class JobManager:
    """One job at a time. Printed lines are kept for the window."""

    def __init__(self, runner: Runner | None = None):
        self.runner = runner or default_runner
        self.cond = threading.Condition()
        self.stopped = threading.Event()
        self.status = "idle"
        self.job: str | None = None
        self.generation = 0
        self.next_id = 0
        self.lines: list[tuple[int, str]] = []
        self.thread: threading.Thread | None = None

    def start(self, kind: str) -> tuple[int, dict]:
        if kind not in _KINDS:
            return 400, {"error": "Choose collect or weekly."}
        with self.cond:
            if self.status == "running":
                return 409, {
                    "error": "A job is already running.",
                    "job": self.job,
                    "status": self.status,
                }
            self.status = "running"
            self.job = kind
            self.generation += 1
            self.lines = []
            self.thread = threading.Thread(
                target=self._run,
                args=(kind,),
                name=f"stock-agent-{kind}",
                daemon=True,
            )
            self.thread.start()
            self.cond.notify_all()
            return 202, self._payload_locked()

    def snapshot(self) -> dict:
        with self.cond:
            return self._payload_locked()

    def wait(self, timeout: float) -> bool:
        with self.cond:
            thread = self.thread
            running = self.status == "running"
        if thread is None or not running:
            return True
        thread.join(timeout)
        return not thread.is_alive()

    def close(self) -> None:
        self.stopped.set()
        with self.cond:
            self.cond.notify_all()

    def wait_from(
        self,
        cursor: int,
        timeout: float,
        generation: int | None = None,
    ) -> tuple[list[tuple[int, str]], dict]:
        """Block until new lines arrive, the job changes, or the timeout ends."""
        deadline = time.monotonic() + timeout
        with self.cond:
            while not self.stopped.is_set():
                fresh = any(index > cursor for index, _text in self.lines)
                if fresh or (generation is not None and self.generation != generation):
                    break
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                self.cond.wait(remaining)
            indexed = [(index, text) for index, text in self.lines if index > cursor]
            return indexed, self._payload_locked()

    def _run(self, kind: str) -> None:
        writer = _LineCapture(self, sys.stdout)
        previous = sys.stdout
        sys.stdout = writer
        status = "finished"
        try:
            self.runner(kind)
        except Exception as exc:
            status = "failed"
            message = str(exc).strip() or exc.__class__.__name__
            print(f"Stopped: {message}")
        finally:
            writer.flush_partial()
            sys.stdout = previous
            with self.cond:
                self.status = status
                self.cond.notify_all()

    def _append(self, line: str) -> None:
        with self.cond:
            self.next_id += 1
            self.lines.append((self.next_id, line))
            self.cond.notify_all()

    def _payload_locked(self) -> dict:
        return {
            "job": self.job,
            "status": self.status,
            "generation": self.generation,
            "lines": [text for _index, text in self.lines],
            "weekly_note": WEEKLY_NOTE,
        }


class _LineCapture:
    def __init__(self, manager: JobManager, underlying):
        self._manager = manager
        self._underlying = underlying
        self._buffer = ""
        self._lock = threading.Lock()

    def write(self, text: str) -> int:
        if not isinstance(text, str):
            text = str(text)
        try:
            self._underlying.write(text)
        except Exception:
            pass
        with self._lock:
            self._buffer += text
            while "\n" in self._buffer:
                line, self._buffer = self._buffer.split("\n", 1)
                self._emit(line)
        return len(text)

    def flush(self) -> None:
        try:
            self._underlying.flush()
        except Exception:
            pass

    def flush_partial(self) -> None:
        with self._lock:
            if self._buffer.strip():
                self._emit(self._buffer)
            self._buffer = ""

    def _emit(self, line: str) -> None:
        cleaned = line.rstrip()
        if cleaned.strip():
            self._manager._append(cleaned)


def default_runner(kind: str) -> None:
    from stock_agent.core.config import Settings
    from stock_agent.jobs.collect import run_collection
    from stock_agent.jobs.weekly import run_weekly

    settings = Settings.load()
    if kind == "collect":
        print("Collecting today.")
        summary = run_collection(settings)
        print(
            f"Done. Members {summary['members']}, priced {summary['priced']}, "
            f"rows {summary['rows']}, stats {summary['stats']}, articles {summary['articles']}."
        )
        return
    if kind == "weekly":
        print("Starting the weekly analysis.")
        print(WEEKLY_NOTE)
        summary = run_weekly(settings)
        print(
            f"Week {summary['week_ending']}: clusters {summary['clusters']}, "
            f"impacts {summary['impacts']}, scores {summary['scores']}, email {summary['email_status']}."
        )
        if summary.get("report_path"):
            print(summary["report_path"])
        return
    raise ValueError(f"Unknown job {kind}")
