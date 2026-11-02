"""Embedded Energy tab: totals, tariff and usage history, one line per plug plus the overall."""
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
from ui.charts import OVERALL, LineColors, LineToggles, UsageChart, UsageLine
from ui.theme import energy_error, theme


RANGES = ("Today by hour", "This quarter", "Last 12 months", "All time")
HOURLY, QUARTER, YEAR, ALL = range(4)


def fmt_minutes(minutes: int) -> str:
    return f"{minutes // 60} h {minutes % 60:02d} m"


class HistoryPanel(QWidget):
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

        self._price = QDoubleSpinBox(decimals=4, maximum=1000, value=store.price_per_kwh())
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
        self._toggles = LineToggles(colors)
        self._toggles.changed.connect(self._render_history)
        self._chart = UsageChart()
        self._empty = QLabel()
        self._empty.setWordWrap(True)
        self._empty.setProperty("tone", "muted")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 20, 0, 8)
        layout.setSpacing(16)
        layout.addLayout(header)
        layout.addLayout(totals)
        layout.addWidget(self._usage)
        layout.addWidget(self._summary_error)
        layout.addWidget(self._toggles)
        layout.addWidget(self._chart, 1)
        layout.addWidget(self._history_error)
        layout.addWidget(self._empty)
        note = QLabel("Cost uses your saved tariff. Totals add up every plug.")
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
        """Invalidate in-flight results, e.g. when the account or the set of plugs changes."""
        self._revision += 1
        self._names = {}
        self._controller = None
        self._summaries, self._usages, self._rows, self._hours = {}, {}, {}, {}
        self._name.setText("Energy")
        self._detail.setText("Scan for plugs in Devices to see their energy.")
        self._today.setText("—")
        self._month.setText("—")
        self._today_cost.setText("Estimated cost —")
        self._month_cost.setText("Estimated cost —")
        self._shown = ([], "day")
        self._loading_older = set()
        self._export.setEnabled(False)
        self._runtime.setText("—")
        self._runtime_month.setText("This month —")
        self._usage.setText("")
        self._toggles.set_plugs([])
        self._chart.show_lines([], [])
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
        self._render_history()
        return False

    def load(self, controller: TapoController, names: dict[str, str]) -> None:
        self.clear()
        self._controller = controller
        self._names = dict(names)
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
        sums = list(self._summaries.values())
        if sums:
            today, month = sum(x.today_wh for x in sums), sum(x.month_wh for x in sums)
            self._today.setText(f"{today / 1000:.2f} kWh")
            self._month.setText(f"{month / 1000:.2f} kWh")
            self._today_cost.setText(f"Estimated cost {self._cost(today)}")
            self._month_cost.setText(f"Estimated cost {self._cost(month)}")
            self._runtime.setText(fmt_minutes(sum(x.today_minutes for x in sums)))
            self._runtime_month.setText(f"This month {fmt_minutes(sum(x.month_minutes for x in sums))}")

    def _on_usage(self, ip: str, usage: UsageSummary | None, error: BaseException | None) -> None:
        if error:  # secondary info: stay quiet unless the login is bad
            if isinstance(error, AuthError):
                self.auth_failed.emit(error)
            return
        self._usages[ip] = usage
        usages = list(self._usages.values())
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

    def _export_csv(self) -> None:
        rows, kind = self._shown
        name = f"Energy - {RANGES[self._range.currentIndex()]}.csv"
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
        per_plug = {ip: dict(self._plug_rows(ip)) for ip in self._names}
        keys = sorted({key for rows in per_plug.values() for key in rows})
        overall = [sum(rows.get(key, 0) for rows in per_plug.values()) for key in keys]
        self._toggles.set_plugs(list(self._names.items()))
        lines = []
        if self._toggles.shown(OVERALL):  # the overall always sums every plug, shown or not
            lines.append(UsageLine("Overall", None, overall))
        for ip, rows in per_plug.items():
            if self._toggles.shown(ip):
                first = min(rows, default=None)  # no point before the plug's first day; a missing day after it is 0
                wh = [rows.get(key, 0) if first is not None and key >= first else None for key in keys]
                lines.append(UsageLine(self._names[ip], self._colors(ip), wh))
        kind = {HOURLY: "hour", QUARTER: "day"}.get(choice, "month")
        self._shown = (list(zip(keys, overall, strict=True)), kind)
        self._export.setEnabled(bool(keys))
        self._chart.show_lines(lines, keys, kind)
        self._empty.setText("No energy data is available yet.")
        self._empty.setVisible(not keys and not self._history_error.isVisible())

    def _show_error(self, label: QLabel, error: BaseException) -> None:
        label.setText(energy_error(error))
        label.setToolTip(str(error))
        label.show()
        if isinstance(error, AuthError):
            self.auth_failed.emit(error)
