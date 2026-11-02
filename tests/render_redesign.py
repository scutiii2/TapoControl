"""Render actual native widgets with synthetic data, never credentials or real devices.

Usage: .venv/Scripts/python.exe tests/render_redesign.py
"""

import math
import os
import sys
import time
from collections import deque
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtGui import QFontDatabase  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from core.controller import EnergySummary  # noqa: E402
from core.store import DeviceInfo, Store  # noqa: E402
from ui.main_window import MainWindow  # noqa: E402


class OfflineRunner:
    """Fail closed if preview accidentally tries to submit network work."""

    def submit(self, coro, callback) -> None:
        coro.close()
        raise AssertionError("Native preview must not perform network operations")


class NativePreview:
    def __init__(self, app: QApplication) -> None:
        self.app = app
        self.output = Path(__file__).resolve().parents[1] / "artifacts" / "redesign"
        self.output.mkdir(parents=True, exist_ok=True)
        self.store = Store(Path(":memory:"))
        self.window = MainWindow(self.store, OfflineRunner())
        self.window._tray.hide()
        self.window._controller = object()
        names = ["Workstation", "Living room fan", "Desk lamp", "Coffee station"]
        devices = [DeviceInfo(f"192.0.2.{21 + i}", name, "P110") for i, name in enumerate(names)]
        self.store.save_devices(devices)
        self.window._devices = {d.ip: d for d in devices}
        self.window._state = {devices[0].ip: (True, 182.4), devices[1].ip: (True, 42.8), devices[2].ip: (False, 0)}
        self.window._energy = {
            d.ip: EnergySummary(wh, month)
            for d, wh, month in zip(devices, [1460, 610, 70, 200], [30000, 12000, 1620, 5000], strict=True)
        }
        now = time.time()
        for i, d in enumerate(devices[:3]):
            values = [182.4 + 15 * math.sin(k / 8) if i == 0 else 42.8 if i == 1 else 0 for k in range(120)]
            self.window._samples[d.ip] = deque(values, maxlen=120)
            self.window._times[d.ip] = deque([now - (119 - k) * 5 for k in range(120)], maxlen=120)
        self.window._render()
        self.window.show()
        self.shots = iter([
            ("overview-expanded", 1440, 1060, False, 0),
            ("overview-collapsed", 1440, 1060, True, 0),
            ("overview-narrow", 760, 640, True, 0),
            ("devices-narrow", 760, 640, True, 1),
            ("account", 1440, 1060, False, 3),
            ("settings", 1440, 1060, False, 4),
        ])
        self.advance()

    def advance(self) -> None:
        shot = next(self.shots, None)
        if shot is None:
            self.window.hide()
            self.store.close()
            self.app.quit()
            return
        self.name, width, height, collapsed, page = shot
        self.window._tabs.set_collapsed(collapsed)
        self.window._tabs.setCurrentIndex(page)
        self.window.resize(width, height)
        QTimer.singleShot(200, self.capture)

    def capture(self) -> None:
        path = self.output / f"{self.name}.png"
        if not self.window.grab().save(str(path)):
            raise RuntimeError(f"Could not render {path}")
        print(f"{path} ({self.window.width()}x{self.window.height()})", flush=True)
        self.advance()


if __name__ == "__main__":
    application = QApplication(sys.argv)
    font_dir = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
    for font_file in ("segoeui.ttf", "segoeuib.ttf", "seguisb.ttf"):
        if (font_dir / font_file).exists():
            QFontDatabase.addApplicationFont(str(font_dir / font_file))
    application.setQuitOnLastWindowClosed(False)
    preview = NativePreview(application)
    sys.exit(application.exec())
