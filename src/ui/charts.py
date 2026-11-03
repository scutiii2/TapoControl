"""Chart widgets: rolling live watts and usage per day, month or hour, built on one shared base."""
import time
import math
from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass

from PySide6.QtCharts import QAreaSeries, QChart, QChartView, QLineSeries, QValueAxis
from PySide6.QtCore import QMargins, QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QCheckBox, QGridLayout, QLayout, QWidget

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
    label_font = QFont(t.FONT_FAMILY)
    label_font.setPixelSize(t.FONT_CAPTION)
    for axis in chart.axes():
        axis.setLabelsBrush(QColor(colors.muted))
        axis.setLabelsFont(label_font)
        axis.setTitleBrush(QColor(colors.muted))
        axis.setTitleFont(label_font)
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


class LineToggles(QWidget):
    """A checkbox for the overall line and one per plug; hidden keys stay hidden when the boxes are rebuilt."""

    changed = Signal()

    def __init__(self, colors: LineColors, *, include_overall: bool = True):
        super().__init__()
        self._colors = colors
        self._include_overall = include_overall
        self._boxes: dict[str, QCheckBox] = {}
        self._signature: tuple = ()
        self._names: list[tuple[str, str]] = []
        self.hidden: set[str] = set()
        self._row = QGridLayout(self)
        self._row.setContentsMargins(0, 0, 0, 0)
        self._row.setHorizontalSpacing(t.SP_LG)
        self._row.setVerticalSpacing(t.SP_XS)
        self._row.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        self._used_columns = 0
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
        if names and self._include_overall:
            self._add(OVERALL, "Overall", line_color(None))
        for key, label in names:
            self._add(key, label, line_color(self._colors(key)))
        self._reflow()

    def _add(self, key: str, label: str, color: str) -> None:
        box = QCheckBox(label)
        box.setToolTip(label)
        box.setAccessibleName(label)
        box.setMinimumHeight(24)
        box.setStyleSheet(
            "QCheckBox { font-size: 10px; spacing: 5px; }"
            f"QCheckBox::indicator {{ width: 6px; height: 6px; border: 1px solid {color}; border-radius: 3px; }}"
            f"QCheckBox::indicator:checked {{ background: {color}; }}"
        )
        box.setChecked(self.shown(key))
        box.toggled.connect(lambda on, key=key: self._toggled(key, on))
        self._boxes[key] = box

    def minimumSizeHint(self) -> QSize:
        return QSize(0, 24)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._reflow()

    def _reflow(self) -> None:
        while self._row.count():
            self._row.takeAt(0)
        for column in range(self._used_columns + 1):
            self._row.setColumnStretch(column, 0)
        row, col, used, maximum = 0, 0, 0, 0
        for box in self._boxes.values():
            box.ensurePolished()
            label = box.fontMetrics().elidedText(
                box.accessibleName(), Qt.TextElideMode.ElideRight, max(0, self.width() - 24)
            )
            box.setText(label.replace("&", "&&"))
            box.setMaximumWidth(max(24, self.width()))
            width = box.sizeHint().width() + t.SP_LG
            if col and used + width > self.width():
                row, col, used = row + 1, 0, 0
            self._row.addWidget(box, row, col, Qt.AlignmentFlag.AlignLeft)
            col, used = col + 1, used + width
            maximum = max(maximum, col)
        self._used_columns = maximum
        self._row.setColumnStretch(maximum, 1)
        self.setMinimumHeight((row + 1) * 24 + row * t.SP_XS)

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
        self.fill_first_series = False
        self._areas: list[QAreaSeries] = []
        # Keep Python wrappers alive: QAreaSeries does not retain them reliably in PySide6.
        self._area_bounds: list[tuple[QLineSeries, QLineSeries]] = []
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
        for area in self._areas:
            fill = QColor(line_color(self._drawn[0][1]))
            fill.setAlphaF(0.12)
            area.setBrush(QBrush(fill))
            area.setPen(QPen(Qt.PenStyle.NoPen))
        self.viewport().update()

    def _clear_series(self) -> None:
        for area in self._areas:
            self.chart().removeSeries(area)
            area.deleteLater()
        self._areas = []
        self._area_bounds = []
        for series, _, _ in self._drawn:
            self.chart().removeSeries(series)
            series.deleteLater()
        self._drawn = []

    def _add_series(
        self, points: Sequence[tuple[float, float]], color: int | None, dashed: bool = False,
    ) -> QLineSeries:
        series = QLineSeries()
        series.append([QPointF(x, y) for x, y in points])
        series.setPointsVisible(not dashed and len(points) <= MARKER_LIMIT)
        if self.fill_first_series and not self._drawn and points and not dashed:
            upper = QLineSeries()
            upper.append([QPointF(x, y) for x, y in points])
            lower = QLineSeries()
            lower.append([QPointF(x, 0) for x, _ in points])
            area = QAreaSeries(upper, lower)
            self.chart().addSeries(area)
            area.attachAxis(self._x)
            area.attachAxis(self._y)
            self._areas.append(area)
            self._area_bounds.append((upper, lower))
        self.chart().addSeries(series)
        series.attachAxis(self._x)
        series.attachAxis(self._y)
        self._drawn.append((series, color, dashed))
        return series

    def _fit_y(self, peak: float, minimum: float, decimals: int) -> None:
        target = max(minimum, peak * 1.2)
        raw_step = target / 3
        magnitude = 10 ** math.floor(math.log10(raw_step))
        step = next(factor * magnitude for factor in (1, 2, 5, 10) if factor * magnitude >= raw_step)
        self._y.setRange(0, 3 * step)
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
        font = QFont(t.FONT_FAMILY)
        font.setPixelSize(t.FONT_CAPTION)
        painter.setFont(font)
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
    """One series of the live chart: `times` are epoch seconds. `color` is a slot; None is the overall.

    `forecast` is predicted (epoch seconds, watts) after the last reading, drawn dashed to the right of now.
    """

    name: str
    times: Sequence[float]
    watts: Sequence[float]
    color: int | None = None
    estimates: Sequence[tuple[float, float]] = ()
    forecast: Sequence[tuple[float, float]] = ()


