"""Moduł „Finanse" — parser arkusza, cykl życia importu i domknięcie ról.

Trzy rzeczy, których nie wolno tu zgubić, bo każda kiedyś kłamała w produkcie:

1. Wiersz z brakującą liczbą MUSI się zaimportować. Pomijanie takich wierszy
   znaczyłoby, że suma w kaflu cicho nie obejmuje kogoś, kogo widać w arkuszu.
2. Sześć kolumn spoza tabeli wynikowej NIE MOŻE wyjść żadną odpowiedzią API.
   Nie ma ich nawet w schemacie bazy — ten test pilnuje, żeby nie wróciły
   tylnymi drzwiami (np. przez `raw_payload` dołożony „na wszelki wypadek").
3. Re-import ZASTĘPUJE, ale nie kasuje. Poprzednia wersja z własnymi ręcznymi
   poprawkami musi dać się przywrócić.
"""

import uuid
from io import BytesIO

import pytest
from httpx import AsyncClient
from openpyxl import Workbook

from app.services.finance_import import (
    REQUIRED_HEADERS,
    FinanceHeaderError,
    FinanceWorkbookError,
    parse_finance_workbook,
)

pytestmark = pytest.mark.asyncio


# ── Budowanie arkusza ───────────────────────────────────────────────────────


def _row(**values) -> list:
    return [values.get(header) for header in REQUIRED_HEADERS]


def _workbook(rows: list[list], headers: list[str] | None = None) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.append(list(headers if headers is not None else REQUIRED_HEADERS))
    for row in rows:
        ws.append(row)
    buffer = BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def _sample_rows() -> list[list]:
    return [
        _row(
            **{
                "Imię i nazwisko": "Adrian Kruk",
                "Średnia Stawka MD": 950,
                "Ilość MD": 22,
                # Polski zapis z walutą i twardą spacją — tak wychodzi z Excela.
                "Wynagrodzenie": "20 900,00 zł",
                "Klient": "BNP Paribas",
                "Stawka MD": 1190,
                "Faktura": 26180,
                "Marża PLN": "5 280,00",
                "Marża %": "20,2%",
                "Uwagi": "tajna notatka",
                "Projekt": "Projekt X",
                "Stawka z VD": 1000,
                "Czy wystawiono fakturę": "TAK",
                "Data wysłania": "2026-08-05",
                "Płatny urlop": 2,
            }
        ),
        _row(
            **{
                "Imię i nazwisko": "Magdalena Dąbrowska",
                "Średnia Stawka MD": 990,
                "Ilość MD": None,  # brak danych — wiersz MUSI wejść
                "Wynagrodzenie": "b/d",  # nieparsowalne — też
                "Klient": "Orange Polska",
                "Stawka MD": 1240,
                "Faktura": 27280,
                "Marża PLN": 5500,
                "Marża %": 20.2,
            }
        ),
    ]


# ── Parser ──────────────────────────────────────────────────────────────────


async def test_parser_imports_rows_with_missing_numbers_instead_of_skipping():
    """Brak/niepoprawna liczba → pole NULL i licznik „do uzupełnienia".

    NIE pominięcie wiersza (pkt 4.1 ticketu): rekruter widzi osobę w arkuszu,
    więc jej brak w tabeli czytałby się jak utrata danych, a suma w kaflu
    cicho przestawałaby ją obejmować.
    """
    result = parse_finance_workbook(_workbook(_sample_rows()))

    assert len(result.rows) == 2
    assert result.needs_completion == 1
    assert not result.critical_errors

    magda = result.rows[1]
    assert magda.consultant_name == "Magdalena Dąbrowska"
    assert magda.md_count is None
    assert magda.compensation is None
    assert set(magda.missing_fields) == {"md_count", "compensation"}
    # Reszta wiersza przechodzi normalnie.
    assert magda.invoice_amount == 27280


async def test_parser_reads_polish_money_and_percent():
    """Kwoty zostają Decimalem — porównujemy z Decimalem, nie z floatem.

    ``float`` w tym miejscu to nie kosmetyka: mieszanie go z ``Decimal``
    rzuca TypeError, a właśnie taki rozjazd potrafił kiedyś zwrócić 500
    bez nagłówków CORS (front widział wtedy „Network Error").
    """
    from decimal import Decimal

    result = parse_finance_workbook(_workbook(_sample_rows()))
    adrian = result.rows[0]
    assert adrian.compensation == Decimal("20900.00")  # „20 900,00 zł"
    assert adrian.margin_pln == Decimal("5280.00")  # „5 280,00"
    assert adrian.margin_pct == Decimal("20.2")  # „20,2%"


