"""Chart widgets: rolling live watts and usage per day, month or hour, built on one shared base."""
import time
from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass

from PySide6.QtCharts import QChart, QChartView, QLineSeries, QValueAxis
from PySide6.QtCore import QMargins, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QCheckBox, QHBoxLayout, QWidget

from ui import tokens as t
from ui.theme import series_color, theme

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
    chart.setBackgroundRoundness(t.RADIUS_LG)
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


OVERALL = "overall"  # toggle key for the sum of all plugs


class LineColors:
    """A plug keeps its color slot whatever the filter, so toggling never repaints the others.

    A slot is an index into the theme's validated series colors. `None` is the overall, drawn in the text color.
    """

    def __init__(self) -> None:
        self._slots: dict[str, int] = {}

    def __call__(self, key: str) -> int:
        return self._slots.setdefault(key, len(self._slots))


def line_color(slot: int | None) -> str:
    return theme().colors.text if slot is None else series_color(slot)


def swatch(color: str) -> QIcon:
    pixmap = QPixmap(12, 12)
    pixmap.fill(QColor(color))
    return QIcon(pixmap)


class LineToggles(QWidget):
    """A checkbox for the overall line and one per plug; hidden keys stay hidden when the boxes are rebuilt."""

    changed = Signal()

    def __init__(self, colors: LineColors):
        super().__init__()
        self._colors = colors
        self._boxes: dict[str, QCheckBox] = {}
        self._signature: tuple = ()
        self._names: list[tuple[str, str]] = []
        self.hidden: set[str] = set()
        self._row = QHBoxLayout(self)
        self._row.setContentsMargins(0, 0, 0, 0)
        self._row.setSpacing(t.SP_LG)
        theme().changed.connect(self._retheme)

    def _retheme(self) -> None:
        """The swatches carry theme colors, so rebuild them when the theme changes."""
        self._signature = ()
        self.set_plugs(self._names)

    def shown(self, key: str) -> bool:
        return key not in self.hidden

    def set_plugs(self, names: Sequence[tuple[str, str]]) -> None:
        """`names` are (ip, label); the boxes are rebuilt only when the plugs, labels or theme change."""
        signature = (theme().colors.text, theme().colors.series, *names)
        if signature == self._signature:
            return
        self._signature = signature
        self._names = list(names)
        while self._row.count():
            item = self._row.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._boxes = {}
        if names:
            self._add(OVERALL, "Overall", line_color(None))
        for key, label in names:
            self._add(key, label, line_color(self._colors(key)))
        self._row.addStretch(1)

    def _add(self, key: str, label: str, color: str) -> None:
        box = QCheckBox(label)
        box.setMinimumHeight(t.TARGET - t.SP_SM)  # a comfortable click area, not just the tick
        box.setIcon(swatch(color))
        box.setChecked(self.shown(key))
        box.toggled.connect(lambda on, key=key: self._toggled(key, on))
        self._row.addWidget(box)
        self._boxes[key] = box

    def _toggled(self, key: str, on: bool) -> None:
        self.hidden.discard(key) if on else self.hidden.add(key)
        self.changed.emit()


