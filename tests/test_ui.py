"""UI flow checks with in-memory storage and fake controller coroutines only."""
import asyncio
import time
import os
from datetime import date
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "offscreen"

import keyring
import pytest
from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtGui import QCloseEvent, QFontDatabase
from PySide6.QtWidgets import QApplication, QPushButton

from core.controller import AuthError, EnergySummary, UsageSummary
from core.store import DeviceInfo, Store
from ui.main_window import MainWindow
from ui.theme import theme


class FakeController:
    def __init__(self):
        self.calls = []

    async def snapshot(self, ip):
        self.calls.append(("snapshot", ip))
        return True, 34.8

    async def set_power(self, ip, on):
        self.calls.append(("power", ip, on))

    async def discover(self):
        self.calls.append(("discover",))
        return []

    async def energy(self, ip):
        self.calls.append(("energy", ip))
        return EnergySummary(420, 12680)

    async def set_timer(self, ip, minutes, on):
        self.calls.append(("timer", ip, minutes, on))

    async def clear_timer(self, ip):
        self.calls.append(("clear_timer", ip))

    async def usage(self, ip):
        self.calls.append(("usage", ip))
        return UsageSummary(700, 3000, 300, 1200)

    async def power_history(self, ip, hours):
        self.calls.append(("power", ip, hours))
        return [(time.time() - 1200, 30.0), (time.time() - 900, 40.0)]

    async def hourly_today(self, ip):
        self.calls.append(("hourly", ip))
        return [5, 0, 7]

    async def daily_history(self, ip):
        self.calls.append(("history", ip))
        return [(date(2026, 11, 1), 420)]

    async def full_history(self, ip):
        self.calls.append(("history", ip))
        return [(date(2026, 11, 1), 420)]


class FakeRunner:
    def __init__(self):
        self.pending = []

    def submit(self, coro, callback):
        self.pending.append((coro, callback))

    def finish(self):
        pending, self.pending = self.pending, []
        for coro, callback in pending:
            callback(asyncio.run(coro), None)

    def close(self):
        for coro, _ in self.pending:
            coro.close()
        self.pending.clear()


@pytest.fixture(scope="module")
def app():
    application = QApplication.instance() or QApplication([])
    font_dir = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
    for font_file in ("segoeui.ttf", "segoeuib.ttf", "seguisb.ttf"):
        if (font_dir / font_file).exists():
            QFontDatabase.addApplicationFont(str(font_dir / font_file))
    return application


@pytest.fixture
def window(app, monkeypatch):
    def forbidden(*args):
        raise AssertionError("Real keyring access is forbidden")

    monkeypatch.setattr(keyring, "get_password", forbidden)
    monkeypatch.setattr(keyring, "set_password", forbidden)
    store = Store(Path(":memory:"))
    runner = FakeRunner()
    controller = FakeController()
    monkeypatch.setattr("ui.main_window.TapoController", lambda *_: controller)
    w = MainWindow(store, runner)
    w._controller = controller
    devices = [DeviceInfo("192.168.1.2", "Desk", "P110"), DeviceInfo("192.168.1.3", "Lamp", "P110")]
    store.save_devices(devices)
    w._devices = {d.ip: d for d in devices}
    w._state = {devices[0].ip: (True, 34.8), devices[1].ip: (False, 0.0)}
    w._render()
    yield w, runner, controller
    w._timer.stop()
    w._tray.hide()
    w.hide()
    runner.close()
    w.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()
    store.close()


def test_card_toggle_targets_clicked_plug_and_waits_for_snapshot(window):
    w, runner, controller = window
    card = w._cards["192.168.1.3"]
    card.toggle.click()
    assert w._selected_ip() == "192.168.1.3"
    assert not card.toggle.isChecked()
    assert not card.toggle.isEnabled()
    runner.finish()
    assert ("power", "192.168.1.3", True) in controller.calls
    runner.finish()
    assert card.toggle.isChecked()
    assert card.toggle.isEnabled()


def test_refresh_preserves_card_identity_and_selection(window):
    w, _, _ = window
    w._list.setCurrentRow(1)
    card = w._cards["192.168.1.3"]
    w._state["192.168.1.3"] = (True, 9.5)
    w._render()
    assert w._cards["192.168.1.3"] is card
    assert w._selected_ip() == "192.168.1.3"
    assert card.toggle.isChecked()
    w._state.pop("192.168.1.3")
    w._render()
    assert not card.toggle.isEnabled()
    assert card.property("offline") is True


def test_resizing_keeps_card_controls_inside_viewport(window, app):
    w, _, _ = window
    w._tabs.setCurrentWidget(w._tabs.widget(1))  # Devices
    w.show()
    app.processEvents()
    w.resize(760, 640)
    app.processEvents()
    card = w._cards["192.168.1.2"]
    assert card.width() <= w._list.viewport().width()
    assert card._menu.geometry().right() < card.width()


def test_auth_failure_uses_account_tab_and_resumes_after_submission(window, monkeypatch):
    w, runner, _ = window
    saved = []
    monkeypatch.setattr(keyring, "set_password", lambda *values: saved.append(values))
    w._timer.start()
    w._on_error(AuthError("fake rejected credentials"))
    assert w._tabs.currentWidget() is w._login
    assert not w._timer.isActive()
    assert w._auth_required
    w.scan()
    w.set_all_power(True)
    assert not runner.pending
    w._login.email.setText("test@example.invalid")
    w._login.password.setText("fake-password")
    w._login._accept()
    assert saved == [("TapoControl", "test@example.invalid", "fake-password")]
    assert not w._auth_required
    assert w._timer.isActive()
    assert not w._login.password.text()
    assert w._tabs.currentIndex() == 1
    assert len(runner.pending) == 4  # snapshots and today's device energy, per plug