async def test_parser_skips_blank_rows_but_rejects_nameless_ones():
    rows = _sample_rows()
    rows.append([None] * len(REQUIRED_HEADERS))  # pusty wiersz separujący
    rows.append(_row(**{"Imię i nazwisko": None, "Ilość MD": 5}))

    result = parse_finance_workbook(_workbook(rows))

    assert len(result.rows) == 2  # pusty wiersz nie jest błędem
    assert len(result.critical_errors) == 1
    assert "Imię i nazwisko" in result.critical_errors[0].reason


async def test_parser_rejects_workbook_with_missing_headers():
    headers = [h for h in REQUIRED_HEADERS if h != "Faktura"]
    with pytest.raises(FinanceHeaderError) as exc_info:
        parse_finance_workbook(_workbook([], headers=headers))
    assert exc_info.value.missing == ["Faktura"]


async def test_parser_rejects_non_workbook_bytes():
    with pytest.raises(FinanceWorkbookError):
        parse_finance_workbook(b"to nie jest xlsx")


# ── Role ────────────────────────────────────────────────────────────────────


async def _headers_for(app_client: AsyncClient, role_value: str) -> dict[str, str]:
    from app.core.database import AsyncSessionLocal
    from app.core.security import hash_password
    from app.models.user import User, UserRole

    email = f"fin-{role_value}-{uuid.uuid4().hex[:8]}@example.com"
    password = f"P4ss_{uuid.uuid4().hex[:6]}!"
    async with AsyncSessionLocal() as db:
        role = UserRole(role_value)
        db.add(
            User(
                email=email,
                password_hash=hash_password(password),
                name=f"Fin {role_value}",
                role=role,
                # `finance` jest rolą WYŁĄCZNĄ (CHECK
                # ck_users_exclusive_finance_viewer_roles) — lista musi mieć
                # dokładnie tę jedną wartość.
                roles=[role.value],
                is_active=True,
                profile_completed=True,
            )
        )
        await db.commit()
    login = await app_client.post(
        "/api/auth/login", json={"email": email, "password": password}
    )
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


@pytest.mark.parametrize(
    "role", ["recruiter", "sourcer", "tac", "delivery_lead", "head_of_recruitment"]
)
async def test_finance_endpoints_forbidden_for_other_roles(
    app_client: AsyncClient, role: str
):
    headers = await _headers_for(app_client, role)
    for path in ("/api/finance/periods", "/api/finance/imports"):
        resp = await app_client.get(path, headers=headers)
        assert resp.status_code == 403, f"{role} {path}: {resp.status_code}"


async def test_finance_endpoints_allowed_for_finance_role(app_client: AsyncClient):
    headers = await _headers_for(app_client, "finance")
    resp = await app_client.get("/api/finance/periods", headers=headers)
    assert resp.status_code == 200, resp.text


async def test_finance_endpoints_allowed_for_admin(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
):
    resp = await app_client.get("/api/finance/periods", headers=app_auth_headers)
    assert resp.status_code == 200, resp.text


# ── Cykl życia importu ──────────────────────────────────────────────────────


async def _reset_period(year: int, month: int) -> None:
    """Usuń wszystkie biegi importu dla okresu.

    Testy muszą być idempotentne niezależnie od stanu bazy: `conftest` nie
    czyści tabel między uruchomieniami, a indeks częściowy „jedna aktualna
    wersja miesiąca" sprawia, że drugi przebieg tego samego testu dostawałby
    409 zamiast 201. W CI każdy shard ma świeżego postgresa, więc bez tego
    testy byłyby zielone tam i czerwone lokalnie — najgorszy rodzaj testu.
    Wiersze lecą kaskadą (FK ON DELETE CASCADE).
    """
    from sqlalchemy import delete

    from app.core.database import AsyncSessionLocal
    from app.models.finance import FinanceImportRun

    async with AsyncSessionLocal() as db:
        await db.execute(
            delete(FinanceImportRun).where(
                FinanceImportRun.period_year == year,
                FinanceImportRun.period_month == month,
            )
        )
        await db.commit()


