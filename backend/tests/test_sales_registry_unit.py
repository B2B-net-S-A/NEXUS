"""Dane firm z rejestrów (biała lista VAT, KRS): parser, klient i zapis w karcie, bez bazy.

Odpowiedzi to nagrania prawdziwych API z 13.11.2026 z fikcyjnymi nazwami i numerami
(``tests/data/sales_registry``). Bez sieci.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable

import httpx
import pytest

from app.models.sales import SalesCompany
from app.services.sales import bot_card_history, registry
from app.services.sales import registry_cards as cards

DATA = Path(__file__).parent / "data" / "sales_registry"
DAY = date(2026, 11, 13)
ACTIVE_NIP, MISSING_NIP, REMOVED_NIP = "1112223332", "4445556665", "7778889998"


def _load(name: str) -> Any:
    return json.loads((DATA / name).read_text(encoding="utf-8"))


def _client(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.fixture(autouse=True)
def _no_backoff(monkeypatch):
    monkeypatch.setattr(registry, "BACKOFF_SECONDS", 0)


# ── Parser ───────────────────────────────────────────────────────────────


def test_vat_batch_reads_active_missing_and_removed_subjects() -> None:
    found = registry.parse_vat_batch(
        _load("vat_batch.json"), [ACTIVE_NIP, MISSING_NIP, REMOVED_NIP], DAY
    )
    active = found[ACTIVE_NIP]
    assert active is not None
    assert (active.regon, active.krs, active.city) == (
        "111222333",
        "0000111222",
        "Bielsko-Biała",
    )
    assert (active.vat_status, active.removed) == ("active", False)
    assert active.url == (
        "https://wl-api.mf.gov.pl/api/search/nip/1112223332?date=2026-11-13"
    )
    assert found[MISSING_NIP] is None
    removed = found[REMOVED_NIP]
    assert removed is not None and removed.removed
    # Znak sterujący z odpowiedzi nie trafia na ekran.
    assert removed.name == "DAWNA FIRMA TESTOWA"


def test_vat_batch_ignores_entries_for_numbers_not_asked() -> None:
    found = registry.parse_vat_batch(_load("vat_batch.json"), [MISSING_NIP], DAY)
    assert found == {MISSING_NIP: None}


def test_vat_batch_trims_overlong_text_and_rejects_wrong_shape() -> None:
    data = _load("vat_batch.json")
    data["result"]["entries"][0]["subjects"][0]["name"] = "X" * 5000
    found = registry.parse_vat_batch(data, [ACTIVE_NIP], DAY)
    assert len(found[ACTIVE_NIP].name) == 500
    with pytest.raises(registry.RegistryUnavailable):
        registry.parse_vat_batch({"result": "zły kształt"}, [ACTIVE_NIP], DAY)


def test_vat_subject_with_other_nip_is_not_taken() -> None:
    data = _load("vat_batch.json")
    data["result"]["entries"][0]["subjects"][0]["nip"] = MISSING_NIP
    assert registry.parse_vat_batch(data, [ACTIVE_NIP], DAY) == {ACTIVE_NIP: None}


def test_krs_reads_identifiers_city_and_state() -> None:
    record = registry.parse_krs(_load("krs_active.json"), "0000111222")
    assert record.state == registry.ACTIVE
    # REGON z KRS ma 14 cyfr z „00000” na końcu: na kartę idzie 9-cyfrowy.
    assert (record.nip, record.regon, record.city, record.country) == (
        ACTIVE_NIP,
        "111222333",
        "Bielsko-Biała",
        "PL",
    )
    liquidation = registry.parse_krs(_load("krs_liquidation.json"), "0000333444")
    assert (liquidation.state, liquidation.city) == (
        registry.LIQUIDATION,
        "Zielona Góra",
    )


def test_krs_full_extract_with_removal_entry_means_removed() -> None:
    record = registry.parse_krs_full(_load("krs_full_removed.json"), "0000555666")
    assert (record.state, record.removed_on) == (registry.REMOVED, "17.03.2016")


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("111-222-33-32", "1112223332"),
        ("PL1112223332", "1112223332"),
        ("1112223333", None),
        ("", None),
    ],
)
def test_nip_needs_checksum(value: str, expected: str | None) -> None:
    assert registry.valid_nip(value) == expected


def test_krs_and_regon_normalisation() -> None:
    assert registry.valid_krs("111222") == "0000111222"
    assert registry.valid_krs("0000000000") is None
    assert registry.valid_krs("12345678901") is None
    assert registry.valid_regon("11122233300000") == "111222333"
    assert registry.valid_regon("12345678901234") == "12345678901234"
    assert registry.valid_regon("1234") is None


# ── Klient: limit czasu, ponowienie, limit MF ────────────────────────────


@pytest.mark.asyncio
async def test_vat_retries_timeout_then_reads_answer() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if len(calls) == 1:
            raise httpx.ReadTimeout("wolno", request=request)
        return httpx.Response(200, json=_load("vat_batch.json"))

    async with _client(handler) as client:
        found = await registry.fetch_vat(client, [ACTIVE_NIP, MISSING_NIP], DAY)
    assert calls == [f"/api/search/nips/{ACTIVE_NIP},{MISSING_NIP}"] * 2
    assert found[ACTIVE_NIP] is not None and found[MISSING_NIP] is None


@pytest.mark.asyncio
async def test_registry_timeout_after_all_attempts_is_unavailable() -> None:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        raise httpx.ConnectTimeout("brak", request=request)

    async with _client(handler) as client:
        with pytest.raises(registry.RegistryUnavailable):
            await registry.fetch_krs(client, "0000111222")
    assert len(calls) == registry.ATTEMPTS


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(429),
        httpx.Response(
            400, json={"message": "Przekroczono limit zapytań.", "code": "WL-191"}
        ),
    ],
)
async def test_vat_quota_is_its_own_error(response: httpx.Response) -> None:
    async with _client(lambda request: response) as client:
        with pytest.raises(registry.RegistryQuotaExceeded):
            await registry.fetch_vat(client, [ACTIVE_NIP], DAY)


@pytest.mark.asyncio
async def test_missing_current_extract_checks_full_extract() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if "OdpisAktualny" in request.url.path:
            return httpx.Response(204)
        return httpx.Response(200, json=_load("krs_full_removed.json"))

    async with _client(handler) as client:
        record = await registry.fetch_krs(client, "0000555666")
    assert record.state == registry.REMOVED


@pytest.mark.asyncio
async def test_unknown_krs_is_not_found() -> None:
    async with _client(lambda request: httpx.Response(404)) as client:
        record = await registry.fetch_krs(client, "0000999999")
    assert record.state == registry.NOT_FOUND


# ── Pola z rejestru i karta ──────────────────────────────────────────────


def _records() -> tuple[registry.VatRecord, registry.KrsRecord]:
    vat = registry.parse_vat_batch(_load("vat_batch.json"), [ACTIVE_NIP], DAY)
    krs = registry.parse_krs(_load("krs_active.json"), "0000111222")
    return vat[ACTIVE_NIP], krs


def test_krs_wins_over_vat_and_each_field_has_its_source() -> None:
    vat, krs = _records()
    fields = cards.proposed_fields(vat, krs)
    assert {key: item["value"] for key, item in fields.items()} == {
        "legal_name": "PRZYKŁADOWA SPÓŁKA Z OGRANICZONĄ ODPOWIEDZIALNOŚCIĄ",
        "regon": "111222333",
        "hq_city": "Bielsko-Biała",
        "nip": ACTIVE_NIP,
        "krs": "0000111222",
        "hq_country": "PL",
    }
    assert fields["hq_city"]["source"] == "krs"
    assert fields["hq_city"]["url"].startswith("https://api-krs.ms.gov.pl/")


def test_removed_company_gives_no_fields_but_a_state() -> None:
    removed = registry.KrsRecord(
        krs="0000555666", state=registry.REMOVED, url=registry.krs_url("0000555666")
    )
    target = cards.Target(1, None, "0000555666", "|0000555666")
    assert cards.proposed_fields(None, removed) == {}
    assert cards.registry_state(None, removed, target) == registry.REMOVED


def test_states_for_vat_only_cards() -> None:
    vat, _ = _records()
    gone = registry.parse_vat_batch(_load("vat_batch.json"), [REMOVED_NIP], DAY)
    target = cards.Target(1, ACTIVE_NIP, None, f"{ACTIVE_NIP}|")
    assert cards.registry_state(vat, None, target) == registry.ACTIVE
    assert cards.registry_state(gone[REMOVED_NIP], None, target) == (
        registry.VAT_REMOVED
    )
    assert cards.registry_state(None, None, target) == registry.NOT_FOUND
    bad = cards.Target(1, None, None, "1112223333|")
    assert cards.registry_state(None, None, bad) == registry.INVALID_NIP


@pytest.mark.asyncio
async def test_human_field_stays_and_empty_fields_are_filled() -> None:
    vat, krs = _records()
    company = SalesCompany(
        id=1,
        name="Przykładowa",
        normalized_name="przykladowa",
        nip="111-222-33-32",
        krs="111222",
        legal_name="Nazwa wpisana ręcznie",
        hq_city="Katowice",
    )
    outcomes = await cards.apply_registry(
        None,
        company,
        cards.proposed_fields(vat, krs),  # type: ignore[arg-type]
    )
    assert company.legal_name == "Nazwa wpisana ręcznie"
    assert company.hq_city == "Katowice"
    assert (company.regon, company.nip, company.krs) == (
        "111222333",
        "111-222-33-32",
        "111222",
    )
    assert company.hq_country is None
    assert outcomes == {
        "legal_name": {"result": cards.KEPT, "before": "Nazwa wpisana ręcznie"},
        "nip": {"result": cards.SAME},
        "krs": {"result": cards.SAME},
        "regon": {"result": cards.APPLIED, "before": None},
        "hq_city": {"result": cards.KEPT, "before": "Katowice"},
    }


@pytest.mark.asyncio
async def test_field_with_last_automat_value_is_updated() -> None:
    vat, krs = _records()
    company = SalesCompany(
        id=1,
        name="Przykładowa",
        normalized_name="przykladowa",
        nip=ACTIVE_NIP,
        krs="0000111222",
        legal_name="Stara nazwa od bota",
        hq_city="Katowice",
        hq_country="PL",
    )
    from_bot = {"legal_name": "stara  NAZWA od bota"}
    from_registry = {"hq_city": "Katowice"}
    outcomes = await cards.apply_registry(
        None,  # type: ignore[arg-type]
        company,
        cards.proposed_fields(vat, krs),
        owned=(from_registry, from_bot),
    )
    assert company.legal_name == ("PRZYKŁADOWA SPÓŁKA Z OGRANICZONĄ ODPOWIEDZIALNOŚCIĄ")
    assert company.hq_city == "Bielsko-Biała"
    assert outcomes["legal_name"] == {
        "result": cards.APPLIED,
        "before": "Stara nazwa od bota",
    }
    assert outcomes["hq_city"]["before"] == "Katowice"
    assert outcomes["hq_country"] == {"result": cards.SAME}


def test_registry_owned_takes_last_applied_value() -> None:
    history = [
        {"lines": [{"field": "hq_city", "after": "Katowice", "result": "applied"}]},
        {"lines": [{"field": "hq_city", "after": "Gliwice", "result": "kept"}]},
        {"lines": [{"field": "regon", "after": "111222333", "result": "applied"}]},
    ]
    assert cards.registry_owned(history) == {
        "hq_city": "Katowice",
        "regon": "111222333",
    }


def test_history_groups_lines_by_registry_and_skips_same() -> None:
    vat, krs = _records()
    fields = cards.proposed_fields(vat, krs)
    fields["krs"] = {**fields["krs"], "source": "vat"}
    outcomes = {
        "legal_name": {"result": cards.SAME},
        "regon": {"result": cards.APPLIED, "before": None},
        "krs": {"result": cards.TAKEN, "other_id": 7, "other_name": "Inna"},
    }
    at = datetime(2026, 11, 13, 1, 0, tzinfo=timezone.utc)
    entries = cards.history_entries(
        fields, outcomes, state=registry.ACTIVE, vat=vat, krs=krs, at=at
    )
    assert sorted(entries, key=lambda entry: entry["source"]) == [
        {
            "at": "2026-11-13T01:00:00+00:00",
            "source": "krs",
            "lines": [
                {
                    "field": "regon",
                    "before": None,
                    "after": "111222333",
                    "result": "applied",
                    "url": fields["regon"]["url"],
                }
            ],
        },
        {
            "at": "2026-11-13T01:00:00+00:00",
            "source": "vat",
            "lines": [
                {
                    "field": "krs",
                    "before": None,
                    "after": "0000111222",
                    "result": "taken",
                    "url": fields["krs"]["url"],
                    "other_id": 7,
                    "other_name": "Inna",
                }
            ],
        },
    ]
    assert (
        cards.history_entries(
            fields,
            {"legal_name": {"result": cards.SAME}},
            state="active",
            vat=vat,
            krs=krs,
            at=at,
        )
        == []
    )


def test_removed_company_history_line_and_card_history_entry() -> None:
    removed = registry.KrsRecord(
        krs="0000555666",
        state=registry.REMOVED,
        url=registry.krs_url("0000555666"),
        removed_on="17.03.2016",
    )
    at = datetime(2026, 11, 13, 1, 0, tzinfo=timezone.utc)
    entries = cards.history_entries(
        {}, {}, state=registry.REMOVED, vat=None, krs=removed, at=at
    )
    [entry] = bot_card_history.registry_entries({"registry_history": entries})
    assert entry.bot == "Rejestry (KRS)"
    [line] = entry.lines
    assert (line.label, line.after, line.note, line.source) == (
        "Stan w rejestrze",
        "firma wykreślona z KRS",
        "od 17.03.2016, karta zostaje",
        removed.url,
    )


def test_card_history_maps_registry_lines_and_survives_junk() -> None:
    custom = {
        "registry_history": [
            "zły wpis",
            {"at": "nie-data", "lines": []},
            {
                "at": "2026-11-13T01:00:00+00:00",
                "source": "vat",
                "lines": [
                    {
                        "field": "legal_name",
                        "before": "Ręczna",
                        "after": "Z REJESTRU",
                        "result": "kept",
                        "url": "https://wl-api.mf.gov.pl/x",
                    },
                    {
                        "field": "nip",
                        "after": ACTIVE_NIP,
                        "result": "taken",
                        "other_id": 9,
                        "other_name": "Druga",
                        "url": "https://wl-api.mf.gov.pl/x",
                    },
                    {"field": "nieznane", "after": "x", "result": "applied"},
                ],
            },
        ]
    }
    [entry] = bot_card_history.registry_entries(custom)
    assert entry.bot == "Rejestry (biała lista VAT)"
    kept, taken = entry.lines
    assert (kept.label, kept.before, kept.after, kept.note) == (
        "Nazwa prawna",
        "Ręczna",
        "Z REJESTRU",
        bot_card_history.KEPT_NOTE,
    )
    assert (taken.other_company_id, taken.other_company_name) == (9, "Druga")
    older = bot_card_history.Entry(
        at=datetime(2026, 11, 1, tzinfo=timezone.utc), bot="Dane firm"
    )
    built = bot_card_history.build([], with_people=False, extra=[older, entry])
    assert [item.bot for item in built] == [entry.bot, "Dane firm"]


def test_identifiers_changed_only_on_new_number() -> None:
    company = SalesCompany(name="X", normalized_name="x", nip="1112223332")
    assert cards.identifiers_changed("|", company)
    assert not cards.identifiers_changed("1112223332|", company)
    company.nip = None
    assert not cards.identifiers_changed("1112223332|", company)
