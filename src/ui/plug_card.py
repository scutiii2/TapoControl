"""Plug cards with confirmed power state and keyboard-accessible controls."""
from PySide6.QtCore import QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QAbstractButton, QFrame, QHBoxLayout, QLabel, QMenu, QSizePolicy, QToolButton, QVBoxLayout

from ui.theme import theme


class PowerSwitch(QAbstractButton):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setFixedSize(50, 32)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        theme().changed.connect(self.update)

    def paintEvent(self, event) -> None:
        c = theme().colors
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor(c.accent if self.hasFocus() else c.border), 1))
        painter.setBrush(QColor(c.accent if self.isChecked() and self.isEnabled() else c.raised))
        painter.drawRoundedRect(QRectF(2, 4, 46, 24), 12, 12)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(c.accent_text if self.isChecked() and self.isEnabled() else c.muted))
        painter.drawEllipse(QRectF(26 if self.isChecked() else 6, 8, 16, 16))


class ElidedLabel(QLabel):
    def __init__(self, text: str = ""):
        super().__init__()
        self._full_text = text
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)

    def setText(self, text: str) -> None:
        self._full_text = text
        self.setToolTip(text)
        super().setText(self.fontMetrics().elidedText(text, Qt.TextElideMode.ElideRight, self.width()))

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.setText(self._full_text)


class PlugCard(QFrame):
    selected = Signal()
    power_requested = Signal(bool)
    rename_requested = Signal()
    energy_requested = Signal()

    def __init__(self, ip: str):
        super().__init__()
        self.setObjectName("DeviceCard")
        self.setProperty("card", True)
        self.setMinimumHeight(80)
        self._on = False
        self._name = ElidedLabel()
        self._name.setStyleSheet("font-size: 15px; font-weight: 600;")
        self._ip = QLabel(ip)
        self._ip.setProperty("tone", "muted")
        self._ip.setTextFormat(Qt.TextFormat.PlainText)
        self._status = QLabel()
        self._status.setFixedWidth(140)
        self._watts = QLabel()
        self._watts.setFixedWidth(90)
        self._watts.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._watts.setStyleSheet("font-size: 21px; font-weight: 600;")
        self.toggle = PowerSwitch(self)
        self.toggle.setAccessibleName(f"Power for {ip}")
        self.toggle.clicked.connect(self._request_power)
        menu = QMenu(self)
        menu.addAction("Rename…", self.rename_requested.emit)
        menu.addAction("Energy…", self.energy_requested.emit)
        self._menu = QToolButton()
        self._menu.setText("…")
        self._menu.setAccessibleName(f"Actions for {ip}")
        self._menu.setToolTip("Rename or view energy")
        self._menu.setMenu(menu)
        self._menu.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self._menu.setFixedSize(36, 34)
        self._menu.setStyleSheet("padding: 0; font-size: 20px;")
        row = QHBoxLayout(self)
        row.setContentsMargins(18, 12, 12, 12)
        row.setSpacing(16)
        labels = QVBoxLayout()
        labels.setSpacing(4)
        labels.addWidget(self._name)
        labels.addWidget(self._ip)
        row.addLayout(labels, 1)
        row.addWidget(self._status)
        row.addWidget(self._watts)
        row.addWidget(self.toggle)
        row.addWidget(self._menu)

    def sizeHint(self) -> QSize:
        return QSize(650, 82)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.selected.emit()
        super().mousePressEvent(event)

    def _request_power(self, on: bool) -> None:
        # The visual state follows snapshots, never an optimistic network result.
        self.toggle.setChecked(self._on)
        self.power_requested.emit(on)

    def update_state(self, name: str, state: tuple[bool, float] | None, selected: bool, busy: bool) -> None:
        self._name.setText(name)
        self._name.setTextFormat(Qt.TextFormat.PlainText)
        self._on = bool(state and state[0])
        self._status.setText("●  ON" if self._on else "●  OFF" if state else "Offline - retrying")
        self._status.setProperty("tone", "success" if self._on else "muted")
        self._watts.setText(f"{state[1]:.1f} W" if state else "—")
        self.toggle.setChecked(self._on)
        self.toggle.setEnabled(state is not None and not busy)
        self.toggle.setToolTip("Updating power…" if busy else "Turn off" if self._on else "Turn on")
        self.toggle.setAccessibleName(f"Power for {name}")
        changed = self.property("selected") != selected or self.property("offline") != (state is None)
        self.setProperty("selected", selected)
        self.setProperty("offline", state is None)
        if changed:
            self.style().unpolish(self)
            self.style().polish(self)
            for label in self.findChildren(QLabel):
                label.style().unpolish(label)
                label.style().polish(label)
        self._status.style().unpolish(self._status)
        self._status.style().polish(self._status)
