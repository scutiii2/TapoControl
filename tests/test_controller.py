import asyncio
from datetime import date, datetime
from types import SimpleNamespace as NS

import pytest

from core.controller import AuthError, TapoController, monthly_totals, previous_quarter, quarter_start, trim_leading_zeros


class FakePlug:
    def __init__(self, fail=None):
        self.fail = fail
        self.calls = []

    def _check(self):
        if self.fail:
            raise Exception(self.fail)

    async def on(self):
        self._check()
        self.calls.append("on")

    async def off(self):
        self._check()
        self.calls.append("off")

    async def get_device_info(self):
        self._check()
        return NS(device_on=True, nickname="Desk", model="P110", device_id="abc")

    async def get_current_power(self):
        return NS(current_power=12)

    async def get_energy_usage(self):
        return NS(today_energy=150, month_energy=4200, today_runtime=90, month_runtime=600)

    async def get_energy_data(self, interval, start_date, end_date=None):
        return NS(entries=[100, 200], start_date_time=start_date)

    async def get_device_usage(self):
        return NS(power_usage=NS(today=1, past7=700, past30=3000), time_usage=NS(today=2, past7=300, past30=1200))


class FakeClient:
    def __init__(self, plug):
        self.plug = plug
        self.logins = 0

    async def p110(self, ip):
        self.logins += 1
        return self.plug


def controller(plug=None):
    return TapoController("e", "p", client=FakeClient(plug or FakePlug()))


def test_snapshot_returns_state_and_watts():
    assert asyncio.run(controller().snapshot("1.1.1.1")) == (True, 12.0)


def test_set_power_calls_plug():
    plug = FakePlug()
    asyncio.run(controller(plug).set_power("1.1.1.1", False))
    asyncio.run(controller(plug).set_power("1.1.1.1", True))
    assert plug.calls == ["off", "on"]


def test_unauthorized_becomes_autherror():
    with pytest.raises(AuthError):
        asyncio.run(controller(FakePlug(fail="Unauthorized")).snapshot("1.1.1.1"))


def test_discover_carries_device_id(monkeypatch):
    c = controller()

    async def ips(timeout):
        return ["1.1.1.9"]

    monkeypatch.setattr(c, "_find_ips", ips)
    [d] = asyncio.run(c.discover())
    assert (d.ip, d.alias, d.device_id) == ("1.1.1.9", "Desk", "abc")


def test_energy_and_history():
    c = controller()
    assert asyncio.run(c.energy("1.1.1.1")).month_wh == 4200
    rows = asyncio.run(c.daily_history("1.1.1.1"))
    assert rows[0][1] == 100  # day 2 is dropped when today is the quarter's first day
    assert all(isinstance(d, date) for d, _ in rows)


def test_logs_in_once_per_plug_and_again_after_error():
    plug = FakePlug()
    client = FakeClient(plug)
    c = TapoController("e", "p", client=client)

    async def run():
        await asyncio.gather(c.snapshot("1.1.1.1"), c.energy("1.1.1.1"), c.daily_history("1.1.1.1"))
        await c.snapshot("1.1.1.1")
        assert client.logins == 1
        plug.fail = "boom"
        with pytest.raises(Exception, match="boom"):
            await c.snapshot("1.1.1.1")
        plug.fail = None
        await c.snapshot("1.1.1.1")

    asyncio.run(run())
    assert client.logins == 2


def test_expired_session_relogs_in_once():
    plug = FakePlug(fail='Tapo(DeviceError { code: -2402, kind: "TPAP_SESSION_INVALID" })')
    client = FakeClient(plug)
    c = TapoController("e", "p", client=client)
    with pytest.raises(Exception, match="SESSION_INVALID"):
        asyncio.run(c.snapshot("1.1.1.1"))
    assert client.logins == 2  # one retry, then give up


def test_full_history_walks_back_quarters_and_stops_at_empty():
    this_q = quarter_start(date.today())
    last_q = previous_quarter(this_q)

    class Plug(FakePlug):
        async def get_energy_data(self, interval, start_date, end_date=None):
            entries = {this_q: [10, 20, 30], last_q: [0, 0, 5, 6]}.get(start_date, [0] * 90)
            return NS(entries=entries, start_date_time=start_date)

    rows = asyncio.run(controller(Plug()).full_history("1.1.1.1"))
    assert rows[0] == (last_q.replace(day=3), 5)  # leading zeros trimmed
    assert (last_q.replace(day=4), 6) in rows
    assert all(a[0] < b[0] for a, b in zip(rows, rows[1:]))


def test_full_history_keeps_current_quarter_when_older_fails():
    class Plug(FakePlug):
        async def get_energy_data(self, interval, start_date, end_date=None):
            if start_date != quarter_start(date.today()):
                raise Exception("no data")
            return NS(entries=[10], start_date_time=start_date)

    assert asyncio.run(controller(Plug()).full_history("1.1.1.1")) == [(quarter_start(date.today()), 10)]


def test_monthly_totals_and_trim():
    rows = [(date(2026, 1, 30), 1), (date(2026, 1, 31), 2), (date(2026, 2, 1), 4)]
    assert monthly_totals(rows) == [(date(2026, 1, 1), 3), (date(2026, 2, 1), 4)]
    assert trim_leading_zeros([(date(2026, 1, 1), 0), (date(2026, 1, 2), 5), (date(2026, 1, 3), 0)]) == [
        (date(2026, 1, 2), 5), (date(2026, 1, 3), 0)]


def test_energy_runtime_usage_and_hourly():
    c = controller()
    e = asyncio.run(c.energy("1.1.1.1"))
    assert (e.today_minutes, e.month_minutes) == (90, 600)
    u = asyncio.run(c.usage("1.1.1.1"))
    assert (u.wh_7d, u.wh_30d, u.minutes_7d, u.minutes_30d) == (700, 3000, 300, 1200)
    assert asyncio.run(c.hourly_today("1.1.1.1")) == [100, 200][: datetime.now().hour + 1]
