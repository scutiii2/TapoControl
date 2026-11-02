import asyncio
from datetime import date
from types import SimpleNamespace as NS

import pytest

from core.controller import AuthError, TapoController


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
        return NS(today_energy=150, month_energy=4200)

    async def get_energy_data(self, interval, start_date):
        return NS(entries=[100, 200], start_date_time=start_date)


class FakeClient:
    def __init__(self, plug):
        self.plug = plug

    async def p110(self, ip):
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
