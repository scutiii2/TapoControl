"""Switch-first Devices layout with a secondary collapsible live chart."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ui import tokens as t
from ui.device_grid import DeviceList
from ui.page_layout import ControlPage, panel, text_label


class DevicesPage(ControlPage):
    def __init__(self, chart, ranges, toggles, scan, all_on, all_off):
        super().__init__()
        toolbar = QHBoxLayout()
        self.count = text_label("No plugs yet", muted=True)
        toolbar.addWidget(self.count, 1)
        toolbar.addWidget(scan)
        self.bulk = QPushButton("All devices")
        menu = QMenu(self.bulk)
        self.power_on = menu.addAction("Turn all on", all_on.click)
        self.power_off = menu.addAction("Turn all off", all_off.click)
        self.bulk.setMenu(menu)
        toolbar.addWidget(self.bulk)
        self.content.addLayout(toolbar)

        table, table_layout = panel()
        table_layout.setContentsMargins(0, 0, 0, 0)
        self.empty = text_label("No plugs yet. Scan your network to find Tapo P110 plugs.", muted=True)
        self.empty.setContentsMargins(t.SP_XL, t.SP_LG, t.SP_XL, t.SP_XL)
        table_layout.addWidget(self.empty)
        self.list = DeviceList()
        self.list.setSpacing(0)
        self.list.setAccessibleName("Smart plugs")
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        table_layout.addWidget(self.list)
        self.total = text_label("Waiting for power readings", "caption")
        self.total.setContentsMargins(t.SP_XL, t.SP_SM, t.SP_XL, t.SP_LG)
        table_layout.addWidget(self.total)
        table.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)  # panels never stretch to fill
        self.content.addWidget(table)

        chart_panel, chart_layout = panel()
        chart_head = QHBoxLayout()
        chart_head.addWidget(text_label("Live power", "heading"), 1)
        chart_head.addWidget(ranges)
        self.chart_toggle = QToolButton()
        self.chart_toggle.setText("Hide chart")
        self.chart_toggle.setCheckable(True)
        self.chart_toggle.setChecked(True)
        self.chart_toggle.setAccessibleName("Show live power chart")
        self.chart_toggle.toggled.connect(self._show_chart)
        chart_head.addWidget(self.chart_toggle)
        chart_layout.addLayout(chart_head)
        self.chart_body = QWidget()
        body = QVBoxLayout(self.chart_body)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(t.SP_SM)
        self.chart_note = QLabel()
        self.chart_note.setProperty("tone", "muted")
        self.chart_note.setWordWrap(True)
        body.addWidget(self.chart_note)
        body.addWidget(toggles)
        chart.setMinimumHeight(210)
        chart.setMaximumHeight(280)
        body.addWidget(chart)
        chart_layout.addWidget(self.chart_body)
        chart_panel.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        self.content.addWidget(chart_panel)
        self.content.addStretch()

    def _show_chart(self, shown: bool) -> None:
        self.chart_body.setVisible(shown)
        self.chart_toggle.setText("Hide chart" if shown else "Show chart")

    def show_status(self, *, count: int, online: int, on: int, watts: float, price: float, enabled: bool) -> None:
        self.count.setText(f"{on} on · {online - on} off · {count - online} offline")
        self.empty.setVisible(not count)
        self.list.setVisible(bool(count))
        self.list.setFixedHeight(max(1, count * t.DEVICE_HEIGHT + 2 * self.list.frameWidth()))
        power = f"{watts:.1f} W" if online else "—"
        cost = f" · {watts / 1000 * price:.2f} / h" if online and price else ""
        self.total.setText(f"{power} · {online} of {count} plugs reporting{cost}")
        self.bulk.setEnabled(enabled and bool(count))
        self.power_on.setEnabled(enabled and bool(count))
        self.power_off.setEnabled(enabled and bool(count))
