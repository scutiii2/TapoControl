"""Small widgets shared by several pages."""
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QBoxLayout, QFrame, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget

from ui import tokens as t
from ui.theme import theme


class MetricValue(QLabel):
    """Keep a plain accessible value while painting smaller units, as CSS does in the mockup."""

    def __init__(self, text: str = "—", size: int = t.FONT_METRIC) -> None:
        super().__init__(text)
        self._size = size
        self.setMinimumHeight(round(size * 1.4))
        self.setMinimumWidth(round(size * 4))  # Ignored policy would otherwise collapse it beside a stretching label
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)

    def paintEvent(self, event) -> None:
        value, separator, unit = self.text().partition(" ")
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        font = QFont(t.FONT_FAMILY)
        font.setPixelSize(self._size)
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


class Sparkline(QWidget):
    """Trend line of recent values, ending in a dot on the latest one."""

    def __init__(self, height: int = t.SPARK_HEIGHT) -> None:
        super().__init__()
        self._points: list[float] = []
        self.setFixedHeight(height)
        self.setMinimumWidth(96)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_points(self, points) -> None:
        self._points = list(points)
        self.update()

    def paintEvent(self, event) -> None:
        count = len(self._points)
        if count < 2:
            return
        pad = 4
        low, high = min(self._points), max(self._points)
        span = (high - low) or 1
        path = QPainterPath()
        for index, value in enumerate(self._points):
            x = pad + index * (self.width() - 2 * pad) / (count - 1)
            rise = (value - low) / span if high != low else 0.5
            y = self.height() - pad - rise * (self.height() - 2 * pad)
            if index:
                path.lineTo(x, y)
            else:
                path.moveTo(x, y)
        color = QColor(theme().colors.series[0])
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(color, 2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        painter.drawPath(path)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        end = path.currentPosition()
        painter.drawEllipse(end, 3.5, 3.5)


def _card() -> QFrame:
    card = QFrame()
    card.setProperty("card", True)
    layout = QVBoxLayout(card)
    layout.setContentsMargins(t.METRIC_PAD, t.METRIC_PAD, t.METRIC_PAD, t.METRIC_PAD)
    layout.setSpacing(t.SP_SM)
    return card


def _caption(text: str, right: bool = False) -> QLabel:
    label = QLabel(text)
    label.setProperty("role", "caption")
    label.setWordWrap(True)
    if right:
        label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    return label


class SummaryPanel(QWidget):
    """One large card for the live figure, its trend and two totals, beside three small stat cards."""

    def __init__(self) -> None:
        super().__init__()
        self._outer = QBoxLayout(QBoxLayout.Direction.LeftToRight, self)
        self._outer.setContentsMargins(0, 0, 0, 0)
        self._outer.setSpacing(t.PANEL_GAP)
        hero = _card()
        hero_layout = hero.layout()
        top = QHBoxLayout()
        top.setSpacing(t.SP_XL)
        lead = QVBoxLayout()
        lead.setSpacing(t.SP_SM)
        self.now = MetricValue("—", t.FONT_HERO)
        self.now_cost = _caption("—")
        lead.addWidget(_caption("Power right now"))
        lead.addWidget(self.now)
        lead.addWidget(self.now_cost)
        self.trend = Sparkline()
        top.addLayout(lead)
        top.addWidget(self.trend, 1, Qt.AlignmentFlag.AlignVCenter)
        hero_layout.addLayout(top)
        hero_layout.addStretch()
        totals = QHBoxLayout()
        totals.setSpacing(t.SP_XL)
        self.today, self.today_cost, self.today_trend = self._total(totals, "Used today", "Since midnight")
        self.month, self.month_cost, self.month_trend = self._total(totals, "This month", "Month to date")
        hero_layout.addLayout(totals)
        self._outer.addWidget(hero, 3)
        self._side = QBoxLayout(QBoxLayout.Direction.TopToBottom)
        self._side.setSpacing(t.PANEL_GAP)
        self.top, self.top_note = self._stat("Highest usage today", "No readings yet")
        self.plugs, self.plugs_note = self._stat("Plugs online", "No plugs yet")
        self.cost, self.cost_note = self._stat("Cost today", "No tariff set")
        self._outer.addLayout(self._side, 2)

    def _total(self, row: QHBoxLayout, title: str, sub: str) -> tuple[MetricValue, QLabel, Sparkline]:
        column = QVBoxLayout()
        column.setSpacing(t.SP_XS)
        value, detail = MetricValue("—", t.FONT_VALUE), _caption(sub)
        spark = Sparkline(t.SPARK_SMALL)
        figure = QHBoxLayout()
        figure.addWidget(value, 1)
        figure.addWidget(spark, 1, Qt.AlignmentFlag.AlignVCenter)
        column.addWidget(_caption(title))
        column.addLayout(figure)
        column.addWidget(detail)
        row.addLayout(column, 1)
        return value, detail, spark

    def _stat(self, title: str, sub: str) -> tuple[MetricValue, QLabel]:
        card = _card()
        card.layout().addWidget(_caption(title))
        row = QHBoxLayout()
        value, note = MetricValue("—", t.FONT_VALUE), _caption(sub, right=True)
        row.addWidget(value)
        row.addWidget(note, 1)
        card.layout().addLayout(row)
        self._side.addWidget(card, 1)
        return value, note

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        narrow = self.width() < 700
        self._outer.setDirection(QBoxLayout.Direction.TopToBottom if narrow else QBoxLayout.Direction.LeftToRight)
        self._side.setDirection(QBoxLayout.Direction.LeftToRight if narrow else QBoxLayout.Direction.TopToBottom)


def cost_line(wh: float, price: float, hint: str) -> str:
    """Cost of `wh` at `price` per kWh, or `hint` when no tariff is set (0.00 would read as free)."""
    return f"Estimated cost {wh / 1000 * price:.2f}" if price else hint


def metric_card(
    row: QHBoxLayout, title: str, sub: str = "—", *, highlight: bool = False,
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
