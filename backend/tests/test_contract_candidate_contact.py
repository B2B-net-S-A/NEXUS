"""Kontakt do konsultanta na umowie — kolejność źródeł i edycja w miejscu.

Kryteria akceptacji ticketu „E-mail i telefon kandydata w widoku kontraktu",
każde osobnym testem:

* dane z generatora (zapisane na umowie) wygrywają z profilem kandydata;
* brak danych na umowie → wartość z profilu, oznaczona jako taka;
* brak w obu źródłach → puste pole, nie zgadywanie;
* edycja w widoku kontraktu zapisuje się i nadpisuje profil;
* wyczyszczenie pola PRZYWRACA fallback do profilu (a nie zostawia pustkę);
* umowa odpięta od usuniętego kandydata nie wywraca odpowiedzi;
* twarde usunięcie kandydata zabiera kontakt z umowy (art. 17 RODO).
"""

from __future__ import annotations

import uuid
from datetime import date
from types import SimpleNamespace

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.services.contract_candidate_contact import (
    normalize_email,
    normalize_phone,
    resolve_contact,
)

pytestmark = pytest.mark.asyncio


# ── Czysta reguła kolejności źródeł ──────────────────────────────────────────


def _candidate(email=None, phone=None):
    return SimpleNamespace(email=email, phone=phone)


def test_contract_value_wins_over_the_candidate_profile():
    resolved = resolve_contact(
        contract_email="z.umowy@example.com",
        contract_phone="+48 111 111 111",
        candidate=_candidate("z.profilu@example.com", "+48 222 222 222"),
    )
    assert resolved.email == "z.umowy@example.com"
    assert resolved.email_source == "contract"
    assert resolved.phone == "+48 111 111 111"
    assert resolved.phone_source == "contract"


def test_empty_contract_value_falls_back_to_the_profile_and_says_so():
    resolved = resolve_contact(
        contract_email=None,
        contract_phone="   ",
        candidate=_candidate("z.profilu@example.com", "+48 222 222 222"),
    )
    assert resolved.email == "z.profilu@example.com"
    assert resolved.email_source == "candidate_profile"
    # Same białe znaki na umowie to brak wartości, nie nadpisanie pustką.
    assert resolved.phone == "+48 222 222 222"
    assert resolved.phone_source == "candidate_profile"


def test_missing_in_both_sources_stays_empty_without_a_source():
    resolved = resolve_contact(
        contract_email=None, contract_phone=None, candidate=_candidate()
    )
    assert resolved.email is None and resolved.email_source is None
    assert resolved.phone is None and resolved.phone_source is None


def test_a_contract_detached_from_a_deleted_candidate_still_resolves():
    """`candidate is None` to legalny stan (migracja 0225), nie błąd."""

    resolved = resolve_contact(
        contract_email="z.umowy@example.com", contract_phone=None, candidate=None
    )
    assert resolved.email == "z.umowy@example.com"
    assert resolved.phone is None


def test_each_field_resolves_independently():
    """E-mail z umowy obok telefonu z profilu — nie „wszystko albo nic"."""

    resolved = resolve_contact(
        contract_email="z.umowy@example.com",
        contract_phone=None,
        candidate=_candidate("z.profilu@example.com", "+48 222 222 222"),
    )
    assert (resolved.email_source, resolved.phone_source) == (
        "contract",
        "candidate_profile",
    )


async def test_an_unloaded_candidate_relation_never_triggers_a_lazy_load():
    """Niezaładowana relacja degraduje do „brak profilu", nie do 500.

    Sięgnięcie po niezaładowaną relację w sesji async to ``MissingGreenlet``,
    czyli 500 BEZ nagłówków CORS — przeglądarka pokazuje „Network Error" bez
    statusu. Wszyscy dzisiejsi wołający robią `selectinload`, ale resolver nie
    może wisieć na ich dyscyplinie.
    """

    from sqlalchemy.orm import noload

    from app.core.database import AsyncSessionLocal
    from app.models.contract import Contract
    from app.services.contract_candidate_contact import resolve_for_contract

    contract_id, _, _profil = await _seed_contract(
        with_email=True, phone="+48 500 100 200"
    )
    async with AsyncSessionLocal() as db:
        contract = (
            await db.execute(
                select(Contract)
                .where(Contract.id == contract_id)
                .options(noload(Contract.candidate))
            )
        ).scalar_one()
        resolved = resolve_for_contract(contract)

    # Kandydat NIE jest załadowany, więc fallback do profilu nie zadziała —
    # ale odczyt się nie wywraca, a nadpisanie z umowy nadal by przeszło.
    assert resolved.email is None
    assert resolved.email_source is None


def test_normalization_lowercases_email_but_leaves_the_phone_format_alone():
    assert normalize_email("  Jan.Kowalski@Example.COM ") == "jan.kowalski@example.com"
    # Prefiks i spacje zostają: to numer do wybrania, nie klucz porównania.
    assert normalize_phone("  +48 600 100 200 ") == "+48 600 100 200"
    assert normalize_email("   ") is None and normalize_phone("") is None


# ── Ścieżka HTTP ─────────────────────────────────────────────────────────────


#: `candidates.email` jest UNIQUE — każdy seed potrzebuje własnego adresu,
#: inaczej drugi test w pliku wywraca się na wstawianiu kandydata.
def profile_email(unique: str) -> str:
    return f"profil-{unique}@example.com"


