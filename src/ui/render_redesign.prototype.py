"""Render throwaway HTML mockups with Qt's event loop; no account or plug access.

Usage: .venv/Scripts/python.exe src/ui/render_redesign.prototype.py
"""

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu")
# This renderer opens only the bundled, local, sample-data HTML file.
os.environ.setdefault("QTWEBENGINE_DISABLE_SANDBOX", "1")

from PySide6.QtCore import QTimer, QUrl  # noqa: E402
from PySide6.QtWebEngineWidgets import QWebEngineView  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402


class MockupRenderer:
    """Capture each sample layout after its browser rendering completes."""

    def __init__(self, app: QApplication) -> None:
        self.app = app
        self.variants = iter("ABC")
        self.current = ""
        self.view = QWebEngineView()
        self.view.resize(1440, 1180)
        self.view.loadFinished.connect(self.loaded)
        self.view.show()
        self.advance()

    def advance(self) -> None:
        self.current = next(self.variants, "")
        if not self.current:
            self.app.quit()
            return
        url = QUrl.fromLocalFile(str(Path(__file__).with_name("redesign.prototype.html").resolve()))
        url.setQuery(f"variant={self.current}")
        self.view.load(url)

    def loaded(self, success: bool) -> None:
        if not success:
            self.app.exit(1)
            return
        QTimer.singleShot(700, self.verify)

    def verify(self) -> None:
        self.view.page().runJavaScript(
            """(() => {
                const first = document.querySelector('[data-device="0"]');
                const before = first.getAttribute('aria-checked');
                first.click();
                const changed = document.querySelector('[data-device="0"]')
                    .getAttribute('aria-checked') !== before;
                document.querySelector('[data-device="0"]').click();
                const original = variant;
                document.getElementById('next').click();
                const navigated = variant !== original;
                document.getElementById('prev').click();
                document.querySelector('.sidebar-toggle').click();
                const collapsed = variant === 'C'
                    || document.querySelector('.app').classList.contains('collapsed');
                const expandedState = document.querySelector('.sidebar-toggle')
                    .getAttribute('aria-expanded') === 'false';
                return changed && navigated && variant === original
                    && collapsed && expandedState
                    && document.querySelector('[data-device="3"]').disabled;
            })()""",
            self.verified,
        )

    def verified(self, success: bool) -> None:
        if not success:
            print(f"Interaction check failed: {self.current}", flush=True)
            self.app.exit(1)
            return
        QTimer.singleShot(150, self.capture)

    def capture(self) -> None:
        destination = Path(__file__).with_name(f"redesign.prototype.{self.current}.png")
        if not self.view.grab().save(str(destination)):
            self.app.exit(1)
            return
        print(destination, flush=True)
        self.advance()


if __name__ == "__main__":
    application = QApplication(sys.argv)
    renderer = MockupRenderer(application)
    sys.exit(application.exec())
