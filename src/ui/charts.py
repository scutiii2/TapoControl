"""Chart widgets: rolling live watts and daily kWh bars."""
from collections import deque
from datetime import date

from PySide6.QtCharts import QBarCategoryAxis, QBarSeries, QBarSet, QChart, QChartView, QLineSeries, QValueAxis
from PySide6.QtCore import QMargins, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QCursor, QFont, QPainter, QPen
from PySide6.QtWidgets import QToolTip

from ui.theme import theme

BOTTOM = Qt.AlignmentFlag.AlignBottom
LEFT = Qt.AlignmentFlag.AlignLeft


def style_chart(view: QChartView) -> None:
    colors = theme().colors
    chart = view.chart()
    chart.setBackgroundBrush(QColor(colors.surface))
    chart.setBackgroundRoundness(10)
    chart.setPlotAreaBackgroundVisible(False)
    chart.setTitleBrush(QColor(colors.text))
    chart.setTitleFont(QFont("Segoe UI", 11, QFont.Weight.DemiBold))
    view.setStyleSheet("background: transparent; border: none;")
    for axis in chart.axes():
        axis.setLabelsBrush(QColor(colors.muted))
        axis.setLabelsFont(QFont("Segoe UI", 9))
        axis.setTitleBrush(QColor(colors.muted))
        axis.setTitleFont(QFont("Segoe UI", 9))
        axis.setLineVisible(False)
        axis.setGridLinePen(QPen(QColor(colors.border), 0.5))


