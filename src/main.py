import sys

from PySide6.QtWidgets import QApplication

from core.async_runner import AsyncRunner
from core.store import Store, default_db_path
from ui.main_window import MainWindow


def main() -> None:
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)  # window hides to tray
    store = Store(default_db_path())
    window = MainWindow(store, AsyncRunner())
    if "--minimized" not in sys.argv:  # autostart keeps the window in the tray
        window.show()
    window.start()
    code = app.exec()
    store.close()
    sys.exit(code)
