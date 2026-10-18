"""Biała lista VAT (R6, R7, R9): ``white_list.search`` / ``white_list.check``.

Bez sieci: klient wykazu podmieniony na fałszywy serwer (``httpx.MockTransport``)
z odpowiedziami w kształcie z dokumentacji API wykazu (wersja 1.6.1). NIP-y
i rachunki fikcyjne, z poprawnymi sumami kontrolnymi (repo jest publiczne).
"""

from __future__ import annotations

import json
import logging
from datetime import date, timedelta

import httpx
import pytest

from app.models.hr_ops import HrAuditEvent
from app.services.hr import white_list

NIP = "1234563218"
OTHER_NIP = "7777777777"
TODAY = date(2026, 10, 17)


def _nrb(bban: str) -> str:
    """Fikcyjny NRB (26 cyfr) z poprawnymi cyframi kontrolnymi."""

    check = 98 - int(f"{bban}252100") % 97
    return f"{check:02d}{bban}"


ACCOUNT = _nrb("123400000000000000004521")
SECOND_ACCOUNT = _nrb("123400000000000000009910")
FOREIGN_ACCOUNT = _nrb("987600000000000000001180")


class _Session:
    """Sesja zastępcza: zbiera wpisy śladu bez bazy."""

    def __init__(self) -> None:
        self.added: list[object] = []

    def add(self, obj: object) -> None:
        self.added.append(obj)

    def events(self) -> list[HrAuditEvent]:
        return [obj for obj in self.added if isinstance(obj, HrAuditEvent)]


class _Registry:
    """Fałszywy wykaz MF: liczy zapytania i oddaje przygotowane odpowiedzi."""

    def __init__(self) -> None:
        self.calls: list[httpx.Request] = []
        self.subjects = {
            NIP: {
                "name": "Nowak Recruitment Ola Nowak",
                "nip": NIP,
                "statusVat": "Czynny",
                "regon": "000000000",
                "accountNumbers": [ACCOUNT, SECOND_ACCOUNT, ACCOUNT, "12345"],
                "hasVirtualAccounts": False,
            }
        }
        self.response: httpx.Response | None = None
        self.error: Exception | None = None

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        if self.error is not None:
            raise self.error
        if self.response is not None:
            return self.response
        parts = request.url.path.split("/")
        meta = {
            "requestId": f"req-{len(self.calls)}",
            "requestDateTime": "17-10-2026 14:05:00",
        }
        if request.url.path.startswith("/api/search/nip/"):
            return httpx.Response(
                200, json={"result": {"subject": self.subjects.get(parts[-1]), **meta}}
            )
        if "/bank-account/" in request.url.path:
            nip, account = parts[4], parts[6]
            subject = self.subjects.get(nip) or {}
            assigned = "TAK" if account in subject.get("accountNumbers", []) else "NIE"
            return httpx.Response(
                200, json={"result": {"accountAssigned": assigned, **meta}}
            )
        return httpx.Response(404, json={"code": "WL-100", "message": "brak"})


@pytest.fixture
def registry(monkeypatch):
    fake = _Registry()
    transport = httpx.MockTransport(fake.handler)
    monkeypatch.setattr(
        white_list,
        "_http_client",
        lambda base_url: httpx.AsyncClient(base_url=base_url, transport=transport),
    )
    monkeypatch.setattr(white_list.settings, "WHITE_LIST_MODE", "live")
    monkeypatch.setattr(white_list, "business_today", lambda: TODAY)
    white_list.reset_memory()
    yield fake
    white_list.reset_memory()


# ── Numery ───────────────────────────────────────────────────────────────────


def test_rachunek_normalizowany_do_26_cyfr_z_suma_kontrolna():
    spaced = f"PL {ACCOUNT[:2]} {ACCOUNT[2:6]} {ACCOUNT[6:10]}-{ACCOUNT[10:]}"
    assert white_list.normalize_account(spaced) == ACCOUNT
    assert white_list.last4(spaced) == "4521"
    assert white_list.account_valid(ACCOUNT)
    broken = ACCOUNT[:-1] + str((int(ACCOUNT[-1]) + 1) % 10)
    assert not white_list.account_valid(broken)
    assert not white_list.account_valid(ACCOUNT[:-1])
    assert not white_list.account_valid("DE" + ACCOUNT)


def test_bledny_numer_rachunku_nie_trafia_do_komunikatu():
    broken = ACCOUNT[:-1] + str((int(ACCOUNT[-1]) + 1) % 10)
    with pytest.raises(white_list.WhiteListError) as caught:
        white_list.normalize_account(broken)
    assert caught.value.code == "invalid_account"
    assert broken not in caught.value.message
    assert broken not in str(caught.value)


def test_nip_z_suma_kontrolna():
    assert white_list.clean_nip("123-456-32-18") == NIP
    assert white_list.clean_nip("PL1234563218") == NIP
    for wrong in ("1234563219", "123456321", "", "abcdefghij"):
        with pytest.raises(white_list.WhiteListError) as caught:
            white_list.clean_nip(wrong)
        assert caught.value.code == "invalid_nip"
        assert caught.value.http_status == 422


