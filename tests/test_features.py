from datetime import date

from core.alerts import AlertEngine, AlertSettings
from core.export import history_csv


def test_high_power_alert_fires_once_per_episode_and_rearms():
    engine, settings = AlertEngine(), AlertSettings(max_watts=100)
    check = lambda w, t=0.0: engine.check("a", "Laptop", (True, w), False, settings, t)  # noqa: E731
    assert check(90) == []
    assert check(120) == ["Laptop is drawing 120 W (limit 100 W)"]
    assert check(130) == []  # same episode
    assert check(80) == []  # drops below: re-arms
    assert len(check(150)) == 1


def test_on_too_long_alert_resets_when_plug_turns_off():
    engine, settings = AlertEngine(), AlertSettings(max_on_minutes=30)
    on = lambda t: engine.check("a", "Server", (True, 5.0), False, settings, t)  # noqa: E731
    assert on(0) == [] and on(1700) == []
    assert on(1800) == ["Server has been on for 30 minutes"]
    assert on(1900) == []
    engine.check("a", "Server", (False, 0.0), False, settings, 2000)
    assert on(2100) == [] and on(2100 + 1800) != []  # a new on-episode counts from zero


def test_offline_alert_needs_setting_and_flag_and_fires_once():
    engine = AlertEngine()
    assert engine.check("a", "TV", None, True, AlertSettings(), 0) == []
    on = AlertSettings(offline=True)
    assert engine.check("a", "TV", None, False, on, 0) == []  # not offline long enough yet
    assert engine.check("a", "TV", None, True, on, 0) == ["TV is offline"]
    assert engine.check("a", "TV", None, True, on, 1) == []
    engine.check("a", "TV", (True, 1.0), False, on, 2)  # back online
    assert engine.check("a", "TV", None, True, on, 3) == ["TV is offline"]


def test_history_csv_for_each_kind():
    assert history_csv([(date(2026, 11, 2), 1500)], "day", 10.0) == "date,kWh,cost\n2026-11-02,1.500,15.00\n"
    assert history_csv([(date(2026, 11, 1), 2000)], "month", 0.0).splitlines()[1] == "2026-11,2.000,0.00"
    assert history_csv([(7, 250)], "hour", 4.0).splitlines()[1] == "07:00,0.250,1.00"
