"""Forecast of coming usage from stored history: same-weekday means for days, a recent mean for months."""
from collections.abc import Mapping
from datetime import date, timedelta
from statistics import fmean

DAY_HORIZON = 7
MONTH_HORIZON = 3
MIN_DAYS = 14  # two full weeks of history before a weekly pattern means anything
WEEKS_USED = 4
MONTHS_USED = 3
MIN_MONTHS = 2


def forecast_days(rows: Mapping[date, int], today: date, horizon: int = DAY_HORIZON) -> list[tuple[date, int]]:
    """Wh for each of the next `horizon` days: the mean of that weekday over the last four weeks.

    Today is partial, so it is left out of the sample. Returns [] when there is under two weeks of history.
    """
    if len(rows) < MIN_DAYS:
        return []
    recent = {day: wh for day, wh in rows.items() if today - timedelta(weeks=WEEKS_USED) <= day < today}
    if not recent:
        return []
    overall = fmean(recent.values())
    result = []
    for step in range(1, horizon + 1):
        day = today + timedelta(days=step)
        same_weekday = [wh for d, wh in recent.items() if d.weekday() == day.weekday()]
        result.append((day, round(fmean(same_weekday) if same_weekday else overall)))
    return result


def forecast_months(rows: Mapping[date, int], today: date, horizon: int = MONTH_HORIZON) -> list[tuple[date, int]]:
    """Wh for each of the next `horizon` months (keyed by first day): the mean of the last full months.

    `rows` is monthly totals keyed by first day. Returns [] with fewer than two full months.
    """
    this_month = today.replace(day=1)
    full = sorted(month for month in rows if month < this_month)[-MONTHS_USED:]
    if len(full) < MIN_MONTHS:
        return []
    mean = round(fmean(rows[month] for month in full))
    result, month = [], this_month
    for _ in range(horizon):
        month = (month + timedelta(days=32)).replace(day=1)
        result.append((month, mean))
    return result
