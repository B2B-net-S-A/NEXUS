"""Runda 7 (R7-X2-1): paragony migracji w publicznym logu Actions.

Workflow „Coolify Ops → migration-receipts” drukuje wynik
``scripts.show_migration_receipts`` w logu, który widzi każdy (repo publiczne).
Paragon ``0304_contract_order_sync_repair`` niósł migawkę raportu z nazwiskami
i stawkami konsultantów. Te testy pilnują, że wydruk przepuszcza wyłącznie
liczby, daty i ID — niezależnie od tego, co leży w bazie — i że korekta 0304
pisze szczegóły pod kluczem, którego kanał w ogóle nie czyta.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from types import SimpleNamespace

from scripts import show_migration_receipts as receipts

_NAME = "Janina Przykładowa-Kowalska"
_CLIENT = "Bank Przykładowy S.A."
_ORDER = "ZAM/2026/77 Janina Przykładowa"
_RATE = 187.35
_RATE_CLIENT = 1499.5

_LEGACY_0304 = {
    "business_day": "2026-09-17",
    "executed_at": "2026-09-17T02:11:05.123456+00:00",
    "report_rows": 1,
    "drafts_found": 1,
    "drafts_activated": 1,
    "sync_errors": 0,
    "snapshot": [
        {
            "candidate_name": _NAME,
            "client_name": _CLIENT,
            "contract_id": 4321,
            "order_id": 98765,
            "order_number": _ORDER,
            "order_cost": _RATE,
            "contract_revenue": _RATE_CLIENT,
            "cost_status": "niezgodne",
        }
    ],
    "repaired": [
        {
            "contract_id": 4321,
            "activated": True,
            "rate_candidate": _RATE,
            "rate_client": _RATE_CLIENT,
            "action": "activated",
        }
    ],
    _NAME: 3,
}


def _printed(value) -> str:
    return json.dumps(receipts.redact(value), ensure_ascii=False)


def test_legacy_0304_receipt_prints_no_names_rates_or_order_titles():
    text = _printed(_LEGACY_0304)

    for secret in (
        _NAME,
        "Janina",
        "Kowalska",
        _CLIENT,
        _ORDER,
        str(_RATE),
        str(_RATE_CLIENT),
        "1499",
        "niezgodne",
    ):
        assert secret not in text, secret
    # Liczniki, ID, daty i flagi zostają — po to jest ten kanał.
    redacted = receipts.redact(_LEGACY_0304)
    assert redacted["business_day"] == "2026-09-17"
    assert redacted["executed_at"] == "2026-09-17T02:11:05.123456+00:00"
    assert redacted["drafts_activated"] == 1
    assert redacted["snapshot"][0]["contract_id"] == 4321
    assert redacted["snapshot"][0]["order_id"] == 98765
    assert redacted["repaired"][0]["activated"] is True
    assert redacted["repaired"][0]["rate_candidate"] == "<kwota>"
    assert redacted["snapshot"][0]["candidate_name"].startswith("<napis")


def test_counters_whose_name_contains_rate_as_a_substring_survive():
    redacted = receipts.redact(
        {"generated_rows": 5, "migrated_ids": [1, 2], "md_rate_revenue": 900}
    )
    assert redacted["generated_rows"] == 5
    assert redacted["migrated_ids"] == [1, 2]
    assert redacted["md_rate_revenue"] == "<kwota>"


def test_long_lists_of_objects_are_capped_but_id_lists_are_not():
    rows = [{"contract_id": i} for i in range(250)]
    redacted = receipts.redact({"rows": rows, "ids": list(range(250))})
    assert len(redacted["ids"]) == 250
    assert len(redacted["rows"]) == receipts._MAX_LISTED_OBJECTS + 1
    assert "pominięto 150" in redacted["rows"][-1]


class _FakeResult:
    def __init__(self, keys):
        self._keys = keys

    def scalars(self):
        return iter(self._keys)


class _FakeSession:
    def __init__(self, rows):
        self._rows = rows

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def execute(self, _stmt):
        return _FakeResult(list(self._rows))

    async def get(self, _model, key):
        return self._rows.get(key)


def test_show_prints_the_receipt_without_the_personal_data(monkeypatch, capsys):
    stamp = datetime(2026, 9, 17, 2, 11, tzinfo=timezone.utc)
    rows = {
        "0304_contract_order_sync_repair": SimpleNamespace(
            value=_LEGACY_0304, updated_at=stamp
        ),
        # Szczegóły i ustawienia kont: kanał nie może ich nawet wypisać.
        "repair_details_0304_contract_order_sync_repair": SimpleNamespace(
            value={"snapshot": [{"candidate_name": _NAME}]}, updated_at=stamp
        ),
        "columns:recruiter": SimpleNamespace(value={"x": _NAME}, updated_at=stamp),
    }
    monkeypatch.setattr(receipts, "AsyncSessionLocal", lambda: _FakeSession(rows))

    assert asyncio.run(receipts.show(None)) == 0
    out = capsys.readouterr().out

    assert "0304_contract_order_sync_repair" in out
    assert "repair_details_0304" not in out
    assert "columns:recruiter" not in out
    for secret in (_NAME, _CLIENT, _ORDER, str(_RATE), str(_RATE_CLIENT)):
        assert secret not in out, secret
    assert '"drafts_activated": 1' in out


def test_show_failure_prints_only_the_error_class(monkeypatch, capsys):
    def _boom():
        raise RuntimeError(f"DETAIL: Key (name)=({_NAME}) already exists")

    monkeypatch.setattr(receipts, "AsyncSessionLocal", _boom)
    monkeypatch.setattr("sys.argv", ["show_migration_receipts"])

    assert receipts.main() == 1
    out = capsys.readouterr().out
    assert _NAME not in out
    assert "RuntimeError" in out


def test_0304_details_key_is_not_receipt_shaped():
    from app.services.contract_order_sync import REPAIR_DETAILS_KEY, REPAIR_MARKER

    assert receipts.is_receipt_key(REPAIR_MARKER)
    assert not receipts.is_receipt_key(REPAIR_DETAILS_KEY)


class _SettingsDb:
    def __init__(self, rows):
        self._rows = rows

    async def get(self, _model, key):
        value = self._rows.get(key)
        return None if value is None else SimpleNamespace(value=value)


def test_order_sync_report_reads_details_and_falls_back_to_the_legacy_receipt():
    from app.services.contract_order_sync import REPAIR_DETAILS_KEY, REPAIR_MARKER
    from app.services.contract_order_sync_repair import load_repair_details

    assert asyncio.run(load_repair_details(_SettingsDb({}))) is None

    # Paragon sprzed 26.09.2026: migawka w samym paragonie.
    summary, snapshot, repaired = asyncio.run(
        load_repair_details(_SettingsDb({REPAIR_MARKER: _LEGACY_0304}))
    )
    assert summary["drafts_activated"] == 1
    assert snapshot[0]["candidate_name"] == _NAME
    assert repaired[0]["contract_id"] == 4321

    # Nowy kształt: paragon z licznikami, szczegóły osobno.
    new_receipt = {"drafts_activated": 1, "repaired_contract_ids": [4321]}
    details = {"snapshot": [{"order_id": 1}], "repaired": [{"contract_id": 4321}]}
    summary, snapshot, repaired = asyncio.run(
        load_repair_details(
            _SettingsDb({REPAIR_MARKER: new_receipt, REPAIR_DETAILS_KEY: details})
        )
    )
    assert summary == new_receipt
    assert snapshot == [{"order_id": 1}]
    assert repaired == [{"contract_id": 4321}]