def test_initial_account_tab_submission_scans_when_no_devices(window, monkeypatch):
    w, runner, _ = window
    monkeypatch.setattr(keyring, "set_password", lambda *_: None)
    w._store.save_devices([])
    w._devices.clear()
    w._controller = None
    w.start()
    assert w._tabs.currentWidget() is w._login
    assert not runner.pending
    w._login.email.setText("test@example.invalid")
    w._login.password.setText("fake-password")
    w._login._accept()
    runner.finish()
    assert w._tabs.currentIndex() == 1


def test_new_account_ignores_old_energy_and_snapshot_auth_errors(window, monkeypatch):
    w, runner, _ = window
    monkeypatch.setattr(keyring, "set_password", lambda *_: None)
    w._show_history()
    old_energy = runner.pending[0][1]
    w.refresh()
    old_snapshot = runner.pending[2][1]
    w._login.email.setText("test@example.invalid")
    w._login.password.setText("fake-password")
    w._login._accept()
    old_energy(None, AuthError("old account"))
    old_snapshot(None, AuthError("old account"))
    assert not w._auth_required
    assert w._timer.isActive()
    assert not w._history._names


def test_other_snapshot_does_not_enable_switch_before_confirmation(window):
    w, runner, _ = window
    card = w._cards["192.168.1.3"]
    card.toggle.click()
    runner.finish()
    coro, other_snapshot = runner.pending.pop(0)
    coro.close()
    other_snapshot((True, 34.8), None)
    w._list.setCurrentRow(0)
    assert not card.toggle.isEnabled()
    runner.finish()
    assert card.toggle.isEnabled()


def test_snapshot_started_before_toggle_cannot_confirm_power(window):
    w, runner, _ = window
    w.refresh()
    card = w._cards["192.168.1.3"]
    card.toggle.click()
    coro, power_done = runner.pending.pop()
    coro.close()
    power_done(None, None)
    coro, old_snapshot = runner.pending.pop(1)
    coro.close()
    old_snapshot((False, 0.0), None)
    assert not card.toggle.isEnabled()
    runner.finish()
    assert card.toggle.isEnabled()
    assert card.toggle.isChecked()


def test_energy_rejects_old_selection_callbacks_and_preserves_raw_error(window):
    w, runner, controller = window
    panel = w._history
    panel.load(controller, {"192.168.1.2": "Desk"})
    old_callback = runner.pending[0][1]
    panel.load(controller, {"192.168.1.3": "Lamp"})
    runner.finish()
    old_callback(EnergySummary(999999, 999999), None)
    assert panel._today.text() == "0.42 kWh"
    panel._on_summary("192.168.1.3", None, TimeoutError("exact low-level message"))
    assert "timed out" in panel._summary_error.text()
    assert panel._summary_error.toolTip() == "exact low-level message"


def test_tab_energy_actions_and_live_theme_changes(window):
    w, runner, _ = window
    w._cards["192.168.1.3"].energy_requested.emit()
    assert w._selected_ip() == "192.168.1.3"
    assert w._tabs.currentWidget() is w._history
    runner.finish()
    w._chart.show_samples([1.0, 2.0], "x")
    for scheme in (Qt.ColorScheme.Dark, Qt.ColorScheme.Light):
        theme().apply(scheme)
        assert w._chart._lines[0].pen().color().name() == theme().colors.text


def test_card_rename_and_all_power_keep_existing_actions(window, monkeypatch):
    w, runner, controller = window
    monkeypatch.setattr("ui.main_window.QInputDialog.getText", lambda *args, **kwargs: ("New nickname", True))
    w._cards["192.168.1.3"].rename_requested.emit()
    assert w._devices["192.168.1.3"].alias == "New nickname"
    assert w._selected_ip() == "192.168.1.3"
    w.set_all_power(False)
    runner.finish()
    assert ("power", "192.168.1.2", False) in controller.calls
    assert ("power", "192.168.1.3", False) in controller.calls


def test_close_hides_to_tray_and_show_restores(window, app):
    w, _, _ = window
    w.show()
    app.processEvents()
    event = QCloseEvent()
    w.closeEvent(event)
    assert not event.isAccepted()
    assert not w.isVisible()
    w.show_window()
    assert w.isVisible()


def test_energy_history_is_stored_and_range_switches_to_monthly(window):
    w, runner, controller = window
    panel = w._history
    panel.load(controller, {"192.168.1.2": "Desk"})
    runner.finish()
    assert not w._store.backfilled("192.168.1.2")  # current quarter shows first
    runner.finish()  # then the one-off backfill of older quarters
    assert w._store.backfilled("192.168.1.2")
    assert w._store.daily("192.168.1.2") == [(date(2026, 11, 1), 420)]
    panel._range.setCurrentIndex(3)
    assert panel._chart._kind == "month"
    panel._range.setCurrentIndex(0)
    runner.finish()
    assert panel._chart._kind == "hour" and panel._chart._keys == [0, 1, 2]
    assert panel._chart._lines[0].wh == [5, 0, 7]
    assert "Last 7 days: 0.70 kWh" in panel._usage.text()
    panel.load(controller, {"192.168.1.2": "Desk"})  # second open: stored rows still shown
    assert panel._rows == {}  # cleared until the plug answers


