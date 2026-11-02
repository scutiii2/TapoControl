"""Approved light dashboard: metrics, live power, usage breakdown and real plug controls."""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QLayout, QPushButton, QScrollArea, QVBoxLayout, QWidget

from ui import tokens as t
from ui.charts import Line, LineColors, LineToggles, LiveChart
from ui.device_grid import DeviceGrid
from ui.usage_breakdown import UsageBreakdown
from ui.widgets import MetricGrid, cost_line, metric_card


class OverviewPage(QScrollArea):
    card_added = Signal(str, object)
    all_power_requested = Signal(bool)

    def __init__(self, colors: LineColors):
        super().__init__()
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._colors = colors
        self._names: dict[str, str] = {}
        self._hours: dict[str, list[int]] = {}
        self._power_lines: list[tuple[str, Line]] = []
        self._power_title = "Live watts"
        self._power_span = None
        self._power_interval = 5
        cards = MetricGrid()
        self._now, self._now_cost = metric_card(cards, "Power right now", highlight=True)
        self._today, self._today_cost = metric_card(cards, "Used today", "Since midnight")
        self._month, self._month_cost = metric_card(cards, "This month", "Month to date")
        self._plugs, self._plugs_online = metric_card(cards, "Plugs online", "No plugs yet")
        self._toggles = LineToggles(colors, include_overall=False)
        self._toggles.changed.connect(self._render_power)
        self._chart = LiveChart(120)
        self._chart.fill_first_series = True
        self._chart.setMinimumHeight(205)
        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        layout.setContentsMargins(0, t.SP_SM, 0, t.SP_XL)
        layout.setSpacing(t.SECTION_GAP)
        layout.addWidget(cards)
        middle = QHBoxLayout()
        middle.setSpacing(t.PANEL_GAP)
        panel = QFrame()
        panel.setProperty("card", True)
        chart = QVBoxLayout(panel)
        chart.setContentsMargins(t.PANEL_X, t.PANEL_Y, t.PANEL_X, t.PANEL_Y)
        chart.setSpacing(t.SP_SM)
        head = QHBoxLayout()
        title = QLabel("Live power")
        title.setProperty("role", "heading")
        self._range = QLabel("Last 10 minutes")
        self._range.setProperty("role", "caption")
        head.addWidget(title, 1)
        head.addWidget(self._range)
        chart.addLayout(head)
        chart.addWidget(self._toggles)
        chart.addWidget(self._chart, 1)
        middle.addWidget(panel, 1)
        self._breakdown = UsageBreakdown()
        middle.addWidget(self._breakdown)
        layout.addLayout(middle)
        toolbar = QHBoxLayout()
        heading = QLabel("Your devices")
        heading.setProperty("role", "heading")
        self._device_count = QLabel("No plugs yet")
        self._device_count.setProperty("role", "caption")
        toolbar.addWidget(heading)
        toolbar.addWidget(self._device_count)
        toolbar.addStretch()
        self._all_on = QPushButton("Turn all on")
        self._all_off = QPushButton("Turn all off")
        for button, on in ((self._all_on, True), (self._all_off, False)):
            button.setProperty("compact", True)
            button.clicked.connect(lambda checked=False, on=on: self.all_power_requested.emit(on))
            toolbar.addWidget(button)
        layout.addLayout(toolbar)
        self._empty = QLabel("No plugs yet. Scan your network to find Tapo P110 plugs.")
        self._empty.setProperty("tone", "muted")
        self._empty.setWordWrap(True)
        layout.addWidget(self._empty)
        self._grid = DeviceGrid()
        self.device_cards = self._grid.cards
        layout.addWidget(self._grid)
        layout.addStretch()
        self.setWidget(body)

    def set_plugs(self, names: dict[str, str]) -> None:
        """Follow the plug list; forget hours of plugs that are gone."""
        if names == self._names:
            return
        self._names = dict(names)
        self._hours = {ip: hours for ip, hours in self._hours.items() if ip in names}
        for ip, card in self._grid.sync(list(names)):
            self.card_added.emit(ip, card)
        self._empty.setVisible(not names)
        self._grid.setVisible(bool(names))

    def show_live(self, watts: float, on: int, online: int, price: float) -> None:
        self._now.setText(f"{watts:.1f} W" if online else "—")
        self._now_cost.setText(f"Cost {watts / 1000 * price:.2f} / h" if price else f"Across {on} active plugs")
        if not online:
            self._now_cost.setText("Waiting for power readings")
        elif online < len(self._names):
            self._now_cost.setText(f"Partial · {online} of {len(self._names)} plugs")
        self._plugs.setText(f"{online} / {len(self._names)}")
        offline = len(self._names) - online
        self._plugs_online.setText(
            f"{offline} plug{'s' if offline != 1 else ''} offline" if offline else "All plugs connected"
        )
        self._device_count.setText(f"{online} online · {offline} offline")

    def show_energy(self, today_wh: int | None, month_wh: int | None, price: float) -> None:
        for value, cost, wh in ((self._today, self._today_cost, today_wh), (self._month, self._month_cost, month_wh)):
            value.setText("—" if wh is None else f"{wh / 1000:.2f} kWh")
            cost.setText("Waiting for energy readings" if wh is None else cost_line(
                wh, price, "Since midnight" if value is self._today else "Month to date"
            ))

    def show_device_energy(self, energy: dict[str, int]) -> None:
        self._breakdown.show_usage(self._names, energy, self._colors)
        if 0 < len(energy) < len(self._names):
            note = f"Partial · {len(energy)} of {len(self._names)} plugs"
            self._today_cost.setText(note)
            self._month_cost.setText(note)
        for ip, card in self.device_cards.items():
            card.show_today(energy.get(ip))

    def set_controls_enabled(self, enabled: bool) -> None:
        self._all_on.setEnabled(enabled and bool(self._names))
        self._all_off.setEnabled(enabled and bool(self._names))

    def set_hours(self, ip: str, hours: list[int]) -> None:
        if ip in self._names:
            self._hours[ip] = hours
            self._breakdown.setToolTip(f"{len(hours)} hourly readings received for {self._names[ip]}")

    def show_power(self, lines: list[tuple[str, Line]], title: str, span: float | None, interval: float) -> None:
        self._power_lines, self._power_title = lines, title
        self._power_span, self._power_interval = span, interval
        self._render_power()

    def _render_power(self) -> None:
        available = [(key, line) for key, line in self._power_lines if line.watts]
        self._toggles.set_plugs([(key, line.name) for key, line in available])
        lines = [line for key, line in available if self._toggles.shown(key)]
        self._chart._empty_text = (
            "No readings yet. They appear here as the plugs answer." if self._power_lines
            else "No active plugs reporting power."
        )
        self._chart.show_lines(lines, self._power_title, self._power_span, self._power_interval)
        self._chart.chart().setTitle("")
        self._chart._y.setTitleVisible(False)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.widget().setFixedWidth(self.viewport().width())
        self._breakdown.setVisible(self.viewport().width() >= 840)
