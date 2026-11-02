"""Async access to Tapo P110 plugs on the LAN. Only this module talks to python-kasa and tapo."""
import asyncio
import functools
from dataclasses import dataclass
from datetime import date, datetime, timedelta

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
    today_minutes: int = 0  # time the plug was on
    month_minutes: int = 0


@dataclass(frozen=True)
class UsageSummary:
    """Plug-reported totals over the last 7 and 30 days."""

    wh_7d: int
    wh_30d: int
    minutes_7d: int
    minutes_30d: int


def quarter_start(day: date) -> date:
    """Daily energy data is requested per calendar quarter."""
    return date(day.year, (day.month - 1) // 3 * 3 + 1, 1)


def daily_rows(start: date, entries: list[int], today: date) -> list[tuple[date, int]]:
    """Pair each daily Wh entry with its date, dropping days after `today`."""
    rows = [(start + timedelta(days=i), wh) for i, wh in enumerate(entries)]
    return [r for r in rows if r[0] <= today]


def previous_quarter(start: date) -> date:
    """First day of the quarter before the one starting at `start`."""
    return quarter_start(start - timedelta(days=1))


def trim_leading_zeros(rows: list[tuple[date, int]]) -> list[tuple[date, int]]:
    """Days before the plug first measured anything come back as 0; they are not usage."""
    first = next((i for i, (_, wh) in enumerate(rows) if wh), len(rows))
    return rows[first:]


def monthly_totals(rows: list[tuple[date, int]]) -> list[tuple[date, int]]:
    """Sum daily Wh per calendar month, keyed by the month's first day."""
    totals: dict[date, int] = {}
    for day, wh in rows:
        key = day.replace(day=1)
        totals[key] = totals.get(key, 0) + wh
    return sorted(totals.items())


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
        # Each p110() call is a fresh login, and the plug locks itself after failed logins,
        # so log in once per plug and run its calls one at a time.
        self._plugs: dict = {}
        self._locks: dict[str, asyncio.Lock] = {}

    async def _call(self, ip: str, fn):
        """Run `fn(plug)` on a cached handler; drop the handler on error so the next call logs in again."""
        async with self._locks.setdefault(ip, asyncio.Lock()):
            for attempt in (1, 2):
                try:
                    if ip not in self._plugs:
                        self._plugs[ip] = await self._client.p110(ip)
                    return await fn(self._plugs[ip])
                except Exception as e:
                    self._plugs.pop(ip, None)
                    # An expired session is routine: log in once more, but never retry other errors (lockout risk).
                    if attempt == 2 or "SESSION_INVALID" not in str(e):
                        raise

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
            i = await self._call(ip, lambda plug: plug.get_device_info())
            return DeviceInfo(ip, i.nickname or ip, i.model, i.device_id)

        return sorted(await asyncio.gather(*map(info, ips)), key=lambda d: d.alias)

    @_mapped
    async def set_power(self, ip: str, on: bool) -> None:
        await self._call(ip, lambda plug: plug.on() if on else plug.off())

    @_mapped
    async def snapshot(self, ip: str) -> tuple[bool, float]:
        """Return (is_on, watts)."""

        async def read(plug):
            return await asyncio.gather(plug.get_device_info(), plug.get_current_power())

        info, power = await self._call(ip, read)
        return info.device_on, float(power.current_power)

    @_mapped
    async def energy(self, ip: str) -> EnergySummary:
        usage = await self._call(ip, lambda plug: plug.get_energy_usage())
        return EnergySummary(
            int(usage.today_energy), int(usage.month_energy),
            int(usage.today_runtime or 0), int(usage.month_runtime or 0),
        )

    @_mapped
    async def usage(self, ip: str) -> UsageSummary:
        u = await self._call(ip, lambda plug: plug.get_device_usage())
        return UsageSummary(
            int(u.power_usage.past7), int(u.power_usage.past30), int(u.time_usage.past7), int(u.time_usage.past30)
        )

    @_mapped
    async def hourly_today(self, ip: str) -> list[int]:
        """Wh per hour since midnight, one entry per elapsed hour including the current one."""
        now = datetime.now()
        data = await self._call(ip, lambda plug: plug.get_energy_data(EnergyDataInterval.Hourly, now.date(), now.date()))
        return [int(wh) for wh in data.entries][: now.hour + 1]

    @_mapped
    async def daily_history(self, ip: str) -> list[tuple[date, int]]:
        """Wh per day for the current quarter."""
        today = date.today()
        start = quarter_start(today)
        return await self._quarter(ip, start, today)

    async def _quarter(self, ip: str, start: date, today: date) -> list[tuple[date, int]]:
        data = await self._call(ip, lambda plug: plug.get_energy_data(EnergyDataInterval.Daily, start))
        quarter_end = quarter_start(start + timedelta(days=95)) - timedelta(days=1)
        return daily_rows(start, list(data.entries), min(today, quarter_end))

    @_mapped
    async def full_history(self, ip: str, max_quarters: int = 12) -> list[tuple[date, int]]:
        """Daily Wh from every quarter the plug still remembers, oldest first. Stops at the first empty quarter."""
        today = date.today()
        start = quarter_start(today)
        rows = await self._quarter(ip, start, today)  # current quarter: errors propagate
        for _ in range(max_quarters - 1):
            start = previous_quarter(start)
            try:
                older = await self._quarter(ip, start, today)
            except AuthError:
                raise
            except Exception:
                break  # the plug does not hold data this far back
            if not any(wh for _, wh in older):
                break
            rows = older + rows
        return trim_leading_zeros(rows)
