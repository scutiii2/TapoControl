"""Today's per-plug energy, using the same compact stack and rows as the approved mockup."""

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from ui import tokens as t
from ui.plug_card import ElidedLabel
from ui.theme import series_color, theme
from ui.widgets import MetricValue


class UsageStack(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setFixedHeight(7)
        self.values: list[tuple[int, int]] = []
        theme().changed.connect(self.update)

    def paintEvent(self, event) -> None:
        total = sum(value for value, _ in self.values)
        if not total:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        available = max(0, self.width() - 3 * (len(self.values) - 1))
        left = 0.0
        for value, color in self.values:
            width = available * value / total
            painter.setBrush(QColor(series_color(color)))
            painter.drawRoundedRect(QRectF(left, 0, width, 7), 3, 3)
            left += width + 3


class UsageBreakdown(QFrame):
    def __init__(self) -> None:
        super().__init__()
        self.setProperty("card", True)
        self.setFixedWidth(246)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(t.PANEL_X, t.PANEL_Y, t.PANEL_X, t.PANEL_Y)
        layout.setSpacing(t.SP_SM)
        heading = QLabel("Today's usage")
        heading.setProperty("role", "heading")
        layout.addWidget(heading)
        layout.addSpacing(t.SP_SM)
        self.total = MetricValue()
        self.total.setProperty("role", "metric")
        layout.addWidget(self.total)
        self.note = QLabel("Waiting for energy readings")
        self.note.setProperty("role", "caption")
        self.note.setWordWrap(True)
        layout.addWidget(self.note)
        layout.addSpacing(t.SP_SM)
        self.stack = UsageStack()
        layout.addWidget(self.stack)
        layout.addSpacing(t.SP_SM)
        self.rows = QVBoxLayout()
        self.rows.setSpacing(t.SP_MD)
        layout.addLayout(self.rows)
        layout.addStretch()
        self._labels: dict[str, tuple[QWidget, QLabel, QLabel]] = {}
        theme().changed.connect(self._retheme)
        self._colors: dict[str, int] = {}

    def show_usage(self, names: dict[str, str], energy: dict[str, int], colors) -> None:
        for ip in self._labels.keys() - names.keys():
            widget, _, _ = self._labels.pop(ip)
            self.rows.removeWidget(widget)
            widget.deleteLater()
            self._colors.pop(ip, None)
        for ip, name in names.items():
            self._colors[ip] = colors(ip)
            if ip not in self._labels:
                widget = QWidget()
                row = QHBoxLayout(widget)
                row.setContentsMargins(0, 0, 0, 0)
                row.setSpacing(t.SP_SM)
                dot = QLabel("●")
                dot.setObjectName("SeriesDot")
                label = ElidedLabel()
                label.setProperty("role", "caption")
                value = QLabel()
                value.setProperty("role", "caption")
                row.addWidget(dot)
                row.addWidget(label, 1)
                row.addWidget(value)
                self.rows.addWidget(widget)
                self._labels[ip] = widget, label, value
            _, label, value = self._labels[ip]
            label.setText(name)
            value.setText(f"{energy[ip] / 1000:.2f}" if ip in energy else "—")
        known = {ip: wh for ip, wh in energy.items() if ip in names}
        total = sum(known.values())
        self.total.setText(f"{total / 1000:.2f} kWh" if known else "—")
        if not known:
            note = "Waiting for energy readings"
        elif len(known) < len(names):
            note = f"Partial · {len(known)} of {len(names)} plugs"
        else:
            note = "Across all plugs"
        self.note.setText(note)
        self.stack.values = [(wh, colors(ip)) for ip, wh in known.items() if wh > 0]
        self.stack.update()
        self._retheme()

    def _retheme(self) -> None:
        for ip, (widget, _, _) in self._labels.items():
            widget.findChild(QLabel, "SeriesDot").setStyleSheet(
                f"color: {series_color(self._colors[ip])}; font-size: 9px;"
            )