def test_live_chart_breaks_line_over_gap_and_keeps_restored_samples():
    import time

    from ui.charts import LiveChart

    chart = LiveChart(120)
    now = time.time()
    chart.show_samples([5.0, 6.0, 7.0], "x", [now - 400, now - 395, now - 5])
    assert len(chart._lines) == 2  # app was closed between the second and third reading
    assert len(chart._bridges) == 1  # dashed link across that gap
    chart.show_samples([5.0], "x", [now - 900])  # older than the 10 minute window
    assert chart._lines == [] and chart._points == [[]]


def test_long_chart_window_fetches_plug_history_and_ignores_failure(window):
    w, runner, controller = window
    w._window.setCurrentIndex(1)  # last hour
    runner.finish()
    assert ("power", w._selected_ip(), 24) in controller.calls  # a day, so the chart can scroll back
    assert w._chart._names == ["Overall", "Desk", "Lamp"]
    assert [w for _, w in w._chart._points[0]] == [60.0, 80.0]  # overall: both plugs summed
    assert "average watts" in w._chart.chart().title()
    ip = w._selected_ip()
    before = list(w._long[ip])
    w._long_fetched.clear()
    w._fetch_long()
    runner.pending[-1][1](None, RuntimeError("unsupported"))  # failure keeps what the chart already had
    assert w._long[ip] == before and len(w._chart._points[0]) == 2


def test_chart_toggles_hide_lines_but_overall_still_sums_every_plug(window):
    w, runner, _ = window
    w._window.setCurrentIndex(1)
    runner.finish()
    colors = dict(w._colors._slots)
    assert len(colors) == 2 and len(set(colors.values())) == 2
    w._toggles._boxes["192.168.1.2"].setChecked(False)
    assert w._chart._names == ["Overall", "Lamp"]
    assert [v for _, v in w._chart._points[0]] == [60.0, 80.0]
    assert w._colors._slots == colors  # the others keep their colors
    w._toggles._boxes["overall"].setChecked(False)
    assert w._chart._names == ["Lamp"]
    w._toggles._boxes["192.168.1.2"].setChecked(True)
    assert w._chart._names == ["Desk", "Lamp"]


def test_chart_hover_lists_every_line_at_the_cursor():
    from ui.charts import Line, LiveChart

    chart = LiveChart(120)
    now = time.time()
    chart.show_lines([Line("A", [now - 5], [1.0]), Line("B", [now - 6], [2.0], 0)], "x")
    rows = chart._rows_at(chart._slot(now - 5))
    assert [(i, v) for i, _, v in rows] == [(0, 1.0), (1, 2.0)]


def test_energy_chart_sums_plugs_and_toggles_lines(window):
    w, runner, controller = window
    panel = w._history
    panel.load(controller, {"192.168.1.2": "Desk", "192.168.1.3": "Lamp"})
    runner.finish()
    runner.finish()
    assert panel._today.text() == "0.84 kWh"  # both plugs added up
    assert [line.name for line in panel._chart._lines] == ["Desk", "Lamp"]  # one stacked segment per plug
    assert panel._chart._totals() == [840]  # the whole bar is the overall
    desk = panel._chart._lines[0].wh[0]
    panel._toggles._boxes["192.168.1.2"].setChecked(False)  # filtering a plug out restacks the rest
    assert [line.name for line in panel._chart._lines] == ["Lamp"]
    assert panel._chart._totals() == [840 - desk]
    assert panel._today.text() == "0.84 kWh"  # the summary cards still count every plug
    assert panel._colors("192.168.1.3") == w._colors("192.168.1.3")  # same color on both tabs


def test_energy_follows_renames_and_clears_when_plugs_change(window):
    w, runner, controller = window
    panel = w._history
    panel.load(controller, {"192.168.1.2": "Desk", "192.168.1.3": "Lamp"})
    runner.finish()
    assert not panel.set_names({"192.168.1.2": "Desk 2", "192.168.1.3": "Lamp"})
    assert [line.name for line in panel._chart._lines][0] == "Desk 2"
    assert panel.set_names({"192.168.1.2": "Desk 2"})
    assert not panel._names


def test_gap_is_dashed_through_plug_estimates():
    from ui.charts import LiveChart

    chart = LiveChart(120)
    now = time.time()
    estimates = [(now - 300, 50.0), (now - 100, 60.0)]
    chart.show_samples([5.0, 6.0], "x", [now - 500, now - 20], estimates=estimates)
    [bridge] = chart._bridges
    assert bridge.count() == 4  # last reading, two plug averages inside the gap, next reading
    chart.show_samples([5.0, 6.0], "x", [now - 500, now - 20])
    assert chart._bridges[0].count() == 2  # no estimates: straight dashed line


def test_cards_show_hourly_cost_when_a_tariff_is_set(window):
    w, runner, _ = window
    w._store.set_price_per_kwh(10.0)
    w._state["192.168.1.3"] = (True, 100.0)
    w._render()
    assert w._cards["192.168.1.3"]._cost.text() == "1.00 / h"
    assert "/ h" in w._count.text()
    w._store.set_price_per_kwh(0.0)
    w._render()
    assert w._cards["192.168.1.3"]._cost.text() == ""


