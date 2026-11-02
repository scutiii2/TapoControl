import sys
import tempfile
import time
from pathlib import Path

from PySide6.QtCore import QLockFile
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication

from core.async_runner import AsyncRunner
from core.store import Store, default_db_path
from ui.main_window import MainWindow

INSTANCE_NAME = "TapoControl-single-instance"
SHOW = b"show"
WAIT_MS = 500


def acquire_instance_lock(path: str | None = None) -> QLockFile | None:
    """The one lock every copy races for; None when another copy holds it. Keep the result alive while running."""
    lock = QLockFile(path or str(Path(tempfile.gettempdir()) / "TapoControl.lock"))
    lock.setStaleLockTime(0)  # a lock is stale only when its process is gone, never because it is old
    return lock if lock.tryLock(0) else None


def notify_running_instance(name: str = INSTANCE_NAME, show: bool = True) -> bool:
    """Tell a copy that is already running to open its window. True when one answered."""
    socket = QLocalSocket()
    socket.connectToServer(name)
    if not socket.waitForConnected(WAIT_MS):
        return False
    if show:
        socket.write(SHOW)
        socket.waitForBytesWritten(WAIT_MS)
    socket.disconnectFromServer()
    return True


def serve_instance(window: MainWindow, name: str = INSTANCE_NAME) -> QLocalServer | None:
    """Listen for later launches, and open the window when one asks."""
    server = QLocalServer(window)

    def connected() -> None:
        socket = server.nextPendingConnection()

        def read() -> None:
            if socket.readAll().data() == SHOW:
                window.show_window()

        socket.readyRead.connect(read)
        socket.disconnected.connect(socket.deleteLater)
        read()  # the client may have written and left before this slot ran

    server.newConnection.connect(connected)
    return server if server.listen(name) else None  # None: the name is taken


def main() -> None:
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)  # window hides to tray
    minimized = "--minimized" in sys.argv  # autostart keeps the window in the tray
    lock = acquire_instance_lock()
    if lock is None:  # a copy is running: ask it to open its window, then leave
        for _ in range(10):  # it may still be starting its server
            if notify_running_instance(show=not minimized):
                break
            time.sleep(0.2)
        sys.exit(0)
    store = Store(default_db_path())
    window = MainWindow(store, AsyncRunner())
    serve_instance(window)
    if not minimized:
        window.show()
    window.start()
    code = app.exec()
    store.close()
    lock.unlock()
    sys.exit(code)