async def _seed_contract(
    *, with_email: bool, phone: str | None
) -> tuple[int, int, str]:
    """Kandydat + klient + umowa. Zwraca (contract_id, candidate_id, e-mail)."""

    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate
    from app.models.client import Client
    from app.models.contract import Contract, ContractStatus, ContractType

    unique = uuid.uuid4().hex[:8]
    email = profile_email(unique) if with_email else None
    async with AsyncSessionLocal() as db:
        candidate = Candidate(
            name="Jan",
            lastname=f"Kontaktowy{unique}",
            email=email,
            phone=phone,
        )
        client = Client(name=f"Klient Kontaktowy {unique}")
        db.add_all([candidate, client])
        await db.flush()
        contract = Contract(
            candidate_id=candidate.id,
            client_id=client.id,
            contract_type=ContractType.b2b,
            status=ContractStatus.draft,
            start_date=date(2026, 1, 1),
        )
        db.add(contract)
        await db.commit()
        return contract.id, candidate.id, email or ""


async def test_detail_serves_the_profile_value_until_someone_overrides_it(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
):
    contract_id, _, profil = await _seed_contract(
        with_email=True, phone="+48 500 100 200"
    )

    detail = (
        await app_client.get(f"/api/contracts/{contract_id}", headers=app_auth_headers)
    ).json()
    assert detail["candidate_email"] is None, "umowa nie ma jeszcze nadpisania"
    assert detail["candidate_email_effective"] == profil
    assert detail["candidate_email_source"] == "candidate_profile"
    assert detail["candidate_phone_effective"] == "+48 500 100 200"

    patched = await app_client.patch(
        f"/api/contracts/{contract_id}",
        headers=app_auth_headers,
        json={"candidate_email": " Umowa@Example.COM ", "candidate_phone": "+48 999"},
    )
    assert patched.status_code == 200, patched.text
    body = patched.json()
    assert body["candidate_email"] == "umowa@example.com"
    assert body["candidate_email_effective"] == "umowa@example.com"
    assert body["candidate_email_source"] == "contract"
    assert body["candidate_phone_effective"] == "+48 999"
    assert body["candidate_phone_source"] == "contract"


async def test_clearing_the_override_restores_the_profile_value(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
):
    """Wyczyszczenie pola nie może zostawić pustki obok wypełnionego profilu."""

    contract_id, _, profil = await _seed_contract(
        with_email=True, phone="+48 500 100 200"
    )
    await app_client.patch(
        f"/api/contracts/{contract_id}",
        headers=app_auth_headers,
        json={"candidate_email": "umowa@example.com"},
    )

    # Pusty string (tak wysyła edycja w miejscu po skasowaniu treści)…
    body = (
        await app_client.patch(
            f"/api/contracts/{contract_id}",
            headers=app_auth_headers,
            json={"candidate_email": ""},
        )
    ).json()
    assert body["candidate_email"] is None
    assert body["candidate_email_effective"] == profil
    assert body["candidate_email_source"] == "candidate_profile"

    # …i jawny null robią to samo.
    await app_client.patch(
        f"/api/contracts/{contract_id}",
        headers=app_auth_headers,
        json={"candidate_phone": "+48 999"},
    )
    body = (
        await app_client.patch(
            f"/api/contracts/{contract_id}",
            headers=app_auth_headers,
            json={"candidate_phone": None},
        )
    ).json()
    assert body["candidate_phone"] is None
    assert body["candidate_phone_effective"] == "+48 500 100 200"


async def test_omitting_the_field_leaves_the_override_untouched(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
):
    """PATCH jest częściowy — zapis innego pola nie może kasować kontaktu."""

    contract_id, _, _profil = await _seed_contract(with_email=False, phone=None)
    await app_client.patch(
        f"/api/contracts/{contract_id}",
        headers=app_auth_headers,
        json={"candidate_email": "umowa@example.com"},
    )
    body = (
        await app_client.patch(
            f"/api/contracts/{contract_id}",
            headers=app_auth_headers,
            json={"project_name": "Projekt bez kontaktu"},
        )
    ).json()
    assert body["candidate_email"] == "umowa@example.com"


async def test_missing_in_both_sources_renders_as_empty_over_http(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
):
    contract_id, _, _profil = await _seed_contract(with_email=False, phone=None)
    detail = (
        await app_client.get(f"/api/contracts/{contract_id}", headers=app_auth_headers)
    ).json()
    assert detail["candidate_email_effective"] is None
    assert detail["candidate_phone_effective"] is None
    assert detail["candidate_email_source"] is None


async def test_an_over_long_value_is_refused_not_silently_truncated(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
):
    """Przycięty numer wygląda na poprawny i nie da się go odróżnić od literówki."""

    contract_id, _, _profil = await _seed_contract(with_email=False, phone=None)
    refused = await app_client.patch(
        f"/api/contracts/{contract_id}",
        headers=app_auth_headers,
        json={"candidate_phone": "+48 " + "1" * 40},
    )
    assert refused.status_code == 422
    assert refused.json()["detail"]["code"] == "candidate_phone_too_long"


async def test_erasing_the_candidate_takes_the_contact_off_the_contract(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
):
    """Art. 17 RODO: wiersz umowy zostaje, kontakt do usuniętej osoby — nie."""

    from app.core.database import AsyncSessionLocal
    from app.models.contract import Contract

    contract_id, candidate_id, _profil = await _seed_contract(
        with_email=True, phone="+48 500 100 200"
    )
    await app_client.patch(
        f"/api/contracts/{contract_id}",
        headers=app_auth_headers,
        json={
            "candidate_email": "umowa@example.com",
            "candidate_phone": "+48 600 600 600",
        },
    )

    deleted = await app_client.delete(
        f"/api/candidates/{candidate_id}", headers=app_auth_headers
    )
    assert deleted.status_code in (200, 204), deleted.text

    async with AsyncSessionLocal() as db:
        contract = await db.get(Contract, contract_id)
        assert contract is not None, "umowa ma przeżyć usunięcie kandydata"
        assert contract.candidate_email is None
        assert contract.candidate_phone is None