def test_alert_notification_uses_tray_and_settings_tab_saves(window, monkeypatch):
    w, runner, _ = window
    shown = []
    monkeypatch.setattr(w._tray, "showMessage", lambda title, text, *args: shown.append(text))
    w._settings.watts.setValue(50)
    assert w._store.setting("alert_watts") == "50"
    w._on_snapshot("192.168.1.3", (True, 80.0), None)
    assert shown and "80 W" in shown[0]
    w._on_snapshot("192.168.1.3", (True, 90.0), None)
    assert len(shown) == 1


def test_csv_export_writes_shown_rows(window, monkeypatch, tmp_path):
    from PySide6.QtWidgets import QFileDialog

    w, runner, controller = window
    panel = w._history
    panel.load(controller, {"192.168.1.2": "Desk"})
    runner.finish()
    runner.finish()
    target = tmp_path / "out.csv"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (str(target), ""))
    panel._range.setCurrentIndex(3)  # all time, monthly
    assert panel._export.isEnabled()
    panel._export_csv()
    runner.finish()
    assert target.read_text(encoding="utf-8").splitlines()[0] == "month,kWh,cost"
    assert "days stored since" in panel._detail.text()


def test_timer_menu_sets_timer_and_card_shows_countdown(window):
    from ui.plug_card import timer_note

    w, runner, controller = window
    ip = "192.168.1.3"
    w._cards[ip].timer_requested.emit(30, False)
    runner.finish()
    assert ("timer", ip, 30, False) in controller.calls
    w._render_cards()
    assert w._cards[ip]._ip.text() == f"{ip} · off in 30 min"
    w._cards[ip].timer_cancelled.emit()
    runner.finish()
    assert ("clear_timer", ip) in controller.calls and w._cards[ip]._ip.text() == ip
    assert timer_note(95 * 60, True) == "on in 1 h 35 min" and timer_note(5, False) == "off in 1 min"


def test_side_tabs_switch_pages_and_report_changes(app):
    from PySide6.QtWidgets import QLabel

    from ui.side_tabs import SideTabs

    tabs = SideTabs()
    first, second = QLabel("a"), QLabel("b")
    tabs.addTab(first, "overview", "Overview")
    tabs.addTab(second, "settings", "Settings", bottom=True)
    seen = []
    tabs.currentChanged.connect(seen.append)
    assert tabs.currentWidget() is first and tabs._buttons[0].isChecked()
    tabs._buttons[1].click()
    assert tabs.currentWidget() is second and seen == [1] and tabs._buttons[1].isChecked()
    tabs.setCurrentWidget(second)  # already open: no change signal
    assert seen == [1] and tabs.widget(0) is first
    assert tabs._buttons[0].toolTip() == "Overview (Ctrl+1)" and tabs._buttons[0].accessibleName() == "Overview"
    assert not tabs._buttons[0].icon().isNull() and tabs.kind(1) == "settings"


def test_sidebar_collapse_preserves_page_and_keyboard_labels(app):
    from PySide6.QtWidgets import QLabel

    from ui.side_tabs import SideTabs

    tabs = SideTabs()
    tabs.addTab(QLabel("overview"), "overview", "Overview")
    settings = QLabel("settings")
    tabs.addTab(settings, "settings", "Settings", bottom=True)
    tabs.setCurrentWidget(settings)
    tabs.show()
    app.processEvents()
    assert tabs._rail.width() == 212
    assert tabs._buttons[0].text() == "Overview"
    tabs.collapse_button.click()
    app.processEvents()
    assert tabs._rail.width() == 76
    assert tabs.currentWidget() is settings
    assert tabs._buttons[0].toolTip() == "Overview (Ctrl+1)"
    assert tabs._buttons[0].accessibleName() == "Overview"
    tabs._buttons[0].click()
    assert tabs.currentIndex() == 0
    tabs.collapse_button.click()
    assert tabs._rail.width() == 212
    tabs.hide()


@pytest.mark.parametrize("scheme", [Qt.ColorScheme.Light, Qt.ColorScheme.Dark])
@pytest.mark.parametrize("collapsed", [False, True])
def test_sidebar_footer_controls_align_with_navigation(window, app, scheme, collapsed):
    w, _, _ = window
    sidebar = w._tabs
    theme().apply(scheme)
    sidebar.set_collapsed(collapsed)
    w.show()
    app.processEvents()
    navigation = sidebar._buttons[0]
    for button in (*sidebar._buttons, sidebar.theme_button, sidebar.collapse_button):
        assert button.size() == navigation.size()
        assert button.iconSize() == navigation.iconSize()
        assert button.geometry().left() == navigation.geometry().left()
        assert button.toolButtonStyle() == navigation.toolButtonStyle()
    assert sidebar.collapse_button.text() == ("Expand sidebar" if collapsed else "Collapse sidebar")
    selected = sidebar.currentWidget()
    sidebar.theme_button.click()
    assert sidebar.currentWidget() is selected
    sidebar.collapse_button.click()
    assert sidebar.currentWidget() is selected
    theme().set_mode("light")


def test_overview_controls_target_plug_and_wait_for_confirmation(window):
    w, runner, controller = window
    card = w._overview.device_cards["192.168.1.3"]
    card.toggle.click()
    assert not card.toggle.isChecked()
    assert not card.toggle.isEnabled()
    runner.finish()
    assert ("power", "192.168.1.3", True) in controller.calls
    assert not card.toggle.isEnabled()
    runner.finish()
    assert card.toggle.isChecked() and card.toggle.isEnabled()