class LiveChart(BaseChart):
    """Watt lines (one per plug, plus the overall) over the last `max_samples` x SAMPLE_SECONDS.

    A forecast extends the view to the right of now. Drag, the wheel or the arrow keys move the window back
    through the data held; double-click or End returns to now.
    """

    FORECAST_TOLERANCE = 1.5  # slots: forecast points are spaced further apart than readings
    view_changed = Signal()  # the window moved or the data changed

    def __init__(self, max_samples: int):
        super().__init__("W")
        self._x.setRange(0, max_samples)
        self._max = max_samples
        self._names: list[str] = []
        self._colors: list[int | None] = []
        self._points: list[list[tuple[float, float]]] = []  # per line: (slot, watts); max_samples is the view's end
        self._all: list[list[tuple[float, float]]] = []  # the same plus forecast points
        self._lines: list[QLineSeries] = []
        self._bridges: list[QLineSeries] = []
        self._span = max_samples * SAMPLE_SECONDS
        self._gap_slots = GAP_SLOTS
        self._input: Sequence[Line] = ()
        self._now = time.time()
        self._ahead = 0.0  # seconds of forecast after now
        self._oldest: float | None = None
        self._view_end = self._now
        self._view_end_held: float | None = None  # None: follow now; else the pinned end of a panned view
        self._drag: tuple[float, float] | None = None  # press x, view end at press
        self._y.setLabelFormat("%.0f")
        self._empty_text = "No readings yet. They appear here as the plugs answer."
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
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
        span = span or self._max * SAMPLE_SECONDS
        if span != self._span:  # a new range starts at now again
            self._view_end_held = None
        self._span = span
        self._gap_slots = GAP_SLOTS * interval / self._span * self._max
        self._now = time.time()
        self._input = list(lines)
        self._ahead = max((ts for line in lines for ts, _ in line.forecast), default=self._now) - self._now
        self._oldest = min((line.times[0] for line in lines if len(line.times)), default=None)
        self.chart().setTitle(title)
        self._rebuild()

    def _live_end(self) -> float:
        return self._now + self._ahead

    def _earliest_end(self) -> float:
        """The furthest back the view may end: its start stays on data."""
        if self._oldest is None:
            return self._live_end()
        return min(self._live_end(), self._oldest + self._span)

    def can_pan(self) -> bool:
        return self._earliest_end() < self._live_end()

    def pan_to(self, view_end: float | None) -> None:
        """Pin the view's end (epoch seconds), or None to follow now."""
        if view_end is not None:
            view_end = max(self._earliest_end(), min(view_end, self._live_end()))
            if view_end >= self._live_end():
                view_end = None
        if view_end != self._view_end_held:
            self._view_end_held = view_end
            self._rebuild()

    def _rebuild(self) -> None:
        held = self._view_end_held
        if held is not None:
            held = max(self._earliest_end(), min(held, self._live_end()))
        self._view_end = self._live_end() if held is None or held >= self._live_end() else held
        self._view_end_held = None if self._view_end >= self._live_end() else self._view_end
        self._hover = None
        self._clear_series()
        self._lines, self._bridges = [], []
        self._names = [line.name for line in self._input]
        self._colors = [line.color for line in self._input]
        self._points, self._all = [], []
        for line in self._input:
            points = [(self._slot(t), w) for t, w in zip(line.times, line.watts, strict=True)]
            ahead = [(self._slot(t), w) for t, w in line.forecast]
            anchor = points[-1:]  # the dashed forecast continues from the last reading
            points = [p for p in points if 0 <= p[0] <= self._max]
            ahead = [p for p in ahead if 0 <= p[0] <= self._max]
            self._points.append(points)
            self._all.append(points + ahead)
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
            if ahead:
                self._bridges.append(self._add_series([*anchor, *ahead], line.color, dashed=True))
        peak = max((w for points in self._all for _, w in points), default=0)
        self._fit_y(peak, 10.0, 1 if peak < 10 else 0)
        self._apply_theme()
        pairs = zip(self._names, self._points, strict=True)
        latest = [f"{name} {points[-1][1]:.1f} W" for name, points in pairs if points]
        self._describe("Latest: " + ", ".join(latest) if latest else "No readings yet")
        self.viewport().setCursor(Qt.CursorShape.OpenHandCursor if self.can_pan() else Qt.CursorShape.ArrowCursor)
        self.viewport().update()
        self.view_changed.emit()

    def _has_points(self) -> bool:
        return any(self._points)

    def _slot(self, ts: float) -> float:
        return self._max - (self._view_end - ts) / self._span * self._max

    def _when(self, ts: float) -> str:
        """A time as a distance from now: "Now", "10 min ago" or "in 15 min"."""
        delta = self._now - ts
        if abs(delta) < self._span * 0.02:
            return "Now"
        delta = round(delta / 60) * 60 or delta  # whole minutes: the view's edges are not on round times
        return ago_label(delta) if delta > 0 else "in " + ago_label(-delta).removesuffix(" ago")

    def _label_row(self) -> Sequence[tuple[float, str]]:
        return [(i / 5, self._when(self._view_end - self._span * (1 - i / 5))) for i in range(6)]

    def _tolerance(self, slot: float) -> float:
        return self.FORECAST_TOLERANCE if slot > self._slot(self._now) else self._gap_slots

    def _hover_at(self, x: float) -> float | None:
        """Slot of the point (reading or forecast) nearest the cursor, over all lines."""
        area = self._plot_area()
        slots = [s for points in self._all for s, _ in points]
        if not slots or not area.left() <= x <= area.right():
            return None
        slot = (x - area.left()) / area.width() * self._max
        nearest = min(slots, key=lambda s: abs(s - slot))
        return nearest if abs(nearest - slot) <= self._tolerance(nearest) else None

    def _rows_at(self, slot: float) -> list[tuple[int, float, float]]:
        """(line index, slot, watts) of each line's point near `slot`."""
        rows = []
        for i, points in enumerate(self._all):
            if points:
                near = min(points, key=lambda p: abs(p[0] - slot))
                if abs(near[0] - slot) <= self._tolerance(near[0]):
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
        ts = self._view_end - (self._max - self._hover) / self._max * self._span
        away = round(self._now - ts)
        if away < -SAMPLE_SECONDS:
            heading = "in " + age_text(-away).removesuffix(" ago") + "  ·  forecast"
        else:
            heading = age_text(max(away, 0))
        return area.left() + self._hover / self._max * area.width(), heading, dots, entries

    def _color_of(self, index: int) -> str:
        return line_color(self._colors[index])

    def drawForeground(self, painter: QPainter, rect: QRectF) -> None:
        area = self._plot_area()
        now_slot = self._slot(self._now)
        painter.save()
        font = QFont(t.FONT_FAMILY)
        font.setPixelSize(t.FONT_CAPTION)
        painter.setFont(font)
        painter.setPen(QPen(QColor(theme().colors.muted), 1, Qt.PenStyle.DashLine))
        if self._ahead and 0 <= now_slot <= self._max:  # where the readings end and the forecast begins
            x = area.left() + now_slot / self._max * area.width()
            painter.drawLine(QPointF(x, area.top()), QPointF(x, area.bottom()))
            painter.drawText(QRectF(x + 6, area.top(), 90, 16), LEFT | Qt.AlignmentFlag.AlignVCenter, "Forecast")
        if self._view_end_held is not None:
            painter.drawText(
                QRectF(area.left() + 6, area.top(), 260, 16), LEFT | Qt.AlignmentFlag.AlignVCenter,
                "Earlier data · double-click for now",
            )
        painter.restore()
        super().drawForeground(painter, rect)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self.can_pan():
            self._drag = (event.position().x(), self._view_end)
            self.viewport().setCursor(Qt.CursorShape.ClosedHandCursor)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._drag is not None:
            origin, end = self._drag
            self.pan_to(end - (event.position().x() - origin) / self._plot_area().width() * self._span)
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if self._drag is not None:
            self._drag = None
            self.viewport().setCursor(Qt.CursorShape.OpenHandCursor)
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:
        self.pan_to(None)
        super().mouseDoubleClickEvent(event)

    def wheelEvent(self, event) -> None:
        delta = event.angleDelta()
        steps = delta.x() or delta.y()
        if self.can_pan() and steps:
            self.pan_to(self._view_end - steps / 120 * self._span * 0.1)
            event.accept()
        else:
            super().wheelEvent(event)

    def keyPressEvent(self, event) -> None:
        moves = {Qt.Key.Key_Left: -0.25, Qt.Key.Key_Right: 0.25, Qt.Key.Key_PageUp: -0.9, Qt.Key.Key_PageDown: 0.9}
        if event.key() == Qt.Key.Key_End:
            self.pan_to(None)
        elif event.key() == Qt.Key.Key_Home:
            self.pan_to(self._earliest_end())
        elif event.key() in moves and self.can_pan():
            self.pan_to(self._view_end + moves[event.key()] * self._span)
        else:
            super().keyPressEvent(event)


