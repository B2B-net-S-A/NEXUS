"""Regresja: kwota PLN z ``Decimal`` nie może wywracać odpowiedzi.

Incydent (2026-08-12, prod): profil klienta **Alior Bank** zwracał 5xx bez
nagłówków CORS, więc zakładka „Profil" pokazywała „Nie udało się wczytać
profilu klienta." Przyczyna: ``ActiveConsultantItem.monthly_rate_client`` było
zadeklarowane jako ``Optional[int]``, a ``Contract.monthly_rate_client`` zwraca
``Decimal`` — stawka godzinowa 141,18 zł × 160 h = **22 588,80 zł**. Pydantic v2
odrzuca ``Decimal`` z częścią dziesiętną dla pola ``int`` (``int_from_float``),
co leci jako ``ResponseValidationError`` poza handlerami aplikacji.

Dlaczego defekt przeżył miesiące: na 531 kontraktów w bazie Alior był JEDYNYM
klientem z niecałkowitą kwotą miesięczną, więc 29 pozostałych aktywnych klientów
działało i żaden smoke-test tego nie dotknął. Dlatego ten plik seeduje dokładnie
ten kształt danych (stawka godzinowa dająca grosze), a nie „jakiś" kontrakt.

Testowane są WSZYSTKIE cztery powierzchnie z tym samym wzorcem, bo naprawa
tylko profilu zostawiłaby trzy pozostałe zepsute — w tym
``GET /api/admin/clients-overview``, który zwraca ``list[OverviewRow]``, więc
JEDEN taki wiersz wywracał całą listę dla wszystkich użytkowników.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import AsyncIterator

import pytest
import pytest_asyncio
from httpx import AsyncClient
from pydantic import ValidationError


# Realne wartości z prod (kontrakt 490, Alior Bank).
HOURLY_RATE_CLIENT = Decimal("141.18")
HOURLY_RATE_CANDIDATE = Decimal("100")
BILLING_HOURS = 160

# 141.18 × 160 = 22588.80 → zaokrąglenie pół w górę
EXPECTED_MONTHLY_CLIENT = 22589
# 100 × 160 = 16000.00 → już całkowite
EXPECTED_MONTHLY_CANDIDATE = 16000
# (141.18 − 100) × 160 = 6588.80
EXPECTED_MONTHLY_MARGIN = 6589


@pytest_asyncio.fixture
async def fractional_contract() -> AsyncIterator[dict[str, int]]:
    """Klient + kandydat + AKTYWNY kontrakt godzinowy o niecałkowitej kwocie /mc.

    Sprząta po sobie: wiersz z groszami jest trucizną dla współdzielonej bazy CI
    (wywraca listy innych testów), więc nie zostawiamy go po sobie.
    """
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate
    from app.models.client import Client
    from app.models.contract import Contract, ContractStatus, RateUnit

    suffix = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        client = Client(name=f"WholePLN Regression {suffix}")
        candidate = Candidate(name="WholePLN", lastname=f"Regression {suffix}")
        db.add_all([client, candidate])
        await db.flush()

        contract = Contract(
            client_id=client.id,
            candidate_id=candidate.id,
            rate_client=HOURLY_RATE_CLIENT,
            rate_candidate=HOURLY_RATE_CANDIDATE,
            rate_unit=RateUnit.hourly,
            billing_hours_per_month=BILLING_HOURS,
            status=ContractStatus.active,
        )
        db.add(contract)
        await db.commit()
        ids = {
            "client_id": client.id,
            "candidate_id": candidate.id,
            "contract_id": contract.id,
        }

    try:
        yield ids
    finally:
        # Kolejność ma znaczenie: kontrakt trzyma FK na kandydata i klienta.
        async with AsyncSessionLocal() as db:
            for model, key in (
                (Contract, "contract_id"),
                (Candidate, "candidate_id"),
                (Client, "client_id"),
            ):
                row = await db.get(model, ids[key])
                if row is not None:
                    await db.delete(row)
            await db.commit()


@pytest.mark.asyncio
async def test_model_property_really_is_fractional_decimal(
    fractional_contract: dict[str, int],
) -> None:
    """Straż przy założeniu testu: bez ułamka reszta pliku nic nie dowodzi.

    Gdyby ktoś kiedyś zmienił ``monthly_rate`` tak, że zwraca liczbę całkowitą
    (albo ``float``), wszystkie testy niżej przechodziłyby z fałszywego powodu.
    """
    from app.core.database import AsyncSessionLocal
    from app.models.contract import Contract

    async with AsyncSessionLocal() as db:
        contract = await db.get(Contract, fractional_contract["contract_id"])
        assert contract is not None
        monthly = contract.monthly_rate_client
        assert isinstance(monthly, Decimal), f"oczekiwano Decimal, jest {type(monthly)}"
        assert monthly == Decimal("22588.80")
        assert monthly % 1 != 0, "kwota musi mieć grosze — inaczej test nic nie mierzy"
        assert contract.monthly_margin == Decimal("6588.80")


@pytest.mark.asyncio
async def test_client_profile_survives_fractional_monthly_amount(
    app_client: AsyncClient,
    app_auth_headers: dict[str, str],
    fractional_contract: dict[str, int],
) -> None:
    """GET /api/clients/{id}/profile — 200 i zaokrąglone pełne złotówki."""
    resp = await app_client.get(
        f"/api/clients/{fractional_contract['client_id']}/profile",
        headers=app_auth_headers,
    )
    assert resp.status_code == 200, resp.text

    consultants = resp.json()["active_consultants"]
    row = next(
        (
            c
            for c in consultants
            if c["contract_id"] == fractional_contract["contract_id"]
        ),
        None,
    )
    assert row is not None, f"kontrakt nie trafił na listę konsultantów: {consultants}"
    assert row["monthly_rate_client"] == EXPECTED_MONTHLY_CLIENT
    assert row["monthly_rate_candidate"] == EXPECTED_MONTHLY_CANDIDATE
    assert row["monthly_margin"] == EXPECTED_MONTHLY_MARGIN


@pytest.mark.asyncio
async def test_admin_clients_overview_survives_fractional_margin(
    app_client: AsyncClient,
    app_auth_headers: dict[str, str],
    fractional_contract: dict[str, int],
) -> None:
    """GET /api/admin/clients-overview — jeden zły wiersz nie wywraca CAŁEJ listy.

    Endpoint nie ma limitu (zwraca wszystkich klientów) i deklaruje
    ``list[OverviewRow]``, więc przed poprawką ten seed 5xx-ował listę
    wszystkim użytkownikom, nie tylko przy jednym kliencie.
    """
    resp = await app_client.get("/api/admin/clients-overview", headers=app_auth_headers)
    assert resp.status_code == 200, resp.text

    rows = resp.json()
    row = next(
        (r for r in rows if r["client_id"] == fractional_contract["client_id"]), None
    )
    assert row is not None, (
        "zaseedowany klient musi być na liście (endpoint bez limitu)"
    )
    assert row["monthly_margin_total"] == EXPECTED_MONTHLY_MARGIN


# ── Warstwa schematów: wszystkie cztery powierzchnie z tym wzorcem ───────────


def _candidate_brief() -> dict[str, object]:
    return {"id": 1, "name": "Test Kandydat"}


def test_active_consultant_item_rounds_fractional_decimal() -> None:
    from app.schemas.client_profile import ActiveConsultantItem

    item = ActiveConsultantItem(
        contract_id=1,
        candidate=_candidate_brief(),
        monthly_rate_client=Decimal("22588.80"),
        monthly_rate_candidate=Decimal("16000.00"),
        monthly_margin=Decimal("6588.80"),
    )
    assert item.monthly_rate_client == EXPECTED_MONTHLY_CLIENT
    assert item.monthly_rate_candidate == EXPECTED_MONTHLY_CANDIDATE
    assert item.monthly_margin == EXPECTED_MONTHLY_MARGIN


def test_overview_row_rounds_fractional_decimal() -> None:
    from app.schemas.admin_clients_overview import DlKpiRow, OverviewRow

    row = OverviewRow(
        client_id=1, name="Alior", monthly_margin_total=Decimal("22691.20")
    )
    assert row.monthly_margin_total == 22691

    dl = DlKpiRow(
        dl_user_id=1,
        dl_name="DL",
        dl_email="dl@example.com",
        monthly_margin_total=Decimal("6588.80"),
    )
    assert dl.monthly_margin_total == EXPECTED_MONTHLY_MARGIN


def test_client_dashboard_rounds_fractional_decimal() -> None:
    from app.schemas.my_clients import ClientDashboardResponse

    dash = ClientDashboardResponse(
        client_id=1,
        client_name="Alior",
        monthly_margin_total=Decimal("22691.20"),
    )
    assert dash.monthly_margin_total == 22691


def test_request_history_entry_rounds_fractional_decimal() -> None:
    """``fee_rate`` bierze ``contract.monthly_margin`` (Decimal) — ten sam wzorzec.

    Defekt utajony: kontrakty Aliora nie mają ``job_id``, więc tą ścieżką nie
    dało się go dziś wywołać na prodzie. Test pilnuje go, zanim jakikolwiek
    kontrakt ze stawką w groszach dostanie powiązanie z rekrutacją.
    """
    from app.schemas.request_history import RequestHistoryEntry

    entry = RequestHistoryEntry(
        job_id=1,
        title="Senior Java Developer",
        status="published",
        is_in_progress=True,
        similarity=0.5,
        similarity_source="sql_same_client",
        created_at="2026-08-12T10:00:00Z",
        fee_rate=Decimal("6588.80"),
    )
    assert entry.fee_rate == EXPECTED_MONTHLY_MARGIN


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (Decimal("22588.80"), 22589),  # pół w górę
        (Decimal("22588.50"), 22589),  # dokładnie pół → w górę
        (Decimal("22588.49"), 22588),  # w dół
        (Decimal("22588.00"), 22588),  # już całkowite
        (Decimal("-700.80"), -701),  # marża ujemna (stawka kosztowa > przychodowej)
        (22588.80, 22589),  # float, np. z ręcznego wywołania
        (22588, 22588),  # int przechodzi bez zmian
        (None, None),  # Optional zostaje Optional
    ],
)
def test_whole_pln_coercion_matrix(value: object, expected: object) -> None:
    from app.schemas.client_profile import ActiveConsultantItem

    item = ActiveConsultantItem(
        contract_id=1, candidate=_candidate_brief(), monthly_margin=value
    )
    assert item.monthly_margin == expected


def test_whole_pln_still_rejects_non_numeric() -> None:
    """Koercja NIE jest szerokim tłumieniem — śmieci nadal są odrzucane.

    Gdyby walidator „na wszelki wypadek" zwracał ``None`` dla nieznanych typów,
    błąd danych zamieniłby się w cichy brak kwoty na ekranie.
    """
    from app.schemas.client_profile import ActiveConsultantItem

    with pytest.raises(ValidationError):
        ActiveConsultantItem(
            contract_id=1, candidate=_candidate_brief(), monthly_margin="dużo"
        )
