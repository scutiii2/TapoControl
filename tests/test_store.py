import keyring
import pytest
from keyring.backend import KeyringBackend

from core.controller import is_p110
from core.store import DeviceInfo, Store


class MemoryKeyring(KeyringBackend):
    priority = 1

    def __init__(self):
        self.data = {}

    def set_password(self, service, username, password):
        self.data[(service, username)] = password

    def get_password(self, service, username):
        return self.data.get((service, username))


@pytest.fixture
def store(tmp_path):
    backend = MemoryKeyring()
    keyring.set_keyring(backend)
    s = Store(tmp_path / "t.db")
    yield s
    s.close()


def test_account_roundtrip_keeps_password_out_of_db(store, tmp_path):
    assert store.account() is None
    store.save_account("a@b.c", "secret")
    assert store.account() == ("a@b.c", "secret")
    store.close()
    assert b"secret" not in (tmp_path / "t.db").read_bytes()


def test_devices_replace_and_sorted(store):
    store.save_devices([DeviceInfo("1.1.1.2", "b", "P110"), DeviceInfo("1.1.1.1", "a", "P110M")])
    assert [d.alias for d in store.devices()] == ["a", "b"]
    store.save_devices([DeviceInfo("1.1.1.3", "c", "P110")])
    assert [d.ip for d in store.devices()] == ["1.1.1.3"]


def test_mapped_maps_unauthorized_to_autherror():
    import asyncio

    from core.controller import AuthError, _mapped

    def failing(message):
        @_mapped
        async def fn():
            raise Exception(message)

        return fn()

    with pytest.raises(AuthError):
        asyncio.run(failing('Tapo(Unauthorized { kind: "TPAP_CREDENTIALS" })'))
    with pytest.raises(Exception, match="timeout") as e:
        asyncio.run(failing("timeout"))
    assert not isinstance(e.value, AuthError)


def test_is_p110():
    assert is_p110("P110M") and is_p110("p110")
    assert not is_p110("P100") and not is_p110(None)


def test_nickname_survives_rescan_and_clears(store):
    store.save_devices([DeviceInfo("1.1.1.1", "plug", "P110")])
    store.set_nickname("1.1.1.1", " Desk ")
    store.save_devices([DeviceInfo("1.1.1.1", "plug", "P110")])
    assert store.devices()[0].alias == "Desk"
    store.set_nickname("1.1.1.1", "")
    assert store.devices()[0].alias == "plug"


def test_price_default_and_roundtrip(store):
    assert store.price_per_kwh() == 0.0
    store.set_price_per_kwh(0.1234)
    assert store.price_per_kwh() == 0.1234


def test_quarter_start_and_daily_rows():
    from datetime import date

    from core.controller import daily_rows, quarter_start

    assert quarter_start(date(2026, 11, 2)) == date(2026, 10, 1)
    assert quarter_start(date(2026, 3, 31)) == date(2026, 1, 1)
    rows = daily_rows(date(2026, 10, 30), [10, 20, 30, 40], date(2026, 11, 1))
    assert rows == [(date(2026, 10, 30), 10), (date(2026, 10, 31), 20), (date(2026, 11, 1), 30)]


def test_nickname_follows_device_to_new_ip(store):
    store.save_devices([DeviceInfo("1.1.1.1", "plug", "P110", "id1")])
    store.set_nickname("1.1.1.1", "Desk")
    store.save_devices([DeviceInfo("1.1.1.7", "plug", "P110", "id1")])
    assert [(d.ip, d.alias) for d in store.devices()] == [("1.1.1.7", "Desk")]


def test_old_devices_table_gets_device_id_column(tmp_path):
    import sqlite3

    old = sqlite3.connect(tmp_path / "old.db")
    old.execute("CREATE TABLE devices (ip TEXT PRIMARY KEY, alias TEXT NOT NULL, model TEXT NOT NULL)")
    old.execute("INSERT INTO devices VALUES ('1.1.1.1', 'a', 'P110')")
    old.commit()
    old.close()
    s = Store(tmp_path / "old.db")
    assert s.devices() == [DeviceInfo("1.1.1.1", "a", "P110", "")]
    s.close()


def test_daily_energy_saved_replaced_and_follows_device(store):
    from datetime import date

    store.save_devices([DeviceInfo("1.1.1.1", "Desk", "P110", "abc")])
    store.save_daily("1.1.1.1", [(date(2026, 1, 2), 5), (date(2026, 1, 1), 3)])
    store.save_daily("1.1.1.1", [(date(2026, 1, 2), 9)])  # plug's value wins
    assert store.daily("1.1.1.1") == [(date(2026, 1, 1), 3), (date(2026, 1, 2), 9)]
    store.save_devices([DeviceInfo("1.1.1.7", "Desk", "P110", "abc")])
    assert store.daily("1.1.1.1") == [] and len(store.daily("1.1.1.7")) == 2


def test_backfill_flag(store):
    assert not store.backfilled("1.1.1.1")
    store.set_backfilled("1.1.1.1")
    assert store.backfilled("1.1.1.1")