def test_overview_partial_energy_is_marked_and_offline_card_stays_unknown(window):
    w, _, _ = window
    w._energy = {"192.168.1.2": EnergySummary(1000, 5000)}
    w._state.pop("192.168.1.3")
    w._render()
    assert "1 of 2" in w._overview._today_cost.text()
    assert "partial" in w._overview._today_cost.text().lower()
    offline = w._overview.device_cards["192.168.1.3"]
    assert not offline.toggle.isEnabled()
    assert offline._watts.text() == "—"
    assert offline.today.text() == "— kWh today"


def test_overview_does_not_report_zero_when_no_plugs_answer(window):
    w, _, _ = window
    w._state.clear()
    w._render()
    assert w._overview._now.text() == "—"
    assert "Waiting" in w._overview._now_cost.text()


def test_overview_collapsed_sidebar_keeps_rows_without_replacing_them(window, app):
    w, _, _ = window
    w.show()
    w.resize(1440, 1060)
    app.processEvents()
    before = w._overview.device_cards["192.168.1.3"]
    w._tabs.collapse_button.click()
    w.resize(760, 640)
    app.processEvents()
    assert w._overview.device_cards["192.168.1.3"] is before
    assert before.toggle.geometry().right() < before.width()


def test_overview_long_alias_and_many_plugs_remain_scrollable(window, app):
    w, _, _ = window
    first = "192.168.1.2"
    long_name = "Workstation " * 40
    w._devices[first] = DeviceInfo(first, long_name, "P110")
    for n in range(4, 15):
        ip = f"192.0.2.{n}"
        w._devices[ip] = DeviceInfo(ip, f"Plug {n}", "P110")
        w._state[ip] = (False, 0.0)
    w._render()
    w.show()
    w.resize(760, 640)
    for _ in range(3):
        app.processEvents()
    card = w._overview.device_cards[first]
    assert card._name.toolTip() == long_name
    assert card.toggle.geometry().right() < card.width()
    scroll = w._overview.verticalScrollBar()
    assert scroll.maximum() > 0
    scroll.setValue(scroll.maximum())
    app.processEvents()
    last = w._overview.device_cards["192.0.2.14"]
    assert w._overview.viewport().rect().contains(last.mapTo(w._overview.viewport(), last.rect().center()))


def test_live_chart_scaling_preserves_detail_at_typical_plug_load(app):
    from ui.charts import LiveChart

    chart = LiveChart(120)
    chart.show_samples([182.4, 225.2], "Live watts")
    assert chart._y.min() == 0
    assert chart._y.max() == 300
    assert chart._y.tickCount() == 4


def test_overview_range_buttons_share_the_chart_range(window):
    w, _, _ = window
    assert w._overview._chart._span == 600
    w._overview._ranges.button(1).click()
    assert w._window.currentIndex() == 1
    assert w._chart._span == 3600 and w._overview._chart._span == 3600
    w._window.setCurrentIndex(0)
    assert w._overview._ranges.button(0).isChecked()
    assert w._overview._chart._span == 600


def test_overview_keeps_confirmed_zero_watt_readings(window):
    from collections import deque

    w, _, _ = window
    ip = "192.168.1.2"
    w._state[ip] = (True, 0.0)
    w._samples[ip] = deque([0.0])
    w._times[ip] = deque([time.time()])
    w._render()
    assert w._overview._chart._names == ["Desk"]
    assert w._overview._chart._points[0][-1][1] == 0.0


def test_long_chart_legend_elides_and_retains_accessible_name(app):
    from ui.charts import LineColors, LineToggles

    label = "Very long workstation alias " * 8
    toggles = LineToggles(LineColors(), include_overall=False)
    toggles.set_plugs([("plug", label)])
    toggles.resize(240, 40)
    toggles.show()
    app.processEvents()
    box = toggles._boxes["plug"]
    assert box.geometry().right() < toggles.width()
    assert box.text() != label
    assert box.toolTip() == label
    assert box.accessibleName() == label
    box.click()
    assert not toggles.shown("plug")
    toggles.hide()


def test_overview_shows_totals_and_fetches_once_a_minute(window):
    w, runner, controller = window
    assert w._tabs.currentWidget() is w._overview
    w.refresh()
    runner.finish()
    assert w._overview._today.text() == "0.84 kWh"  # both plugs added up
    assert w._overview._now.text() == "69.6 W"  # the fake snapshot gives 34.8 W per plug
    assert w._overview._plugs.text() == "2 / 2"
    assert w._overview._chart._names == ["Desk", "Lamp"]
    assert w._overview._chart._points[0][-1][1] == 34.8  # live watts, not hourly energy
    w._toggles._boxes["overall"].setChecked(False)  # the Devices toggles are separate
    assert w._overview._chart._names == ["Desk", "Lamp"]
    controller.calls.clear()
    w.refresh()
    runner.finish()
    assert ("energy", "192.168.1.2") not in controller.calls  # fetched less than a minute ago
    w._tabs.setCurrentWidget(w._login)
    w._overview_fetched.clear()
    w.refresh()
    assert not any(c[0] == "energy" for c in controller.calls)  # nothing fetched while the Overview is closed


