"""Overview tab: the headline numbers across all plugs and today's usage by hour."""
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget

from ui.charts import OVERALL, LineColors, LineToggles, UsageChart, UsageLine
from ui.widgets import metric_card


class OverviewPage(QWidget):
    def __init__(self, colors: LineColors):
        super().__init__()
        self._colors = colors
        self._names: dict[str, str] = {}
        self._hours: dict[str, list[int]] = {}  # ip -> Wh per hour of today
        cards = QHBoxLayout()
        self._now, self._now_cost = metric_card(cards, "NOW", "Cost —")
        self._today, self._today_cost = metric_card(cards, "TODAY", "Estimated cost —")
        self._month, self._month_cost = metric_card(cards, "THIS MONTH", "Estimated cost —")
        self._plugs, self._plugs_online = metric_card(cards, "PLUGS ON", "— online")
        self._toggles = LineToggles(colors)
        self._toggles.changed.connect(self._render_chart)
        self._chart = UsageChart()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 14, 0, 0)
        layout.setSpacing(12)
        layout.addLayout(cards)
        layout.addWidget(self._toggles)
        layout.addWidget(self._chart, 1)

    def set_plugs(self, names: dict[str, str]) -> None:
        """Follow the plug list; forget hours of plugs that are gone."""
        if names == self._names:
            return
        self._names = dict(names)
        self._hours = {ip: hours for ip, hours in self._hours.items() if ip in names}
        self._render_chart()

    def show_live(self, watts: float, on: int, online: int, price: float) -> None:
        self._now.setText(f"{watts:.1f} W")
        self._now_cost.setText(f"Cost {watts / 1000 * price:.2f} / h" if price else "Set a tariff in Energy")
        self._plugs.setText(f"{on} of {len(self._names)}")
        self._plugs_online.setText(f"{online} online")

    def show_energy(self, today_wh: int | None, month_wh: int | None, price: float) -> None:
        for value, cost, wh in ((self._today, self._today_cost, today_wh), (self._month, self._month_cost, month_wh)):
            value.setText("—" if wh is None else f"{wh / 1000:.2f} kWh")
            cost.setText("Estimated cost —" if wh is None else f"Estimated cost {wh / 1000 * price:.2f}")

    def set_hours(self, ip: str, hours: list[int]) -> None:
        if ip in self._names:
            self._hours[ip] = hours
            self._render_chart()

    def _render_chart(self) -> None:
        self._toggles.set_plugs(list(self._names.items()))
        count = max((len(hours) for hours in self._hours.values()), default=0)
        keys = list(range(count))

        def per_hour(hours: list[int]) -> list[int]:
            return [hours[key] if key < len(hours) else 0 for key in keys]

        lines = []
        if self._toggles.shown(OVERALL) and self._hours:  # the overall always sums every plug, shown or not
            columns = [per_hour(hours) for hours in self._hours.values()]
            lines.append(UsageLine("Overall", None, [sum(column[key] for column in columns) for key in keys]))
        for ip, hours in self._hours.items():
            if self._toggles.shown(ip):
                lines.append(UsageLine(self._names[ip], self._colors(ip), per_hour(hours)))
        self._chart.show_lines(lines, keys, "hour")
