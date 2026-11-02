"""Chart widgets: rolling live watts and daily kWh bars."""
from collections import deque
from datetime import date

from PySide6.QtCharts import QBarCategoryAxis, QBarSeries, QBarSet, QChart, QChartView, QLineSeries, QValueAxis
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QPainter

BOTTOM = Qt.AlignmentFlag.AlignBottom
LEFT = Qt.AlignmentFlag.AlignLeft


class LiveChart(QChartView):
    """Last N watt samples of one plug."""

    def __init__(self, max_samples: int):
        super().__init__(QChart())
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        chart = self.chart()
        chart.legend().hide()
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

    def show_samples(self, samples: deque[float] | None, title: str) -> None:
        samples = samples or ()
        self.chart().setTitle(title)
        self._series.replace([QPointF(i, w) for i, w in enumerate(samples)])
        self._y.setRange(0, max(10.0, max(samples, default=0) * 1.2))


class DailyBars(QChartView):
    """kWh per day."""

    def __init__(self):
        super().__init__(QChart())
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.chart().legend().hide()

    def show_rows(self, rows: list[tuple[date, int]]) -> None:
        chart = self.chart()
        chart.removeAllSeries()
        for axis in chart.axes():
            chart.removeAxis(axis)
        bars = QBarSet("kWh")
        bars.append([wh / 1000 for _, wh in rows])
        series = QBarSeries()
        series.append(bars)
        chart.addSeries(series)
        x = QBarCategoryAxis()
        x.append([d.strftime("%d/%m") for d, _ in rows])
        x.setLabelsAngle(-90)
        y = QValueAxis()
        y.setTitleText("kWh")
        y.setRange(0, max((wh for _, wh in rows), default=0) / 1000 * 1.2 or 1)
        chart.addAxis(x, BOTTOM)
        chart.addAxis(y, LEFT)
        series.attachAxis(x)
        series.attachAxis(y)
