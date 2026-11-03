"""Render control pages offline with synthetic data, in both themes and window sizes.

Usage: .venv/Scripts/python.exe tests/render_control_pages.py
"""

import sys
import time
from datetime import date, timedelta
from pathlib import Path

from render_redesign import NativePreview, QApplication, QFontDatabase, QTimer

from core.controller import EnergySummary
from ui.theme import theme


class ControlPreview(NativePreview):
    """Reuse the fail-closed preview; changing pages never dispatches plug work."""

    def advance(self) -> None:
        if not hasattr(self, "_control_shots"):
            self.output = Path(__file__).resolve().parents[1] / ".impeccable" / "review"
            self.output.mkdir(parents=True, exist_ok=True)
            self.window._timers["192.0.2.22"] = (time.time() + 1800, False)
            history = self.window._history
            history._names = {ip: d.alias for ip, d in self.window._devices.items()}
            history._sync_filter()
            history._summaries = {
                ip: EnergySummary(wh, month, 120 + i * 60, 2000 + i * 100)
                for i, (ip, wh, month) in enumerate(zip(
                    history._names, [1460, 610, 70, 200], [30000, 12000, 1620, 5000], strict=True,
                ))
            }
            history._rows = {
                ip: [(date.today() - timedelta(days=14 - k), round(wh * (0.8 + (k % 4) * 0.1))) for k in range(15)]
                for ip, wh in zip(history._names, [1460, 610, 70, 200], strict=True)
            }
            history._render_totals()
            history._render_history()
            history._detail.setText("4 plugs · sample history")
            self.window._render_cards()
            self._control_shots = iter([
                (f"{name}-{mode}-{size}", page, mode, width, height, collapsed)
                for mode in ("light", "dark")
                for size, width, height, collapsed in (("desktop", 1440, 1060, False), ("narrow", 760, 640, True))
                for name, page in (("devices", 1), ("energy", 2), ("account", 3), ("settings", 4))
            ] + [("overview-preserved", 0, "light", 1440, 1060, False)])
        shot = next(self._control_shots, None)
        if shot is None:
            self.window.hide()
            self.store.close()
            self.app.quit()
            return
        self.name, page, mode, width, height, collapsed = shot
        theme().set_mode(mode)
        self.window._tabs.blockSignals(True)
        self.window._tabs.setCurrentIndex(page)
        self.window._tabs.blockSignals(False)
        self.window._show_page(page)
        self.window._tabs.set_collapsed(collapsed)
        self.window.resize(width, height)
        QTimer.singleShot(250, self.capture)


if __name__ == "__main__":
    application = QApplication(sys.argv)
    for name in ("segoeui.ttf", "segoeuib.ttf", "seguisb.ttf"):
        QFontDatabase.addApplicationFont(str(Path("C:/Windows/Fonts") / name))
    application.setQuitOnLastWindowClosed(False)
    preview = ControlPreview(application)
    sys.exit(application.exec())
