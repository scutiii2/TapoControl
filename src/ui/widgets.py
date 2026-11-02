"""Small widgets shared by several pages."""
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import QFrame, QGridLayout, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget

from ui import tokens as t
from ui.theme import theme


class MetricValue(QLabel):
    """Keep a plain accessible value while painting smaller units, as CSS does in the mockup."""

    def __init__(self, text: str = "—") -> None:
        super().__init__(text)
        self.setMinimumHeight(36)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)

    def paintEvent(self, event) -> None:
        value, separator, unit = self.text().partition(" ")
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        font = QFont(t.FONT_FAMILY)
        font.setPixelSize(t.FONT_METRIC)
        font.setWeight(QFont.Weight.DemiBold)
        font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, -1)
        painter.setFont(font)
        painter.setPen(QColor(theme().colors.text))
        baseline = (self.height() - painter.fontMetrics().height()) / 2 + painter.fontMetrics().ascent()
        painter.drawText(QRectF(0, 0, self.width(), self.height()), Qt.AlignmentFlag.AlignVCenter, value)
        width = painter.fontMetrics().horizontalAdvance(value)
        if separator:
            font.setPixelSize(14)
            font.setWeight(QFont.Weight.Normal)
            font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 0)
            painter.setFont(font)
            painter.setPen(QColor(theme().colors.muted))
            painter.drawText(QRectF(width + 4, baseline - painter.fontMetrics().ascent(),
                                   self.width() - width - 4, painter.fontMetrics().height()), unit)


class MetricGrid(QWidget):
    """Four summary columns on desktop, two at narrow widths."""

    def __init__(self) -> None:
        super().__init__()
        self._cards: list[QWidget] = []
        self._columns = 0
        self._grid = QGridLayout(self)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setSpacing(t.CARD_GAP)

    def addWidget(self, card: QWidget, stretch: int = 1) -> None:
        self._cards.append(card)
        self._reflow(force=True)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._reflow()

    def _reflow(self, force: bool = False) -> None:
        columns = 2 if self.width() < 700 else 4
        if self._columns == columns and not force:
            return
        self._columns = columns
        while self._grid.count():
            self._grid.takeAt(0)
        for col in range(4):
            self._grid.setColumnStretch(col, 1 if col < columns else 0)
        for index, card in enumerate(self._cards):
            self._grid.addWidget(card, index // columns, index % columns)


def cost_line(wh: float, price: float, hint: str) -> str:
    """Cost of `wh` at `price` per kWh, or `hint` when no tariff is set (0.00 would read as free)."""
    return f"Estimated cost {wh / 1000 * price:.2f}" if price else hint


def metric_card(
    row: QHBoxLayout | MetricGrid, title: str, sub: str = "—", *, highlight: bool = False,
) -> tuple[QLabel, QLabel]:
    """A titled card with a big value and a muted line under it; returns (value label, sub label)."""
    card = QFrame()
    card.setProperty("card", True)
    card.setProperty("highlight", highlight)
    card.setMinimumHeight(128)
    card.setMinimumWidth(0)
    card.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
    layout = QVBoxLayout(card)
    layout.setContentsMargins(t.METRIC_PAD, t.METRIC_PAD, t.METRIC_PAD, t.METRIC_PAD)
    layout.setSpacing(t.SP_SM)
    heading = QLabel(title)
    heading.setProperty("role", "caption")
    value = MetricValue()
    value.setProperty("role", "metric")
    detail = QLabel(sub)
    detail.setProperty("role", "caption")
    detail.setWordWrap(True)
    for label in (heading, value, detail):
        layout.addWidget(label)
    row.addWidget(card, 1)
    return value, detail
