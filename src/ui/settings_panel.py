"""Settings tab: start with Windows and notification limits."""
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QCheckBox, QFormLayout, QFrame, QLabel, QSpinBox, QVBoxLayout, QWidget

from core import autostart as real_autostart
from core.alerts import AlertSettings
from core.store import Store
from ui import tokens as t


def load_alert_settings(store: Store) -> AlertSettings:
    return AlertSettings(
        int(store.setting("alert_watts", "0")),
        int(store.setting("alert_minutes", "0")),
        store.setting("alert_offline", "0") == "1",
    )


class SettingsPanel(QWidget):
    changed = Signal()  # alert limits were edited

    def __init__(self, parent, store: Store, autostart=real_autostart):
        super().__init__(parent)
        self._store = store
        self._autostart = autostart
        current = load_alert_settings(store)

        self.start_with_windows = QCheckBox("Start with Windows, minimized to the tray")
        try:
            self.start_with_windows.setChecked(autostart.is_enabled())
        except OSError:
            self.start_with_windows.setEnabled(False)
        self.start_with_windows.toggled.connect(self._on_autostart)
        self._autostart_error = QLabel()
        self._autostart_error.setProperty("tone", "error")
        self._autostart_error.setWordWrap(True)
        self._autostart_error.hide()

        self.watts = QSpinBox(maximum=100000, suffix=" W", specialValueText="Off", value=current.max_watts)
        self.watts.setAccessibleName("Notify above watts")
        self.minutes = QSpinBox(maximum=100000, suffix=" min", specialValueText="Off", value=current.max_on_minutes)
        self.minutes.setAccessibleName("Notify when on longer than")
        self.offline = QCheckBox("Notify when a plug goes offline")
        self.offline.setChecked(current.offline)
        for widget in (self.watts, self.minutes):
            widget.valueChanged.connect(self._save)
        self.offline.toggled.connect(self._save)

        startup = QFrame()
        startup.setProperty("card", True)
        startup_layout = QVBoxLayout(startup)
        startup_layout.setContentsMargins(t.CARD_PAD, t.CARD_PAD, t.CARD_PAD, t.CARD_PAD)
        startup_layout.setSpacing(t.SP_SM)
        startup_layout.addWidget(self.start_with_windows)
        startup_layout.addWidget(self._autostart_error)
        alerts = QFrame()
        alerts.setProperty("card", True)
        form = QFormLayout(alerts)
        form.setContentsMargins(t.CARD_PAD, t.CARD_PAD, t.CARD_PAD, t.CARD_PAD)
        form.setVerticalSpacing(t.SP_MD)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.FieldsStayAtSizeHint)  # a field stays beside its label
        form.addRow("Notify above", self.watts)
        form.addRow("Notify when on longer than", self.minutes)
        form.addRow(self.offline)

        startup_heading = QLabel("Start-up")
        startup_heading.setProperty("role", "heading")
        heading = QLabel("Notifications")
        heading.setProperty("role", "heading")
        note = QLabel("Each notice appears once per episode, from the tray, while the app is running.")
        note.setProperty("tone", "muted")
        note.setWordWrap(True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, t.PAGE_TOP, 0, 0)
        layout.setSpacing(t.SP_SM)
        layout.addWidget(startup_heading)
        layout.addWidget(startup)
        layout.addSpacing(t.SP_LG)  # a larger gap between the two groups than inside each
        layout.addWidget(heading)
        layout.addWidget(alerts)
        layout.addWidget(note)
        layout.addStretch(1)

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
