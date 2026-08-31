"""Zapisy zamówień, które kończyły się „Network Error" zamiast odmową.

Wspólny mianownik wszystkich czterech przypadków: NIEOBSŁUŻONY wyjątek przy
``commit()``. Leci ponad ``CORSMiddleware``, więc przeglądarka blokuje
odpowiedź i użytkownik widzi wyłącznie „Network Error" — bez statusu, bez
treści, bez wskazówki, co poprawić. Zgłoszenie brzmiało dokładnie tak:
„przy próbie zapisania zamówienia otrzymuje komunikat network error,
a zamówienie nie zostaje zapisane".

Testy sprawdzają SKUTEK dla użytkownika (kod odpowiedzi i to, czy dane
faktycznie powstały), a nie to, którędy poszedł wyjątek — bo dokładnie ta
różnica decyduje, czy zgłoszenie wróci.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal

from httpx import AsyncClient

_TODAY = date.today()


async def _seed_client_with_contract(
    *, client_name: str | None = None,
) -> tuple[int, int, int]:
    """Klient + kandydat + aktywny kontrakt. Zwraca (client_id, contract_id, candidate_id)."""
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate
    from app.models.client import Client
    from app.models.contract import Contract, ContractStatus, RateUnit

    suffix = uuid.uuid4().hex[:6]
    async with AsyncSessionLocal() as db:
        client = Client(name=client_name or f"OrderWrite-{suffix}")
        db.add(client)
        await db.flush()

        candidate = Candidate(
            name="Damian",
            lastname=f"Krawczyk-{suffix}",
            email=f"ow-{suffix}@example.com",
        )
        db.add(candidate)
        await db.flush()

        contract = Contract(
            candidate_id=candidate.id,
            client_id=client.id,
            status=ContractStatus.active,
            start_date=_TODAY - timedelta(days=30),
            rate_candidate=Decimal("1240.000"),
            rate_client=Decimal("1640.000"),
            rate_unit=RateUnit.daily,
        )
        db.add(contract)
        await db.commit()
        return client.id, contract.id, candidate.id


async def _count_orders(client_id: int) -> int:
    from sqlalchemy import func, select

    from app.core.database import AsyncSessionLocal
    from app.models.client_order import ClientOrder

    async with AsyncSessionLocal() as db:
        return await db.scalar(
            select(func.count(ClientOrder.id)).where(ClientOrder.client_id == client_id)
        )


async def _group_md_budget(client_id: int) -> Decimal | None:
    from sqlalchemy import select

    from app.core.database import AsyncSessionLocal
    from app.models.client_order_group import ClientOrderGroup

    async with AsyncSessionLocal() as db:
        value = await db.scalar(
            select(ClientOrderGroup.md_budget_total).where(
                ClientOrderGroup.client_id == client_id
            )
        )
    return None if value is None else Decimal(str(value))


def _md_order_form(contract_id: int, **overrides) -> dict[str, str]:
    form = {
        "contract_id": str(contract_id),
        "title": f"3728_{uuid.uuid4().hex[:4]}",
        "order_type": "md",
        "order_status": "draft",
        "start_date": _TODAY.isoformat(),
        "rate_candidate": "1240",
        "rate_client": "1640",
        "rate_unit": "daily",
        "md_quantity": "85",
    }
    form.update(overrides)
    return form


# ── 1. Przyczyna zgłoszenia: POST /orders z liczbą MD ───────────────────────


async def test_creating_an_md_order_with_a_budget_succeeds(
    app_client: AsyncClient, app_auth_headers: dict
):
    """POST z ``md_quantity`` kończył się 500 bez CORS i zerem wierszy w bazie.

    ``_apply_md_order_quantity`` ustawia ``md_total`` i pola wejściowe, ale
    NIE ``md_remaining`` — jedynym writerem tej kolumny jest
    ``recompute_remaining``. PATCH wołał ją od początku, POST dostał
    ``md_quantity`` osobno i wywołania nie przeniósł, więc wiersz łamał CHECK
    ``ck_client_orders_md_coherence`` przy każdej próbie.
    """
    client_id, contract_id, _ = await _seed_client_with_contract()

    resp = await app_client.post(
        f"/api/clients/{client_id}/orders",
        data=_md_order_form(contract_id),
        headers=app_auth_headers,
    )

    assert resp.status_code == 201, resp.text
    # „Zamówienie nie zostaje zapisane" było dosłownie prawdziwe — całe
    # tworzenie się cofało. Liczymy wiersze, nie tylko kod odpowiedzi.
    assert await _count_orders(client_id) == 1
    # Budżet ma NAPRAWDĘ gdzieś wylądować, a nie tylko nie wybuchnąć. Zwykłe
    # zamówienie MD trzyma pulę NA LINII (wspólna pula grupy to dwie świadome
    # odmiany klientowe — Cyfrowy Polsat i Lotte Wedel), więc sprawdzamy linię.
    assert Decimal(str(resp.json()["md_quantity"])) == Decimal("85")
    assert await _group_md_budget(client_id) is None


async def test_creating_an_md_order_with_a_budget_and_a_file_succeeds(
    app_client: AsyncClient, app_auth_headers: dict
):
    """Ta sama ścieżka co w zgłoszeniu: formularz wysyła pola RAZEM z PDF-em."""
    client_id, contract_id, _ = await _seed_client_with_contract()

    resp = await app_client.post(
        f"/api/clients/{client_id}/orders",
        data=_md_order_form(contract_id),
        files={"file": ("zamowienie.pdf", b"%PDF-1.4 dummy", "application/pdf")},
        headers=app_auth_headers,
    )

    assert resp.status_code == 201, resp.text
    assert resp.json()["has_file"] is True


async def test_md_budget_without_a_rate_is_a_readable_refusal(
    app_client: AsyncClient, app_auth_headers: dict
):
    """Braku stawki pilnuje bramka PRZED zapisem, a nie CHECK przy commicie."""
    client_id, contract_id, _ = await _seed_client_with_contract()

    resp = await app_client.post(
        f"/api/clients/{client_id}/orders",
        data=_md_order_form(contract_id, rate_client="0"),
        headers=app_auth_headers,
    )

    assert resp.status_code == 422, resp.text
    assert "stawk" in resp.text.lower()


# ── 2. Nazwa pliku dłuższa niż kolumna ──────────────────────────────────────


async def test_a_very_long_pdf_name_does_not_break_the_upload(
    app_client: AsyncClient, app_auth_headers: dict
):
    """``filename`` szło do ``VARCHAR(255)`` SUROWE, mimo obcięcia na dysku.

    Realna polska nazwa PO banku bez trudu przekracza 255 znaków, a wtedy
    ``StringDataRightTruncationError`` przy commicie zabierał cały upload —
    mimo że plik leżał już na wolumenie.
    """
    client_id, contract_id, _ = await _seed_client_with_contract()
    long_name = (
        "Zamowienie nr 445-2026 do Umowy Ramowej o swiadczenie uslug "
        "informatycznych zawartej pomiedzy Bankiem a Wykonawca " * 3
    ).replace(" ", "-") + ".pdf"
    assert len(long_name) > 255

    resp = await app_client.post(
        f"/api/clients/{client_id}/orders",
        data=_md_order_form(contract_id),
        files={"file": (long_name, b"%PDF-1.4 dummy", "application/pdf")},
        headers=app_auth_headers,
    )

    assert resp.status_code == 201, resp.text
    stored = resp.json()["filename"]
    assert len(stored) <= 255
    # Rozszerzenie musi przeżyć obcięcie — po nim front rozpoznaje typ pliku.
    assert stored.endswith(".pdf")


async def test_a_rate_too_wide_for_the_column_is_a_readable_refusal(
    app_client: AsyncClient, app_auth_headers: dict
):
    """Materializacja przepisuje stawkę do WĘŻSZEJ kolumny zamówienia.

    ``md_rate_*`` to Numeric(12,2) (10 cyfr całkowitych), a ``rate_*``
    Numeric(12,3) (9 cyfr) — przy jednostce godzinowej konwersja ×8 mogła
    wyjść poza zakres i wywalić commit nieobsłużonym błędem sterownika.
    Odmowa musi paść PRZED zapisem i nazwać pole, a nie wrócić jako ogólne
    „nieoczekiwany błąd serwera".
    """
    client_id, contract_id, _ = await _seed_client_with_contract()

    resp = await app_client.post(
        f"/api/clients/{client_id}/orders",
        data=_md_order_form(
            contract_id,
            rate_unit="hourly",
            rate_client="999999999.999",
            rate_candidate="999999999.999",
            md_quantity="10",
        ),
        headers=app_auth_headers,
    )

    assert resp.status_code == 422, resp.text
    assert "przekracza zakres" in resp.text


# ── 3. Klucze obce w PATCH ──────────────────────────────────────────────────


async def _create_order(
    app_client: AsyncClient, headers: dict, client_id: int, contract_id: int
) -> int:
    resp = await app_client.post(
        f"/api/clients/{client_id}/orders",
        data=_md_order_form(contract_id),
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def test_patch_with_an_unknown_job_is_refused_not_crashed(
    app_client: AsyncClient, app_auth_headers: dict
):
    """``job_id`` leciał ślepym ``setattr`` prosto do commitu (FK violation)."""
    client_id, contract_id, _ = await _seed_client_with_contract()
    order_id = await _create_order(
        app_client, app_auth_headers, client_id, contract_id
    )

    resp = await app_client.patch(
        f"/api/clients/{client_id}/orders/{order_id}",
        json={"job_id": 2147483647},
        headers=app_auth_headers,
    )

    assert resp.status_code == 400, resp.text
    assert "job_id" in resp.text


async def test_patch_with_an_unknown_framework_contract_is_refused(
    app_client: AsyncClient, app_auth_headers: dict
):
    client_id, contract_id, _ = await _seed_client_with_contract()
    order_id = await _create_order(
        app_client, app_auth_headers, client_id, contract_id
    )

    resp = await app_client.patch(
        f"/api/clients/{client_id}/orders/{order_id}",
        json={"framework_contract_id": 2147483647},
        headers=app_auth_headers,
    )

    assert resp.status_code == 400, resp.text
    assert "framework_contract_id" in resp.text


# ── 4. Sieć bezpieczeństwa: 500 dociera do przeglądarki ─────────────────────


async def test_unhandled_error_response_carries_cors_headers(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    """Nawet nieprzewidziany błąd MUSI dotrzeć jako 500 z nagłówkami CORS.

    Bez tego przeglądarka blokuje odpowiedź i cała klasa awarii wygląda dla
    użytkownika jak zerwane połączenie, a w zgłoszeniu jak nic.
    """
    from app.api import client_orders as co

    client_id, contract_id, _ = await _seed_client_with_contract()

    def _boom(*args, **kwargs):
        raise RuntimeError("celowa awaria testowa")

    monkeypatch.setattr(co, "_fit_filename_column", _boom)

    resp = await app_client.post(
        f"/api/clients/{client_id}/orders",
        data=_md_order_form(contract_id),
        files={"file": ("x.pdf", b"%PDF-1.4 dummy", "application/pdf")},
        headers={**app_auth_headers, "Origin": "http://localhost:3000"},
    )

    assert resp.status_code == 500, resp.text
    assert "access-control-allow-origin" in {k.lower() for k in resp.headers}
    # Treść jest ogólna (bez typu wyjątku i ścieżek), ale JEST — użytkownik
    # dostaje zdanie po polsku zamiast „Network Error".
    assert "nieoczekiwany błąd" in resp.json()["detail"].lower()
