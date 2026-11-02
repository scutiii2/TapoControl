from collections import deque

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QInputDialog,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QPushButton,
    QStyle,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

from core.async_runner import AsyncRunner
from core.controller import AuthError, TapoController
from core.store import DeviceInfo, Store
from ui.charts import LiveChart
from ui.history_dialog import HistoryDialog
from ui.login_dialog import LoginDialog

REFRESH_MS = 5000
SAMPLES = 120  # 10 minutes of watts at REFRESH_MS


class MainWindow(QMainWindow):
    def __init__(self, store: Store, runner: AsyncRunner):
        super().__init__()
        self.setWindowTitle("TapoControl")
        self._store = store
        self._runner = runner
        self._controller: TapoController | None = None
        self._devices: dict[str, DeviceInfo] = {}
        self._state: dict[str, tuple[bool, float]] = {}
        self._inflight: set[str] = set()
        self._samples: dict[str, deque[float]] = {}

        self._list = QListWidget()
        self._chart = LiveChart(SAMPLES)
        self._list.currentItemChanged.connect(lambda *_: self._render_chart())
        scan = QPushButton("Scan network")
        turn_on = QPushButton("Turn on")
        turn_off = QPushButton("Turn off")
        all_on = QPushButton("All on")
        all_off = QPushButton("All off")
        rename = QPushButton("Rename...")
        history = QPushButton("Energy...")
        account = QPushButton("Account...")
        scan.clicked.connect(self.scan)
        turn_on.clicked.connect(lambda: self._set_power(True))
        turn_off.clicked.connect(lambda: self._set_power(False))
        all_on.clicked.connect(lambda: self.set_all_power(True))
        all_off.clicked.connect(lambda: self.set_all_power(False))
        rename.clicked.connect(self._rename)
        history.clicked.connect(self._show_history)
        account.clicked.connect(lambda: self.prompt_login())
        root = QWidget()
        layout = QVBoxLayout(root)
        layout.addWidget(self._list, 1)
        layout.addWidget(self._chart, 2)
        for buttons in ((scan, turn_on, turn_off, all_on, all_off), (rename, history, account)):
            row = QHBoxLayout()
            for b in buttons:
                row.addWidget(b)
            layout.addLayout(row)
        self.setCentralWidget(root)
        self.resize(560, 560)
        self._setup_tray()

        self._timer = QTimer(self, interval=REFRESH_MS)
        self._timer.timeout.connect(self.refresh)

    def _setup_tray(self) -> None:
        """Closing the window hides it to the tray; Quit in the tray menu exits."""
        self._tray = QSystemTrayIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_ComputerIcon), self)
        menu = QMenu(self)
        for text, slot in (
            ("Show", self._show_from_tray),
            ("All on", lambda: self.set_all_power(True)),
            ("All off", lambda: self.set_all_power(False)),
            ("Quit", QApplication.quit),
        ):
            action = QAction(text, menu)
            action.triggered.connect(slot)
            menu.addAction(action)
        self._tray.setContextMenu(menu)
        self._tray.setToolTip("TapoControl")
        self._tray.activated.connect(
            lambda reason: self._show_from_tray() if reason == QSystemTrayIcon.ActivationReason.Trigger else None
        )
        self._tray.show()

    def _show_from_tray(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def closeEvent(self, event) -> None:
        if self._tray.isVisible():
            self.hide()
            event.ignore()
        else:
            event.accept()
            QApplication.quit()

    def start(self) -> None:
        for d in self._store.devices():
            self._devices[d.ip] = d
        self._render()
        account = self._store.account()
        if account is None and not self.prompt_login():
            return
        if account is not None:
            self._controller = TapoController(*account)
        self._timer.start()
        if self._devices:
            self.refresh()
        else:
            self.scan()

    def prompt_login(self, message: str = "") -> bool:
        current = self._store.account()
        dialog = LoginDialog(self, current[0] if current else "", message)
        if dialog.exec() != LoginDialog.DialogCode.Accepted:
            return False
        email, password = dialog.credentials()
        self._store.save_account(email, password)
        self._controller = TapoController(email, password)
        if self._devices:
            self.refresh()
        return True

    def scan(self) -> None:
        if not self._controller:
            return
        self.statusBar().showMessage("Scanning...")
        self._runner.submit(self._controller.discover(), self._on_scanned)

    def refresh(self) -> None:
        if not self._controller:
            return
        for ip in self._devices:
            if ip not in self._inflight:
                self._inflight.add(ip)
                self._runner.submit(self._controller.snapshot(ip), lambda r, e, ip=ip: self._on_snapshot(ip, r, e))

    def _selected_ip(self) -> str | None:
        item = self._list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _set_power(self, on: bool) -> None:
        ip = self._selected_ip()
        if ip and self._controller:
            self._runner.submit(self._controller.set_power(ip, on), self._on_toggled)

    def set_all_power(self, on: bool) -> None:
        if not self._controller:
            return
        for ip in self._devices:
            self._runner.submit(self._controller.set_power(ip, on), self._on_toggled)

    def _rename(self) -> None:
        ip = self._selected_ip()
        if not ip:
            return
        name, ok = QInputDialog.getText(
            self, "Rename", "Name (empty = name from Tapo app):", text=self._devices[ip].alias
        )
        if ok:
            self._store.set_nickname(ip, name)
            self._devices = {d.ip: d for d in self._store.devices()}
            self._render()

    def _show_history(self) -> None:
        ip = self._selected_ip()
        if ip and self._controller:
            HistoryDialog(self, self._store, self._runner, self._controller, ip, self._devices[ip].alias).exec()

    def _on_scanned(self, devices: list[DeviceInfo] | None, error: BaseException | None) -> None:
        if error:
            return self._on_error(error)
        self._store.save_devices(devices)
        self._devices = {d.ip: d for d in self._store.devices()}
        self._state = {ip: s for ip, s in self._state.items() if ip in self._devices}
        self._render()
        self.statusBar().showMessage(f"Found {len(devices)} P110" if devices else "No P110 found", 5000)
        self.refresh()

    def _on_snapshot(self, ip: str, state: tuple[bool, float] | None, error: BaseException | None) -> None:
        self._inflight.discard(ip)
        if error:
            self._state.pop(ip, None)
            if isinstance(error, AuthError):
                return self._on_error(error)
        elif state:
            self._state[ip] = state
            self._samples.setdefault(ip, deque(maxlen=SAMPLES)).append(state[1])
        self._render()

    def _on_toggled(self, _result, error: BaseException | None) -> None:
        if error:
            return self._on_error(error)
        self.refresh()

    def _on_error(self, error: BaseException) -> None:
        if isinstance(error, AuthError):
            self._timer.stop()
            if self.prompt_login("Login failed. Check your Tapo email and password."):
                self._timer.start()
        else:
            self.statusBar().showMessage(f"Error: {error}", 8000)

    def _render(self) -> None:
        selected = self._selected_ip()
        self._list.blockSignals(True)
        self._list.clear()
        for ip, d in self._devices.items():
            state = self._state.get(ip)
            if state is None:
                status = "offline / unknown"
            else:
                on, watts = state
                status = f"{'ON' if on else 'OFF'}  {watts:.1f} W"
            item = QListWidgetItem(f"{d.alias}  ({ip})  -  {status}")
            item.setData(Qt.ItemDataRole.UserRole, ip)
            self._list.addItem(item)
            if ip == selected:
                self._list.setCurrentItem(item)
        self._list.blockSignals(False)
        self._render_chart()

    def _render_chart(self) -> None:
        ip = self._selected_ip()
        title = f"{self._devices[ip].alias} - live watts" if ip in self._devices else "Select a plug"
        self._chart.show_samples(self._samples.get(ip), title)