async def _import(
    app_client: AsyncClient,
    headers: dict[str, str],
    *,
    year: int,
    month: int,
    rows: list[list] | None = None,
    replace: bool = False,
):
    return await app_client.post(
        "/api/finance/imports",
        headers=headers,
        files={
            "file": (
                "wyniki.xlsx",
                _workbook(rows if rows is not None else _sample_rows()),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
        data={"year": str(year), "month": str(month), "replace": str(replace).lower()},
    )


async def test_import_results_and_hidden_columns_never_serialised(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
):
    """Sześć kolumn spoza tabeli nie wychodzi ŻADNĄ odpowiedzią API.

    Arkusz w `_sample_rows` niesie je z rozpoznawalnymi wartościami („tajna
    notatka", „Projekt X"), więc gdyby kiedykolwiek trafiły do modelu albo do
    schematu, ten test to złapie.
    """
    year, month = 2031, 3
    await _reset_period(year, month)
    resp = await _import(app_client, app_auth_headers, year=year, month=month)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["imported"] == 2
    assert body["needs_completion"] == 1

    results = await app_client.get(
        "/api/finance/results",
        headers=app_auth_headers,
        params={"year": year, "month": month},
    )
    assert results.status_code == 200, results.text
    payload = results.text
    for forbidden in ("tajna notatka", "Projekt X", "Stawka z VD", "Płatny urlop"):
        assert forbidden not in payload, f"{forbidden!r} wyciekło w /results"

    data = results.json()
    assert {r["consultant_name"] for r in data["rows"]} == {
        "Adrian Kruk",
        "Magdalena Dąbrowska",
    }
    # Kafle liczone z tych samych wierszy, które widać w tabeli.
    assert data["totals"]["cost"] == 20900.0  # tylko Adrian ma wynagrodzenie
    assert data["totals"]["revenue"] == 26180.0 + 27280.0
    assert data["needs_completion_count"] == 1


async def test_reimport_requires_confirmation_then_archives_and_restores(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
):
    year, month = 2031, 4
    await _reset_period(year, month)
    first = await _import(app_client, app_auth_headers, year=year, month=month)
    assert first.status_code == 201, first.text
    first_run_id = first.json()["run_id"]

    # Ręczna poprawka — jej liczba ma się pojawić w ostrzeżeniu.
    results = await app_client.get(
        "/api/finance/results",
        headers=app_auth_headers,
        params={"year": year, "month": month},
    )
    row_id = results.json()["rows"][0]["id"]
    patched = await app_client.patch(
        f"/api/finance/results/{row_id}",
        headers=app_auth_headers,
        json={"md_count": 21},
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["md_count"] == 21.0
    assert "md_count" in patched.json()["edited_fields"]

    # Bez `replace` → 409 z konkretnymi liczbami.
    conflict = await _import(app_client, app_auth_headers, year=year, month=month)
    assert conflict.status_code == 409, conflict.text
    detail = conflict.json()["detail"]
    assert detail["code"] == "period_exists"
    assert detail["row_count"] == 2
    assert detail["edited_row_count"] == 1

    # Z `replace` → nowa wersja aktualna, stara zarchiwizowana (nie skasowana).
    second = await _import(
        app_client, app_auth_headers, year=year, month=month, replace=True
    )
    assert second.status_code == 201, second.text
    assert second.json()["replaced_run_id"] == first_run_id

    archive = await app_client.get("/api/finance/imports", headers=app_auth_headers)
    by_id = {r["id"]: r for r in archive.json()}
    assert by_id[first_run_id]["status"] == "superseded"
    assert by_id[second.json()["run_id"]]["status"] == "current"

    # Przywrócenie oddaje starą wersję WRAZ z jej ręczną poprawką.
    restored = await app_client.post(
        f"/api/finance/imports/{first_run_id}/restore", headers=app_auth_headers
    )
    assert restored.status_code == 200, restored.text
    assert restored.json()["status"] == "current"

    after = await app_client.get(
        "/api/finance/results",
        headers=app_auth_headers,
        params={"year": year, "month": month},
    )
    assert after.json()["run_id"] == first_run_id
    edited = [r for r in after.json()["rows"] if r["edited_fields"]]
    assert len(edited) == 1 and edited[0]["md_count"] == 21.0


async def test_import_rejects_workbook_with_wrong_headers(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
):
    await _reset_period(2031, 5)
    headers = [h for h in REQUIRED_HEADERS if h != "Marża PLN"]
    resp = await app_client.post(
        "/api/finance/imports",
        headers=app_auth_headers,
        files={
            "file": (
                "zly.xlsx",
                _workbook([], headers=headers),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
        data={"year": "2031", "month": "5", "replace": "false"},
    )
    assert resp.status_code == 422, resp.text
    detail = resp.json()["detail"]
    assert detail["code"] == "invalid_headers"
    assert "Marża PLN" in detail["missing"]


async def test_import_rejects_non_xlsx_extension(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
):
    resp = await app_client.post(
        "/api/finance/imports",
        headers=app_auth_headers,
        files={"file": ("wyniki.csv", b"a,b,c", "text/csv")},
        data={"year": "2031", "month": "6", "replace": "false"},
    )
    assert resp.status_code == 415, resp.text


async def test_editable_fields_contract_matches_parser():
    """Lista pól edytowalnych w API musi odpowiadać liczbowym z parsera.

    Rozjazd oznaczałby albo pole, którego nie da się poprawić po imporcie,
    albo pole zapisywalne, którego import nigdy nie wypełnia.
    """
    from app.schemas.finance import EDITABLE_NUMERIC_FIELDS
    from app.services.finance_import import NUMERIC_FIELDS

    assert set(EDITABLE_NUMERIC_FIELDS) == set(NUMERIC_FIELDS)


async def test_cannot_edit_rows_of_superseded_run(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
):
    """Wiersze zastąpionej wersji są ZAMROŻONE.

    Bez tego „Przywróć jako aktualny" kłamie: przywrócony bieg wracałby ze
    zmianami wprowadzonymi już PO jego zarchiwizowaniu, czyli nie w tym
    stanie, w jakim go porzucono. Archiwum ma być zapisem historii, a nie
    drugą, edytowalną kopią danych.
    """
    year, month = 2031, 7
    await _reset_period(year, month)

    first = await _import(app_client, app_auth_headers, year=year, month=month)
    assert first.status_code == 201, first.text
    results = await app_client.get(
        "/api/finance/results",
        headers=app_auth_headers,
        params={"year": year, "month": month},
    )
    frozen_row_id = results.json()["rows"][0]["id"]

    # Zastąpienie archiwizuje pierwszy bieg.
    second = await _import(
        app_client, app_auth_headers, year=year, month=month, replace=True
    )
    assert second.status_code == 201, second.text

    blocked = await app_client.patch(
        f"/api/finance/results/{frozen_row_id}",
        headers=app_auth_headers,
        json={"md_count": 99},
    )
    assert blocked.status_code == 409, blocked.text
    assert "zastąpionej" in blocked.json()["detail"]

    # Nieistniejący wiersz nadal 404 — 409 nie może zjadać tego rozróżnienia.
    missing = await app_client.patch(
        "/api/finance/results/99999999",
        headers=app_auth_headers,
        json={"md_count": 1},
    )
    assert missing.status_code == 404, missing.text


async def test_failed_import_leaves_no_orphan_file(
    app_client: AsyncClient, app_auth_headers: dict[str, str], monkeypatch
):
    """Nieudany commit nie zostawia arkusza bez wiersza w bazie.

    Plik musi trafić na dysk przed wstawieniem wiersza (`file_path` jest NOT
    NULL), więc jedyną obroną jest sprzątanie przy wyjątku. Przy 15 MB na plik
    osierocone kopie zbierałyby się cicho i bezterminowo.
    """
    from app.api import finance as finance_api

    year, month = 2031, 8
    await _reset_period(year, month)

    saved: list[str] = []
    deleted: list[str] = []
    real_save = finance_api.storage_service.save_finance_import
    real_delete = finance_api.storage_service.delete_finance_import

    def _save(**kwargs):
        rel, size = real_save(**kwargs)
        saved.append(rel)
        return rel, size

    def _delete(rel):
        deleted.append(rel)
        return real_delete(rel)

    monkeypatch.setattr(finance_api.storage_service, "save_finance_import", _save)
    monkeypatch.setattr(finance_api.storage_service, "delete_finance_import", _delete)

    async def _boom(*args, **kwargs):
        raise RuntimeError("commit padł")

    monkeypatch.setattr(finance_api, "_persist_import", _boom)

    with pytest.raises(RuntimeError):
        await _import(app_client, app_auth_headers, year=year, month=month)

    assert saved, "plik nie został w ogóle zapisany — test nie sprawdza tego, co miał"
    assert deleted == saved, (
        f"osierocony plik po nieudanym imporcie: {set(saved) - set(deleted)}"
    )


async def test_lock_period_attempts_lock_when_dialect_unknown():
    """Nierozpoznany silnik → PRÓBUJEMY wziąć blokadę, nie pomijamy jej.

    ``AsyncSession.bind`` jest w SQLAlchemy 2.0 wycofywane i bywa ``None``.
    Warunek „pomiń, jeśli to nie postgres" zamieniał taki przypadek w CICHY
    brak blokady — najgorszy tryb awarii, bo objawia się dopiero losowym 500
    przy dwóch równoległych importach tego samego miesiąca.
    """
    from app.api import finance as finance_api

    executed: list[str] = []

    class _NoBindSession:
        bind = None

        def get_bind(self):
            raise RuntimeError("brak rozstrzygalnego bindu")

        async def execute(self, stmt, params=None):
            executed.append(str(stmt))

    await finance_api._lock_period(_NoBindSession(), 2031, 9)
    assert executed, "przy nieznanym dialekcie blokada została po cichu pominięta"
    assert "pg_advisory_xact_lock" in executed[0]