def paint_readout(
    painter: QPainter, area: QRectF, x: float, head: str,
    dots: Sequence[tuple[QPointF, str]], entries: Sequence[tuple[str, str]],
) -> None:
    """Hover layer: a crosshair at `x`, a dot per line and a box with `head` over the (color, text) `entries`."""
    c = theme().colors
    painter.setPen(QPen(QColor(c.control), 1))
    painter.drawLine(QPointF(x, area.top()), QPointF(x, area.bottom()))
    for point, color in dots:
        painter.setPen(QPen(QColor(c.surface), 2))
        painter.setBrush(QColor(color))
        painter.drawEllipse(point, 4.5, 4.5)
    metrics = painter.fontMetrics()
    width = max(metrics.horizontalAdvance(t) for t in [head, *(t for _, t in entries)]) + 34
    box = QRectF(0, 0, width, 12 + 18 * (len(entries) + 1))
    edge = x + 10 if x + 10 + box.width() <= area.right() else x - 10 - box.width()
    box.moveTopLeft(QPointF(max(area.left(), edge), area.top() + 4))
    painter.setPen(QPen(QColor(c.border), 1))
    painter.setBrush(QColor(c.raised))
    painter.drawRoundedRect(box, t.RADIUS_MD, t.RADIUS_MD)
    middle = Qt.AlignmentFlag.AlignVCenter
    painter.setPen(QColor(c.muted))
    painter.drawText(QRectF(box.left() + 10, box.top() + 6, width - 20, 18), middle, head)
    for n, (color, text) in enumerate(entries, 1):
        top = box.top() + 6 + 18 * n
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(color))
        painter.drawEllipse(QPointF(box.left() + 14, top + 9), 4, 4)
        painter.setPen(QColor(c.text))
        painter.drawText(QRectF(box.left() + 24, top, width - 30, 18), middle, text)


MARKER_LIMIT = 40  # a line with more points than this draws no point markers


class BaseChart(QChartView):
    """The look every chart shares: size, margins, axes, line pens, label row and hover readout.

    A subclass fills the chart with `_add_series`, and supplies `_label_row`, `_hover_at` and `_readout`.
    """

    def __init__(self, unit: str):
        super().__init__(QChart())
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        chart = self.chart()
        chart.legend().hide()
        chart.setMargins(QMargins(8, 4, 16, 30))
        self.setMinimumHeight(220)
        self.setMouseTracking(True)
        self._x = QValueAxis()
        self._x.setLabelsVisible(False)
        self._x.setGridLineVisible(False)
        self._y = QValueAxis()
        self._y.setTitleText(unit)
        self._y.setTickCount(4)
        chart.addAxis(self._x, BOTTOM)
        chart.addAxis(self._y, LEFT)
        self._drawn: list[tuple[QLineSeries, int | None, bool]] = []  # series, color slot (None: overall), dashed
        self._empty_text = ""
        self._hover = None
        theme().changed.connect(self._apply_theme)

    def _apply_theme(self) -> None:
        style_chart(self)
        colors = theme().colors
        for series, slot, dashed in self._drawn:
            if dashed:
                color = colors.control if slot is None else line_color(slot)
                series.setPen(QPen(QColor(color), 1.5, Qt.PenStyle.DashLine))
            else:  # the overall is the heavier line, so it also differs from the plugs by weight, not only by color
                series.setPen(QPen(QColor(line_color(slot)), 3 if slot is None else 2))
        self.viewport().update()

    def _clear_series(self) -> None:
        for series, _, _ in self._drawn:
            self.chart().removeSeries(series)
        self._drawn = []

    def _add_series(
        self, points: Sequence[tuple[float, float]], color: int | None, dashed: bool = False,
    ) -> QLineSeries:
        series = QLineSeries()
        series.append([QPointF(x, y) for x, y in points])
        series.setPointsVisible(not dashed and len(points) <= MARKER_LIMIT)
        self.chart().addSeries(series)
        series.attachAxis(self._x)
        series.attachAxis(self._y)
        self._drawn.append((series, color, dashed))
        return series

    def _fit_y(self, peak: float, minimum: float, decimals: int) -> None:
        self._y.setRange(0, max(minimum, peak * 1.2))
        self._y.applyNiceNumbers()
        self._y.setLabelFormat(f"%.{decimals}f")

    def _plot_area(self) -> QRectF:
        return self.chart().mapRectToScene(self.chart().plotArea())

    def _label_row(self) -> Sequence[tuple[float, str]]:
        """(fraction of the plot width, text) labels under the plot."""
        return ()

    def _has_points(self) -> bool:
        return True

    def _describe(self, text: str) -> None:
        """Screen readers cannot hover: put the chart's title and latest values into its accessible text."""
        self.setAccessibleName(self.chart().title())
        self.setAccessibleDescription(text)

    def _hover_at(self, x: float):
        """What is under the cursor at scene x (None for nothing)."""
        return None

    def _readout(self, area: QRectF):
        """(x, heading, dots, entries) for `paint_readout`, or None."""
        return None

    def mouseMoveEvent(self, event) -> None:
        super().mouseMoveEvent(event)
        self._hover = self._hover_at(self.mapToScene(event.position().toPoint()).x())
        self.viewport().update()

    def leaveEvent(self, event) -> None:
        super().leaveEvent(event)
        self._hover = None
        self.viewport().update()

    def drawForeground(self, painter: QPainter, rect: QRectF) -> None:
        super().drawForeground(painter, rect)
        area = self._plot_area()
        painter.save()
        painter.setPen(QColor(theme().colors.muted))
        painter.setFont(QFont("Segoe UI", 9))
        for fraction, text in self._label_row():
            x = area.left() + fraction * area.width()
            box = QRectF(x - 40, area.bottom() + 8, 80, 18)
            align = Qt.AlignmentFlag.AlignHCenter
            if box.left() < area.left():
                box.moveLeft(area.left())
                align = Qt.AlignmentFlag.AlignLeft
            elif box.right() > area.right():
                box.moveRight(area.right())
                align = Qt.AlignmentFlag.AlignRight
            painter.drawText(box, align | Qt.AlignmentFlag.AlignVCenter, text)
        if self._empty_text and not self._has_points():
            painter.setFont(QFont("Segoe UI", 11))
            painter.drawText(area, Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap, self._empty_text)
        readout = self._readout(area) if self._hover is not None else None
        if readout:
            paint_readout(painter, area, *readout)
        painter.restore()


