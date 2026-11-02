"""Single-instance launch: a second start wakes the first instead of opening another copy."""
import os
import subprocess
import sys
import time
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "offscreen"

import pytest
from PySide6.QtCore import QObject
from PySide6.QtWidgets import QApplication

from main import acquire_instance_lock, notify_running_instance, serve_instance

CHILD = """
import sys
from PySide6.QtCore import QCoreApplication
from main import notify_running_instance

app = QCoreApplication([])
sys.exit(0 if notify_running_instance(sys.argv[1], sys.argv[2] == "show") else 1)
"""


class FakeWindow(QObject):
    def __init__(self):
        super().__init__()
        self.shown = 0

    def show_window(self) -> None:
        self.shown += 1


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def pump(app, until, seconds: float = 10.0) -> None:
    end = time.monotonic() + seconds
    while time.monotonic() < end and not until():
        app.processEvents()
        time.sleep(0.01)


def launch(name: str, mode: str) -> subprocess.Popen:
    """A second copy of the app: a separate process that only runs the notify step."""
    env = {**os.environ, "PYTHONPATH": str(Path(__file__).parent.parent / "src")}
    return subprocess.Popen([sys.executable, "-c", CHILD, name, mode], env=env)


def test_second_launch_opens_the_running_window_once(app):
    name = f"tapocontrol-test-{os.getpid()}"
    window = FakeWindow()
    server = serve_instance(window, name)
    assert server is not None
    second = launch(name, "show")
    pump(app, lambda: window.shown and second.poll() is not None)
    assert second.returncode == 0 and window.shown == 1
    quiet = launch(name, "quiet")  # an autostart launch stays quiet
    pump(app, lambda: quiet.poll() is not None)
    pump(app, lambda: False, 0.3)
    assert quiet.returncode == 0 and window.shown == 1
    server.close()
    assert not notify_running_instance(name)  # nothing listening: this launch is the first copy


def test_only_one_copy_holds_the_lock(tmp_path):
    path = str(tmp_path / "app.lock")
    first = acquire_instance_lock(path)
    assert first is not None
    assert acquire_instance_lock(path) is None  # a second copy cannot start
    first.unlock()
    again = acquire_instance_lock(path)
    assert again is not None  # released on exit, so the next start works
    again.unlock()