def test_headline_names_the_open_page(window):
    w, _, _ = window
    seen = {}
    for index in range(5):
        w._tabs.setCurrentIndex(index)
        seen[w._tabs.kind(index)] = w._headline.text()
    assert list(seen.values()) == ["Overview", "Devices", "Energy", "Account", "Settings"]


def test_scan_shows_pending_state_and_recovers_on_failure(window):
    w, runner, _ = window
    w.scan()
    assert w._scan.text() == "Scanning…" and not w._scan.isEnabled()
    w._render()  # the 5 second refresh must not re-enable it while the scan runs
    assert not w._scan.isEnabled()
    runner.pending[-1][1](None, TimeoutError("slow"))
    assert w._scan.text() == "Scan network" and w._scan.isEnabled()
    assert "did not answer in time" in w.statusBar().currentMessage()  # plain words, kept until replaced


def test_login_confirms_only_after_a_plug_answers(window, monkeypatch):
    w, runner, _ = window
    monkeypatch.setattr(keyring, "set_password", lambda *_: None)
    w._login.email.setText("test@example.invalid")
    w._login.password.setText("fake-password")
    w._login._accept()
    assert "Checking" in w._login._message.text()  # saved, not yet confirmed
    runner.finish()
    assert w._login._message.text().startswith("Signed in")