class LiveChart(QChartView):
    """Last N watt samples of one plug."""

    def __init__(self, max_samples: int):
        super().__init__(QChart())
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        chart = self.chart()
        chart.legend().hide()
        chart.setMargins(QMargins(8, 4, 16, 26))
        self.setMinimumHeight(200)
        self._series = QLineSeries()
        chart.addSeries(self._series)
        x = QValueAxis()
        x.setRange(0, max_samples)
        x.setLabelsVisible(False)
        self._max = max_samples
        self._samples: list[float] = []
        self._hover: int | None = None
        self.setMouseTracking(True)
        self._y = QValueAxis()
        self._y.setTitleText("W")
        chart.addAxis(x, BOTTOM)
        chart.addAxis(self._y, LEFT)
        self._series.attachAxis(x)
        self._series.attachAxis(self._y)
        self._y.setTickCount(4)
        self._y.setLabelFormat("%.0f")
        x.setGridLineVisible(False)
        theme().changed.connect(self._apply_theme)
        self._apply_theme()

    def _apply_theme(self) -> None:
        style_chart(self)
        self._series.setPen(QPen(QColor(theme().colors.accent), 2.5))

    def show_samples(self, samples: deque[float] | None, title: str) -> None:
        samples = list(samples or ())
        self._samples = samples
        self._hover = None
        self.chart().setTitle(title)
        # Newest sample sits at the right edge ("now"); history fills in from there.
        offset = self._max - len(samples)
        self._series.replace([QPointF(offset + i, w) for i, w in enumerate(samples)])
        self._y.setRange(0, max(10.0, max(samples, default=0) * 1.2))
        self._y.applyNiceNumbers()
        self._y.setLabelFormat("%.1f" if max(samples, default=0) < 10 else "%.0f")
        self.viewport().update()

    def _index_at(self, x: float) -> int | None:
        area = self.chart().mapRectToScene(self.chart().plotArea())
        if not self._samples or not area.left() <= x <= area.right():
            return None
        slot = round((x - area.left()) / area.width() * self._max)
        index = slot - (self._max - len(self._samples))
        return min(max(index, 0), len(self._samples) - 1) if slot >= self._max - len(self._samples) else None

    def mouseMoveEvent(self, event) -> None:
        super().mouseMoveEvent(event)
        self._hover = self._index_at(self.mapToScene(event.position().toPoint()).x())
        self.viewport().update()

    def leaveEvent(self, event) -> None:
        super().leaveEvent(event)
        self._hover = None
        self.viewport().update()

    def drawForeground(self, painter: QPainter, rect: QRectF) -> None:
        super().drawForeground(painter, rect)
        c = theme().colors
        area = self.chart().mapRectToScene(self.chart().plotArea())
        painter.save()
        painter.setPen(QColor(c.muted))
        painter.setFont(QFont("Segoe UI", 9))
        for slot, label, align in ((0, "10 min ago", Qt.AlignmentFlag.AlignLeft), (self._max // 2, "5 min ago", Qt.AlignmentFlag.AlignHCenter), (self._max, "now", Qt.AlignmentFlag.AlignRight)):
            x = area.left() + slot / self._max * area.width()
            box = QRectF(x - 40, area.bottom() + 6, 80, 18)
            if align == Qt.AlignmentFlag.AlignLeft:
                box.moveLeft(x)
            elif align == Qt.AlignmentFlag.AlignRight:
                box.moveRight(x)
            painter.drawText(box, align | Qt.AlignmentFlag.AlignVCenter, label)
        if self._hover is not None:
            slot = self._max - len(self._samples) + self._hover
            x = area.left() + slot / self._max * area.width()
            value = self._samples[self._hover]
            y = area.bottom() - value / (self._y.max() or 1) * area.height()
            painter.setPen(QPen(QColor(c.control), 1))
            painter.drawLine(QPointF(x, area.top()), QPointF(x, area.bottom()))
            painter.setPen(QPen(QColor(c.surface), 2))
            painter.setBrush(QColor(c.accent))
            painter.drawEllipse(QPointF(x, y), 4.5, 4.5)
            ago = (len(self._samples) - 1 - self._hover) * 5
            text = f"{value:.1f} W · " + ("now" if ago == 0 else f"{ago} s ago" if ago < 60 else f"{ago // 60} min {ago % 60:02d} s ago")
            box = QRectF(0, 0, painter.fontMetrics().horizontalAdvance(text) + 16, 24)
            box.moveTopLeft(QPointF(min(x + 10, area.right() - box.width()), max(area.top(), y - 34)))
            painter.setPen(QPen(QColor(c.border), 1))
            painter.setBrush(QColor(c.raised))
            painter.drawRoundedRect(box, 6, 6)
            painter.setPen(QColor(c.text))
            painter.drawText(box, Qt.AlignmentFlag.AlignCenter, text)
        painter.restore()


class DailyBars(QChartView):
    """kWh per day."""

    def __init__(self):
        super().__init__(QChart())
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.chart().legend().hide()
        self.chart().setTitle("Daily usage")
        self.chart().setMargins(QMargins(8, 4, 16, 30))
        self.setMinimumHeight(250)
        self._rows: list[tuple[date, int]] = []
        self._kind = "day"
        self._bars = QBarSet("kWh")
        self._bars.hovered.connect(self._on_hover)
        series = QBarSeries()
        series.append(self._bars)
        series.setBarWidth(0.6)
        self.chart().addSeries(series)
        self._x = QBarCategoryAxis()
        self._x.setVisible(False)
        self._y = QValueAxis()
        self._y.setTitleText("kWh")
        self._y.setTickCount(4)
        self._y.setLabelFormat("%.2f")
        self.chart().addAxis(self._x, BOTTOM)
        self.chart().addAxis(self._y, LEFT)
        series.attachAxis(self._x)
        series.attachAxis(self._y)
        theme().changed.connect(self._apply_theme)
        self.show_rows([])

    def _on_hover(self, hovering: bool, index: int) -> None:
        if hovering and index < len(self._rows):
            key, wh = self._rows[index]
            QToolTip.showText(QCursor.pos(), f"{self._label(key, tooltip=True)} · {wh / 1000:.2f} kWh", self)
        else:
            QToolTip.hideText()

    def _label(self, key, tooltip: bool = False) -> str:
        """`key` is a date, or an hour number for the hourly view."""
        if self._kind == "hour":
            return f"{key:02d}:00"
        if self._kind == "month":
            return key.strftime("%B %Y" if tooltip else "%b %Y")
        return key.strftime("%a %d %b" if tooltip else "%d %b")

    def _apply_theme(self) -> None:
        style_chart(self)
        self._bars.setColor(QColor(theme().colors.accent))
        self._bars.setBorderColor(QColor(theme().colors.accent))
        self.viewport().update()

    def show_rows(self, rows: list[tuple[date | int, int]], kind: str = "day") -> None:
        """kind: "day" / "month" rows are (date, Wh); "hour" rows are (hour, Wh)."""
        self._rows = list(rows)
        self._kind = kind
        self.chart().setTitle({"day": "Daily usage", "month": "Monthly usage", "hour": "Usage today by hour"}[kind])
        if self._bars.count():
            self._bars.remove(0, self._bars.count())
        self._x.clear()
        if rows:
            self._bars.append([wh / 1000 for _, wh in rows])
            self._x.append([str(k) for k, _ in rows])
        self._y.setRange(0, max((wh for _, wh in rows), default=0) / 1000 * 1.2 or 1)
        self._apply_theme()

    def drawForeground(self, painter: QPainter, rect: QRectF) -> None:
        super().drawForeground(painter, rect)
        if not self._rows:
            return
        # Paint sparse date labels so a whole quarter remains readable at small widths.
        area = self.chart().mapRectToScene(self.chart().plotArea())
        count = len(self._rows)
        ticks = min(count, max(2, int(area.width() / 100)))
        indices = sorted({round(i * (count - 1) / max(1, ticks - 1)) for i in range(ticks)})
        painter.save()
        painter.setPen(QColor(theme().colors.muted))
        painter.setFont(QFont("Segoe UI", 9))
        for index in indices:
            x = area.left() + (index + 0.5) * area.width() / count
            label = self._label(self._rows[index][0])
            painter.drawText(QRectF(x - 36, area.bottom() + 8, 72, 22), Qt.AlignmentFlag.AlignCenter, label)
        painter.restore()
