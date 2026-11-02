"""Local persistence: SQLite for the account email and known plugs, Windows Credential Manager for the password."""
import os
import sqlite3
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import keyring

SERVICE = "TapoControl"


@dataclass(frozen=True)
class DeviceInfo:
    ip: str
    alias: str
    model: str
    device_id: str = ""


def default_db_path() -> Path:
    return Path(os.environ.get("APPDATA", Path.home())) / "TapoControl" / "tapo.db"


class Store:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(path)
        self._db.executescript(
            "CREATE TABLE IF NOT EXISTS account (id INTEGER PRIMARY KEY CHECK (id = 1), email TEXT NOT NULL);"
            "CREATE TABLE IF NOT EXISTS devices (ip TEXT PRIMARY KEY, alias TEXT NOT NULL, model TEXT NOT NULL);"
            # Separate table so a rescan (which rewrites devices) keeps the user's names.
            "CREATE TABLE IF NOT EXISTS nicknames (ip TEXT PRIMARY KEY, nickname TEXT NOT NULL);"
            # Daily Wh copied off the plug so history outlives what the plug itself keeps.
            "CREATE TABLE IF NOT EXISTS daily_energy (ip TEXT NOT NULL, day TEXT NOT NULL, wh INTEGER NOT NULL, PRIMARY KEY (ip, day));"
            "CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);"
        )
        if "device_id" not in [r[1] for r in self._db.execute("PRAGMA table_info(devices)")]:
            self._db.execute("ALTER TABLE devices ADD COLUMN device_id TEXT NOT NULL DEFAULT ''")

    def save_account(self, email: str, password: str) -> None:
        with self._db:
            self._db.execute("INSERT OR REPLACE INTO account (id, email) VALUES (1, ?)", (email,))
        keyring.set_password(SERVICE, email, password)

    def account(self) -> tuple[str, str] | None:
        row = self._db.execute("SELECT email FROM account WHERE id = 1").fetchone()
        email = row[0] if row else None
        password = keyring.get_password(SERVICE, email) if email else None
        return (email, password) if password else None

    def save_devices(self, devices: list[DeviceInfo]) -> None:
        old_ips = {r[0]: r[1] for r in self._db.execute("SELECT device_id, ip FROM devices WHERE device_id != ''")}
        with self._db:
            for d in devices:
                # Same device at a new IP: its nickname moves with it.
                if d.device_id in old_ips and old_ips[d.device_id] != d.ip:
                    for table in ("nicknames", "daily_energy"):
                        self._db.execute(f"UPDATE OR REPLACE {table} SET ip = ? WHERE ip = ?", (d.ip, old_ips[d.device_id]))
            self._db.execute("DELETE FROM devices")
            self._db.executemany(
                "INSERT INTO devices (ip, alias, model, device_id) VALUES (?, ?, ?, ?)",
                [(d.ip, d.alias, d.model, d.device_id) for d in devices],
            )

    def devices(self) -> list[DeviceInfo]:
        rows = self._db.execute(
            "SELECT d.ip, COALESCE(n.nickname, d.alias) AS name, d.model, d.device_id FROM devices d "
            "LEFT JOIN nicknames n ON n.ip = d.ip ORDER BY name"
        )
        return [DeviceInfo(*r) for r in rows]

    def set_nickname(self, ip: str, nickname: str) -> None:
        """Empty nickname clears it, falling back to the name set in the Tapo app."""
        with self._db:
            if nickname.strip():
                self._db.execute("INSERT OR REPLACE INTO nicknames VALUES (?, ?)", (ip, nickname.strip()))
            else:
                self._db.execute("DELETE FROM nicknames WHERE ip = ?", (ip,))

    def price_per_kwh(self) -> float:
        row = self._db.execute("SELECT value FROM settings WHERE key = 'price_per_kwh'").fetchone()
        return float(row[0]) if row else 0.0

    def set_price_per_kwh(self, price: float) -> None:
        with self._db:
            self._db.execute("INSERT OR REPLACE INTO settings VALUES ('price_per_kwh', ?)", (str(price),))

    def save_daily(self, ip: str, rows: list[tuple[date, int]]) -> None:
        """The plug is the source of truth for the days it reports, so its values replace stored ones."""
        with self._db:
            self._db.executemany(
                "INSERT OR REPLACE INTO daily_energy VALUES (?, ?, ?)", [(ip, d.isoformat(), wh) for d, wh in rows]
            )

    def daily(self, ip: str) -> list[tuple[date, int]]:
        rows = self._db.execute("SELECT day, wh FROM daily_energy WHERE ip = ? ORDER BY day", (ip,))
        return [(date.fromisoformat(d), wh) for d, wh in rows]

    def backfilled(self, ip: str) -> bool:
        return self._db.execute("SELECT 1 FROM settings WHERE key = ?", (f"backfilled:{ip}",)).fetchone() is not None

    def set_backfilled(self, ip: str) -> None:
        with self._db:
            self._db.execute("INSERT OR REPLACE INTO settings VALUES (?, '1')", (f"backfilled:{ip}",))

    def close(self) -> None:
        self._db.close()
