from datetime import date, timedelta

from core.forecast import forecast_days, forecast_months

TODAY = date(2026, 11, 4)  # a Wednesday


def test_days_repeat_the_same_weekday_average():
    days = [TODAY - timedelta(days=n) for n in range(1, 40)]
    rows = {day: 1000 if day.weekday() == 5 else 100 for day in days}
    result = dict(forecast_days(rows, TODAY))
    assert len(result) == 7 and min(result) == TODAY + timedelta(days=1)
    assert result[date(2026, 11, 7)] == 1000  # Saturday is the heavy day
    assert result[date(2026, 11, 5)] == 100


def test_days_need_two_weeks_of_history():
    assert forecast_days({TODAY - timedelta(days=n): 100 for n in range(1, 10)}, TODAY) == []


def test_months_use_the_last_full_months_and_skip_the_partial_one():
    rows = {date(2026, 8, 1): 100, date(2026, 9, 1): 200, date(2026, 10, 1): 300, date(2026, 11, 1): 9999}
    result = forecast_months(rows, TODAY)
    assert result == [(date(2026, 12, 1), 200), (date(2027, 1, 1), 200), (date(2027, 2, 1), 200)]


def test_months_need_two_full_months():
    assert forecast_months({date(2026, 10, 1): 300, date(2026, 11, 1): 50}, TODAY) == []


def test_power_forecast_follows_the_usual_day_and_fades_the_last_reading_shift():
    from datetime import datetime

    from core.profile import SLOT_SECONDS, forecast_power, slot_key

    now = datetime(2026, 11, 4, 12, 0).timestamp()
    profile = {slot_key(now + n * SLOT_SECONDS): (50.0, 100) for n in range(-2, 40)}
    points = forecast_power((now - 5, 80.0), profile, now, 3600)
    assert len(points) == 12 and points[0][0] > now
    assert 50 < points[0][1] < 80 and abs(points[-1][1] - 50) < 5  # starts near the reading, settles on usual
    assert forecast_power((now - 5, 80.0), {}, now, 3600) == []  # no usual day learned yet
    assert forecast_power((now - 5, 80.0), {slot_key(now - 5): (50.0, 100)}, now, 3600) == []  # unknown ahead
