"""Embedded Energy tab: totals, tariff and usage history, one line per plug plus the overall."""
import asyncio
from datetime import date, timedelta

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QCursor, QGuiApplication
from PySide6.QtWidgets import (
    QBoxLayout,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QScrollBar,
    QToolTip,
)

from core.async_runner import AsyncRunner
from core.export import history_csv
from core.forecast import forecast_days, forecast_months
from core.controller import AuthError, EnergySummary, TapoController, UsageSummary, monthly_totals, quarter_start
from core.store import Store
from ui.charts import LineColors, LineToggles, UsageChart, UsageLine
from ui import tokens as t
from ui.theme import energy_error, theme
from ui.widgets import cost_line, metric_card
from ui.split_button import SplitButton
from ui.page_layout import ChoiceBox, ControlPage, DecimalBox, panel, text_label
from ui.usage_breakdown import UsageBreakdown


RANGES = ("Today by hour", "This quarter", "Last 12 months", "All time")
HOURLY, QUARTER, YEAR, ALL = range(4)


def fmt_minutes(minutes: int) -> str:
    return f"{minutes // 60} h {minutes % 60:02d} m"


class HistoryPanel(ControlPage):
    auth_failed = Signal(object)

    def __init__(self, parent, store: Store, runner: AsyncRunner, colors: LineColors):
        super().__init__(parent)
        theme()
        self._store = store
        self._runner = runner
        self._colors = colors
        self._revision = 0
        self._names: dict[str, str] = {}  # ip -> plug name, for the plugs being shown
        self._controller: TapoController | None = None
        self._summaries: dict[str, EnergySummary] = {}
        self._usages: dict[str, UsageSummary] = {}
        self._rows: dict[str, list[tuple[date, int]]] = {}
        self._hours: dict[str, list[int]] = {}
        self._shown: tuple[list, str] = ([], "day")
        self._loading_older: set[str] = set()
        self._exporting = False

        self._price = DecimalBox(decimals=4, maximum=1000, value=store.price_per_kwh())
        self._price.setSpecialValueText("Unset")
        self._price.setMinimumWidth(140)
        self._price.setAccessibleName("Tariff per kWh")
        self._price.valueChanged.connect(self._on_price)
        self._name = QLabel("Energy")
        self._name.setTextFormat(Qt.TextFormat.PlainText)
        self._name.setProperty("role", "heading")
        self._name.setWordWrap(True)
        self._detail = QLabel("Scan for plugs in Devices to see their energy.")
        self._detail.setProperty("tone", "muted")
        self._detail.setWordWrap(True)
        header = QHBoxLayout()
        self._device_filter = ChoiceBox()
        self._device_filter.addItem("All plugs", None)
        self._device_filter.setAccessibleName("Energy device filter")
        self._device_filter.setMaximumWidth(280)
        self._device_filter.currentIndexChanged.connect(self._filter_changed)
        header.addWidget(self._device_filter, 1)
        self._range = ChoiceBox()
        self._range.setMaximumWidth(240)
        self._range.addItems(RANGES)
        self._range.setAccessibleName("History range")
        self._range.setCurrentIndex(QUARTER)
        self._range.currentIndexChanged.connect(self._range_changed)
        header.addWidget(self._range, 1)
        header.addStretch()
        split = self._split = SplitButton("Export CSV…")
        self._export = split.main
        self._export.clicked.connect(self._export_csv)
        split.add_action("Copy CSV to clipboard", self._copy_csv)
        header.addWidget(split)
        totals = QHBoxLayout()
        self._today, self._today_cost = metric_card(totals, "Today", "Since midnight")
        self._month, self._month_cost = metric_card(totals, "This month", "Month to date")
        self._runtime, self._runtime_month = metric_card(totals, "On today", "Combined runtime across plugs")
        for index in range(totals.count()):
            totals.itemAt(index).widget().setMinimumHeight(108)
        self._usage = QLabel()
        self._usage.setProperty("tone", "muted")
        self._usage.setWordWrap(True)
        self._summary_error = self._error_label()
        self._history_error = self._error_label()
        self._toggles = LineToggles(colors, include_overall=False)  # the stack is the overall
        self._toggles.changed.connect(self._render_history)
        self._chart = UsageChart()
        self._pan = QScrollBar(Qt.Orientation.Horizontal)
        self._pan.setAccessibleName("Scroll through usage history")
        self._pan.valueChanged.connect(self._chart.set_start)
        self._chart.view_changed.connect(self._sync_pan)
        self._forecast_note = text_label("", "caption")
        self._forecast_note.hide()
        self._empty = QLabel()
        self._empty.setWordWrap(True)
        self._empty.setProperty("tone", "muted")
        layout = self.content
        layout.setSpacing(t.SP_LG)
        layout.addLayout(header)
        layout.addLayout(totals)
        self._coverage = text_label("Waiting for energy readings", "caption")
        status = QHBoxLayout()
        status.addWidget(self._detail, 1)
        status.addWidget(self._coverage)
        layout.addLayout(status)
        layout.addWidget(self._summary_error)
        chart_panel, chart = panel("Usage history")
        chart.addWidget(self._toggles)
        self._chart.setMinimumHeight(220)
        self._chart.setMaximumHeight(260)
        chart.addWidget(self._chart)
        chart.addWidget(self._pan)
        chart.addWidget(self._forecast_note)
        chart.addWidget(self._history_error)
        chart.addWidget(self._empty)
        layout.addWidget(chart_panel)
        self._bottom = QBoxLayout(QBoxLayout.Direction.LeftToRight)
        self._bottom.setSpacing(t.SP_LG)
        self._breakdown = UsageBreakdown()
        self._breakdown.setMinimumWidth(0)
        self._breakdown.setMaximumWidth(16777215)
        self._bottom.addWidget(self._breakdown, 1)
        tariff_panel, tariff_layout = panel("Tariff & cost")
        tariff_row = QHBoxLayout()
        tariff = text_label("Rate per kWh")
        tariff.setBuddy(self._price)
        tariff_row.addWidget(tariff, 1)
        tariff_row.addWidget(self._price)
        tariff_layout.addLayout(tariff_row)
        tariff_layout.addWidget(text_label("Set your rate to estimate costs.", "caption"))
        self._cost_today = QLabel("—")
        self._cost_month = QLabel("—")
        for title, value in (("Cost today", self._cost_today), ("This month", self._cost_month)):
            row = QHBoxLayout()
            row.addWidget(text_label(title), 1)
            row.addWidget(value)
            tariff_layout.addLayout(row)
        tariff_layout.addWidget(text_label("Estimates use your saved tariff.", "caption"))
        tariff_layout.addStretch()
        self._bottom.addWidget(tariff_panel, 1)
        layout.addLayout(self._bottom)
        layout.addWidget(self._usage)
        layout.addStretch()
        self.clear()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._bottom.setDirection(
            QBoxLayout.Direction.TopToBottom if self.viewport().width() < 760 else QBoxLayout.Direction.LeftToRight
        )

    def _selected_names(self) -> dict[str, str]:
        ip = self._device_filter.currentData()
        return {ip: self._names[ip]} if ip in self._names else self._names

    def _filter_changed(self) -> None:
        self._render_totals()
        self._render_usage()
        self._render_history()

    def _sync_filter(self) -> None:
        selected = self._device_filter.currentData()
        self._device_filter.blockSignals(True)
        self._device_filter.clear()
        self._device_filter.addItem("All plugs", None)
        for ip, name in self._names.items():
            self._device_filter.addItem(name, ip)
        self._device_filter.setCurrentIndex(max(0, self._device_filter.findData(selected)))
        self._device_filter.blockSignals(False)

    def _error_label(self) -> QLabel:
        label = QLabel()
        label.setProperty("tone", "error")
        label.setTextFormat(Qt.TextFormat.PlainText)
        label.setWordWrap(True)
        label.hide()
        return label

    def clear(self) -> None:
        """Invalidate in-flight results, e.g. when the account or the set of plugs changes."""
        self._revision += 1
        self._names = {}
        self._sync_filter()
        self._controller = None
        self._summaries, self._usages, self._rows, self._hours = {}, {}, {}, {}
        self._name.setText("Energy")
        self._detail.setText("Scan for plugs in Devices to see their energy.")
        self._today.setText("—")
        self._month.setText("—")
        self._today_cost.setText("Since midnight")
        self._month_cost.setText("Month to date")
        self._cost_today.setText("—")
        self._cost_month.setText("—")
        self._coverage.setText("Waiting for energy readings")
        self._breakdown.show_usage({}, {}, self._colors)
        self._shown = ([], "day")
        self._loading_older = set()
        self._export.setEnabled(False)
        self._runtime.setText("—")
        self._runtime_month.setText("This month —")
        self._usage.setText("")
        self._toggles.set_plugs([])
        self._chart.show_lines([], [])
        self._forecast_note.hide()
        self._summary_error.hide()
        self._history_error.hide()
        self._empty.setText("No plugs yet. Scan your network in Devices.")
        self._empty.show()

    def set_names(self, names: dict[str, str]) -> bool:
        """Follow renames without reloading; True when the set of plugs changed and the tab was cleared."""
        if self._controller is None or names == self._names:
            return False
        if names.keys() != self._names.keys():
            self.clear()
            return True
        self._names = dict(names)
        self._sync_filter()
        self._render_totals()
        self._render_usage()
        self._render_history()
        return False

    def load(self, controller: TapoController, names: dict[str, str]) -> None:
        self.clear()
        self._controller = controller
        self._names = dict(names)
        self._sync_filter()
        revision = self._revision
        count = len(names)
        self._name.setText(next(iter(names.values())) if count == 1 else "All plugs")
        self._detail.setText(f"{count} plug{'s' if count != 1 else ''}")
        self._today.setText("Loading…")
        self._month.setText("Loading…")
        self._empty.setText("Loading daily history…")

        def guarded(handler, ip):
            def callback(result, error):
                if revision == self._revision:
                    handler(ip, result, error)

            return callback

        for ip in names:
            self._runner.submit(controller.energy(ip), guarded(self._on_summary, ip))
            self._runner.submit(controller.usage(ip), guarded(self._on_usage, ip))
            # The current quarter shows up first; older quarters are fetched once afterwards.
            self._runner.submit(controller.daily_history(ip), guarded(self._on_history, ip))
        self._render_history()

    def _cost(self, wh: int) -> str:
        return f"{wh / 1000 * self._price.value():.2f}"

    def _render_totals(self) -> None:
        names = self._selected_names()
        sums = [self._summaries[ip] for ip in names if ip in self._summaries]
        self._coverage.setText(
            f"Partial · {len(sums)} of {len(names)} plugs reporting" if len(sums) < len(names)
            else f"{len(sums)} plugs reporting"
        )
        self._breakdown.show_usage(names, {ip: s.today_wh for ip, s in self._summaries.items()}, self._colors)
        if not sums:
            self._today.setText("—")
            self._month.setText("—")
            self._runtime.setText("—")
            self._cost_today.setText("—")
            self._cost_month.setText("—")
            self._today_cost.setText("Waiting for energy readings")
            self._month_cost.setText("Waiting for energy readings")
            self._runtime_month.setText("Combined runtime across plugs")
        if sums:
            today, month = sum(x.today_wh for x in sums), sum(x.month_wh for x in sums)
            self._today.setText(f"{today / 1000:.2f} kWh")
            self._month.setText(f"{month / 1000:.2f} kWh")
            hint = "Set a tariff below for cost"
            self._today_cost.setText(cost_line(today, self._price.value(), hint))
            self._month_cost.setText(cost_line(month, self._price.value(), hint))
            self._cost_today.setText(self._cost(today) if self._price.value() else "—")
            self._cost_month.setText(self._cost(month) if self._price.value() else "—")
            self._runtime.setText(fmt_minutes(sum(x.today_minutes for x in sums)))
            self._runtime_month.setText(f"This month {fmt_minutes(sum(x.month_minutes for x in sums))}")

    def _on_usage(self, ip: str, usage: UsageSummary | None, error: BaseException | None) -> None:
        if error:  # secondary info: stay quiet unless the login is bad
            if isinstance(error, AuthError):
                self.auth_failed.emit(error)
            return
        self._usages[ip] = usage
        self._render_usage()

    def _render_usage(self) -> None:
        usages = [self._usages[ip] for ip in self._selected_names() if ip in self._usages]
        if not usages:
            self._usage.clear()
            return
        self._usage.setText(
            f"Last 7 days: {sum(u.wh_7d for u in usages) / 1000:.2f} kWh · "
            f"on {fmt_minutes(sum(u.minutes_7d for u in usages))}      "
            f"Last 30 days: {sum(u.wh_30d for u in usages) / 1000:.2f} kWh · "
            f"on {fmt_minutes(sum(u.minutes_30d for u in usages))}"
        )

    def _range_changed(self) -> None:
        if self._range.currentIndex() == HOURLY and self._controller:
            revision = self._revision

            def requested(ip):
                def hours(result, error):
                    if revision == self._revision:
                        self._hours[ip] = result or []
                        if error:
                            self._show_error(self._history_error, error)
                        self._render_history()

                return hours

            for ip in self._names:
                self._runner.submit(self._controller.hourly_today(ip), requested(ip))
        self._render_history()

    def _on_price(self, value: float) -> None:
        self._store.set_price_per_kwh(value)
        self._render_totals()

    def _on_summary(self, ip: str, summary: EnergySummary | None, error: BaseException | None) -> None:
        if error:
            if not self._summaries:
                self._today.setText("—")
                self._month.setText("—")
            self._show_error(self._summary_error, error)
            return
        self._summaries[ip] = summary
        self._render_totals()

    def _on_history(self, ip: str, rows: list[tuple[date, int]] | None, error: BaseException | None) -> None:
        self._empty.hide()
        if error:
            self._show_error(self._history_error, error)
        else:
            self._store.save_daily(ip, rows or [])
            if not self._store.backfilled(ip):
                self._backfill(ip)
        # Stored days stay visible even when the plug is unreachable.
        self._rows[ip] = self._store.daily(ip)
        self._set_detail()
        self._render_history()

    def _set_detail(self) -> None:
        """Say how much daily history is on file, so a missing history is visible rather than silent."""
        if self._loading_older or not self._names:
            return
        count = len(self._names)
        plugs = f"{count} plug{'s' if count != 1 else ''}"
        firsts = [rows[0][0] for rows in self._rows.values() if rows]
        if firsts:
            first = min(firsts)
            stored = f"{(date.today() - first).days + 1} days stored since {first:%d %b %Y}"
        else:
            stored = "no daily history stored"
        self._detail.setText(f"{plugs} · {stored}")

    def _copy_csv(self) -> None:
        rows, kind = self._shown
        QGuiApplication.clipboard().setText(history_csv(rows, kind, self._price.value()))
        QToolTip.showText(QCursor.pos(), "Copied to clipboard", self)

    def _export_csv(self) -> None:
        if self._exporting:
            return
        rows, kind = self._shown
        name = f"Energy - {RANGES[self._range.currentIndex()]}.csv"
        path, _ = QFileDialog.getSaveFileName(self, "Export energy history", name, "CSV files (*.csv)")
        if not path:
            return
        price = self._price.value()
        revision = self._revision

        def write() -> None:
            Path(path).write_text(history_csv(rows, kind, price), encoding="utf-8", newline="")

        async def save() -> None:
            await asyncio.to_thread(write)

        def done(_result, error):
            self._exporting = False
            self._export.setText("Export CSV…")
            self._export.setEnabled(bool(self._shown[0]))
            if revision != self._revision:
                return
            if error:
                self._history_error.setText("Could not save the file. Try another location.")
                self._history_error.setToolTip(str(error))
                self._history_error.show()
            else:
                self._history_error.hide()

        self._exporting = True
        self._export.setText("Exporting…")
        self._export.setEnabled(False)
        self._runner.submit(save(), done)

    def _backfill(self, ip: str) -> None:
        """One-off fetch of every older quarter the plug remembers."""
        revision = self._revision
        self._loading_older.add(ip)
        self._detail.setText("Loading older history…")

        def done(rows, error):
            if revision != self._revision:
                return
            self._loading_older.discard(ip)
            if error:
                self._detail.setText("Older history unavailable for a plug")
                self._detail.setToolTip(str(error))
                return
            self._store.save_daily(ip, rows or [])
            self._store.set_backfilled(ip)
            self._rows[ip] = self._store.daily(ip)
            self._set_detail()
            self._render_history()

        self._runner.submit(self._controller.full_history(ip), done)

    def _plug_rows(self, ip: str) -> list[tuple]:
        """The plug's (key, Wh) rows for the chosen range."""
        choice = self._range.currentIndex()
        rows = self._rows.get(ip, [])
        if choice == HOURLY:
            rows = list(enumerate(self._hours.get(ip, [])))
        elif choice == QUARTER:
            rows = [r for r in rows if r[0] >= quarter_start(date.today())]
        elif choice == YEAR:
            rows = [r for r in rows if r[0] >= (date.today().replace(day=1) - timedelta(days=335)).replace(day=1)]
        if choice in (YEAR, ALL):
            rows = monthly_totals(rows)
        return rows

    def _render_history(self) -> None:
        if not self._names:
            return
        choice = self._range.currentIndex()
        names = self._selected_names()
        per_plug = {ip: dict(self._plug_rows(ip)) for ip in names}
        keys = sorted({key for rows in per_plug.values() for key in rows})
        overall = [sum(rows.get(key, 0) for rows in per_plug.values()) for key in keys]
        self._toggles.set_plugs(list(names.items()))
        lines = []
        for ip, rows in per_plug.items():
            if self._toggles.shown(ip):
                first = min(rows, default=None)  # no point before the plug's first day; a missing day after it is 0
                wh = [rows.get(key, 0) if first is not None and key >= first else None for key in keys]
                lines.append(UsageLine(self._names[ip], self._colors(ip), wh))
        kind = {HOURLY: "hour", QUARTER: "day"}.get(choice, "month")
        self._shown = (list(zip(keys, overall, strict=True)), kind)
        self._export.setEnabled(bool(keys) and not self._exporting)
        forecasts = self._forecast(choice, names)
        future = sorted({key for rows in forecasts.values() for key, _ in rows})
        for line, ip in zip(lines, [ip for ip in per_plug if self._toggles.shown(ip)], strict=True):
            predicted = dict(forecasts.get(ip, []))
            line.wh = [*line.wh, *(predicted.get(key) for key in future)]
        self._chart.show_lines(lines, [*keys, *future], kind, len(keys) if future else None)
        self._forecast_note.setText(
            "Lighter dashed bars are a forecast: "
            + ("each weekday's average over the last four weeks." if choice == QUARTER
               else "the average of the last three full months.")
        )
        self._forecast_note.setVisible(bool(future))
        self._empty.setText("No energy data is available yet.")
        self._empty.setVisible(not keys and not self._history_error.isVisible())

    def _sync_pan(self) -> None:
        """Keep the scroll bar on the chart's window; it is hidden when everything fits."""
        chart = self._chart
        self._pan.blockSignals(True)
        self._pan.setRange(0, chart.max_start())
        self._pan.setPageStep(chart.window_size())
        self._pan.setValue(chart.start())
        self._pan.blockSignals(False)
        self._pan.setVisible(chart.max_start() > 0)

    def _forecast(self, choice: int, names: dict[str, str]) -> dict[str, list[tuple[date, int]]]:
        """Each shown plug's predicted days or months, from everything stored (not only the chosen range)."""
        if choice == HOURLY:
            return {}
        forecasts = {}
        for ip in names:
            rows = self._rows.get(ip, [])
            if choice == QUARTER:
                forecasts[ip] = forecast_days(dict(rows), date.today())
            else:
                forecasts[ip] = forecast_months(dict(monthly_totals(rows)), date.today())
        return forecasts

    def _show_error(self, label: QLabel, error: BaseException) -> None:
        label.setText(energy_error(error))
        label.setToolTip(str(error))
        label.show()
        if isinstance(error, AuthError):
            self.auth_failed.emit(error)