@dataclass
class UsageLine:
    """One plug's Wh per key, None where the plug has no point. `color` is the plug's color slot."""

    name: str
    color: int | None
    wh: Sequence[int | None]


class UsageChart(BaseChart):
    """kWh per day, month or hour as stacked bars: each plug is one segment, so the whole bar is the overall.

    Only a window of bars is shown; drag, the wheel or the arrow keys move it through the past and the forecast.
    Keys from `forecast_from` on are predicted and drawn lighter with a dashed outline.
    """

    TITLES = {"day": "Daily usage", "month": "Monthly usage", "hour": "Usage today by hour"}
    WINDOW = {"day": 30, "month": 12, "hour": 24}  # bars in view
    BAR_MAX = 28  # thin marks: bars never grow wider than this, however few there are
    SEGMENT_GAP = 2  # surface-colored gap between stacked segments
    view_changed = Signal()  # the window moved or the data changed

    def __init__(self):
        super().__init__("kWh")
        self._keys: list = []  # a date, or an hour number for the hourly view
        self._kind = "day"
        self._lines: list[UsageLine] = []
        self._forecast_from = 0
        self._start = 0
        self._drag: tuple[float, int] | None = None  # press x, window start at press
        self._empty_text = "No usage recorded yet."
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.show_lines([], [], "day")

    def _label(self, key, tooltip: bool = False) -> str:
        if self._kind == "hour":
            return f"{key:02d}:00"
        if self._kind == "month":
            return key.strftime("%B %Y" if tooltip else "%b %Y")
        return key.strftime("%a %d %b" if tooltip else "%d %b")

    def _totals(self) -> list[int]:
        return [sum(line.wh[index] or 0 for line in self._lines) for index in range(len(self._keys))]

    def window_size(self) -> int:
        return min(self.WINDOW[self._kind], len(self._keys))

    def max_start(self) -> int:
        return max(0, len(self._keys) - self.WINDOW[self._kind])

    def start(self) -> int:
        return self._start

    def set_start(self, start: int) -> None:
        start = max(0, min(start, self.max_start()))
        if start != self._start:
            self._start, self._hover = start, None
            self._after_move()

    def _after_move(self) -> None:
        self._x.setRange(-0.5, max(self.window_size(), 1) - 0.5)
        if self._drag is None:
            self.viewport().setCursor(
                Qt.CursorShape.OpenHandCursor if self.max_start() else Qt.CursorShape.ArrowCursor
            )
        self.viewport().update()
        self.view_changed.emit()

    def show_lines(
        self, lines: Sequence[UsageLine], keys: Sequence, kind: str = "day", forecast_from: int | None = None,
    ) -> None:
        """`kind` is "day" / "month" (keys are dates) or "hour" (keys are hours); each line has a value per key."""
        followed = kind != self._kind or self._start >= self.max_start()  # a view parked at the end stays there
        self._lines, self._keys, self._kind, self._hover = list(lines), list(keys), kind, None
        self._forecast_from = len(self._keys) if forecast_from is None else forecast_from
        self._start = self.max_start() if followed else min(self._start, self.max_start())
        self.chart().setTitle(self.TITLES[kind])
        self._clear_series()
        peak = max(self._totals(), default=0) / 1000
        self._fit_y(peak, 0.1, 2 if peak < 10 else 0)
        self._apply_theme()
        real = self._forecast_from
        if real and self._lines:
            last = [f"{line.name} {(line.wh[real - 1] or 0) / 1000:.2f} kWh" for line in self._lines]
            text = f"Latest: {', '.join(last)}; total {self._totals()[real - 1] / 1000:.2f} kWh"
            if real < len(self._keys):
                text += f"; forecast for the next {len(self._keys) - real} bars"
            self._describe(text)
        else:
            self._describe("No usage recorded yet")
        self._after_move()

    def _has_points(self) -> bool:
        return bool(self._keys) and bool(self._lines)

    def _label_row(self) -> Sequence[tuple[float, str]]:
        """Sparse labels so a window of bars stays readable at small widths."""
        count = self.window_size()
        if not count:
            return ()
        ticks = min(count, max(2, int(self._plot_area().width() / 100)))
        indices = sorted({round(i * (count - 1) / max(1, ticks - 1)) for i in range(ticks)})
        return [((index + 0.5) / count, self._label(self._keys[self._start + index])) for index in indices]

    def drawForeground(self, painter: QPainter, rect: QRectF) -> None:
        self._paint_bars(painter)
        super().drawForeground(painter, rect)

    def _paint_bars(self, painter: QPainter) -> None:
        area = self._plot_area()
        count = self.window_size()
        if not count or not self._lines:
            return
        scale = area.height() / (self._y.max() or 1)
        slot = area.width() / count
        width = max(2.0, min(float(self.BAR_MAX), slot * 0.7))
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        if self._hover is not None:  # a soft band behind the hovered bar instead of fading the others
            band = QColor(theme().colors.text)
            band.setAlphaF(0.07)
            painter.setBrush(band)
            painter.drawRoundedRect(
                QRectF(area.left() + (self._hover - self._start) * slot, area.top(), slot, area.height()),
                t.RADIUS_SM, t.RADIUS_SM,
            )
        for position in range(count):
            index = self._start + position
            predicted = index >= self._forecast_from
            left = area.left() + (position + 0.5) * slot - width / 2
            floor = area.bottom()
            segments = [(line, line.wh[index] / 1000) for line in self._lines if (line.wh[index] or 0) > 0]
            for n, (line, kwh) in enumerate(segments):
                top = floor - kwh * scale
                bar = QRectF(left, top, width, floor - top - (self.SEGMENT_GAP if n else 0))
                floor = top
                if bar.height() < 1:
                    continue
                color = QColor(line_color(line.color))
                if predicted:  # lighter fill and a dashed edge: the forecast differs by more than color
                    fill = QColor(color)
                    fill.setAlphaF(0.28)
                    painter.setBrush(fill)
                    painter.setPen(QPen(color, 1, Qt.PenStyle.DashLine))
                    bar = bar.adjusted(0.5, 0.5, -0.5, -0.5)
                else:
                    painter.setBrush(color)
                    painter.setPen(Qt.PenStyle.NoPen)
                if n == len(segments) - 1:  # only the end of the whole stack is rounded
                    radius = min(4.0, bar.height() / 2, width / 2)
                    rounded = QPainterPath()
                    rounded.addRoundedRect(bar, radius, radius)
                    square = QPainterPath()  # odd-even filling would punch a hole where the two overlap
                    square.addRect(QRectF(bar.left(), bar.center().y(), bar.width(), bar.height() / 2))
                    painter.drawPath(rounded.united(square))
                else:
                    painter.drawRect(bar)
        painter.restore()

    def _hover_at(self, x: float) -> int | None:
        area = self._plot_area()
        if not self._keys or not area.left() <= x <= area.right():
            return None
        count = self.window_size()
        return self._start + min(count - 1, int((x - area.left()) / area.width() * count))

    def _readout(self, area: QRectF):
        x = area.left() + (self._hover - self._start + 0.5) * area.width() / self.window_size()
        entries = [
            (line_color(line.color), f"{line.name}  {line.wh[self._hover] / 1000:.2f} kWh")
            for line in self._lines if line.wh[self._hover] is not None
        ]
        if not entries:
            return None
        if len(entries) > 1:
            entries.append((theme().colors.text, f"Total  {self._totals()[self._hover] / 1000:.2f} kWh"))
        heading = self._label(self._keys[self._hover], tooltip=True)
        if self._hover >= self._forecast_from:
            heading += "  ·  forecast"
        return x, heading, [], entries

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self.max_start():
            self._drag = (event.position().x(), self._start)
            self.viewport().setCursor(Qt.CursorShape.ClosedHandCursor)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._drag is not None:
            origin, start = self._drag
            slot = self._plot_area().width() / max(self.window_size(), 1)
            self.set_start(start - round((event.position().x() - origin) / slot))
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if self._drag is not None:
            self._drag = None
            self._after_move()
        super().mouseReleaseEvent(event)

    def wheelEvent(self, event) -> None:
        delta = event.angleDelta()
        steps = delta.x() or delta.y()
        if self.max_start() and steps:
            self.set_start(self._start - round(steps / 120) * 3)
            event.accept()
        else:
            super().wheelEvent(event)

    def keyPressEvent(self, event) -> None:
        page = self.window_size()
        moves = {Qt.Key.Key_Left: -1, Qt.Key.Key_Right: 1, Qt.Key.Key_PageUp: -page, Qt.Key.Key_PageDown: page,
                 Qt.Key.Key_Home: -len(self._keys), Qt.Key.Key_End: len(self._keys)}
        if event.key() in moves and self.max_start():
            self.set_start(self._start + moves[event.key()])
        else:
            super().keyPressEvent(event)
