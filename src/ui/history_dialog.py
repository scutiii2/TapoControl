"""Energy history of one plug: today/month totals, cost estimate, daily kWh bars."""
from datetime import date

from PySide6.QtWidgets import QDialog, QDoubleSpinBox, QFormLayout, QLabel, QVBoxLayout

from core.async_runner import AsyncRunner
from core.controller import EnergySummary, TapoController
from core.store import Store
from ui.charts import DailyBars


class HistoryDialog(QDialog):
    def __init__(self, parent, store: Store, runner: AsyncRunner, controller: TapoController, ip: str, name: str):
        super().__init__(parent)
        self.setWindowTitle(f"Energy - {name}")
        self.resize(640, 420)
        self._store = store
        self._summary: EnergySummary | None = None

        self._price = QDoubleSpinBox(decimals=4, maximum=1000, value=store.price_per_kwh())
        self._price.setPrefix("per kWh: ")
        self._price.valueChanged.connect(self._on_price)
        self._totals = QLabel("Loading...")
        self._bars = DailyBars()
        form = QFormLayout()
        form.addRow("Tariff", self._price)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self._totals)
        layout.addWidget(self._bars)

        runner.submit(controller.energy(ip), self._on_summary)
        runner.submit(controller.daily_history(ip), self._on_history)

    def _cost(self, wh: int) -> str:
        return f"{wh / 1000 * self._price.value():.2f}"

    def _render_totals(self) -> None:
        s = self._summary
        if s:
            self._totals.setText(
                f"Today: {s.today_wh / 1000:.2f} kWh (cost {self._cost(s.today_wh)})    "
                f"Month: {s.month_wh / 1000:.2f} kWh (cost {self._cost(s.month_wh)})"
            )

    def _on_price(self, value: float) -> None:
        self._store.set_price_per_kwh(value)
        self._render_totals()

    def _on_summary(self, summary: EnergySummary | None, error: BaseException | None) -> None:
        if error:
            self._totals.setText(f"Error: {error}")
            return
        self._summary = summary
        self._render_totals()

    def _on_history(self, rows: list[tuple[date, int]] | None, error: BaseException | None) -> None:
        if not error:
            self._bars.show_rows(rows)