# ── Tryb wyłączony ───────────────────────────────────────────────────────────


async def test_tryb_off_to_blad_a_nie_brak_w_wykazie(registry, monkeypatch):
    monkeypatch.setattr(white_list.settings, "WHITE_LIST_MODE", "off")
    session = _Session()
    with pytest.raises(white_list.WhiteListError) as caught:
        await white_list.search(session, NIP, TODAY)
    assert caught.value.code == "disabled"
    assert caught.value.http_status == 409
    with pytest.raises(white_list.WhiteListError):
        await white_list.check(session, NIP, ACCOUNT, TODAY)
    assert registry.calls == []
    assert session.events() == []


def test_nieznany_tryb_to_off(monkeypatch):
    monkeypatch.setattr(white_list.settings, "WHITE_LIST_MODE", "produkcja")
    assert white_list.current_mode() == "off"


# ── search ───────────────────────────────────────────────────────────────────


async def test_search_mapuje_wpis_wykazu(registry):
    session = _Session()
    entry = await white_list.search(session, NIP, TODAY, actor_id=7, subject_user_id=9)
    assert entry is not None
    assert entry.nip == NIP
    assert entry.name == "Nowak Recruitment Ola Nowak"
    assert entry.vat_status == "active"
    # Duplikat i śmieciowy numer z wykazu odpadają, kolejność zostaje.
    assert entry.accounts == (ACCOUNT, SECOND_ACCOUNT)
    assert entry.lists_account(f"PL{SECOND_ACCOUNT}")
    assert not entry.lists_account(FOREIGN_ACCOUNT)
    assert entry.request_id == "req-1"
    assert entry.requested_at is not None and entry.requested_at.hour == 14
    assert entry.cached is False
    request = registry.calls[0]
    assert request.url.host == "wl-api.mf.gov.pl"
    assert request.url.path == f"/api/search/nip/{NIP}"
    assert request.url.params["date"] == TODAY.isoformat()
    [event] = session.events()
    assert event.action == "white_list_search"
    assert event.actor_user_id == 7 and event.subject_user_id == 9
    assert event.entity_id == NIP
    assert event.details["request_id"] == "req-1"
    assert event.details["found"] is True
    assert ACCOUNT not in json.dumps(event.details)


async def test_search_tego_samego_dnia_z_pamieci(registry, monkeypatch):
    session = _Session()
    first = await white_list.search(session, NIP, TODAY)
    second = await white_list.search(session, NIP, TODAY)
    assert len(registry.calls) == 1
    assert second.cached is True
    assert second.request_id == first.request_id
    assert [e.details["cached"] for e in session.events()] == [False, True]
    assert white_list.usage()["used"]["search"] == 1

    # Następny dzień kalendarza firmy = nowe zapytanie.
    monkeypatch.setattr(white_list, "business_today", lambda: TODAY + timedelta(days=1))
    third = await white_list.search(session, NIP, TODAY)
    assert len(registry.calls) == 2
    assert third.cached is False


async def test_search_nip_spoza_wykazu_to_none(registry):
    session = _Session()
    assert await white_list.search(session, OTHER_NIP, TODAY) is None
    [event] = session.events()
    assert event.details["found"] is False
    assert event.details["request_id"] == "req-1"
    # Brak w wykazie też zostaje w pamięci dnia.
    assert await white_list.search(session, OTHER_NIP, TODAY) is None
    assert len(registry.calls) == 1


async def test_search_inny_nip_w_odpowiedzi_to_awaria(registry):
    registry.subjects[NIP]["nip"] = OTHER_NIP
    with pytest.raises(white_list.WhiteListError) as caught:
        await white_list.search(_Session(), NIP, TODAY)
    assert caught.value.code == "unavailable"


async def test_data_z_przyszlosci_odrzucona_bez_zapytania(registry):
    with pytest.raises(white_list.WhiteListError) as caught:
        await white_list.search(_Session(), NIP, TODAY + timedelta(days=1))
    assert caught.value.code == "invalid_date"
    assert registry.calls == []


async def test_dzienny_limit_bez_kolejnego_zapytania(registry, monkeypatch):
    monkeypatch.setitem(white_list.DAILY_LIMITS, "search", 2)
    session = _Session()
    await white_list.search(session, NIP, TODAY)
    await white_list.search(session, OTHER_NIP, TODAY)
    with pytest.raises(white_list.WhiteListError) as caught:
        await white_list.search(session, NIP, TODAY - timedelta(days=1))
    assert caught.value.code == "quota_exceeded"
    assert caught.value.http_status == 429
    assert len(registry.calls) == 2
    # Wynik z pamięci nie zużywa limitu.
    assert (await white_list.search(session, NIP, TODAY)).cached is True


