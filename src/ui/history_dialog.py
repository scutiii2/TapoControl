"""Embedded Energy tab: totals, tariff and daily history for the selected plug."""
from datetime import date

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QDoubleSpinBox, QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from core.async_runner import AsyncRunner
from core.controller import AuthError, EnergySummary, TapoController
from core.store import Store
from ui.charts import DailyBars
from ui.theme import energy_error, theme


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
        totals = QHBoxLayout()
        self._today, self._today_cost = self._total_card(totals, "TODAY")
        self._month, self._month_cost = self._total_card(totals, "THIS MONTH")
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

        self._runner.submit(controller.energy(ip), summary)
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
            self._bars.show_rows(rows or [])
            self._empty.setText("No daily energy data is available for this plug yet.")
            self._empty.setVisible(not rows)

    def _show_error(self, label: QLabel, error: BaseException) -> None:
        label.setText(energy_error(error))
        label.setToolTip(str(error))
        label.show()
        if isinstance(error, AuthError):
            self.auth_failed.emit(error)
