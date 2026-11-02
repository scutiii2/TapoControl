"""Plug cards with confirmed power state and keyboard-accessible controls."""
import math
from collections.abc import Sequence

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import (
    QAbstractButton,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ui import tokens as t
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
        painter.setPen(QPen(QColor(c.accent if self.hasFocus() else c.control), 1))
        painter.setBrush(QColor(c.accent if self.isChecked() and self.isEnabled() else c.raised))
        painter.drawRoundedRect(QRectF(2, 4, 46, 24), 12, 12)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(c.accent_text if self.isChecked() and self.isEnabled() else c.muted))
        painter.drawEllipse(QRectF(26 if self.isChecked() else 6, 8, 16, 16))


TIMERS = (
    ("Turn off in 15 minutes", 15, False),
    ("Turn off in 30 minutes", 30, False),
    ("Turn off in 1 hour", 60, False),
    ("Turn off in 2 hours", 120, False),
    ("Turn on in 30 minutes", 30, True),
    ("Turn on in 1 hour", 60, True),
)


def timer_note(remaining_seconds: float, on: bool) -> str:
    minutes = max(1, math.ceil(remaining_seconds / 60))
    when = f"{minutes} min" if minutes < 90 else f"{minutes // 60} h {minutes % 60:02d} min"
    return f"{'on' if on else 'off'} in {when}"


def hourly_cost(watts: float, price_per_kwh: float) -> float:
    return watts / 1000 * price_per_kwh


class Sparkline(QWidget):
    """Recent watts of one plug, scaled to its own range."""

    def __init__(self):
        super().__init__()
        self.setFixedSize(84, 30)
        self._values: Sequence[float] = ()
        theme().changed.connect(self.update)

    def set_values(self, values: Sequence[float]) -> None:
        self._values = list(values)
        self.update()

    def paintEvent(self, event) -> None:
        if len(self._values) < 2:
            return
        lo, hi = min(self._values), max(self._values)
        span = (hi - lo) or 1.0
        step = (self.width() - 4) / (len(self._values) - 1)
        points = QPolygonF([
            QPointF(2 + i * step, self.height() - 3 - (v - lo) / span * (self.height() - 6))
            for i, v in enumerate(self._values)
        ])
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor(theme().colors.accent), 1.5))
        painter.drawPolyline(points)


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
    timer_requested = Signal(int, bool)  # minutes, switch on
    timer_cancelled = Signal()

    def __init__(self, ip: str):
        super().__init__()
        self.setObjectName("DeviceCard")
        self.setProperty("card", True)
        self.setMinimumHeight(80)
        self._on = False
        self._name = ElidedLabel()
        self._name.setStyleSheet(f"font-size: {t.FONT_NAME}px; font-weight: 600;")
        self._address = ip
        self._ip = QLabel(ip)
        self._ip.setProperty("tone", "muted")
        self._ip.setTextFormat(Qt.TextFormat.PlainText)
        self._status = QLabel()
        self._status.setFixedWidth(140)
        self._watts = QLabel()
        self._watts.setFixedWidth(90)
        self._watts.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._watts.setStyleSheet(f"font-size: {t.FONT_VALUE}px; font-weight: 600;")
        self._cost = QLabel()
        self._cost.setFixedWidth(90)
        self._cost.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._cost.setProperty("tone", "muted")
        self._spark = Sparkline()
        self.toggle = PowerSwitch(self)
        self.toggle.setAccessibleName(f"Power for {ip}")
        self.toggle.clicked.connect(self._request_power)
        menu = QMenu(self)
        menu.addAction("Rename…", self.rename_requested.emit)
        menu.addAction("Energy…", self.energy_requested.emit)
        timer = menu.addMenu("Timer")
        for label, minutes, on in TIMERS:
            timer.addAction(label, lambda m=minutes, o=on: self.timer_requested.emit(m, o))
        timer.addSeparator()
        timer.addAction("Cancel timer", self.timer_cancelled.emit)
        self._menu = QToolButton()
        self._menu.setText("…")
        self._menu.setAccessibleName(f"Actions for {ip}")
        self._menu.setToolTip("Rename, energy or timer")
        self._menu.setMenu(menu)
        self._menu.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self._menu.setFixedSize(t.TARGET, t.TARGET)
        self._menu.setStyleSheet("padding: 0; font-size: 20px;")
        row = QHBoxLayout(self)
        row.setContentsMargins(t.SP_LG, t.SP_MD, t.SP_MD, t.SP_MD)
        row.setSpacing(t.SP_LG)
        labels = QVBoxLayout()
        labels.setSpacing(t.SP_XS)
        labels.addWidget(self._name)
        labels.addWidget(self._ip)
        row.addLayout(labels, 1)
        row.addWidget(self._status)
        row.addWidget(self._spark)
        numbers = QVBoxLayout()
        numbers.setSpacing(0)
        numbers.addWidget(self._watts)
        numbers.addWidget(self._cost)
        row.addLayout(numbers)
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

    def update_state(self, name: str, state: tuple[bool, float] | None, selected: bool, busy: bool,
                     samples: Sequence[float] = (), price: float = 0.0, note: str = "") -> None:
        self._ip.setText(f"{self._address} · {note}" if note else self._address)
        self._name.setText(name)
        self._name.setTextFormat(Qt.TextFormat.PlainText)
        self._spark.set_values(samples if state else ())
        self._on = bool(state and state[0])
        self._status.setText("●  ON" if self._on else "●  OFF" if state else "Offline - retrying")
        self._status.setProperty("tone", "success" if self._on else "muted")
        self._watts.setText(f"{state[1]:.1f} W" if state else "—")
        self._cost.setText(f"{hourly_cost(state[1], price):.2f} / h" if state and price else "")
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
