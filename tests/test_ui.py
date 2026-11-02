"""UI flow checks with in-memory storage and fake controller coroutines only."""
import asyncio
import time
import os
from datetime import date
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "offscreen"

import keyring
import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QApplication

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
    return QApplication.instance() or QApplication([])


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
    assert w._tabs.currentIndex() == 0
    assert len(runner.pending) == 6  # a snapshot, and energy and hours for the Overview, per plug


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
    assert w._tabs.currentIndex() == 0


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
        assert w._chart._lines[0].pen().color().name() == theme().colors.accent
        assert w._history._chart._series[0].pen().color().name() == theme().colors.accent


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
    w._show_from_tray()
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
    assert ("power", w._selected_ip(), 1) in controller.calls
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
    colors = dict(w._colors._colors)
    assert len(colors) == 2 and len(set(colors.values())) == 2
    w._toggles._boxes["192.168.1.2"].setChecked(False)
    assert w._chart._names == ["Overall", "Lamp"]
    assert [v for _, v in w._chart._points[0]] == [60.0, 80.0]
    assert w._colors._colors == colors  # the others keep their colors
    w._toggles._boxes["overall"].setChecked(False)
    assert w._chart._names == ["Lamp"]
    w._toggles._boxes["192.168.1.2"].setChecked(True)
    assert w._chart._names == ["Desk", "Lamp"]


def test_chart_hover_lists_every_line_at_the_cursor():
    from ui.charts import Line, LiveChart

    chart = LiveChart(120)
    now = time.time()
    chart.show_lines([Line("A", [now - 5], [1.0]), Line("B", [now - 6], [2.0], "#ff0000")], "x")
    rows = chart._rows_at(chart._slot(now - 5))
    assert [(i, v) for i, _, v in rows] == [(0, 1.0), (1, 2.0)]


def test_energy_chart_sums_plugs_and_toggles_lines(window):
    w, runner, controller = window
    panel = w._history
    panel.load(controller, {"192.168.1.2": "Desk", "192.168.1.3": "Lamp"})
    runner.finish()
    runner.finish()
    assert panel._today.text() == "0.84 kWh"  # both plugs added up
    assert [line.name for line in panel._chart._lines] == ["Overall", "Desk", "Lamp"]
    assert panel._chart._lines[0].wh == [840]
    panel._toggles._boxes["192.168.1.2"].setChecked(False)
    assert [line.name for line in panel._chart._lines] == ["Overall", "Lamp"]
    assert panel._chart._lines[0].wh == [840]  # the overall still sums the hidden plug
    assert panel._colors("192.168.1.3") == w._colors("192.168.1.3")  # same color on both tabs


def test_energy_follows_renames_and_clears_when_plugs_change(window):
    w, runner, controller = window
    panel = w._history
    panel.load(controller, {"192.168.1.2": "Desk", "192.168.1.3": "Lamp"})
    runner.finish()
    assert not panel.set_names({"192.168.1.2": "Desk 2", "192.168.1.3": "Lamp"})
    assert [line.name for line in panel._chart._lines][1] == "Desk 2"
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
    assert tabs._buttons[0].toolTip() == "Overview" and not tabs._buttons[0].icon().isNull()


def test_overview_shows_totals_and_fetches_once_a_minute(window):
    w, runner, controller = window
    assert w._tabs.currentWidget() is w._overview
    w.refresh()
    runner.finish()
    assert w._overview._today.text() == "0.84 kWh"  # both plugs added up
    assert w._overview._now.text() == "69.6 W"  # the fake snapshot gives 34.8 W per plug
    assert w._overview._plugs.text() == "2 of 2"
    assert [line.name for line in w._overview._chart._lines] == ["Overall", "Desk", "Lamp"]
    assert w._overview._chart._lines[0].wh == [10, 0, 14]  # fake hours [5, 0, 7] per plug, summed
    w._toggles._boxes["overall"].setChecked(False)  # the Devices toggles are separate
    assert [line.name for line in w._overview._chart._lines][0] == "Overall"
    controller.calls.clear()
    w.refresh()
    runner.finish()
    assert ("energy", "192.168.1.2") not in controller.calls  # fetched less than a minute ago
    w._tabs.setCurrentWidget(w._login)
    w._overview_fetched.clear()
    w.refresh()
    assert not any(c[0] == "energy" for c in controller.calls)  # nothing fetched while the Overview is closed
