"""Runs coroutines on one background asyncio loop and delivers results on the Qt thread."""
import asyncio
import threading
from collections.abc import Callable, Coroutine
from typing import Any

from PySide6.QtCore import QObject, Signal, Slot


class AsyncRunner(QObject):
    _done = Signal(object, object, object)

    def __init__(self):
        super().__init__()
        self._loop = asyncio.new_event_loop()
        threading.Thread(target=self._loop.run_forever, daemon=True).start()
        # Bound QObject slot, so the queued delivery lands on the thread this object lives in.
        self._done.connect(self._dispatch)

    @Slot(object, object, object)
    def _dispatch(self, callback: Callable, result: Any, error: BaseException | None) -> None:
        callback(result, error)

    def submit(self, coro: Coroutine, callback: Callable[[Any, BaseException | None], None]) -> None:
        """Run `coro`; call `callback(result, error)` on the Qt thread when it finishes."""
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        future.add_done_callback(
            lambda f: self._done.emit(callback, None if f.exception() else f.result(), f.exception())
        )
