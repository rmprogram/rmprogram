"""Tareas en segundo plano para que la interfaz nunca se congele."""
from __future__ import annotations

import traceback
from typing import Any, Callable

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal


class _Signals(QObject):
    progress = Signal(float)
    done = Signal(object)
    failed = Signal(str)


class Task(QRunnable):
    """Ejecuta fn(progress=cb, cancel=cb, *args) en otro hilo."""

    def __init__(self, fn: Callable[..., Any], *args, **kwargs):
        super().__init__()
        self.fn, self.args, self.kwargs = fn, args, kwargs
        self.signals = _Signals()
        self._cancel = False
        self.setAutoDelete(False)

    def cancel(self):
        self._cancel = True

    def is_cancelled(self) -> bool:
        return self._cancel

    def run(self):
        try:
            result = self.fn(*self.args, progress=self.signals.progress.emit,
                             cancel=self.is_cancelled, **self.kwargs)
            self.signals.done.emit(result)
        except Exception as exc:  # noqa: BLE001
            msg = str(exc) or exc.__class__.__name__
            if "cancel" not in msg.lower():
                traceback.print_exc()
            self.signals.failed.emit(msg)


_alive: set[Task] = set()  # mantiene vivas las tareas hasta que entregan su resultado


def start(task: Task) -> Task:
    _alive.add(task)
    task.signals.done.connect(lambda *_: _alive.discard(task))
    task.signals.failed.connect(lambda *_: _alive.discard(task))
    QThreadPool.globalInstance().start(task)
    return task