def test_toggle_swatches_follow_the_theme(app):
    from ui.charts import LineColors, LineToggles
    from ui.theme import DARK, LIGHT

    toggles = LineToggles(LineColors())
    toggles.set_plugs([("a", "Desk")])
    seen = []
    for scheme in (Qt.ColorScheme.Dark, Qt.ColorScheme.Light):
        theme().apply(scheme)
        box = toggles._boxes["overall"]
        box.resize(box.sizeHint())
        box.show()
        app.processEvents()
        seen.append(box.grab().toImage().pixelColor(3, box.height() // 2).name())
    assert seen == [DARK.text, LIGHT.text]  # the overall wears the text color on each theme


def test_theme_toggle_flips_scheme_and_buttons_get_pointer_cursor(app):
    theme().set_mode("light")
    theme().cycle()
    assert (theme().mode, theme().dark) == ("dark", True)
    theme().cycle()
    assert theme().mode == "system"
    theme().set_mode("light")
    button = QPushButton()
    button.ensurePolished()
    assert button.cursor().shape() == Qt.CursorShape.PointingHandCursor


def test_clickable_widgets_show_pointer_and_animate_hover_and_press(app):
    theme()  # the application-wide filter that adds cursors and hover layers lives on the theme
    from PySide6.QtCore import QEvent, QPointF
    from PySide6.QtGui import QEnterEvent, QMouseEvent
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QComboBox

    from ui.interaction import PressOverlay

    button = QPushButton("Go")
    button.resize(80, 32)
    button.ensurePolished()
    overlay = button.findChild(PressOverlay)
    assert overlay and overlay._hover.value == 0
    app.sendEvent(button, QEnterEvent(QPointF(5, 5), QPointF(5, 5), QPointF(5, 5)))
    QTest.qWait(250)
    assert overlay._hover.value == 1
    press = QMouseEvent(QEvent.Type.MouseButtonPress, QPointF(5, 5), Qt.MouseButton.LeftButton,
                        Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    app.sendEvent(button, press)
    QTest.qWait(250)
    assert overlay._press.value == 1
    button.setEnabled(False)
    assert button.cursor().shape() == Qt.CursorShape.ArrowCursor
    combo = QComboBox()
    combo.ensurePolished()
    assert combo.cursor().shape() == Qt.CursorShape.PointingHandCursor


def test_hover_animates_on_switches_and_steppers_and_follows_the_cursor_under_a_popup(app):
    theme()  # the application-wide filter that adds cursors and hover layers lives on the theme
    from PySide6.QtCore import QPoint
    from PySide6.QtTest import QTest

    from ui.interaction import PressOverlay
    from ui.page_layout import IntBox
    from ui.plug_card import PowerSwitch

    switch = PowerSwitch()
    switch.show()
    switch.enterEvent(None)
    QTest.qWait(250)
    assert switch._hover.value == 1
    switch.leaveEvent(None)
    QTest.qWait(250)
    assert switch._hover.value == 0

    box = IntBox(maximum=10)
    box.show()
    up = box._button_rects()["up"]
    box._hover_button(up.center())
    assert box.cursor().shape() == Qt.CursorShape.PointingHandCursor and box._fades["up"].goal == 1
    box._hover_button(None)
    assert box._fades["up"].goal == 0 and box.cursor().shape() != Qt.CursorShape.PointingHandCursor

    button = QPushButton("Go")
    button.show()
    button.ensurePolished()
    overlay = button.findChild(PressOverlay)
    overlay.poll_hover(button, QPoint())  # a dropdown is open, so Qt sends no Enter event; the poller reports it
    assert overlay._hover.goal == 1
    overlay.poll_hover(None, QPoint())
    assert overlay._hover.goal == 0
    for widget in (switch, box, button):
        widget.close()


def test_split_button_runs_main_action_and_opens_menu_that_turns_the_chevron(app):
    theme()  # the application-wide filter that adds cursors and hover layers lives on the theme
    from PySide6.QtTest import QTest

    from ui.split_button import SplitButton

    ran = []
    split = SplitButton("Export CSV…")
    split.add_action("Copy CSV to clipboard", lambda: ran.append("copy"))
    split.main.clicked.connect(lambda: ran.append("main"))
    split.show()
    QTest.qWaitForWindowActive(split)
    split.main.click()
    assert ran == ["main"]
    split.main.setEnabled(False)
    assert not split.arrow.isEnabled()
    split.main.setEnabled(True)
    assert split.arrow.isEnabled() and split.arrow.accessibleName() == "More options for Export CSV"
    split.arrow.click()
    QTest.qWait(400)
    assert split.menu.isVisible() and split.arrow.angle == 180
    split.menu.actions()[0].trigger()
    split.menu.hide()
    QTest.qWait(400)
    assert ran == ["main", "copy"] and split.arrow.angle == 0


def test_devices_rows_look_like_overview_rows_and_keep_their_size_when_the_chart_hides(window):
    w, _, _ = window
    device = w._cards["192.168.1.2"]
    compact = w._overview.device_cards["192.168.1.2"]
    assert device._timer_button.menu() is not None
    assert device.height() == compact.height() == 48
    assert device.toggle.size() == compact.toggle.size()
    assert device.cursor().shape() != Qt.CursorShape.PointingHandCursor
    before = device.height()
    w._devices_page.chart_toggle.click()
    assert w._devices_page.chart_body.isHidden()
    assert device.height() == before
    w._devices_page.chart_toggle.click()
    assert not w._devices_page.chart_body.isHidden()


def test_energy_filter_controls_totals_and_export_without_new_requests(window):
    w, runner, controller = window
    panel = w._history
    panel.load(controller, {ip: d.alias for ip, d in w._devices.items()})
    runner.finish()
    runner.finish()
    assert panel._today.text() == "0.84 kWh"
    assert panel._cost_today.text() == "—"
    pending = len(runner.pending)
    panel._device_filter.setCurrentIndex(1)
    assert panel._today.text() == "0.42 kWh"
    assert sum(wh for _, wh in panel._shown[0]) == 420
    assert len(runner.pending) == pending
    panel._price.setValue(10)
    assert panel._cost_today.text() == "4.20"
    panel._device_filter.setCurrentIndex(0)
    assert panel._cost_today.text() == "8.40"


def test_energy_partial_totals_are_explicit_and_clear_resets_costs(window):
    w, _, controller = window
    panel = w._history
    panel.load(controller, {ip: d.alias for ip, d in w._devices.items()})
    panel._on_summary("192.168.1.2", EnergySummary(1000, 5000), None)
    assert "1 of 2" in panel._coverage.text()
    panel._price.setValue(10)
    assert panel._cost_today.text() == "10.00"
    panel.clear()
    assert panel._cost_today.text() == "—"
    assert panel._breakdown.note.text() == "Waiting for energy readings"


def test_settings_theme_selector_tracks_sidebar_and_persists(window):
    w, _, _ = window
    w._settings.appearance.setCurrentIndex(w._settings.appearance.findData("dark"))
    assert theme().mode == "dark"
    assert w._store.setting("theme") == "dark"
    w._tabs.theme_button.click()
    assert w._settings.appearance.currentData() == theme().mode
    assert w._store.setting("theme") == theme().mode
    theme().set_mode("light")


def test_signin_opens_devices_and_preserves_overview_fetch_on_visit(window, monkeypatch):
    w, runner, _ = window
    monkeypatch.setattr(keyring, "set_password", lambda *_: None)
    w._login.email.setText("test@example.invalid")
    w._login.password.setText("fake-password")
    w._login._accept()
    assert w._tabs.kind(w._tabs.currentIndex()) == "devices"
    assert len(runner.pending) == 4  # power snapshot and device energy per plug
    w._tabs.setCurrentWidget(w._overview)
    assert len(runner.pending) == 10  # Overview retains its energy/hour/day fetches


@pytest.mark.parametrize("collapsed", [False, True])
@pytest.mark.parametrize("page_index", [1, 2, 3, 4])
def test_control_pages_keep_actions_inside_small_window(window, app, collapsed, page_index):
    w, _, _ = window
    w._devices["192.168.1.2"] = DeviceInfo("192.168.1.2", "Very long device name " * 20, "P110")
    w._render()
    w._tabs.set_collapsed(collapsed)
    w._tabs.setCurrentIndex(page_index)
    w.resize(760, 640)
    w.show()
    for _ in range(3):
        app.processEvents()
    page = w._tabs.currentWidget()
    assert page.horizontalScrollBar().maximum() == 0
    controls = {
        1: [w._cards["192.168.1.2"].toggle, w._cards["192.168.1.2"]._timer_button],
        2: [w._history._device_filter, w._history._range, w._history._export],
        3: [w._login.email, w._login.password, w._login._submit],
        4: [w._settings.appearance, w._settings.watts, w._settings.minutes, w._settings.offline],
    }
    for control in controls[page_index]:
        right = control.mapTo(page.viewport(), control.rect().topRight()).x()
        assert 0 < right < page.viewport().width()


def test_direct_timer_menu_runs_existing_async_action(window):
    w, runner, controller = window
    card = w._cards["192.168.1.2"]
    card._timer_button.menu().actions()[1].trigger()
    runner.finish()
    assert ("timer", "192.168.1.2", 30, False) in controller.calls


def test_export_keeps_snapshot_and_prevents_duplicate_jobs(window, monkeypatch, tmp_path):
    from PySide6.QtWidgets import QFileDialog

    w, runner, controller = window
    panel = w._history
    panel.load(controller, {ip: d.alias for ip, d in w._devices.items()})
    runner.finish()
    runner.finish()
    target = tmp_path / "filtered.csv"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (str(target), ""))
    panel._device_filter.setCurrentIndex(1)
    panel._price.setValue(10)
    panel._export_csv()
    panel._device_filter.setCurrentIndex(0)
    panel._price.setValue(20)
    assert not panel._export.isEnabled()
    pending = len(runner.pending)
    panel._export_csv()
    assert len(runner.pending) == pending
    runner.finish()
    assert panel._export.isEnabled()
    assert target.read_text(encoding="utf-8").splitlines()[1].endswith(",0.420,4.20")


def test_stale_export_error_does_not_pollute_new_selection(window, monkeypatch, tmp_path):
    from PySide6.QtWidgets import QFileDialog

    w, runner, _ = window
    panel = w._history
    panel._shown = ([(date(2026, 11, 1), 420)], "day")
    target = tmp_path / "old.csv"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (str(target), ""))
    panel._export_csv()
    coro, callback = runner.pending.pop()
    coro.close()
    panel.clear()
    callback(None, OSError("old error"))
    assert not panel._exporting
    assert panel._history_error.isHidden()
    assert not panel._export.isEnabled()


def test_split_button_halves_have_the_same_height(app):
    from ui import tokens
    from ui.split_button import SplitButton

    theme()
    split = SplitButton("Export CSV…")
    split.show()
    app.processEvents()
    assert split.main.height() == split.arrow.height() == tokens.SPLIT_HEIGHT
    split.close()


def test_focus_ring_shows_only_after_keyboard_focus(app):
    theme()
    from PySide6.QtTest import QTest

    button = QPushButton("Go")
    button.show()
    QTest.qWaitForWindowActive(button)  # focus events only arrive in an active window
    button.setFocus(Qt.FocusReason.MouseFocusReason)
    assert not button.property("kbd")
    button.clearFocus()
    button.setFocus(Qt.FocusReason.TabFocusReason)
    assert button.property("kbd")
    button.clearFocus()
    assert not button.property("kbd")
    button.close()


def test_poller_applies_the_pointer_under_the_cursor_while_a_popup_owns_the_mouse(app):
    from PySide6.QtWidgets import QApplication

    from ui.interaction import _poller

    theme()
    button = QPushButton("Go")
    button.ensurePolished()
    _poller._follow_cursor(button)
    assert QApplication.overrideCursor().shape() == Qt.CursorShape.PointingHandCursor
    _poller._follow_cursor(None)
    assert QApplication.overrideCursor() is None


def test_usage_chart_pans_through_a_window_and_marks_the_forecast(app):
    from datetime import timedelta
    from ui.charts import UsageChart, UsageLine

    chart = UsageChart()
    chart.resize(800, 300)
    days = [date(2026, 10, 1) + timedelta(days=n) for n in range(60)]
    chart.show_lines([UsageLine("Desk", 0, [100] * 60)], days, "day", forecast_from=53)
    moved = []
    chart.view_changed.connect(lambda: moved.append(chart.start()))
    assert chart.window_size() == 30 and chart.start() == chart.max_start() == 30  # parked on the forecast end
    chart.set_start(-5)
    assert chart.start() == 0 and moved == [0]
    chart.set_start(999)
    assert chart.start() == 30
    chart._hover = 55
    assert chart._readout(chart._plot_area())[1].endswith("forecast")
    chart.show_lines([UsageLine("Desk", 0, [100] * 60)], days, "day", forecast_from=53)
    assert chart.start() == 30  # a refresh keeps the view parked at the end
    chart.set_start(10)
    chart.show_lines([UsageLine("Desk", 0, [100] * 60)], days, "day", forecast_from=53)
    assert chart.start() == 10  # and keeps a panned view where it was


def test_live_chart_pans_back_and_shows_a_forecast_after_now(app):
    from PySide6.QtTest import QTest
    from ui.charts import Line, LiveChart

    chart = LiveChart(120)
    chart.resize(800, 300)
    now = time.time()
    times = [now - 7200 + i * 300 for i in range(25)]  # two hours of 5-minute readings
    ahead = [(now + 900 * step / 12, 40.0) for step in range(1, 13)]
    chart.show_lines([Line("Desk", times, [30.0] * 25, 0, (), ahead)], "t", 3600, 300)
    assert chart._ahead > 0 and chart.can_pan()
    assert chart._label_row()[-1][1].startswith("in ")  # the right edge is in the future
    chart.show()
    QTest.qWait(100)
    chart._hover = chart._hover_at(chart._plot_area().right() - 5)
    assert "forecast" in chart._readout(chart._plot_area())[1]
    chart.close()
    chart.pan_to(now - 3600)
    assert chart._view_end_held is not None and chart._points[0]  # an earlier hour, still drawn
    chart.pan_to(0)
    assert chart._view_end == chart._earliest_end()  # never past the oldest reading
    chart.show_lines([Line("Desk", times, [30.0] * 25, 0, (), ahead)], "t", 3600, 300)
    assert chart._view_end_held is not None  # a refresh keeps the panned view
    chart.show_lines([Line("Desk", times, [30.0] * 25, 0, (), ahead)], "t", 600, 5)
    assert chart._view_end_held is None  # a new range starts at now
