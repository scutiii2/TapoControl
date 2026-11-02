"""Async access to Tapo P110 plugs on the LAN. Only this module talks to python-kasa and tapo."""
import asyncio
import functools
from dataclasses import dataclass
from datetime import date, timedelta

from kasa import Discover
from tapo import ApiClient
from tapo.requests import EnergyDataInterval

from core.store import DeviceInfo


class AuthError(Exception):
    """Tapo rejected the account email or password."""


@dataclass(frozen=True)
class EnergySummary:
    today_wh: int
    month_wh: int


def quarter_start(day: date) -> date:
    """Daily energy data is requested per calendar quarter."""
    return date(day.year, (day.month - 1) // 3 * 3 + 1, 1)


def daily_rows(start: date, entries: list[int], today: date) -> list[tuple[date, int]]:
    """Pair each daily Wh entry with its date, dropping days after `today`."""
    rows = [(start + timedelta(days=i), wh) for i, wh in enumerate(entries)]
    return [r for r in rows if r[0] <= today]


def is_p110(model: str | None) -> bool:
    return (model or "").upper().startswith("P110")


def _mapped(fn):
    """Turn tapo's bare Exception (Rust error kind in its text) into AuthError when Unauthorized."""

    @functools.wraps(fn)
    async def inner(*args, **kwargs):
        try:
            return await fn(*args, **kwargs)
        except Exception as e:
            raise (AuthError(str(e)) if "Unauthorized" in str(e) else e) from e

    return inner


class TapoController:
    def __init__(self, email: str, password: str, client=None):
        self._client = client or ApiClient(email, password)

    async def _find_ips(self, timeout: int) -> list[str]:
        """Broadcast discovery needs no credentials; python-kasa only finds IPs, tapo does the control."""
        ips: list[str] = []

        def on_raw(raw: dict) -> None:
            result = raw["discovery_response"]["result"]
            if is_p110(result.get("device_model")):
                ips.append(result["ip"])

        await Discover.discover(on_discovered_raw=on_raw, discovery_timeout=timeout)
        return sorted(set(ips))

    @_mapped
    async def discover(self, timeout: int = 5) -> list[DeviceInfo]:
        """Broadcast on the LAN and return P110 plugs only."""
        ips = await self._find_ips(timeout)

        async def info(ip: str) -> DeviceInfo:
            i = await (await self._client.p110(ip)).get_device_info()
            return DeviceInfo(ip, i.nickname or ip, i.model, i.device_id)

        return sorted(await asyncio.gather(*map(info, ips)), key=lambda d: d.alias)

    @_mapped
    async def set_power(self, ip: str, on: bool) -> None:
        plug = await self._client.p110(ip)
        await (plug.on() if on else plug.off())

    @_mapped
    async def snapshot(self, ip: str) -> tuple[bool, float]:
        """Return (is_on, watts)."""
        plug = await self._client.p110(ip)
        info, power = await asyncio.gather(plug.get_device_info(), plug.get_current_power())
        return info.device_on, float(power.current_power)

    @_mapped
    async def energy(self, ip: str) -> EnergySummary:
        plug = await self._client.p110(ip)
        usage = await plug.get_energy_usage()
        return EnergySummary(int(usage.today_energy), int(usage.month_energy))

    @_mapped
    async def daily_history(self, ip: str) -> list[tuple[date, int]]:
        """Wh per day for the current quarter."""
        plug = await self._client.p110(ip)
        today = date.today()
        start = quarter_start(today)
        data = await plug.get_energy_data(EnergyDataInterval.Daily, start)
        return daily_rows(start, list(data.entries), today)