@dataclass
class Line:
    """One series of the live chart: `times` are epoch seconds. `color` is a slot; None is the overall."""

    name: str
    times: Sequence[float]
    watts: Sequence[float]
    color: int | None = None
    estimates: Sequence[tuple[float, float]] = ()


class LiveChart(BaseChart):
    """Watt lines (one per plug, plus the overall) over the last `max_samples` x SAMPLE_SECONDS."""

    def __init__(self, max_samples: int):
        super().__init__("W")
        self._x.setRange(0, max_samples)
        self._max = max_samples
        self._names: list[str] = []
        self._colors: list[int | None] = []
        self._points: list[list[tuple[float, float]]] = []  # per line: (slot, watts); slot == max_samples is "now"
        self._lines: list[QLineSeries] = []
        self._bridges: list[QLineSeries] = []
        self._span = max_samples * SAMPLE_SECONDS
        self._gap_slots = GAP_SLOTS
        self._y.setLabelFormat("%.0f")
        self._empty_text = "No readings yet. They appear here as the plugs answer."
        self._apply_theme()

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
        self._clear_series()
        self._lines, self._bridges = [], []
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
                    self._bridges.append(self._add_series([before, *inside, after], line.color, dashed=True))
                self._lines.append(self._add_series(segment, line.color))
        peak = max((w for points in self._points for _, w in points), default=0)
        self._fit_y(peak, 10.0, 1 if peak < 10 else 0)
        self._apply_theme()
        pairs = zip(self._names, self._points, strict=True)
        latest = [f"{name} {points[-1][1]:.1f} W" for name, points in pairs if points]
        self._describe("Latest: " + ", ".join(latest) if latest else "No readings yet")

    def _has_points(self) -> bool:
        return any(self._points)

    def _slot(self, ts: float) -> float:
        return self._max - (time.time() - ts) / self._span * self._max

    def _label_row(self) -> Sequence[tuple[float, str]]:
        return ((0, ago_label(self._span)), (0.5, ago_label(self._span / 2)), (1, "now"))

    def _hover_at(self, x: float) -> float | None:
        """Slot of the reading nearest the cursor, over all lines."""
        area = self._plot_area()
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

    def _readout(self, area: QRectF):
        rows = self._rows_at(self._hover)
        if not rows:
            return None
        dots = []
        for i, slot, value in rows:
            y = area.bottom() - value / (self._y.max() or 1) * area.height()
            dots.append((QPointF(area.left() + slot / self._max * area.width(), y), self._color_of(i)))
        entries = [(self._color_of(i), f"{self._names[i]}  {value:.1f} W".strip()) for i, _, value in rows]
        ago = round((self._max - self._hover) / self._max * self._span)
        return area.left() + self._hover / self._max * area.width(), age_text(ago), dots, entries

    def _color_of(self, index: int) -> str:
        return line_color(self._colors[index])


