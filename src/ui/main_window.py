import time
from datetime import date
from collections import deque
from collections.abc import Callable, Coroutine
from typing import Any

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QAction, QFont
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidgetItem,
    QListView,
    QMainWindow,
    QMenu,
    QPushButton,
    QScrollArea,
    QSplitter,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

from core.async_runner import AsyncRunner
from core.alerts import AlertEngine
from core.controller import AuthError, EnergySummary, TapoController, merge_power
from core.profile import fill_gaps, total_series
from core.store import DeviceInfo, Store
from ui.charts import OVERALL, Line, LineColors, LineToggles, LiveChart
from ui.history_dialog import HistoryPanel
from ui.login_dialog import LoginPanel
from ui.overview_page import OverviewPage
from ui.plug_card import PlugCard, timer_note
from ui.settings_panel import SettingsPanel
from ui.device_grid import DeviceList
from ui.side_tabs import SideTabs
from ui import tokens as t
from ui.theme import action_error, power_icon, theme

REFRESH_MS = 5000
SAMPLES = 120  # 10 minutes of watts at REFRESH_MS
OFFLINE_RESCAN_AFTER = 3  # consecutive failed refreshes before looking for a new IP
RESCAN_COOLDOWN_S = 60
WINDOWS = (("Last 10 minutes", 0), ("Last hour", 1), ("Last 24 hours", 24))  # label, hours of plug history
LONG_REFRESH_S = 60
PAGES = {  # page kind -> (header title, one line about it)
    "overview": ("Overview", "Power and usage across all your plugs."),
    "devices": ("Devices", "Switch plugs, rename them and set timers."),
    "energy": ("Energy", "Usage history and cost."),
    "account": ("Account", "The Tapo account that signs in to your plugs."),
    "settings": ("Settings", "Start-up and notifications."),
}


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
        self._alerts = AlertEngine()
        self._timers: dict[str, tuple[float, bool]] = {}  # ip -> (epoch deadline, switch on); set from this app only
        self._profiles: dict[str, tuple[float, dict]] = {}
        self._long_fetched: dict[str, tuple[int, float]] = {}  # ip -> (hours, monotonic time)
        self._failures: dict[str, int] = {}
        self._last_rescan = 0.0
        self._auth_required = False
        self._scanning = False
        self._signing_in = False
        self._generation = 0
        self._power_pending: set[str] = set()
        self._power_confirming: set[str] = set()
        self._cards: dict[str, PlugCard] = {}
        self._colors = LineColors()
        self._energy: dict[str, EnergySummary] = {}  # latest energy totals, for the Overview
        self._overview_fetched: dict[str, float] = {}  # ip -> monotonic time of the last Overview fetch
        self._long_failed: set[str] = set()

        self._list = DeviceList()
        self._list.setSpacing(t.SP_SM)
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
        self._all_on = QPushButton("Turn all on")
        self._all_off = QPushButton("Turn all off")
        self._all_on.clicked.connect(lambda: self.set_all_power(True))
        self._all_off.clicked.connect(lambda: self.set_all_power(False))
        self._tabs = SideTabs()
        header = QHBoxLayout()
        header.setSpacing(t.SP_MD)
        self._logo = self._tabs._brand_icon
        header.addWidget(self._tabs.collapse_button)
        breadcrumb = QLabel("Workspace /")
        breadcrumb.setProperty("role", "small")
        breadcrumb.setProperty("tone", "muted")
        header.addWidget(breadcrumb)
        self._title = QLabel()
        self._title.setProperty("role", "small")
        self._title.setProperty("tone", "muted")
        header.addWidget(self._title, 1)
        today = QLabel(date.today().strftime("%A, %B %#d"))
        today.setProperty("role", "caption")
        header.addWidget(today)
        header.addWidget(self._scan)
        self._scan.setProperty("primary", False)
        intro = QHBoxLayout()
        intro.setSpacing(t.SP_MD)
        headings = QVBoxLayout()
        headings.setSpacing(t.SP_SM)
        eyebrow = QLabel("YOUR HOME, AT A GLANCE")
        eyebrow.setProperty("role", "eyebrow")
        self._headline = QLabel("A little less energy. A little more control.")
        self._headline.setProperty("role", "title")
        headline_font = self._headline.font()
        headline_font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, -1.1)
        self._headline.setFont(headline_font)
        self._headline.setWordWrap(True)
        headings.addWidget(eyebrow)
        headings.addWidget(self._headline)
        self._subtitle = QLabel()
        self._subtitle.setProperty("tone", "muted")
        self._subtitle.setProperty("role", "small")
        self._subtitle.setWordWrap(True)
        headings.addWidget(self._subtitle)
        intro.addLayout(headings, 1)
        self._live = QLabel("●  Live · every 5s")
        self._live.setProperty("role", "caption")
        self._live.setStyleSheet("border: 1px solid #e3e9e3; border-radius: 16px; padding: 8px 13px;")
        intro.addWidget(self._live, 0, Qt.AlignmentFlag.AlignVCenter)
        self._tabs.content.setContentsMargins(t.PAGE_X, t.PAGE_Y, t.PAGE_X, t.PAGE_BOTTOM)
        self._tabs.content.setSpacing(t.SECTION_GAP)
        self._tabs.content.insertLayout(0, header)
        self._tabs.content.insertLayout(1, intro)
        devices = QWidget()
        devices_layout = QVBoxLayout(devices)
        devices_layout.setContentsMargins(0, t.PAGE_TOP, 0, 0)
        devices_layout.setSpacing(t.SP_MD)
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
        splitter.setMinimumHeight(560)
        splitter.addWidget(plugs)
        chart_box = QWidget()
        chart_layout = QVBoxLayout(chart_box)
        chart_layout.setContentsMargins(0, 0, 0, 0)
        chart_layout.setSpacing(t.SP_SM)
        chart_head = QHBoxLayout()
        self._chart_note = QLabel()
        self._chart_note.setProperty("tone", "muted")
        chart_head.addWidget(self._chart_note, 1)
        chart_head.addWidget(self._window)
        chart_layout.addLayout(chart_head)
        self._toggles = LineToggles(self._colors)
        self._toggles.changed.connect(self._render_chart)
        chart_layout.addWidget(self._toggles)
        chart_layout.addWidget(self._chart, 1)
        splitter.addWidget(chart_box)
        splitter.setSizes([360, 260])
        devices_layout.addWidget(splitter, 1)
        devices_scroll = QScrollArea()
        devices_scroll.setWidgetResizable(True)
        devices_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        devices_scroll.setWidget(devices)
        self._overview = OverviewPage(self._colors)
        self._overview.card_added.connect(self._connect_card)
        self._overview.all_power_requested.connect(self.set_all_power)
        self._history = HistoryPanel(self, store, runner, self._colors)
        self._history.auth_failed.connect(self._on_error)
        self._login = LoginPanel(self)
        self._settings = SettingsPanel(self, store)
        self._login.submitted.connect(self._save_login)
        self._tabs.addTab(self._overview, "overview", "Overview")
        self._tabs.addTab(devices_scroll, "devices", "Devices")
        self._tabs.addTab(self._history, "energy", "Energy")
        self._tabs.addTab(self._login, "account", "Account", bottom=True)
        self._tabs.addTab(self._settings, "settings", "Settings")
        self._tabs.currentChanged.connect(self._tab_changed)
        self._show_page(self._tabs.currentIndex())
        self.setCentralWidget(self._tabs)
        self.setMinimumSize(760, 640)
        self.resize(1440, 1060)
        note = QLabel("Runs quietly in your system tray")
        note.setProperty("role", "caption")
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
        self._logo.setPixmap(icon.pixmap(35, 35))
        if hasattr(self, "_tray"):
            self._tray.setIcon(icon)

    def _setup_tray(self) -> None:
        """Closing the window hides it to the tray; Quit in the tray menu exits."""
        self._tray = QSystemTrayIcon(power_icon(self._theme.colors.accent), self)
        menu = QMenu(self)
        for text, slot in (
            ("Show", self.show_window),
            ("Turn all on", lambda: self.set_all_power(True)),
            ("Turn all off", lambda: self.set_all_power(False)),
            ("Quit", QApplication.quit),
        ):
            action = QAction(text, menu)
            action.triggered.connect(slot)
            menu.addAction(action)
        self._tray.setContextMenu(menu)
        self._tray.setToolTip("TapoControl")
        self._tray.activated.connect(
            lambda reason: self.show_window() if reason == QSystemTrayIcon.ActivationReason.Trigger else None
        )
        self._tray.show()

    def show_window(self) -> None:
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
        self._signing_in = False
        self._scanning = False
        self._timer.stop()
        self._history.clear()
        self._login.set_message(message)
        self._login.password.clear()
        self._tabs.setCurrentWidget(self._login)
        self.show_window()
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
        self._scanning = False
        self._energy.clear()
        self._overview_fetched.clear()
        self._auth_required = False
        self._login.password.clear()
        self._signing_in = True
        self._login.set_message("Account saved. Checking it with Tapo…", error=False)
        self._tabs.setCurrentIndex(0)
        self._timer.start()
        self._render()
        if self._devices:
            self.refresh()
        else:
            self.scan()

    def scan(self) -> None:
        if not self._can_send():
            return
        self._scanning = True
        self._render()
        self.statusBar().showMessage("Scanning the network…")
        self._submit(self._controller.discover(), self._on_scanned)

    def _submit(self, coro: Coroutine[Any, Any, Any], callback: Callable) -> None:
        """Results from the previous account must not invalidate a new sign-in."""
        generation = self._generation

        def completed(result, error):
            if generation == self._generation:
                callback(result, error)

        self._runner.submit(coro, completed)

    def refresh(self) -> None:
        if not self._can_send():
            return
        for ip in self._devices:
            if ip not in self._inflight:
                self._refresh_ip(ip)
        self._fetch_long()
        self._fetch_overview()

    def _fetch_overview(self) -> None:
        """Energy and today's hours for the Overview: at most once a minute per plug, only while it is open."""
        if self._tabs.currentWidget() is not self._overview or not self._can_send():
            return
        for ip in self._devices:
            last = self._overview_fetched.get(ip)
            if last is not None and time.monotonic() - last < LONG_REFRESH_S:
                continue
            self._overview_fetched[ip] = time.monotonic()
            self._submit(self._controller.energy(ip), self._background(lambda r, ip=ip: self._on_energy(ip, r)))
            self._submit(
                self._controller.hourly_today(ip),
                self._background(lambda r, ip=ip: self._overview.set_hours(ip, r or [])),
            )

    def _background(self, handler: Callable) -> Callable:
        """Callback for secondary data: a bad login is reported, any other failure keeps the old value."""
        def callback(result, error):
            if isinstance(error, AuthError):
                self._on_error(error)
            elif not error:
                handler(result)

        return callback

    def _on_energy(self, ip: str, summary: EnergySummary | None) -> None:
        if summary:
            self._energy[ip] = summary
            self._render_overview()

    def _render_overview(self) -> None:
        price = self._store.price_per_kwh()
        self._overview.set_plugs({ip: d.alias for ip, d in self._devices.items()})
        on = sum(1 for is_on, _ in self._state.values() if is_on)
        total = sum(w for _, w in self._state.values())
        self._overview.show_live(total, on, len(self._state), price)
        sums = [self._energy[ip] for ip in self._devices if ip in self._energy]
        self._overview.show_energy(
            sum(x.today_wh for x in sums) if sums else None, sum(x.month_wh for x in sums) if sums else None, price,
        )
        self._overview.show_device_energy({ip: self._energy[ip].today_wh for ip in self._devices if ip in self._energy})
        self._overview.set_controls_enabled(self._can_send())
        self._tabs.show_connection_count(len(self._state))
        for ip, card in self._overview.device_cards.items():
            self._update_card(ip, card)

    def _refresh_ip(self, ip: str) -> None:
        if not self._can_send() or ip not in self._devices:
            return
        self._inflight.add(ip)
        confirming = ip in self._power_confirming
        self._submit(
            self._controller.snapshot(ip),
            lambda r, e: self._on_snapshot(ip, r, e, confirms_power=confirming),
        )

    def _can_send(self) -> bool:
        return bool(self._controller) and not self._auth_required

    def _selected_ip(self) -> str | None:
        item = self._list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _select_ip(self, ip: str) -> None:
        for index in range(self._list.count()):
            item = self._list.item(index)
            if item.data(Qt.ItemDataRole.UserRole) == ip:
                self._list.setCurrentItem(item)
                return

    def _toggle_ip(self, ip: str, on: bool) -> None:
        self._select_ip(ip)
        if not self._can_send() or ip in self._power_pending:
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

    def _set_timer(self, ip: str, minutes: int, on: bool) -> None:
        if not self._can_send():
            return

        def done(_result, error):
            if error:
                return self._on_error(error)
            self._timers[ip] = (time.time() + minutes * 60, on)
            self._render_cards()

        self._submit(self._controller.set_timer(ip, minutes, on), done)

    def _clear_timer(self, ip: str) -> None:
        if not self._can_send():
            return

        def done(_result, error):
            if error:
                return self._on_error(error)
            self._timers.pop(ip, None)
            self._render_cards()

        self._submit(self._controller.clear_timer(ip), done)

    def _timer_note(self, ip: str) -> str:
        deadline, on = self._timers.get(ip, (0.0, False))
        if deadline <= time.time():
            self._timers.pop(ip, None)
            return ""
        return timer_note(deadline - time.time(), on)

    def set_all_power(self, on: bool) -> None:
        if not self._can_send():
            return
        if self._devices:
            self.statusBar().showMessage(f"Turning {len(self._devices)} plug(s) {'on' if on else 'off'}…", 5000)
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
        if self._devices and self._can_send():
            if self._tabs.currentWidget() is self._history:
                self._load_history()
            else:
                self._tabs.setCurrentWidget(self._history)

    def _load_history(self) -> None:
        if self._devices and self._can_send():
            self._history.load(self._controller, {ip: d.alias for ip, d in self._devices.items()})
        else:
            self._history.clear()

    def _show_page(self, index: int) -> None:
        """The header names the open page, so the icon rail is never the only orientation."""
        kind = self._tabs.kind(index)
        self._title.setText(PAGES[kind][0])
        self._headline.setText(
            "A little less energy. A little more control." if kind == "overview" else PAGES[kind][0]
        )
        self._subtitle.setText(
            "Keep an eye on your usage. Switch things off when you’re done." if kind == "overview" else PAGES[kind][1]
        )
        self._live.setVisible(kind in ("overview", "devices"))
        self._scan.setVisible(kind in ("overview", "devices"))

    def _tab_changed(self, index: int) -> None:
        self._show_page(index)
        page = self._tabs.widget(index)
        if page is self._history:
            self._load_history()
        elif page is self._overview:
            self._fetch_overview()

    def _card_action(self, ip: str, action: str) -> None:
        self._select_ip(ip)
        if action == "rename":
            self._rename()
        else:
            self._show_history()

    def _selection_changed(self, *_args) -> None:
        self._render_cards()

    def _on_scanned(self, devices: list[DeviceInfo] | None, error: BaseException | None) -> None:
        self._scanning = False
        if error:
            self._render()
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
            if self._signing_in:  # the first answer from a plug confirms the login
                self._signing_in = False
                self._login.set_message("Signed in. Your plugs are connected.", error=False)
            self._state[ip] = state
            now = time.time()
            self._samples.setdefault(ip, deque(maxlen=SAMPLES)).append(state[1])
            self._times.setdefault(ip, deque(maxlen=SAMPLES)).append(now)
            self._store.add_sample(ip, now, state[1])
        self._check_alerts(ip)
        self._render()
        if ip in self._power_confirming:
            self._refresh_ip(ip)

    def _check_alerts(self, ip: str) -> None:
        name = self._devices[ip].alias if ip in self._devices else ip
        offline = self._failures.get(ip, 0) >= OFFLINE_RESCAN_AFTER
        for message in self._alerts.check(
            ip, name, self._state.get(ip), offline, self._settings.alert_settings(), time.time()
        ):
            self._tray.showMessage("TapoControl", message, QSystemTrayIcon.MessageIcon.Warning, 8000)

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
            self.statusBar().showMessage(action_error(error))  # stays until the next message, so it is not missed
            self.statusBar().setToolTip(str(error))

    def _render(self) -> None:
        selected = self._selected_ip()
        self._list.blockSignals(True)
        for index in reversed(range(self._list.count())):
            item = self._list.item(index)
            ip = item.data(Qt.ItemDataRole.UserRole)
            if ip not in self._devices:
                self._list.takeItem(index)
                self._cards.pop(ip).deleteLater()
        for ip in self._devices:
            if ip in self._cards:
                continue
            card = PlugCard(ip)
            self._connect_card(ip, card)
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, ip)
            item.setSizeHint(QSize(250, t.DEVICE_HEIGHT))
            self._list.addItem(item)
            self._list.setItemWidget(item, card)
            self._cards[ip] = card
        self._list.fit_cards()
        if selected in self._devices:
            self._select_ip(selected)
        elif self._list.count():
            self._list.setCurrentRow(0)
        self._list.blockSignals(False)
        self._empty.setVisible(not self._devices)
        self._list.setVisible(bool(self._devices))
        online = sum(ip in self._state for ip in self._devices)
        total = sum(w for _, w in self._state.values())
        price = self._store.price_per_kwh()
        cost = f" · {total / 1000 * price:.2f} / h" if price else ""
        self._count.setText(f"DEVICES · {len(self._devices)} plugs · {online} online · {total:.1f} W now{cost}")
        enabled = self._controller is not None and not self._auth_required
        self._scan.setEnabled(enabled and not self._scanning)
        self._scan.setText("Scanning…" if self._scanning else "Scan network")
        self._all_on.setEnabled(enabled and bool(self._devices))
        self._all_off.setEnabled(enabled and bool(self._devices))
        if self._history.set_names({ip: d.alias for ip, d in self._devices.items()}):
            if self._tabs.currentWidget() is self._history:
                self._load_history()
        self._render_cards()
        self._render_chart()
        self._render_overview()

    def _render_cards(self) -> None:
        for ip, card in self._cards.items():
            self._update_card(ip, card)
        for ip, card in self._overview.device_cards.items():
            if ip in self._devices:
                self._update_card(ip, card)

    def _connect_card(self, ip: str, card: PlugCard) -> None:
        """Both device surfaces use the same confirmed-state actions."""
        card.selected.connect(lambda ip=ip: self._select_ip(ip))
        card.power_requested.connect(lambda on, ip=ip: self._toggle_ip(ip, on))
        card.rename_requested.connect(lambda ip=ip: self._card_action(ip, "rename"))
        card.energy_requested.connect(lambda ip=ip: self._card_action(ip, "energy"))
        card.timer_requested.connect(lambda minutes, on, ip=ip: self._set_timer(ip, minutes, on))
        card.timer_cancelled.connect(lambda ip=ip: self._clear_timer(ip))

    def _update_card(self, ip: str, card: PlugCard) -> None:
        card.update_state(
            self._devices[ip].alias, self._state.get(ip), ip == self._selected_ip(),
            ip in self._power_pending or self._controller is None or self._auth_required,
            self._samples.get(ip, ()), self._store.price_per_kwh(), self._timer_note(ip),
        )
        card.show_today(self._energy[ip].today_wh if ip in self._energy else None)

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
        return any(b - a > 2.5 * REFRESH_MS / 1000 for a, b in zip(times, times[1:], strict=False))

    def _fetch_long(self) -> None:
        """Pull each plug's own 5-minute history when a long window is chosen, or to estimate across live gaps."""
        if not self._can_send():
            return
        for ip in self._devices:
            hours = self._window.currentData() or (1 if self._has_gap(ip) else 0)
            if hours:
                self._fetch_long_ip(ip, hours)

    def _fetch_long_ip(self, ip: str, hours: int) -> None:
        last = self._long_fetched.get(ip)
        if last and last[0] == hours and time.monotonic() - last[1] < LONG_REFRESH_S:
            return
        self._long_fetched[ip] = (hours, time.monotonic())

        def done(result, error):
            if error or not result:
                # Unsupported or failing history: the chart keeps our own readings plus the learned pattern.
                self._long_failed.add(ip)
                self._chart_note.setToolTip(str(error) if error else "")
            else:
                self._long_failed.discard(ip)
                self._long[ip] = result
            self._chart_note.setText(
                "A plug has no stored power history, so dashed parts are estimated from its usual day."
                if self._long_failed else ""
            )
            if not error and result:
                self._render_chart()

        self._submit(self._controller.power_history(ip, hours), done)

    def _render_chart(self) -> None:
        self._toggles.set_plugs([(ip, d.alias) for ip, d in self._devices.items()])
        hours = self._window.currentData()
        span = hours * 3600 if hours else None
        interval = 300 if hours else REFRESH_MS / 1000
        keyed_lines = self._power_lines(hours)
        title = f"{self._window.currentText()} · average watts" if hours else "Live watts"
        if not self._devices:
            title = "No plugs yet"
        self._chart.show_lines([line for key, line in keyed_lines if self._toggles.shown(key)], title, span, interval)
        live_lines = self._power_lines(0) if hours else keyed_lines
        active = [(ip, line) for ip, line in live_lines if ip in self._state and self._state[ip][0]]
        self._overview.show_power(active, "Live watts", None, REFRESH_MS / 1000)

    def _power_lines(self, hours: int) -> list[tuple[str, Line]]:
        """Build data once per requested window; the dashboard always keeps its own live window."""
        span = hours * 3600
        interval = 300 if hours else REFRESH_MS / 1000
        now = time.time()
        plugs = []  # (ip, readings, estimates)
        for ip in self._devices:
            if hours:
                points = merge_power(self._long.get(ip, []), self._store.recent_samples(ip, now - span))
                estimates = fill_gaps(points, [], self._profile(ip), 450)
            else:
                points = list(zip(self._times.get(ip, ()), self._samples.get(ip, ()), strict=True))
                estimates = list(self._long.get(ip, ()))
                if points:
                    estimates += fill_gaps(points, estimates, self._profile(ip), 2.5 * interval)
            plugs.append((ip, points, estimates))
        keyed_lines = []
        if plugs:  # the overall always sums every plug, shown or not
            total = total_series([points for _, points, _ in plugs], interval)
            keyed_lines.append((OVERALL, Line("Overall", [t for t, _ in total], [w for _, w in total])))
        for ip, points, estimates in plugs:
            times, watts = [t for t, _ in points], [w for _, w in points]
            keyed_lines.append((ip, Line(self._devices[ip].alias, times, watts, self._colors(ip), estimates)))
        return keyed_lines