@pytest.mark.parametrize(
    ("response", "code"),
    [
        (
            httpx.Response(400, json={"code": "WL-113", "message": "Pole NIP"}),
            "rejected",
        ),
        (
            httpx.Response(
                400, json={"code": "WL-191", "message": "Przekroczono limit"}
            ),
            "quota_exceeded",
        ),
        (httpx.Response(429, json={}), "quota_exceeded"),
        (httpx.Response(503, text="przerwa"), "unavailable"),
        (httpx.Response(200, text="<html>"), "unavailable"),
        (httpx.Response(200, json={"result": {"subject": None}}), "unavailable"),
    ],
)
async def test_bledy_wykazu_maja_kod_i_zdanie(registry, response, code):
    registry.response = response
    with pytest.raises(white_list.WhiteListError) as caught:
        await white_list.search(_Session(), NIP, TODAY)
    assert caught.value.code == code
    assert caught.value.message
    if code == "rejected":
        assert "WL-113" in caught.value.message
        assert caught.value.http_status == 502


async def test_brak_sieci_to_unavailable_i_nie_trafia_do_pamieci(registry):
    registry.error = httpx.ConnectTimeout("timeout")
    with pytest.raises(white_list.WhiteListError) as caught:
        await white_list.search(_Session(), NIP, TODAY)
    assert caught.value.code == "unavailable"
    registry.error = None
    entry = await white_list.search(_Session(), NIP, TODAY)
    assert entry is not None and entry.cached is False


# ── check ────────────────────────────────────────────────────────────────────


async def test_check_tak_i_nie_z_identyfikatorem_zapytania(registry, caplog):
    caplog.set_level(logging.DEBUG, logger="app.services.hr.white_list")
    session = _Session()
    listed = await white_list.check(session, NIP, f"PL {ACCOUNT}", TODAY, actor_id=3)
    assert listed.listed is True
    assert listed.account_last4 == "4521"
    assert listed.request_id == "req-1"
    assert registry.calls[0].url.path == f"/api/check/nip/{NIP}/bank-account/{ACCOUNT}"

    missing = await white_list.check(session, NIP, FOREIGN_ACCOUNT, TODAY)
    assert missing.listed is False
    assert missing.account_last4 == "1180"

    events = session.events()
    assert [e.action for e in events] == ["white_list_check", "white_list_check"]
    assert events[0].details["listed"] is True
    assert events[0].details["account_last4"] == "4521"
    assert events[0].actor_user_id == 3
    for event in events:
        dumped = json.dumps(event.details)
        assert ACCOUNT not in dumped and FOREIGN_ACCOUNT not in dumped
    assert ACCOUNT not in caplog.text


async def test_check_z_pamieci_dnia_po_rachunku(registry):
    session = _Session()
    await white_list.check(session, NIP, ACCOUNT, TODAY)
    again = await white_list.check(session, NIP, ACCOUNT, TODAY)
    other = await white_list.check(session, NIP, SECOND_ACCOUNT, TODAY)
    assert again.cached is True and other.cached is False
    assert len(registry.calls) == 2


async def test_check_awaria_nie_udaje_braku_rachunku(registry, caplog):
    registry.error = httpx.ReadTimeout(f"timeout {ACCOUNT}")
    with pytest.raises(white_list.WhiteListError) as caught:
        await white_list.check(_Session(), NIP, ACCOUNT, TODAY)
    assert caught.value.code == "unavailable"
    assert ACCOUNT not in caught.value.message
    assert ACCOUNT not in caplog.text


async def test_check_nieznana_odpowiedz_to_awaria(registry):
    registry.response = httpx.Response(
        200, json={"result": {"accountAssigned": "MOŻE", "requestId": "x"}}
    )
    with pytest.raises(white_list.WhiteListError) as caught:
        await white_list.check(_Session(), NIP, ACCOUNT, TODAY)
    assert caught.value.code == "unavailable"


async def test_check_zly_rachunek_bez_zapytania(registry):
    with pytest.raises(white_list.WhiteListError) as caught:
        await white_list.check(_Session(), NIP, "1234", TODAY)
    assert caught.value.code == "invalid_account"
    assert registry.calls == []


# ── Tryb symulacji ───────────────────────────────────────────────────────────


async def test_simulate_fikcyjny_wpis_bez_sieci(registry, monkeypatch):
    monkeypatch.setattr(white_list.settings, "WHITE_LIST_MODE", "simulate")
    session = _Session()
    entry = await white_list.search(session, NIP, TODAY)
    assert entry.vat_status == "active"
    assert len(entry.accounts) == 2
    assert all(white_list.account_valid(account) for account in entry.accounts)
    assert entry.request_id.startswith("sim-")
    assert (await white_list.check(session, NIP, entry.accounts[1], TODAY)).listed
    assert not (await white_list.check(session, NIP, ACCOUNT, TODAY)).listed
    assert registry.calls == []
    assert {e.details["mode"] for e in session.events()} == {"simulate"}


async def test_tryb_test_idzie_do_srodowiska_testowego(registry, monkeypatch):
    monkeypatch.setattr(white_list.settings, "WHITE_LIST_MODE", "test")
    await white_list.search(_Session(), NIP, TODAY)
    assert registry.calls[0].url.host == "wl-test.mf.gov.pl"
