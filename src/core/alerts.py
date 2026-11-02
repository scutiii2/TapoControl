"""Decides when a plug reading deserves a notification. Each condition fires once per episode."""
from dataclasses import dataclass


@dataclass(frozen=True)
class AlertSettings:
    max_watts: int = 0  # 0 = off
    max_on_minutes: int = 0  # 0 = off
    offline: bool = False


class AlertEngine:
    def __init__(self) -> None:
        self._high: set[str] = set()
        self._long: set[str] = set()
        self._offline: set[str] = set()
        self._on_since: dict[str, float] = {}

    def check(
        self, ip: str, name: str, state: tuple[bool, float] | None, offline: bool, settings: AlertSettings, now: float,
    ) -> list[str]:
        """`state` is (is_on, watts) or None; `offline` is true once the plug has failed several refreshes."""
        messages: list[str] = []
        if state is None:
            if offline and settings.offline and ip not in self._offline:
                self._offline.add(ip)
                messages.append(f"{name} is offline")
            return messages
        self._offline.discard(ip)
        is_on, watts = state

        if settings.max_watts and watts > settings.max_watts:
            if ip not in self._high:
                self._high.add(ip)
                messages.append(f"{name} is drawing {watts:.0f} W (limit {settings.max_watts} W)")
        else:
            self._high.discard(ip)

        if not is_on:
            self._on_since.pop(ip, None)
            self._long.discard(ip)
        else:
            since = self._on_since.setdefault(ip, now)
            if settings.max_on_minutes and now - since >= settings.max_on_minutes * 60 and ip not in self._long:
                self._long.add(ip)
                messages.append(f"{name} has been on for {settings.max_on_minutes} minutes")
        return messages
