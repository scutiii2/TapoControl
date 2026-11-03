"""Today's per-plug energy: one name, figure and share bar per plug."""

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from ui import tokens as t
from ui.plug_card import ElidedLabel
from ui.theme import series_color, theme


class UsageBar(QWidget):
    """A track with one plug's share of today's total filled in its series colour."""

    def __init__(self) -> None:
        super().__init__()
        self.setFixedHeight(t.BAR_HEIGHT)
        self.share = 0.0
        self.color = 0
        theme().changed.connect(self.update)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        radius = self.height() / 2
        painter.setBrush(QColor(theme().colors.raised))
        painter.drawRoundedRect(QRectF(0, 0, self.width(), self.height()), radius, radius)
        if self.share > 0:
            painter.setBrush(QColor(series_color(self.color)))
            width = max(self.height(), self.width() * self.share)
            painter.drawRoundedRect(QRectF(0, 0, width, self.height()), radius, radius)


class UsageBreakdown(QFrame):
    def __init__(self) -> None:
        super().__init__()
        self.setProperty("card", True)
        self.setFixedWidth(246)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(t.PANEL_X, t.PANEL_Y, t.PANEL_X, t.PANEL_Y)
        layout.setSpacing(t.SP_SM)
        heading = QLabel("Today by plug")
        heading.setProperty("role", "heading")
        layout.addWidget(heading)
        self.note = QLabel("Waiting for energy readings")
        self.note.setProperty("role", "caption")
        self.note.setWordWrap(True)
        layout.addWidget(self.note)
        layout.addSpacing(t.SP_SM)
        self.rows = QVBoxLayout()
        self.rows.setSpacing(t.SP_LG)
        layout.addLayout(self.rows)
        layout.addStretch()
        self._labels: dict[str, tuple[QWidget, ElidedLabel, QLabel, UsageBar]] = {}

    def show_usage(self, names: dict[str, str], energy: dict[str, int], colors) -> None:
        for ip in self._labels.keys() - names.keys():
            widget = self._labels.pop(ip)[0]
            self.rows.removeWidget(widget)
            widget.deleteLater()
        known = {ip: wh for ip, wh in energy.items() if ip in names}
        total = sum(known.values())
        for ip, name in names.items():
            if ip not in self._labels:
                widget = QWidget()
                column = QVBoxLayout(widget)
                column.setContentsMargins(0, 0, 0, 0)
                column.setSpacing(t.SP_XS)
                top = QHBoxLayout()
                label = ElidedLabel()
                label.setProperty("role", "plug-name")
                value = QLabel()
                value.setProperty("role", "caption")
                bar = UsageBar()
                top.addWidget(label, 1)
                top.addWidget(value)
                column.addLayout(top)
                column.addWidget(bar)
                self.rows.addWidget(widget)
                self._labels[ip] = widget, label, value, bar
            _, label, value, bar = self._labels[ip]
            label.setText(name)
            value.setText(f"{energy[ip] / 1000:.2f} kWh" if ip in energy else "—")
            bar.color = colors(ip)
            bar.share = known[ip] / total if ip in known and total else 0.0
            bar.update()
        if not known:
            note = "Waiting for energy readings"
        elif len(known) < len(names):
            note = f"Partial · {len(known)} of {len(names)} plugs"
        else:
            note = ""
        self.note.setText(note)
        self.note.setVisible(bool(note))
