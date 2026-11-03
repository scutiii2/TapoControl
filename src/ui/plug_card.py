"""Plug rows with confirmed power state and keyboard-accessible controls."""
import math
from collections.abc import Sequence

from PySide6.QtCore import QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractButton,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
)

from ui import tokens as t
from ui.interaction import Fade, contains, poller
from ui.theme import theme
from ui.side_tabs import nav_icon


class PowerSwitch(QAbstractButton):
    def __init__(self, parent=None, *, large: bool = False):
        super().__init__(parent)
        self.setCheckable(True)
        self._large = large
        if large:
            self.setFixedSize(52, 44)
        else:
            self.setFixedSize(40, 32)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._hover = Fade(self)
        poller(self)
        theme().changed.connect(self.update)

    def enterEvent(self, event) -> None:
        self._hover.to(1.0)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._hover.to(0.0)
        super().leaveEvent(event)

    def poll_hover(self, under, position) -> None:
        self._hover.to(1.0 if contains(self, under) else 0.0)

    def paintEvent(self, event) -> None:
        c = theme().colors
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        track = c.accent if self.isChecked() else ("#cbd3cb" if c.background == "#f6f8f5" else c.control)
        hover = self._hover.value if self.isEnabled() else 0.0
        painter.setOpacity(1 if self.isEnabled() else 0.45)
        left = 26 if self.isChecked() else 6
        if self._large:
            track_rect, thumb, ring = QRectF(3, 9, 46, 26), QRectF(left, 12, 20, 20), (1, 5, 50, 34, 8)
        else:
            left = 20 if self.isChecked() else 6
            track_rect, thumb, ring = QRectF(3, 6, 34, 20), QRectF(left, 9, 14, 14), (1, 2, 38, 28, 7)
        painter.setBrush(QColor(track))
        painter.drawRoundedRect(track_rect, track_rect.height() / 2, track_rect.height() / 2)
        if hover:  # the track darkens a little and the thumb swells
            shade = QColor(c.text)
            shade.setAlphaF(0.12 * hover)
            painter.setBrush(shade)
            painter.drawRoundedRect(track_rect, track_rect.height() / 2, track_rect.height() / 2)
        painter.setBrush(QColor("#ffffff"))
        painter.drawEllipse(thumb.adjusted(-1.5 * hover, -1.5 * hover, 1.5 * hover, 1.5 * hover))
        if self.hasFocus() and self.property("kbd"):
            painter.setOpacity(1)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor(c.accent), 2))
            x, y, width, height, radius = ring
            painter.drawRoundedRect(QRectF(x, y, width, height), radius, radius)


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

    def __init__(self, ip: str, actions: bool = True):
        super().__init__()
        self.setObjectName("DeviceCard")
        self.setFixedHeight(t.DEVICE_HEIGHT)
        self._on = False
        self._icon_kind = "devices"
        self._name = ElidedLabel()
        self._name.setStyleSheet(f"font-size: {t.FONT_NAME}px; font-weight: 600;")
        self._address = ip
        self._ip = QLabel(ip)
        self._ip.setProperty("tone", "muted")
        self._ip.setTextFormat(Qt.TextFormat.PlainText)
        self._ip.hide()  # Available in the action tooltip; timers get their own visible line.
        self._watts = QLabel()
        self._watts.setProperty("role", "device-value")
        self._watts.setFixedWidth(t.DEVICE_FIGURE_WIDTH)
        self._watts.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._cost = QLabel()
        self._cost.setProperty("role", "caption")
        self._cost.hide()
        self._pill = QLabel()
        self._pill.setProperty("role", "pill")
        self._pill.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._pill.setFixedWidth(t.DEVICE_PILL_WIDTH)
        self.today = QLabel("— kWh today", self)  # read by tests and tooltips; the row shows it in Today by plug
        self.today.hide()
        self._timer_label = QLabel()
        self._timer_label.setProperty("role", "caption")
        self._timer_label.hide()
        self._icon = QLabel()
        self._icon.setFixedSize(32, 32)
        self._icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._icon.setPixmap(nav_icon("devices", "#547454", "#547454").pixmap(19, 19))
        self.toggle = PowerSwitch(self)
        self.toggle.setAccessibleName(f"Power for {ip}")
        self.toggle.clicked.connect(self._request_power)
        menu = QMenu(self)
        menu.addAction("Rename…", self.rename_requested.emit)
        menu.addAction("Energy…", self.energy_requested.emit)
        timer = menu.addMenu("Timer")
        self._timer_menu = timer
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
        self._menu.setProperty("quiet", True)
        self._menu.setStyleSheet("font-size: 16px; font-weight: 600;")  # the dots are the only way to the row actions
        self._menu.setFixedHeight(24)
        row = QHBoxLayout(self)
        row.setContentsMargins(t.PANEL_X, 0, t.PANEL_X, 0)
        row.setSpacing(t.SP_LG)
        row.addWidget(self._icon)
        text = QVBoxLayout()
        text.setSpacing(t.SP_XS)
        text.addStretch()
        text.addWidget(self._name)
        text.addWidget(self._timer_label)
        text.addStretch()
        row.addLayout(text, 1)
        row.addWidget(self._pill, 0, Qt.AlignmentFlag.AlignVCenter)
        row.addWidget(self._watts)
        row.addWidget(self._menu)
        self._menu.setVisible(actions)
        row.addWidget(self.toggle)
        theme().changed.connect(self._apply_theme)
        self._apply_theme()

    def sizeHint(self) -> QSize:
        return QSize(250, t.DEVICE_HEIGHT)

    def _apply_theme(self) -> None:
        c = theme().colors
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
        self._pill.setText(status)
        self._pill.setProperty("state", status.lower())
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
        self._pill.style().unpolish(self._pill)
        self._pill.style().polish(self._pill)


def mark_first(cards) -> None:
    """Only the first row of a table loses its top separator, so the panel's rounded border stays whole."""
    for index, card in enumerate(cards):
        if bool(card.property("first")) != (index == 0):
            card.setProperty("first", index == 0)
            card.style().unpolish(card)
            card.style().polish(card)


class DeviceControlRow(PlugCard):
    """The Overview row plus a timer button, so the Devices page looks the same as Overview."""

    def __init__(self, ip: str):
        super().__init__(ip)
        self._timer_button = QToolButton()
        self._timer_button.setProperty("quiet", True)
        self._timer_button.setIconSize(QSize(16, 16))
        self._timer_button.setFixedSize(28, 24)
        self._timer_button.setAccessibleName(f"Timer for {ip}")
        self._timer_button.setToolTip("Set or cancel timer")
        self._timer_button.setMenu(self._timer_menu)
        self._timer_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        row = self.layout()
        row.insertWidget(row.indexOf(self._menu), self._timer_button)
        theme().changed.connect(self._restyle_timer)
        self._restyle_timer()

    def _restyle_timer(self) -> None:
        c = theme().colors
        self._timer_button.setIcon(nav_icon("timer", c.muted, c.accent))

    def update_state(self, name, state, selected, busy, samples=(), price=0.0, note="") -> None:
        super().update_state(name, state, selected, busy, samples, price, note)
        self._timer_button.setEnabled(state is not None and not busy)
        self._timer_button.setAccessibleName(f"Timer for {name}")
