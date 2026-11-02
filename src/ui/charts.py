"""Chart widgets: rolling live watts and daily kWh bars."""
import time
from collections import deque
from collections.abc import Sequence
from datetime import date

from PySide6.QtCharts import QBarCategoryAxis, QBarSeries, QBarSet, QChart, QChartView, QLineSeries, QValueAxis
from PySide6.QtCore import QMargins, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QCursor, QFont, QPainter, QPen
from PySide6.QtWidgets import QToolTip

from ui.theme import theme

SAMPLE_SECONDS = 5  # must match the main window's refresh interval
GAP_SLOTS = 2.5  # further apart than this many sample intervals and the line breaks


def ago_label(seconds: float) -> str:
    return f"{seconds / 3600:g} h ago" if seconds >= 3600 else f"{seconds / 60:g} min ago"
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
    """Watt samples of one plug over the last `max_samples` x SAMPLE_SECONDS."""

    def __init__(self, max_samples: int):
        super().__init__(QChart())
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        chart = self.chart()
        chart.legend().hide()
        chart.setMargins(QMargins(8, 4, 16, 26))
        self.setMinimumHeight(200)
        self._x = QValueAxis()
        self._x.setRange(0, max_samples)
        self._x.setLabelsVisible(False)
        self._x.setGridLineVisible(False)
        self._max = max_samples
        self._points: list[tuple[float, float]] = []  # (slot, watts); slot == max_samples is "now"
        self._lines: list[QLineSeries] = []
        self._bridges: list[QLineSeries] = []
        self._hover: int | None = None
        self._span = max_samples * SAMPLE_SECONDS
        self._gap_slots = GAP_SLOTS
        self.setMouseTracking(True)
        self._y = QValueAxis()
        self._y.setTitleText("W")
        chart.addAxis(self._x, BOTTOM)
        chart.addAxis(self._y, LEFT)
        self._y.setTickCount(4)
        self._y.setLabelFormat("%.0f")
        theme().changed.connect(self._apply_theme)
        self._apply_theme()

    def _apply_theme(self) -> None:
        style_chart(self)
        for line in self._lines:
            line.setPen(QPen(QColor(theme().colors.accent), 2.5))
        for line in self._bridges:
            pen = QPen(QColor(theme().colors.control), 1.5, Qt.PenStyle.DashLine)
            line.setPen(pen)

    def show_samples(
        self, samples: deque[float] | None, title: str, times: Sequence[float] | None = None,
        span: float | None = None, interval: float = SAMPLE_SECONDS,
        estimates: Sequence[tuple[float, float]] = (),
    ) -> None:
        """`times` are epoch seconds per sample; with them, gaps (app closed) show as gaps.

        `span` is the window in seconds (default: the live window); `interval` the normal spacing of samples.
        `estimates` are (epoch seconds, watts) the plug stored itself; a gap's dashed line runs through those
        points, or straight across when there are none.
        """
        self._span = span or self._max * SAMPLE_SECONDS
        self._gap_slots = GAP_SLOTS * interval / self._span * self._max
        samples = list(samples or ())
        self._hover = None
        self.chart().setTitle(title)
        if times is not None and len(times) == len(samples):
            now = time.time()
            points = [(self._max - (now - t) / self._span * self._max, w) for t, w in zip(times, samples)]
            points = [p for p in points if p[0] >= 0]
        else:
            offset = self._max - len(samples)
            points = [(offset + i, w) for i, w in enumerate(samples)]
        self._points = points
        for line in self._lines + self._bridges:
            self.chart().removeSeries(line)
        self._lines, self._bridges = [], []
        segments: list[list[tuple[float, float]]] = []
        for point in points:
            if segments and point[0] - segments[-1][-1][0] <= self._gap_slots:
                segments[-1].append(point)
            else:
                segments.append([point])
        for i, segment in enumerate(segments):
            if i:  # dashed link over the gap: nothing was measured there
                before, after = segments[i - 1][-1], segment[0]
                inside = sorted(
                    (x, w) for x, w in ((self._slot(t), w) for t, w in estimates) if before[0] < x < after[0]
                )
                self._add_line([before, *inside, after], self._bridges)
            self._add_line(segment, self._lines)
        peak = max((w for _, w in points), default=0)
        self._y.setRange(0, max(10.0, peak * 1.2))
        self._y.applyNiceNumbers()
        self._y.setLabelFormat("%.1f" if peak < 10 else "%.0f")
        self._apply_theme()
        self.viewport().update()

    def _slot(self, ts: float) -> float:
        return self._max - (time.time() - ts) / self._span * self._max

    def _add_line(self, points: list[tuple[float, float]], into: list[QLineSeries]) -> None:
        line = QLineSeries()
        line.append([QPointF(x, w) for x, w in points])
        self.chart().addSeries(line)
        line.attachAxis(self._x)
        line.attachAxis(self._y)
        into.append(line)

    def _index_at(self, x: float) -> int | None:
        area = self.chart().mapRectToScene(self.chart().plotArea())
        if not self._points or not area.left() <= x <= area.right():
            return None
        slot = (x - area.left()) / area.width() * self._max
        index = min(range(len(self._points)), key=lambda i: abs(self._points[i][0] - slot))
        return index if abs(self._points[index][0] - slot) <= self._gap_slots else None

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
        for slot, label, align in ((0, ago_label(self._span), Qt.AlignmentFlag.AlignLeft), (self._max // 2, ago_label(self._span / 2), Qt.AlignmentFlag.AlignHCenter), (self._max, "now", Qt.AlignmentFlag.AlignRight)):
            x = area.left() + slot / self._max * area.width()
            box = QRectF(x - 40, area.bottom() + 6, 80, 18)
            if align == Qt.AlignmentFlag.AlignLeft:
                box.moveLeft(x)
            elif align == Qt.AlignmentFlag.AlignRight:
                box.moveRight(x)
            painter.drawText(box, align | Qt.AlignmentFlag.AlignVCenter, label)
        if self._hover is not None:
            slot, value = self._points[self._hover]
            x = area.left() + slot / self._max * area.width()
            y = area.bottom() - value / (self._y.max() or 1) * area.height()
            painter.setPen(QPen(QColor(c.control), 1))
            painter.drawLine(QPointF(x, area.top()), QPointF(x, area.bottom()))
            painter.setPen(QPen(QColor(c.surface), 2))
            painter.setBrush(QColor(c.accent))
            painter.drawEllipse(QPointF(x, y), 4.5, 4.5)
            ago = round((self._max - slot) / self._max * self._span)
            text = f"{value:.1f} W · " + ("now" if ago <= SAMPLE_SECONDS else f"{ago} s ago" if ago < 60 else f"{ago // 3600} h {ago % 3600 // 60:02d} min ago" if ago >= 3600 else f"{ago // 60} min {ago % 60:02d} s ago")
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
