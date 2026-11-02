import time
from collections import deque
from collections.abc import Callable, Coroutine
from typing import Any

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QListView,
    QMainWindow,
    QMenu,
    QPushButton,
    QSplitter,
    QSystemTrayIcon,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from core.async_runner import AsyncRunner
from core.controller import AuthError, TapoController, merge_power
from core.profile import fill_gaps
from core.store import DeviceInfo, Store
from ui.charts import LiveChart
from ui.history_dialog import HistoryPanel
from ui.login_dialog import LoginPanel
from ui.plug_card import PlugCard
from ui.theme import power_icon, theme

REFRESH_MS = 5000
SAMPLES = 120  # 10 minutes of watts at REFRESH_MS
OFFLINE_RESCAN_AFTER = 3  # consecutive failed refreshes before looking for a new IP
RESCAN_COOLDOWN_S = 60
WINDOWS = (("Last 10 minutes", 0), ("Last hour", 1), ("Last 24 hours", 24))  # label, hours of plug history
LONG_REFRESH_S = 60


class MainWindow(QMainWindow):
    def __init__(self, store: Store, runner: AsyncRunner):
        super().__init__()
        self.setWindowTitle("TapoControl")
        self._theme = theme()
        self._theme.changed.connect(self._apply_theme)
        self._store = store
        self._runner = runner
        self._controller: TapoController | None = None
        self._devices: dict[str, DeviceInfo] = {}
        self._state: dict[str, tuple[bool, float]] = {}
        self._inflight: set[str] = set()
        self._samples: dict[str, deque[float]] = {}
        self._times: dict[str, deque[float]] = {}
        self._long: dict[str, list[tuple[float, float]]] = {}  # plug-stored 5-minute averages
        self._profiles: dict[str, tuple[float, dict]] = {}
        self._long_fetched: dict[str, tuple[int, float]] = {}  # ip -> (hours, monotonic time)
        self._failures: dict[str, int] = {}
        self._last_rescan = 0.0
        self._auth_required = False
        self._generation = 0
        self._power_pending: set[str] = set()
        self._power_confirming: set[str] = set()
        self._cards: dict[str, PlugCard] = {}

        self._list = QListWidget()
        self._list.setSpacing(5)
        self._list.setResizeMode(QListView.ResizeMode.Adjust)
        self._list.setMinimumHeight(100)
        self._list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._list.setAccessibleName("Smart plugs")
        self._chart = LiveChart(SAMPLES)
        self._window = QComboBox()
        self._window.setAccessibleName("Chart range")
        for label, hours in WINDOWS:
            self._window.addItem(label, hours)
        self._window.currentIndexChanged.connect(self._window_changed)
        self._list.currentItemChanged.connect(self._selection_changed)
        self._scan = QPushButton("Scan network")
        self._scan.setProperty("primary", True)
        self._scan.clicked.connect(self.scan)
        self._all_on = QPushButton("All on")
        self._all_off = QPushButton("All off")
        self._all_on.clicked.connect(lambda: self.set_all_power(True))
        self._all_off.clicked.connect(lambda: self.set_all_power(False))
        root = QWidget()
        layout = QVBoxLayout(root)
        layout.setContentsMargins(24, 18, 24, 8)
        layout.setSpacing(16)
        header = QHBoxLayout()
        self._logo = QLabel()
        self._logo.setFixedSize(42, 42)
        header.addWidget(self._logo)
        headings = QVBoxLayout()
        headings.setSpacing(3)
        title = QLabel("Your plugs")
        title.setProperty("role", "title")
        subtitle = QLabel("Local control, at a glance.")
        subtitle.setProperty("tone", "muted")
        headings.addWidget(title)
        headings.addWidget(subtitle)
        header.addLayout(headings, 1)
        header.addWidget(self._scan)
        layout.addLayout(header)
        self._tabs = QTabWidget()
        self._tabs.setDocumentMode(True)
        self._tabs.tabBar().setDrawBase(False)
        self._tabs.setUsesScrollButtons(False)
        devices = QWidget()
        devices_layout = QVBoxLayout(devices)
        devices_layout.setContentsMargins(0, 14, 0, 0)
        devices_layout.setSpacing(10)
        toolbar = QHBoxLayout()
        self._count = QLabel("DEVICES · 0 plugs")
        self._count.setProperty("tone", "muted")
        toolbar.addWidget(self._count, 1)
        toolbar.addWidget(self._all_on)
        toolbar.addWidget(self._all_off)
        devices_layout.addLayout(toolbar)
        plugs = QWidget()
        plugs_layout = QVBoxLayout(plugs)
        plugs_layout.setContentsMargins(0, 0, 0, 0)
        self._empty = QLabel("No plugs yet\nScan your network to find Tapo P110 plugs.")
        self._empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty.setProperty("tone", "muted")
        self._empty.setWordWrap(True)
        plugs_layout.addWidget(self._empty, 1)
        plugs_layout.addWidget(self._list, 1)
        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.setChildrenCollapsible(False)
        splitter.addWidget(plugs)
        chart_box = QWidget()
        chart_layout = QVBoxLayout(chart_box)
        chart_layout.setContentsMargins(0, 0, 0, 0)
        chart_layout.setSpacing(6)
        chart_head = QHBoxLayout()
        self._chart_note = QLabel()
        self._chart_note.setProperty("tone", "muted")
        chart_head.addWidget(self._chart_note, 1)
        chart_head.addWidget(self._window)
        chart_layout.addLayout(chart_head)
        chart_layout.addWidget(self._chart, 1)
        splitter.addWidget(chart_box)
        splitter.setSizes([360, 260])
        devices_layout.addWidget(splitter, 1)
        self._history = HistoryPanel(self, store, runner)
        self._history.auth_failed.connect(self._on_error)
        self._login = LoginPanel(self)
        self._login.submitted.connect(self._save_login)
        self._tabs.addTab(devices, "Devices")
        self._tabs.addTab(self._history, "Energy")
        self._tabs.addTab(self._login, "Account")
        self._tabs.currentChanged.connect(self._tab_changed)
        layout.addWidget(self._tabs, 1)
        self.setCentralWidget(root)
        self.setMinimumSize(760, 640)
        self.resize(920, 900)
        note = QLabel("Refreshes every 5 seconds · Close to keep running in tray")
        note.setProperty("tone", "muted")
        self.statusBar().addPermanentWidget(note)
        self.statusBar().setSizeGripEnabled(False)
        self._setup_tray()
        self._apply_theme()

        self._timer = QTimer(self, interval=REFRESH_MS)
        self._timer.timeout.connect(self.refresh)
        self._render()

    def _apply_theme(self) -> None:
        icon = power_icon(self._theme.colors.accent)
        self.setWindowIcon(icon)
        self._logo.setPixmap(icon.pixmap(40, 40))
        if hasattr(self, "_tray"):
            self._tray.setIcon(icon)

    def _setup_tray(self) -> None:
        """Closing the window hides it to the tray; Quit in the tray menu exits."""
        self._tray = QSystemTrayIcon(power_icon(self._theme.colors.accent), self)
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
        self._restore_samples()
        self._render()
        account = self._store.account()
        if account is None:
            self.prompt_login()
            return
        self._login.email.setText(account[0])
        self._controller = TapoController(*account)
        self._auth_required = False
        self._render()
        self._timer.start()
        if self._devices:
            self.refresh()
        else:
            self.scan()

    def _restore_samples(self) -> None:
        """Reload recent readings so the live chart does not restart empty."""
        now = time.time()
        self._store.prune_samples(now - 86400)
        for ip in self._devices:
            rows = self._store.recent_samples(ip, now - SAMPLES * REFRESH_MS / 1000)[-SAMPLES:]
            self._times[ip] = deque((t for t, _ in rows), maxlen=SAMPLES)
            self._samples[ip] = deque((w for _, w in rows), maxlen=SAMPLES)

    def prompt_login(self, message: str = "") -> None:
        self._auth_required = True
        self._timer.stop()
        self._history.clear()
        self._login.set_message(message)
        self._login.password.clear()
        self._tabs.setCurrentWidget(self._login)
        self._show_from_tray()
        (self._login.password if self._login.email.text() else self._login.email).setFocus()
        self._render()

    def _save_login(self) -> None:
        email, password = self._login.credentials()
        try:
            self._store.save_account(email, password)
        except Exception as error:
            self._login.set_message("Account could not be saved. Try again.")
            self._login._message.setToolTip(str(error))
            return
        self._controller = TapoController(email, password)
        self._generation += 1
        self._inflight.clear()
        self._power_pending.clear()
        self._power_confirming.clear()
        self._history.clear()
        self._auth_required = False
        self._login.password.clear()
        self._login.set_message("Account saved.", error=False)
        self._tabs.setCurrentIndex(0)
        self._timer.start()
        self._render()
        if self._devices:
            self.refresh()
        else:
            self.scan()

    def scan(self) -> None:
        if not self._controller or self._auth_required:
            return
        self.statusBar().showMessage("Scanning...")
        self._submit(self._controller.discover(), self._on_scanned)

    def _submit(self, coro: Coroutine[Any, Any, Any], callback: Callable) -> None:
        """Results from the previous account must not invalidate a new sign-in."""
        generation = self._generation

        def completed(result, error):
            if generation == self._generation:
                callback(result, error)

        self._runner.submit(coro, completed)

    def refresh(self) -> None:
        if not self._controller or self._auth_required:
            return
        for ip in self._devices:
            if ip not in self._inflight:
                self._refresh_ip(ip)
        self._fetch_long()

    def _refresh_ip(self, ip: str) -> None:
        if not self._controller or self._auth_required or ip not in self._devices:
            return
        self._inflight.add(ip)
        confirming = ip in self._power_confirming
        self._submit(
            self._controller.snapshot(ip),
            lambda r, e: self._on_snapshot(ip, r, e, confirms_power=confirming),
        )

    def _selected_ip(self) -> str | None:
        item = self._list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _set_power(self, on: bool) -> None:
        ip = self._selected_ip()
        if ip:
            self._toggle_ip(ip, on)

    def _select_ip(self, ip: str) -> None:
        for index in range(self._list.count()):
            item = self._list.item(index)
            if item.data(Qt.ItemDataRole.UserRole) == ip:
                self._list.setCurrentItem(item)
                return

    def _toggle_ip(self, ip: str, on: bool) -> None:
        self._select_ip(ip)
        if not self._controller or self._auth_required or ip in self._power_pending:
            return
        self._power_pending.add(ip)
        self._render_cards()

        def toggled(result, error):
            if error:
                self._power_pending.discard(ip)
            else:
                self._power_confirming.add(ip)
            self._on_toggled(result, error)
            if error:
                self._render_cards()

        self._submit(self._controller.set_power(ip, on), toggled)

    def set_all_power(self, on: bool) -> None:
        if not self._controller or self._auth_required:
            return
        for ip in self._devices:
            self._submit(self._controller.set_power(ip, on), self._on_toggled)

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
        if ip and self._controller and not self._auth_required:
            if self._tabs.currentWidget() is self._history:
                self._load_history()
            else:
                self._tabs.setCurrentWidget(self._history)

    def _load_history(self) -> None:
        ip = self._selected_ip()
        if ip and self._controller and not self._auth_required:
            self._history.load(self._controller, ip, self._devices[ip].alias)
        else:
            self._history.clear()

    def _tab_changed(self, index: int) -> None:
        if self._tabs.widget(index) is self._history:
            self._load_history()

    def _card_action(self, ip: str, action: str) -> None:
        self._select_ip(ip)
        if action == "rename":
            self._rename()
        else:
            self._show_history()

    def _selection_changed(self, *_args) -> None:
        self._render_cards()
        self._fetch_long()
        self._render_chart()

    def _on_scanned(self, devices: list[DeviceInfo] | None, error: BaseException | None) -> None:
        if error:
            return self._on_error(error)
        self._store.save_devices(devices)
        self._devices = {d.ip: d for d in self._store.devices()}
        self._state = {ip: s for ip, s in self._state.items() if ip in self._devices}
        self._failures = {ip: n for ip, n in self._failures.items() if ip in self._devices}
        self._render()
        self.statusBar().showMessage(f"Found {len(devices)} P110" if devices else "No P110 found", 5000)
        self.refresh()

    def _on_snapshot(
        self, ip: str, state: tuple[bool, float] | None, error: BaseException | None, *, confirms_power: bool = False,
    ) -> None:
        self._inflight.discard(ip)
        if confirms_power:
            self._power_pending.discard(ip)
            self._power_confirming.discard(ip)
        if error:
            self._state.pop(ip, None)
            if isinstance(error, AuthError):
                return self._on_error(error)
            self._failures[ip] = self._failures.get(ip, 0) + 1
            self._maybe_rescan(ip)
        elif state:
            self._failures.pop(ip, None)
            self._state[ip] = state
            now = time.time()
            self._samples.setdefault(ip, deque(maxlen=SAMPLES)).append(state[1])
            self._times.setdefault(ip, deque(maxlen=SAMPLES)).append(now)
            self._store.add_sample(ip, now, state[1])
        self._render()
        if ip in self._power_confirming:
            self._refresh_ip(ip)

    def _maybe_rescan(self, ip: str) -> None:
        """A plug that keeps failing may have a new IP (DHCP); rescan, rate limited."""
        now = time.monotonic()
        if self._failures[ip] >= OFFLINE_RESCAN_AFTER and now - self._last_rescan >= RESCAN_COOLDOWN_S:
            self._last_rescan = now
            self.scan()

    def _on_toggled(self, _result, error: BaseException | None) -> None:
        if error:
            return self._on_error(error)
        self.refresh()

    def _on_error(self, error: BaseException) -> None:
        if isinstance(error, AuthError):
            if not self._auth_required:
                self.prompt_login("Login failed. Check your Tapo email and password.")
        else:
            self.statusBar().showMessage(f"Error: {error}", 8000)

    def _render(self) -> None:
        selected = self._selected_ip()
        self._list.blockSignals(True)
        for index in reversed(range(self._list.count())):
            item = self._list.item(index)
            ip = item.data(Qt.ItemDataRole.UserRole)
            if ip not in self._devices:
                self._list.takeItem(index)
                self._cards.pop(ip).deleteLater()
        for ip, d in self._devices.items():
            if ip in self._cards:
                continue
            card = PlugCard(ip)
            card.selected.connect(lambda ip=ip: self._select_ip(ip))
            card.power_requested.connect(lambda on, ip=ip: self._toggle_ip(ip, on))
            card.rename_requested.connect(lambda ip=ip: self._card_action(ip, "rename"))
            card.energy_requested.connect(lambda ip=ip: self._card_action(ip, "energy"))
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, ip)
            item.setSizeHint(QSize(0, 84))
            self._list.addItem(item)
            self._list.setItemWidget(item, card)
            self._cards[ip] = card
        if selected in self._devices:
            self._select_ip(selected)
        elif self._list.count():
            self._list.setCurrentRow(0)
        self._list.blockSignals(False)
        self._empty.setVisible(not self._devices)
        self._list.setVisible(bool(self._devices))
        online = sum(ip in self._state for ip in self._devices)
        total = sum(w for _, w in self._state.values())
        self._count.setText(f"DEVICES · {len(self._devices)} plugs · {online} online · {total:.1f} W now")
        enabled = self._controller is not None and not self._auth_required
        self._scan.setEnabled(enabled)
        self._all_on.setEnabled(enabled and bool(self._devices))
        self._all_off.setEnabled(enabled and bool(self._devices))
        if self._history._ip not in self._devices:
            if self._history._ip is not None:
                self._history.clear()
        else:
            self._history.set_name(self._devices[self._history._ip].alias)
        self._render_cards()
        self._render_chart()

    def _render_cards(self) -> None:
        selected = self._selected_ip()
        for ip, card in self._cards.items():
            card.update_state(
                self._devices[ip].alias, self._state.get(ip), ip == selected,
                ip in self._power_pending or self._controller is None or self._auth_required,
                self._samples.get(ip, ()),
            )

    def _window_changed(self) -> None:
        self._fetch_long()
        self._render_chart()

    def _profile(self, ip: str) -> dict:
        """The plug's typical day, re-read at most once a minute."""
        cached = self._profiles.get(ip)
        if cached is None or time.monotonic() - cached[0] > 60:
            cached = self._profiles[ip] = (time.monotonic(), self._store.profile(ip))
        return cached[1]

    def _has_gap(self, ip: str) -> bool:
        times = list(self._times.get(ip, ()))
        return any(b - a > 2.5 * REFRESH_MS / 1000 for a, b in zip(times, times[1:]))

    def _fetch_long(self) -> None:
        """Pull the plug's own 5-minute history for the selected plug when a long window is chosen."""
        ip, hours = self._selected_ip(), self._window.currentData()
        if not hours and ip is not None and self._has_gap(ip):
            hours = 1  # the live view only needs the plug's averages to estimate across its gaps
        if not hours or ip is None or not self._controller or self._auth_required:
            return
        last = self._long_fetched.get(ip)
        if last and last[0] == hours and time.monotonic() - last[1] < LONG_REFRESH_S:
            return
        self._long_fetched[ip] = (hours, time.monotonic())

        def done(result, error):
            if ip != self._selected_ip():
                return
            self._chart_note.setToolTip(str(error) if error else "")
            if error or not result:
                # Unsupported or failing history: the chart keeps our own readings plus the learned pattern.
                self._chart_note.setText("The plug has no stored power history, so dashed parts are estimated from its usual day.")
            else:
                self._chart_note.setText("")
                self._long[ip] = result
                self._render_chart()

        self._submit(self._controller.power_history(ip, hours), done)

    def _render_chart(self) -> None:
        ip = self._selected_ip()
        samples = self._samples.get(ip)
        hours = self._window.currentData()
        name = self._devices[ip].alias if ip in self._devices else None
        if hours and name:
            span = hours * 3600
            own = self._store.recent_samples(ip, time.time() - span)
            points = merge_power(self._long.get(ip, []), own)
            peak = max((w for _, w in points), default=0)
            title = f"{name} · average watts · peak {peak:.1f} W" if points else f"{name} - average watts"
            estimates = fill_gaps(points, [], self._profile(ip), 450)
            self._chart.show_samples(
                [w for _, w in points], title, [t for t, _ in points], span=span, interval=300, estimates=estimates
            )
            return
        if name and samples:
            title = f"{name} · now {samples[-1]:.1f} W · peak {max(samples):.1f} W"
        else:
            title = f"{name} - live watts" if name else "Select a plug"
        times = self._times.get(ip)
        estimates = list(self._long.get(ip, ()))
        if samples and times:
            estimates += fill_gaps(list(zip(times, samples)), estimates, self._profile(ip), 2.5 * REFRESH_MS / 1000)
        self._chart.show_samples(samples, title, times, estimates=estimates)