@dataclass
class UsageLine:
    """One line of the usage chart: Wh per key, None where the plug has no point. `color`: a slot, or None (overall)."""

    name: str
    color: int | None
    wh: Sequence[int | None]


class UsageChart(BaseChart):
    """kWh per day, month or hour: one line per plug plus the overall."""

    TITLES = {"day": "Daily usage", "month": "Monthly usage", "hour": "Usage today by hour"}

    def __init__(self):
        super().__init__("kWh")
        self._keys: list = []  # a date, or an hour number for the hourly view
        self._kind = "day"
        self._lines: list[UsageLine] = []
        self._series: list[QLineSeries] = []
        self._empty_text = "No usage recorded yet."
        self.show_lines([], [], "day")

    def _label(self, key, tooltip: bool = False) -> str:
        if self._kind == "hour":
            return f"{key:02d}:00"
        if self._kind == "month":
            return key.strftime("%B %Y" if tooltip else "%b %Y")
        return key.strftime("%a %d %b" if tooltip else "%d %b")

    def show_lines(self, lines: Sequence[UsageLine], keys: Sequence, kind: str = "day") -> None:
        """`kind` is "day" / "month" (keys are dates) or "hour" (keys are hours); each line has a value per key."""
        self._lines, self._keys, self._kind, self._hover = list(lines), list(keys), kind, None
        self.chart().setTitle(self.TITLES[kind])
        self._clear_series()
        self._series = [
            self._add_series([(i, wh / 1000) for i, wh in enumerate(line.wh) if wh is not None], line.color)
            for line in self._lines
        ]
        self._x.setRange(-0.5, max(len(self._keys), 1) - 0.5)
        peak = max((wh for line in self._lines for wh in line.wh if wh is not None), default=0) / 1000
        self._fit_y(peak, 0.1, 2 if peak < 10 else 0)
        self._apply_theme()
        shown = [line for line in self._lines if line.wh and line.wh[-1] is not None]
        last = [f"{line.name} {line.wh[-1] / 1000:.2f} kWh" for line in shown]
        self._describe("Latest: " + ", ".join(last) if last else "No usage recorded yet")

    def _has_points(self) -> bool:
        return bool(self._keys)

    def _label_row(self) -> Sequence[tuple[float, str]]:
        """Sparse labels so a whole quarter stays readable at small widths."""
        count = len(self._keys)
        if not count:
            return ()
        ticks = min(count, max(2, int(self._plot_area().width() / 100)))
        indices = sorted({round(i * (count - 1) / max(1, ticks - 1)) for i in range(ticks)})
        return [((index + 0.5) / count, self._label(self._keys[index])) for index in indices]

    def _hover_at(self, x: float) -> int | None:
        area = self._plot_area()
        if not self._keys or not area.left() <= x <= area.right():
            return None
        return min(len(self._keys) - 1, int((x - area.left()) / area.width() * len(self._keys)))

    def _readout(self, area: QRectF):
        x = area.left() + (self._hover + 0.5) * area.width() / len(self._keys)
        dots, entries = [], []
        for line in self._lines:
            wh = line.wh[self._hover]
            if wh is not None:
                y = area.bottom() - wh / 1000 / (self._y.max() or 1) * area.height()
                dots.append((QPointF(x, y), line_color(line.color)))
                entries.append((line_color(line.color), f"{line.name}  {wh / 1000:.2f} kWh"))
        if not entries:
            return None
        return x, self._label(self._keys[self._hover], tooltip=True), dots, entries
