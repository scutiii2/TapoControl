"""Settings tab: start with Windows and notification limits."""
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QAbstractSpinBox, QComboBox, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from core import autostart as real_autostart
from core.alerts import AlertSettings
from core.store import Store
from ui import tokens as t
from ui.page_layout import SETTINGS_WIDTH, ChoiceBox, IntBox, ControlPage, panel, text_label
from ui.plug_card import PowerSwitch
from ui.theme import theme


def load_alert_settings(store: Store) -> AlertSettings:
    return AlertSettings(
        int(store.setting("alert_watts", "0")),
        int(store.setting("alert_minutes", "0")),
        store.setting("alert_offline", "0") == "1",
    )


class SettingsPanel(ControlPage):
    changed = Signal()  # alert limits were edited

    def __init__(self, parent, store: Store, autostart=real_autostart):
        super().__init__(parent, max_width=SETTINGS_WIDTH)
        self._store = store
        self._autostart = autostart
        current = load_alert_settings(store)

        self.start_with_windows = PowerSwitch(large=True)
        self.start_with_windows.setAccessibleName("Start with Windows, minimized to the tray")
        try:
            self.start_with_windows.setChecked(autostart.is_enabled())
        except OSError:
            self.start_with_windows.setEnabled(False)
        self.start_with_windows.toggled.connect(self._on_autostart)
        self._autostart_error = QLabel()
        self._autostart_error.setProperty("tone", "error")
        self._autostart_error.setWordWrap(True)
        self._autostart_error.hide()

        self.watts = IntBox(maximum=100000, suffix=" W", specialValueText="Off", value=current.max_watts)
        self.watts.setAccessibleName("Notify above watts")
        self.minutes = IntBox(maximum=100000, suffix=" min", specialValueText="Off", value=current.max_on_minutes)
        self.minutes.setAccessibleName("Notify when on longer than")
        self.offline = PowerSwitch(large=True)
        self.offline.setAccessibleName("Notify when a plug goes offline")
        self.offline.setChecked(current.offline)
        for widget in (self.watts, self.minutes):
            widget.valueChanged.connect(self._save)
        self.offline.toggled.connect(self._save)

        startup, startup_layout = panel()
        startup_layout.addWidget(self._row(
            "Start with Windows", "Open minimized in the system tray", self.start_with_windows,
        ))
        startup_layout.addWidget(self._autostart_error)
        appearance, appearance_layout = panel()
        self.appearance = ChoiceBox()
        self.appearance.setAccessibleName("Theme")
        for mode in ("system", "light", "dark"):
            self.appearance.addItem(mode.capitalize(), mode)
        self.appearance.setCurrentIndex(self.appearance.findData(theme().mode))
        self.appearance.currentIndexChanged.connect(self._set_theme)
        theme().changed.connect(self._sync_theme)
        appearance_layout.addWidget(self._row("Theme", "System · Light · Dark", self.appearance))
        alerts, form = panel()
        for title, detail, control in (
            ("High power use", "Notify when a plug exceeds this threshold", self.watts),
            ("Long running plug", "Notify when a plug stays on longer", self.minutes),
            ("Offline plug", "Notify when a plug becomes unreachable", self.offline),
        ):
            form.addWidget(self._row(title, detail, control))
        layout = self.content
        layout.addWidget(text_label("Startup", "heading"))
        layout.addWidget(startup)
        layout.addWidget(text_label("Appearance", "heading"))
        layout.addWidget(appearance)
        layout.addWidget(text_label("Notifications", "heading"))
        layout.addWidget(alerts)
        layout.addWidget(text_label(
            "Each notice appears once per episode, from the tray, while the app is running.", "caption",
        ))
        layout.addWidget(text_label("Changes save automatically.", "caption"))
        layout.addStretch(1)

    def _row(self, title: str, detail: str, control: QWidget) -> QWidget:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, t.SP_SM, 0, t.SP_SM)
        layout.setSpacing(t.SP_LG)
        labels = QVBoxLayout()
        labels.setSpacing(t.SP_XS)
        label = text_label(title, "control-name")
        label.setBuddy(control)
        labels.addWidget(label)
        labels.addWidget(text_label(detail, "caption"))
        layout.addLayout(labels, 1)
        control.setMaximumWidth(180)
        if isinstance(control, (QAbstractSpinBox, QComboBox)):
            control.setMinimumWidth(180)  # inputs line up in one column
        layout.addWidget(control)
        return row

    def _set_theme(self) -> None:
        theme().set_mode(self.appearance.currentData())

    def _sync_theme(self) -> None:
        current = theme().mode
        self.appearance.blockSignals(True)
        self.appearance.setCurrentIndex(self.appearance.findData(current))
        self.appearance.blockSignals(False)
        if self._store.setting("theme", "system") != current:
            self._store.set_setting("theme", current)

    def _on_autostart(self, enabled: bool) -> None:
        try:
            self._autostart.set_enabled(enabled)
            self._autostart_error.hide()
        except OSError as error:
            self._autostart_error.setText("Windows would not save this setting.")
            self._autostart_error.setToolTip(str(error))
            self._autostart_error.show()
            self.start_with_windows.blockSignals(True)
            self.start_with_windows.setChecked(not enabled)
            self.start_with_windows.blockSignals(False)

    def _save(self, *_args) -> None:
        self._store.set_setting("alert_watts", str(self.watts.value()))
        self._store.set_setting("alert_minutes", str(self.minutes.value()))
        self._store.set_setting("alert_offline", "1" if self.offline.isChecked() else "0")
        self.changed.emit()

    def alert_settings(self) -> AlertSettings:
        return AlertSettings(self.watts.value(), self.minutes.value(), self.offline.isChecked())
