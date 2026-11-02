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
from ui.side_tabs import nav_icon


class PowerSwitch(QAbstractButton):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setFixedSize(40, 32)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        theme().changed.connect(self.update)

    def paintEvent(self, event) -> None:
        c = theme().colors
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        track = c.accent if self.isChecked() else ("#cbd3cb" if c.background == "#f6f8f5" else c.control)
        painter.setOpacity(1 if self.isEnabled() else 0.45)
        painter.setBrush(QColor(track))
        painter.drawRoundedRect(QRectF(3, 6, 34, 20), 10, 10)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#ffffff"))
        painter.drawEllipse(QRectF(20 if self.isChecked() else 6, 9, 14, 14))
        if self.hasFocus():
            painter.setOpacity(1)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor(c.accent), 2))
            painter.drawRoundedRect(QRectF(1, 2, 38, 28), 7, 7)


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
        self.setFixedHeight(t.DEVICE_HEIGHT)
        self.setMinimumWidth(t.DEVICE_MIN_WIDTH)
        self._on = False
        self._icon_kind = "devices"
        self._name = ElidedLabel()
        self._name.setStyleSheet(f"font-size: {t.FONT_NAME}px; font-weight: 600;")
        self._address = ip
        self._ip = QLabel(ip)
        self._ip.setProperty("tone", "muted")
        self._ip.setTextFormat(Qt.TextFormat.PlainText)
        self._ip.hide()  # Available in the action tooltip; timers get their own visible line.
        self._status = QLabel()
        self._status.setProperty("role", "caption")
        self._watts = QLabel()
        self._watts.setProperty("role", "device-value")
        self._cost = QLabel()
        self._cost.setProperty("role", "caption")
        self._cost.hide()
        self.today = QLabel("— kWh today")
        self.today.setProperty("role", "caption")
        self._timer_label = QLabel()
        self._timer_label.setProperty("role", "caption")
        self._timer_label.hide()
        self._icon = QLabel()
        self._icon.setFixedSize(35, 35)
        self._icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._icon.setStyleSheet("background: #eff3ec; border-radius: 10px;")
        self._icon.setPixmap(nav_icon("devices", "#547454", "#547454").pixmap(19, 19))
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
        self._menu.setText("Details ↗")
        self._menu.setAccessibleName(f"Actions for {ip}")
        self._menu.setToolTip("Rename, energy or timer")
        self._menu.setMenu(menu)
        self._menu.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self._menu.setProperty("quiet", True)
        self._menu.setFixedHeight(24)
        row = QVBoxLayout(self)
        row.setContentsMargins(t.DEVICE_PAD, t.DEVICE_PAD, t.DEVICE_PAD, t.DEVICE_PAD)
        row.setSpacing(t.SP_XS)
        top = QHBoxLayout()
        top.setSpacing(t.SP_SM)
        top.addWidget(self._icon)
        top.addStretch()
        top.addWidget(self.toggle)
        row.addLayout(top)
        row.addSpacing(t.SP_SM)
        row.addWidget(self._name)
        row.addWidget(self._status)
        row.addWidget(self._timer_label)
        row.addStretch()
        watts = QHBoxLayout()
        watts.setSpacing(t.SP_XS)
        watts.addWidget(self._watts)
        unit = QLabel("W")
        unit.setProperty("role", "caption")
        watts.addWidget(unit, 0, Qt.AlignmentFlag.AlignBottom)
        watts.addStretch()
        row.addLayout(watts)
        row.addSpacing(t.SP_SM)
        self._divider = QFrame()
        self._divider.setFrameShape(QFrame.Shape.HLine)
        self._divider.setFixedHeight(1)
        row.addWidget(self._divider)
        footer = QHBoxLayout()
        footer.setSpacing(t.SP_XS)
        footer.addWidget(self.today, 1)
        footer.addWidget(self._menu)
        row.addLayout(footer)
        theme().changed.connect(self._apply_theme)
        self._apply_theme()

    def sizeHint(self) -> QSize:
        return QSize(250, t.DEVICE_HEIGHT)

    def _apply_theme(self) -> None:
        c = theme().colors
        self._divider.setStyleSheet(f"background: {c.border}; border: none;")
        self._icon.setStyleSheet(f"background: {c.raised}; border-radius: 10px;")
        self._icon.setPixmap(nav_icon(self._icon_kind, c.accent, c.accent).pixmap(19, 19))

    def show_today(self, watt_hours: int | None) -> None:
        self.today.setText("— kWh today" if watt_hours is None else f"{watt_hours / 1000:.2f} kWh today")

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
        self._menu.setToolTip(f"{self._ip.text()} · Rename, energy or timer")
        self._timer_label.setText(note)
        self._timer_label.setVisible(bool(note))
        self._name.setText(name)
        kinds = {
            "monitor": ("workstation", "desktop", "computer", "monitor", "pc"),
            "fan": ("fan",), "lamp": ("lamp", "light"), "coffee": ("coffee",),
        }
        kind = next((key for key, words in kinds.items() if any(word in name.casefold() for word in words)), "devices")
        if kind != self._icon_kind:
            self._icon_kind = kind
            self._apply_theme()
        self._name.setTextFormat(Qt.TextFormat.PlainText)
        self._on = bool(state and state[0])
        status = "On" if self._on else "Off" if state else "Offline"
        dot = "#379567" if state else "#a5ada6"
        self._status.setText(f'<span style="color: {dot}">●</span>  {status} · P110')
        self._status.setProperty("tone", "success" if self._on else "muted")
        self._watts.setText(f"{state[1]:.1f}" if state else "—")
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
