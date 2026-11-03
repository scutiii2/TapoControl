"""Approved light dashboard: metrics, live power, usage breakdown and real plug controls."""
from collections import deque
from datetime import date

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLayout,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ui import tokens as t
from ui.charts import Line, LineColors, LineToggles, LiveChart
from ui.device_grid import DeviceGrid
from ui.usage_breakdown import UsageBreakdown
from ui.widgets import SummaryPanel, cost_line


class OverviewPage(QScrollArea):
    card_added = Signal(str, object)
    scan_requested = Signal()
    range_selected = Signal(int)
    devices_requested = Signal()

    def __init__(self, colors: LineColors):
        super().__init__()
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._colors = colors
        self._names: dict[str, str] = {}
        self._hours: dict[str, list[int]] = {}
        self._days: dict[str, list[tuple[date, int]]] = {}
        self._power_lines: list[tuple[str, Line]] = []
        self._power_title = "Live watts"
        self._power_span = None
        self._power_interval = 5
        cards = SummaryPanel()
        self._summary = cards
        self._trend: deque[float] = deque(maxlen=60)
        self._now, self._now_cost = cards.now, cards.now_cost
        self._today, self._today_cost = cards.today, cards.today_cost
        self._month, self._month_cost = cards.month, cards.month_cost
        self._plugs, self._plugs_online = cards.plugs, cards.plugs_note
        self._toggles = LineToggles(colors, include_overall=False)
        self._toggles.changed.connect(self._render_power)
        self._chart = LiveChart(120)
        self._chart.fill_first_series = True
        self._chart.setMinimumHeight(205)
        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        layout.setContentsMargins(0, t.SP_SM, t.SP_LG, t.SP_XL)  # right gutter keeps content off the scrollbar
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
        self._ranges = QButtonGroup(self)
        self._ranges.idClicked.connect(self.range_selected)
        self._range_row = QHBoxLayout()
        self._range_row.setSpacing(t.SP_XS)
        head.addWidget(title, 1)
        head.addLayout(self._range_row)
        chart.addLayout(head)
        chart.addWidget(self._toggles)
        chart.addWidget(self._chart, 1)
        middle.addWidget(panel, 1)
        self._breakdown = UsageBreakdown()
        middle.addWidget(self._breakdown)
        layout.addLayout(middle)
        devices = QFrame()
        devices.setProperty("card", True)
        table = QVBoxLayout(devices)
        table.setContentsMargins(0, 0, 0, 0)
        table.setSpacing(0)
        toolbar = QHBoxLayout()
        toolbar.setContentsMargins(t.PANEL_X, t.SP_LG, t.PANEL_X, t.SP_LG)
        toolbar.setSpacing(t.SP_MD)
        heading = QLabel("Your devices")
        heading.setProperty("role", "heading")
        self._device_count = QLabel("No plugs yet")
        self._device_count.setProperty("role", "caption")
        toolbar.addWidget(heading)
        toolbar.addWidget(self._device_count)
        toolbar.addStretch()
        view_all = QPushButton("View all devices")
        view_all.setProperty("link", True)
        view_all.clicked.connect(self.devices_requested)
        toolbar.addWidget(view_all)
        table.addLayout(toolbar)
        self._empty = QLabel("No plugs yet. Scan your network to find Tapo P110 plugs.")
        self._empty.setProperty("tone", "muted")
        self._empty.setWordWrap(True)
        self._empty.setContentsMargins(t.PANEL_X, 0, t.PANEL_X, t.SP_LG)
        table.addWidget(self._empty)
        self._scan = QPushButton("Scan network")
        self._scan.setProperty("primary", True)
        self._scan.clicked.connect(self.scan_requested)
        table.addWidget(self._scan, 0, Qt.AlignmentFlag.AlignLeft)
        self._grid = DeviceGrid()
        self.device_cards = self._grid.cards
        table.addWidget(self._grid)
        layout.addWidget(devices)
        layout.addStretch()
        self.setWidget(body)

    def set_ranges(self, labels: list[str]) -> None:
        """One segmented button per chart range; clicking one emits its index."""
        for index, label in enumerate(labels):
            button = QPushButton(label)
            button.setCheckable(True)
            button.setChecked(index == 0)
            button.setProperty("segment", True)
            button.setAccessibleName(f"Chart range {label}")
            self._ranges.addButton(button, index)
            self._range_row.addWidget(button)

    def select_range(self, index: int) -> None:
        button = self._ranges.button(index)
        if button:
            button.setChecked(True)

    def set_plugs(self, names: dict[str, str]) -> None:
        """Follow the plug list; forget hours of plugs that are gone."""
        if names == self._names:
            return
        self._names = dict(names)
        self._hours = {ip: hours for ip, hours in self._hours.items() if ip in names}
        self._days = {ip: rows for ip, rows in self._days.items() if ip in names}
        for ip, card in self._grid.sync(list(names)):
            self.card_added.emit(ip, card)
        self._empty.setVisible(not names)
        self._scan.setVisible(not names)
        self._grid.setVisible(bool(names))

    def show_live(self, watts: float, on: int, online: int, price: float) -> None:
        self._now.setText(f"{watts:.1f} W" if online else "—")
        self._now_cost.setText(f"Cost {watts / 1000 * price:.2f} / h" if price else f"Across {on} active plugs")
        if not online:
            self._now_cost.setText("Waiting for power readings")
        elif online < len(self._names):
            self._now_cost.setText(f"Partial · {online} of {len(self._names)} plugs")
        if online:
            self._trend.append(watts)
        self._summary.trend.set_points(self._trend)
        self._plugs.setText(f"{online} / {len(self._names)}")
        offline = len(self._names) - online
        self._plugs_online.setText(
            f"{offline} plug{'s' if offline != 1 else ''} offline" if offline else "All plugs connected"
        )
        self._device_count.setText(f"{online} online · {offline} offline")

    def show_energy(self, today_wh: int | None, month_wh: int | None, price: float) -> None:
        priced = price and today_wh is not None
        self._summary.cost.setText(f"{today_wh / 1000 * price:.2f}" if priced else "—")
        self._summary.cost_note.setText("Estimated" if priced else "No tariff set")
        for value, cost, wh in ((self._today, self._today_cost, today_wh), (self._month, self._month_cost, month_wh)):
            value.setText("—" if wh is None else f"{wh / 1000:.2f} kWh")
            cost.setText("Waiting for energy readings" if wh is None else cost_line(
                wh, price, "Since midnight" if value is self._today else "Month to date"
            ))

    def show_device_energy(self, energy: dict[str, int]) -> None:
        self._breakdown.show_usage(self._names, energy, self._colors)
        known = {ip: wh for ip, wh in energy.items() if ip in self._names}
        top = max(known, key=known.get) if known else None
        self._summary.top.setText(f"{known[top] / 1000:.2f} kWh" if top else "—")
        self._summary.top_note.setText(self._names[top] if top else "No readings yet")
        if 0 < len(energy) < len(self._names):
            note = f"Partial · {len(energy)} of {len(self._names)} plugs"
            self._today_cost.setText(note)
            self._month_cost.setText(note)
        for ip, card in self.device_cards.items():
            card.show_today(energy.get(ip))

    def set_hours(self, ip: str, hours: list[int]) -> None:
        if ip in self._names:
            self._hours[ip] = hours
            self._breakdown.setToolTip(f"{len(hours)} hourly readings received for {self._names[ip]}")
            longest = max(map(len, self._hours.values()))
            self._summary.today_trend.set_points(
                [sum(h[i] for h in self._hours.values() if i < len(h)) for i in range(longest)]
            )

    def set_days(self, ip: str, rows: list[tuple[date, int]]) -> None:
        """Daily Wh of this month, summed over the plugs, drawn as the month's trend."""
        if ip not in self._names:
            return
        self._days[ip] = rows
        month = date.today().replace(day=1)
        totals: dict[date, int] = {}
        for plug_rows in self._days.values():
            for day, wh in plug_rows:
                if day >= month:
                    totals[day] = totals.get(day, 0) + wh
        self._summary.month_trend.set_points([totals[day] for day in sorted(totals)])

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
