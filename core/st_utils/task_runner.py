"""
Background task runner for Streamlit with pause/resume/stop control.

Usage:
    runner = TaskRunner.get(st.session_state)
    runner.start(steps)  # list of (label, callable) tuples
    runner.pause() / runner.resume() / runner.stop()
    runner.state  # "idle" | "running" | "paused" | "stopped" | "completed" | "error"
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Callable


class StopTask(Exception):
    """Raised when the task is stopped by user."""

    pass


@dataclass
class TaskRunner:
    """Manages a background thread that executes a sequence of steps with pause/stop control."""

    # Public read-only state
    state: str = "idle"  # idle | running | paused | stopped | completed | error
    current_step: int = -1  # 0-indexed, -1 = not started
    total_steps: int = 0
    current_label: str = ""
    error_msg: str = ""

    # Internal
    _pause_event: threading.Event = field(default_factory=threading.Event)
    _stop_event: threading.Event = field(default_factory=threading.Event)
    _thread: threading.Thread | None = None
    _steps: list = field(default_factory=list)
    _before_run: Callable | None = None
    _cleanup_run: Callable | None = None
    _on_success: Callable | None = None
    _on_error: Callable | None = None
    _on_stopped: Callable | None = None

    def __post_init__(self):
        self._pause_event.set()  # not paused initially

    # ------ Singleton per session_state ------
    @staticmethod
    def get(session_state, key: str = "_task_runner") -> "TaskRunner":
        """Get or create a TaskRunner stored in Streamlit session_state."""
        if key not in session_state:
            session_state[key] = TaskRunner()
        return session_state[key]

    # ------ Control API ------

    def start(
        self,
        steps: list[tuple[str, Callable]],
        before_run: Callable | None = None,
        cleanup_run: Callable | None = None,
        on_success: Callable | None = None,
        on_error: Callable | None = None,
        on_stopped: Callable | None = None,
    ):
        """Start executing steps in a background thread.

        Args:
            steps: list of (label, callable) — each callable takes no args.
        """
        if self.state == "running" or self.state == "paused":
            return  # already running

        self._steps = steps
        self._before_run = before_run
        self._cleanup_run = cleanup_run
        self._on_success = on_success
        self._on_error = on_error
        self._on_stopped = on_stopped
        self.total_steps = len(steps)
        self.current_step = -1
        self.current_label = ""
        self.error_msg = ""
        self.state = "running"

        self._pause_event.set()
        self._stop_event.clear()

        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def pause(self):
        if self.state == "running":
            self._pause_event.clear()
            self.state = "paused"

    def resume(self):
        if self.state == "paused":
            self._pause_event.set()
            self.state = "running"

    def stop(self):
        """Request stop. The task will halt before the next step."""
        if self.state in ("running", "paused"):
            self._stop_event.set()
            self._pause_event.set()  # unblock if paused so thread can exit
            self.state = "stopped"

    def reset(self):
        """Reset to idle state (only when not running)."""
        if self.state not in ("running", "paused"):
            self.state = "idle"
            self.current_step = -1
            self.total_steps = 0
            self.current_label = ""
            self.error_msg = ""
            self._steps = []
            self._before_run = None
            self._cleanup_run = None
            self._on_success = None
            self._on_error = None
            self._on_stopped = None

    @property
    def is_active(self) -> bool:
        return self.state in ("running", "paused")

    @property
    def is_done(self) -> bool:
        return self.state in ("completed", "stopped", "error")

    @property
    def progress(self) -> float:
        """0.0 to 1.0"""
        if self.total_steps == 0:
            return 0.0
        return min((self.current_step + 1) / self.total_steps, 1.0)

    # ------ Internal ------

    def _run(self):
        """Execute steps sequentially in background thread."""
        try:
            if self._before_run:
                self._before_run()

            for i, (label, func) in enumerate(self._steps):
                # Check stop before each step
                if self._stop_event.is_set():
                    self.state = "stopped"
                    if self._on_stopped:
                        self._on_stopped()
                    return

                # Block if paused
                self._pause_event.wait()

                # Check stop again after resume
                if self._stop_event.is_set():
                    self.state = "stopped"
                    if self._on_stopped:
                        self._on_stopped()
                    return

                self.current_step = i
                self.current_label = label
                func()

            self.state = "completed"
            if self._on_success:
                self._on_success()
        except Exception as e:
            self.error_msg = str(e)
            self.state = "error"
            if self._on_error:
                self._on_error(e)
        finally:
            if self._cleanup_run:
                try:
                    self._cleanup_run()
                except Exception as cleanup_error:
                    if self.state != "error":
                        self.error_msg = str(cleanup_error)
                        self.state = "error"
