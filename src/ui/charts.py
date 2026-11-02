"""Chart widgets: rolling live watts and daily kWh bars."""
import time
from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

from PySide6.QtCharts import QBarCategoryAxis, QBarSeries, QBarSet, QChart, QChartView, QLineSeries, QValueAxis
from PySide6.QtCore import QMargins, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QCursor, QFont, QPainter, QPen
from PySide6.QtWidgets import QToolTip

from ui.theme import theme

SAMPLE_SECONDS = 5  # must match the main window's refresh interval
GAP_SLOTS = 2.5  # further apart than this many sample intervals and the line breaks


def age_text(seconds: int) -> str:
    if seconds <= SAMPLE_SECONDS:
        return "now"
    if seconds < 60:
        return f"{seconds} s ago"
    if seconds >= 3600:
        return f"{seconds // 3600} h {seconds % 3600 // 60:02d} min ago"
    return f"{seconds // 60} min {seconds % 60:02d} s ago"


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


@dataclass
class Line:
    """One series of the live chart: `times` are epoch seconds. `color` None means the theme accent."""

    name: str
    times: Sequence[float]
    watts: Sequence[float]
    color: str | None = None
    estimates: Sequence[tuple[float, float]] = ()


class LiveChart(QChartView):
    """Watt lines (one per plug, plus the overall) over the last `max_samples` x SAMPLE_SECONDS."""

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
        self._names: list[str] = []
        self._colors: list[str | None] = []
        self._points: list[list[tuple[float, float]]] = []  # per line: (slot, watts); slot == max_samples is "now"
        self._lines: list[QLineSeries] = []
        self._line_colors: list[str | None] = []
        self._bridges: list[QLineSeries] = []
        self._bridge_colors: list[str | None] = []
        self._hover: float | None = None  # slot under the cursor
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
        colors = theme().colors
        for line, color in zip(self._lines, self._line_colors, strict=True):
            line.setPen(QPen(QColor(color or colors.accent), 2.5 if color is None else 2))
        for line, color in zip(self._bridges, self._bridge_colors, strict=True):
            line.setPen(QPen(QColor(color or colors.control), 1.5, Qt.PenStyle.DashLine))

    def show_samples(
        self, samples: deque[float] | None, title: str, times: Sequence[float] | None = None,
        span: float | None = None, interval: float = SAMPLE_SECONDS,
        estimates: Sequence[tuple[float, float]] = (),
    ) -> None:
        """One accent line; without `times` the samples are taken to end now, `interval` apart."""
        samples = list(samples or ())
        if times is None or len(times) != len(samples):
            now = time.time()
            times = [now - (len(samples) - 1 - i) * interval for i in range(len(samples))]
        self.show_lines([Line("", times, samples, None, estimates)], title, span, interval)

    def show_lines(
        self, lines: Sequence[Line], title: str, span: float | None = None, interval: float = SAMPLE_SECONDS,
    ) -> None:
        """`span` is the window in seconds (default: the live window); `interval` the normal spacing of samples.

        A gap (app closed) shows as a gap. A line's `estimates` are (epoch seconds, watts) points the plug
        stored itself; its gap's dashed line runs through those, or straight across when there are none.
        """
        self._span = span or self._max * SAMPLE_SECONDS
        self._gap_slots = GAP_SLOTS * interval / self._span * self._max
        self._hover = None
        self.chart().setTitle(title)
        for series in self._lines + self._bridges:
            self.chart().removeSeries(series)
        self._lines, self._bridges, self._line_colors, self._bridge_colors = [], [], [], []
        self._names, self._colors, self._points = [line.name for line in lines], [line.color for line in lines], []
        for line in lines:
            points = [(self._slot(t), w) for t, w in zip(line.times, line.watts, strict=True)]
            points = [p for p in points if p[0] >= 0]
            self._points.append(points)
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
                        (x, w) for x, w in ((self._slot(t), w) for t, w in line.estimates) if before[0] < x < after[0]
                    )
                    self._add_line([before, *inside, after], self._bridges, self._bridge_colors, line.color)
                self._add_line(segment, self._lines, self._line_colors, line.color)
        peak = max((w for points in self._points for _, w in points), default=0)
        self._y.setRange(0, max(10.0, peak * 1.2))
        self._y.applyNiceNumbers()
        self._y.setLabelFormat("%.1f" if peak < 10 else "%.0f")
        self._apply_theme()
        self.viewport().update()

    def _slot(self, ts: float) -> float:
        return self._max - (time.time() - ts) / self._span * self._max

    def _add_line(
        self, points: list[tuple[float, float]], into: list[QLineSeries], colors: list[str | None], color: str | None,
    ) -> None:
        line = QLineSeries()
        line.append([QPointF(x, w) for x, w in points])
        self.chart().addSeries(line)
        line.attachAxis(self._x)
        line.attachAxis(self._y)
        into.append(line)
        colors.append(color)

    def _slot_at(self, x: float) -> float | None:
        """Slot of the reading nearest the cursor, over all lines."""
        area = self.chart().mapRectToScene(self.chart().plotArea())
        slots = [s for points in self._points for s, _ in points]
        if not slots or not area.left() <= x <= area.right():
            return None
        slot = (x - area.left()) / area.width() * self._max
        nearest = min(slots, key=lambda s: abs(s - slot))
        return nearest if abs(nearest - slot) <= self._gap_slots else None

    def _rows_at(self, slot: float) -> list[tuple[int, float, float]]:
        """(line index, slot, watts) of each line's reading near `slot`."""
        rows = []
        for i, points in enumerate(self._points):
            if points:
                near = min(points, key=lambda p: abs(p[0] - slot))
                if abs(near[0] - slot) <= self._gap_slots:
                    rows.append((i, *near))
        return rows

    def mouseMoveEvent(self, event) -> None:
        super().mouseMoveEvent(event)
        self._hover = self._slot_at(self.mapToScene(event.position().toPoint()).x())
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
        left, center, right = (Qt.AlignmentFlag.AlignLeft, Qt.AlignmentFlag.AlignHCenter, Qt.AlignmentFlag.AlignRight)
        labels = (
            (0, ago_label(self._span), left),
            (self._max // 2, ago_label(self._span / 2), center),
            (self._max, "now", right),
        )
        for slot, label, align in labels:
            x = area.left() + slot / self._max * area.width()
            box = QRectF(x - 40, area.bottom() + 6, 80, 18)
            if align == Qt.AlignmentFlag.AlignLeft:
                box.moveLeft(x)
            elif align == Qt.AlignmentFlag.AlignRight:
                box.moveRight(x)
            painter.drawText(box, align | Qt.AlignmentFlag.AlignVCenter, label)
        rows = self._rows_at(self._hover) if self._hover is not None else []
        if rows:
            x = area.left() + self._hover / self._max * area.width()
            painter.setPen(QPen(QColor(c.control), 1))
            painter.drawLine(QPointF(x, area.top()), QPointF(x, area.bottom()))
            for i, slot, value in rows:
                color = QColor(self._color_of(i))
                dot_x = area.left() + slot / self._max * area.width()
                y = area.bottom() - value / (self._y.max() or 1) * area.height()
                painter.setPen(QPen(QColor(c.surface), 2))
                painter.setBrush(color)
                painter.drawEllipse(QPointF(dot_x, y), 4.5, 4.5)
            ago = round((self._max - self._hover) / self._max * self._span)
            texts = [(self._color_of(i), f"{self._names[i]}  {value:.1f} W".strip()) for i, _, value in rows]
            metrics = painter.fontMetrics()
            head = age_text(ago)
            width = max(metrics.horizontalAdvance(t) for t in [head, *(t for _, t in texts)]) + 34
            box = QRectF(0, 0, width, 12 + 18 * (len(texts) + 1))
            left_edge = x + 10 if x + 10 + box.width() <= area.right() else x - 10 - box.width()
            box.moveTopLeft(QPointF(max(area.left(), left_edge), area.top() + 4))
            painter.setPen(QPen(QColor(c.border), 1))
            painter.setBrush(QColor(c.raised))
            painter.drawRoundedRect(box, 6, 6)
            painter.setPen(QColor(c.muted))
            middle = Qt.AlignmentFlag.AlignVCenter
            painter.drawText(QRectF(box.left() + 10, box.top() + 6, width - 20, 18), middle, head)
            for n, (color, text) in enumerate(texts, 1):
                top = box.top() + 6 + 18 * n
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(color))
                painter.drawEllipse(QPointF(box.left() + 14, top + 9), 4, 4)
                painter.setPen(QColor(c.text))
                painter.drawText(QRectF(box.left() + 24, top, width - 30, 18), middle, text)
        painter.restore()

    def _color_of(self, index: int) -> str:
        """The line's own color; the overall (no color) wears the accent."""
        return self._colors[index] or theme().colors.accent


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
