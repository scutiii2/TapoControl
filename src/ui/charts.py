"""Chart widgets: rolling live watts and daily kWh bars."""
from collections import deque
from datetime import date

from PySide6.QtCharts import QBarCategoryAxis, QBarSeries, QBarSet, QChart, QChartView, QLineSeries, QValueAxis
from PySide6.QtCore import QMargins, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen

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
        chart.setMargins(QMargins(8, 4, 16, 4))
        self.setMinimumHeight(200)
        self._series = QLineSeries()
        chart.addSeries(self._series)
        x = QValueAxis()
        x.setRange(0, max_samples)
        x.setLabelsVisible(False)
        self._y = QValueAxis()
        self._y.setTitleText("W")
        chart.addAxis(x, BOTTOM)
        chart.addAxis(self._y, LEFT)
        self._series.attachAxis(x)
        self._series.attachAxis(self._y)
        self._y.setTickCount(4)
        self._y.setLabelFormat("%.0f")
        x.setGridLineVisible(False)
        x.setTitleText("Last 10 minutes · updated every 5 seconds")
        theme().changed.connect(self._apply_theme)
        self._apply_theme()

    def _apply_theme(self) -> None:
        style_chart(self)
        self._series.setPen(QPen(QColor(theme().colors.accent), 2.5))

    def show_samples(self, samples: deque[float] | None, title: str) -> None:
        samples = samples or ()
        self.chart().setTitle(title)
        self._series.replace([QPointF(i, w) for i, w in enumerate(samples)])
        self._y.setRange(0, max(10.0, max(samples, default=0) * 1.2))
        self._y.applyNiceNumbers()
        self._y.setLabelFormat("%.1f" if max(samples, default=0) < 10 else "%.0f")


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
        self._bars = QBarSet("kWh")
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

    def _apply_theme(self) -> None:
        style_chart(self)
        self._bars.setColor(QColor(theme().colors.accent))
        self._bars.setBorderColor(QColor(theme().colors.accent))
        self.viewport().update()

    def show_rows(self, rows: list[tuple[date, int]]) -> None:
        self._rows = list(rows)
        if self._bars.count():
            self._bars.remove(0, self._bars.count())
        self._x.clear()
        if rows:
            self._bars.append([wh / 1000 for _, wh in rows])
            self._x.append([d.isoformat() for d, _ in rows])
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
            label = self._rows[index][0].strftime("%d %b")
            painter.drawText(QRectF(x - 36, area.bottom() + 8, 72, 22), Qt.AlignmentFlag.AlignCenter, label)
        painter.restore()
