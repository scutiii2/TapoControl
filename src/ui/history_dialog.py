"""Embedded Energy tab: totals, tariff and daily history for the selected plug."""
from datetime import date, timedelta

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from core.async_runner import AsyncRunner
from core.export import history_csv
from core.controller import AuthError, EnergySummary, TapoController, UsageSummary, monthly_totals, quarter_start
from core.store import Store
from ui.charts import DailyBars
from ui.theme import energy_error, theme


RANGES = ("Today by hour", "This quarter", "Last 12 months", "All time")
HOURLY, QUARTER, YEAR, ALL = range(4)


def fmt_minutes(minutes: int) -> str:
    return f"{minutes // 60} h {minutes % 60:02d} m"


class HistoryPanel(QWidget):
    auth_failed = Signal(object)

    def __init__(self, parent, store: Store, runner: AsyncRunner):
        super().__init__(parent)
        theme()
        self._store = store
        self._runner = runner
        self._summary: EnergySummary | None = None
        self._revision = 0
        self._ip: str | None = None
        self._controller: TapoController | None = None
        self._rows: list[tuple[date, int]] = []
        self._shown: tuple[list, str] = ([], "day")
        self._loading_older = False

        self._price = QDoubleSpinBox(decimals=4, maximum=1000, value=store.price_per_kwh())
        self._price.setMinimumWidth(140)
        self._price.setAccessibleName("Tariff per kWh")
        self._price.valueChanged.connect(self._on_price)
        self._name = QLabel("Energy")
        self._name.setTextFormat(Qt.TextFormat.PlainText)
        self._name.setProperty("role", "heading")
        self._name.setWordWrap(True)
        self._detail = QLabel("Select a plug from Devices to view its energy.")
        self._detail.setProperty("tone", "muted")
        self._detail.setWordWrap(True)
        names = QVBoxLayout()
        names.addWidget(self._name)
        names.addWidget(self._detail)
        header = QHBoxLayout()
        header.addLayout(names, 1)
        tariff = QLabel("Tariff / kWh")
        tariff.setProperty("tone", "muted")
        tariff.setBuddy(self._price)
        header.addWidget(tariff)
        header.addWidget(self._price)
        self._range = QComboBox()
        self._range.addItems(RANGES)
        self._range.setAccessibleName("History range")
        self._range.setCurrentIndex(QUARTER)
        self._range.currentIndexChanged.connect(self._range_changed)
        header.addWidget(self._range)
        self._export = QPushButton("Export CSV…")
        self._export.clicked.connect(self._export_csv)
        header.addWidget(self._export)
        totals = QHBoxLayout()
        self._today, self._today_cost = self._total_card(totals, "TODAY")
        self._month, self._month_cost = self._total_card(totals, "THIS MONTH")
        self._runtime, self._runtime_month = self._total_card(totals, "ON TODAY")
        self._usage = QLabel()
        self._usage.setProperty("tone", "muted")
        self._usage.setWordWrap(True)
        self._summary_error = self._error_label()
        self._history_error = self._error_label()
        self._bars = DailyBars()
        self._empty = QLabel("Choose a plug in Devices, then open Energy from its menu.")
        self._empty.setWordWrap(True)
        self._empty.setProperty("tone", "muted")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 20, 0, 8)
        layout.setSpacing(16)
        layout.addLayout(header)
        layout.addLayout(totals)
        layout.addWidget(self._usage)
        layout.addWidget(self._summary_error)
        layout.addWidget(self._bars, 1)
        layout.addWidget(self._history_error)
        layout.addWidget(self._empty)
        note = QLabel("Cost uses your saved tariff. Choose another plug from Devices to view its energy.")
        note.setProperty("tone", "muted")
        note.setWordWrap(True)
        layout.addWidget(note)
        self.clear()

    def _total_card(self, row: QHBoxLayout, title: str) -> tuple[QLabel, QLabel]:
        card = QFrame()
        card.setProperty("card", True)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(20, 16, 20, 16)
        heading = QLabel(title)
        heading.setProperty("tone", "muted")
        value = QLabel("—")
        value.setProperty("role", "metric")
        cost = QLabel("Estimated cost —")
        cost.setProperty("tone", "muted")
        for label in (heading, value, cost):
            layout.addWidget(label)
        row.addWidget(card, 1)
        return value, cost

    def _error_label(self) -> QLabel:
        label = QLabel()
        label.setProperty("tone", "error")
        label.setTextFormat(Qt.TextFormat.PlainText)
        label.setWordWrap(True)
        label.hide()
        return label

    def clear(self) -> None:
        """Invalidate in-flight results when the selected device disappears."""
        self._revision += 1
        self._ip = None
        self._controller = None
        self._summary = None
        self._name.setText("Energy")
        self._detail.setText("Select a plug from Devices to view its energy.")
        self._today.setText("—")
        self._month.setText("—")
        self._today_cost.setText("Estimated cost —")
        self._month_cost.setText("Estimated cost —")
        self._rows = []
        self._shown = ([], "day")
        self._loading_older = False
        self._export.setEnabled(False)
        self._hours: list[int] = []
        self._runtime.setText("—")
        self._runtime_month.setText("This month —")
        self._usage.setText("")
        self._bars.show_rows([])
        self._summary_error.hide()
        self._history_error.hide()
        self._empty.setText("Choose a plug in Devices, then open Energy from its menu.")
        self._empty.show()

    def set_name(self, name: str) -> None:
        self._name.setText(name)

    def load(self, controller: TapoController, ip: str, name: str) -> None:
        self.clear()
        self._ip = ip
        self._controller = controller
        revision = self._revision
        self._name.setText(name)
        self._detail.setText(f"{ip} · Selected plug")
        self._today.setText("Loading…")
        self._month.setText("Loading…")
        self._empty.setText("Loading daily history…")

        def summary(result, error):
            if revision == self._revision:
                self._on_summary(result, error)

        def history(result, error):
            if revision == self._revision:
                self._on_history(result, error)

        def usage(result, error):
            if revision == self._revision:
                self._on_usage(result, error)

        self._runner.submit(controller.energy(ip), summary)
        self._runner.submit(controller.usage(ip), usage)
        # The current quarter shows up first; older quarters are fetched once afterwards.
        self._runner.submit(controller.daily_history(ip), history)

    def _cost(self, wh: int) -> str:
        return f"{wh / 1000 * self._price.value():.2f}"

    def _render_totals(self) -> None:
        s = self._summary
        if s:
            self._today.setText(f"{s.today_wh / 1000:.2f} kWh")
            self._month.setText(f"{s.month_wh / 1000:.2f} kWh")
            self._today_cost.setText(f"Estimated cost {self._cost(s.today_wh)}")
            self._month_cost.setText(f"Estimated cost {self._cost(s.month_wh)}")
            self._runtime.setText(fmt_minutes(s.today_minutes))
            self._runtime_month.setText(f"This month {fmt_minutes(s.month_minutes)}")

    def _on_usage(self, usage: UsageSummary | None, error: BaseException | None) -> None:
        if error:  # secondary info: stay quiet unless the login is bad
            if isinstance(error, AuthError):
                self.auth_failed.emit(error)
            return
        self._usage.setText(
            f"Last 7 days: {usage.wh_7d / 1000:.2f} kWh · on {fmt_minutes(usage.minutes_7d)}      "
            f"Last 30 days: {usage.wh_30d / 1000:.2f} kWh · on {fmt_minutes(usage.minutes_30d)}"
        )

    def _range_changed(self) -> None:
        if self._range.currentIndex() == HOURLY and self._controller and self._ip:
            revision = self._revision

            def hours(result, error):
                if revision == self._revision:
                    self._hours = result or []
                    if error:
                        self._show_error(self._history_error, error)
                    self._render_history()

            self._runner.submit(self._controller.hourly_today(self._ip), hours)
        self._render_history()

    def _on_price(self, value: float) -> None:
        self._store.set_price_per_kwh(value)
        self._render_totals()

    def _on_summary(self, summary: EnergySummary | None, error: BaseException | None) -> None:
        if error:
            self._today.setText("—")
            self._month.setText("—")
            self._show_error(self._summary_error, error)
            return
        self._summary = summary
        self._render_totals()

    def _on_history(self, rows: list[tuple[date, int]] | None, error: BaseException | None) -> None:
        self._empty.hide()
        if error:
            self._show_error(self._history_error, error)
        else:
            self._store.save_daily(self._ip, rows or [])
            if not self._store.backfilled(self._ip):
                self._backfill()
        # Stored days stay visible even when the plug is unreachable.
        self._rows = self._store.daily(self._ip)
        self._set_detail()
        self._render_history()

    def _set_detail(self) -> None:
        """Say how much daily history is on file, so a missing history is visible rather than silent."""
        if self._loading_older or self._ip is None:
            return
        first = f"{self._rows[0][0]:%d %b %Y}" if self._rows else ""
        stored = f"{len(self._rows)} days stored since {first}" if self._rows else "no daily history stored"
        self._detail.setText(f"{self._ip} · {stored}")

    def _export_csv(self) -> None:
        rows, kind = self._shown
        name = f"{self._name.text()} - {RANGES[self._range.currentIndex()]}.csv"
        path, _ = QFileDialog.getSaveFileName(self, "Export energy history", name, "CSV files (*.csv)")
        if not path:
            return
        try:
            Path(path).write_text(history_csv(rows, kind, self._price.value()), encoding="utf-8", newline="")
            self._history_error.hide()
        except OSError as error:
            self._history_error.setText("Could not save the file.")
            self._history_error.setToolTip(str(error))
            self._history_error.show()

    def _backfill(self) -> None:
        """One-off fetch of every older quarter the plug remembers."""
        revision, ip = self._revision, self._ip
        self._loading_older = True
        self._detail.setText(f"{ip} · Loading older history…")

        def done(rows, error):
            if revision != self._revision:
                return
            self._loading_older = False
            if error:
                self._detail.setText(f"{ip} · Older history unavailable")
                self._detail.setToolTip(str(error))
                return
            self._store.save_daily(ip, rows or [])
            self._store.set_backfilled(ip)
            self._rows = self._store.daily(ip)
            self._set_detail()
            self._render_history()

        self._runner.submit(self._controller.full_history(ip), done)

    def _render_history(self) -> None:
        if self._ip is None:
            return
        choice = self._range.currentIndex()
        rows = self._rows
        if choice == HOURLY:
            rows = list(enumerate(self._hours))
        elif choice == QUARTER:
            rows = [r for r in rows if r[0] >= quarter_start(date.today())]
        elif choice == YEAR:
            rows = [r for r in rows if r[0] >= (date.today().replace(day=1) - timedelta(days=335)).replace(day=1)]
        if choice in (YEAR, ALL):
            rows = monthly_totals(rows)
        kind = {HOURLY: "hour", QUARTER: "day"}.get(choice, "month")
        self._shown = (rows, kind)
        self._export.setEnabled(bool(rows))
        self._bars.show_rows(rows, kind=kind)
        self._empty.setText("No energy data is available for this plug yet.")
        self._empty.setVisible(not rows and not self._history_error.isVisible())

    def _show_error(self, label: QLabel, error: BaseException) -> None:
        label.setText(energy_error(error))
        label.setToolTip(str(error))
        label.show()
        if isinstance(error, AuthError):
            self.auth_failed.emit(error)
