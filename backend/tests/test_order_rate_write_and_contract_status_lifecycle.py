"""Zapis stawki kosztowej i zapis statusu umowy — dwie ciche awarie.

Wspólny mianownik obu: żądanie kończy się sukcesem, ekran pokazuje nową
wartość, a system zachowuje się tak, jakby nic się nie stało.

1. **Stawka kosztowa z formularza zamówienia** szła wprost do cache'owanej
   kolumny ``contracts.rate_candidate``, podczas gdy KAŻDY odczyt pieniędzy
   idzie przez ``effective_rate_fields`` → ``_resolve_scheduled_rate``, który
   schodzi do kolumny wyłącznie przy PUSTYM harmonogramie. Dla umowy ze
   stawką progresywną albo z aneksem ``rate_change`` — czyli dla populacji,
   dla której harmonogram powstał — zapis był ignorowany przez marżę wiersza,
   kartę kontraktora, ``/my-clients``, przegląd admina i analitykę. HTTP 200,
   zero logów, rozjazd w raporcie.

2. **Status umowy z rejestru** zapisywany był surowym ``setattr``, czyli
   z pominięciem ``contract_lifecycle``. Terminalny ``void`` dawał się
   wskrzesić do przychodu, ``active`` omijało komplet pól i dowód podpisu,
   a „Zakończony" nie robił tego, co ``/terminate``: bez koherencji
   ``end_date`` (samoleczenie natychmiast cofało status) i bez syncu
   ``ClientOrder`` (zamówienia klienta zostawały otwarte, a skaner wygasania
   dalej alarmował o zakończonej współpracy).

3. Ta sama odpowiedź API podawała marżę z harmonogramu obok stawki kosztowej
   z kolumny, więc karta kontraktora pokazywała
   „stawka przychodowa − stawka kosztowa ≠ marża" i wzrokiem nie dało się
   rozstrzygnąć, która liczba jest prawdziwa.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest
from fastapi import HTTPException
from httpx import AsyncClient

from app.api.client_orders import _apply_candidate_rate, _compute_monthly_margin
from app.api.contracts import _apply_contract_status_change
from app.core.scheduling import business_today
from app.models.client_order import ClientOrder, ClientOrderStatus
from app.models.contract import Contract, ContractStatus, RateUnit
from app.models.contract_candidate_rate import ContractCandidateRate
from app.models.contract_client_rate import ContractClientRate
from app.models.order_type import OrderType
from app.services.contract_lifecycle import ContractTransitionError
from app.services.contract_rates import effective_rate_fields

pytestmark = pytest.mark.asyncio

_TODAY = date.today()
_START = _TODAY - timedelta(days=400)
_STEP = _TODAY - timedelta(days=200)

# Okres 1 = to, co trzymają kolumny legacy. Okres 2 = krok, którego data już
# minęła — każda dzisiejsza liczba ma pochodzić WŁAŚNIE z niego.
_P1_CLIENT = Decimal("15000.000")
_P1_CANDIDATE = Decimal("10000.000")
_P2_CLIENT = Decimal("18000.000")
_P2_CANDIDATE = Decimal("12000.000")


# ── Jednostkowo: zapis stawki trafia tam, skąd czyta odczyt ────────────────


def _scheduled_contract() -> Contract:
    """Umowa z harmonogramem, której kolumny legacy stoją w okresie 1."""
    c = Contract()
    c.rate_unit = RateUnit.monthly
    c.billing_hours_per_month = 160
    c.rate_candidate = _P1_CANDIDATE
    c.rate_client = _P1_CLIENT
    c.framework_rate = None
    c.candidate_rate_schedule = [
        ContractCandidateRate(rate=_P1_CANDIDATE, effective_from=_START),
        ContractCandidateRate(rate=_P2_CANDIDATE, effective_from=_STEP),
    ]
    c.client_rate_schedule = [
        ContractClientRate(rate=_P2_CLIENT, effective_from=_STEP),
    ]
    c.framework_rate_schedule = []
    return c


def test_rate_write_reaches_the_schedule_the_readers_use():
    """Bez tego kroku zapis był no-opem dla KAŻDEJ powierzchni pieniędzy."""
    c = _scheduled_contract()
    today = business_today()
    assert effective_rate_fields(c, today)["rate_candidate"] == _P2_CANDIDATE

    _apply_candidate_rate(c, Decimal("13500.000"), actor_id=7)

    assert effective_rate_fields(c, today)["rate_candidate"] == Decimal("13500.000")
    # Historia zostaje nietknięta — zmienia się przyszłość, nie przeszłość.
    day_before_step = _STEP - timedelta(days=1)
    assert effective_rate_fields(c, day_before_step)["rate_candidate"] == _P1_CANDIDATE


def test_rate_write_keeps_the_cached_column_and_margin_coherent():
    """Filtr „marża od" w rejestrze porównuje UTRWALONĄ kolumnę `margin`."""
    c = _scheduled_contract()

    _apply_candidate_rate(c, Decimal("13500.000"), actor_id=7)

    assert c.rate_candidate == Decimal("13500.000")
    assert c.margin == _P1_CLIENT - Decimal("13500.000")


async def test_historical_order_without_amount_snapshot_uses_dated_schedule():
    """0249 nie zamraża starego cache'u na zamówieniu historycznym."""

    contract = _scheduled_contract()
    order = ClientOrder(
        rate_candidate=None,
        rate_client=None,
        rate_unit=RateUnit.monthly,
        billing_hours_per_month=160,
        rate_client_currency="PLN",
        rate_candidate_currency="PLN",
    )

    assert _compute_monthly_margin(order, contract, business_today()) == (
        _P2_CLIENT - _P2_CANDIDATE
    )


def test_same_day_correction_overwrites_the_step_instead_of_stacking():
    c = _scheduled_contract()
    today = business_today()

    _apply_candidate_rate(c, Decimal("13500.000"), actor_id=7)
    _apply_candidate_rate(c, Decimal("13900.000"), actor_id=7)

    steps_today = [s for s in c.candidate_rate_schedule if s.effective_from == today]
    assert len(steps_today) == 1, "poprawka literówki nie ma puchnąć w historii"
    assert effective_rate_fields(c, today)["rate_candidate"] == Decimal("13900.000")


def test_contract_without_schedule_still_writes_the_legacy_column():
    """Umowy sprzed harmonogramów muszą działać jak dotąd."""
    c = Contract()
    c.rate_unit = RateUnit.monthly
    c.billing_hours_per_month = 160
    c.rate_candidate = Decimal("9000.000")
    c.rate_client = Decimal("12000.000")
    c.framework_rate = None
    c.candidate_rate_schedule = []
    c.client_rate_schedule = []
    c.framework_rate_schedule = []

    _apply_candidate_rate(c, Decimal("9500.000"), actor_id=7)

    assert c.rate_candidate == Decimal("9500.000")
    assert not c.candidate_rate_schedule, "brak harmonogramu = brak nowego kroku"
    assert effective_rate_fields(c, business_today())["rate_candidate"] == Decimal(
        "9500.000"
    )


def test_clearing_a_scheduled_rate_is_refused_instead_of_silently_ignored():
    """Krok nie może mieć pustej stawki, a wyzerowanie kolumny nic nie zmienia."""
    c = _scheduled_contract()

    with pytest.raises(HTTPException) as exc:
        _apply_candidate_rate(c, None, actor_id=7)

    assert exc.value.status_code == 409
    assert effective_rate_fields(c, business_today())["rate_candidate"] == _P2_CANDIDATE


# ── Jednostkowo: status umowy przechodzi przez maszynę stanów ──────────────


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return self

    def unique(self):
        return self

    def all(self):
        return self._rows


class _FakeDb:
    """Minimalna atrapa sesji — te ścieżki tylko czytają zamówienia i dodają audyt."""

    def __init__(self, orders=()):
        self.orders = list(orders)
        # Centralny offboarding najpierw odczytuje pending cases, potem otwarte
        # zamówienia. Ta atrapa zachowuje kolejność dwóch jawnych SELECT-ów.
        self._execute_rows = [[], self.orders]
        self.added: list[object] = []

    async def execute(self, *_args, **_kwargs):
        rows = self._execute_rows.pop(0) if self._execute_rows else []
        return _FakeResult(rows)

    async def scalar(self, *_args, **_kwargs):
        return None

    def add(self, obj):
        self.added.append(obj)


def _contract(status: ContractStatus, **fields) -> Contract:
    c = Contract()
    c.id = 4242
    c.status = status
    c.contract_type = None
    for key, value in fields.items():
        setattr(c, key, value)
    return c


async def test_void_contract_cannot_be_resurrected_by_a_status_write():
    """`ALLOWED_TRANSITIONS[void]` jest PUSTY — void to soft-delete, terminalny.

    Surowy zapis przywracał anulowaną umowę do MRR, liczników konsultantów
    i alertów DL.
    """
    contract = _contract(ContractStatus.void, end_date=None)

    with pytest.raises(ContractTransitionError):
        await _apply_contract_status_change(
            _FakeDb(), contract, ContractStatus.active, actor_id=1
        )

    assert contract.status == ContractStatus.void


async def test_activation_from_draft_still_demands_the_required_fields():
    """`active` z pustymi polami to umowa w przychodzie bez danych do liczenia."""
    contract = _contract(
        ContractStatus.draft,
        start_date=None,
        end_date=None,
        rate_candidate=None,
        rate_client=None,
        work_mode=None,
    )

    with pytest.raises(HTTPException) as exc:
        await _apply_contract_status_change(
            _FakeDb(), contract, ContractStatus.active, actor_id=1
        )

    assert exc.value.status_code == 409
    assert contract.status == ContractStatus.draft


async def test_ending_a_contract_pins_the_end_date_so_the_heal_cannot_undo_it():
    """Umowa bezterminowa „jeszcze się nie skończyła" — bez daty status wracał.

    ``_status_after_end_date_change`` (ten sam handler kilka linii niżej oraz
    dzienny cron) cofa `ended` na `active`, gdy `end_date` jest puste albo
    przyszłe. Zapis wyglądałby na udany i sam się kasował.
    """
    contract = _contract(ContractStatus.active, end_date=None)

    await _apply_contract_status_change(
        _FakeDb(), contract, ContractStatus.ended, actor_id=1
    )

    assert contract.status == ContractStatus.ended
    assert contract.end_date == business_today()


async def test_ending_a_contract_closes_its_open_client_orders():
    """Bez syncu skaner wygasania alarmuje o zamówieniu zakończonej współpracy."""
    when = business_today()
    running = ClientOrder(
        client_id=1,
        order_type=OrderType.periodic.value,
        status=ClientOrderStatus.active,
        start_date=when - timedelta(days=30),
        end_date=when + timedelta(days=120),
    )
    not_started_yet = ClientOrder(
        client_id=1,
        order_type=OrderType.periodic.value,
        status=ClientOrderStatus.active,
        start_date=when + timedelta(days=10),
        end_date=when + timedelta(days=200),
    )
    contract = _contract(ContractStatus.active, end_date=when + timedelta(days=120))

    await _apply_contract_status_change(
        _FakeDb([running, not_started_yet]),
        contract,
        ContractStatus.ended,
        actor_id=1,
    )

    assert running.end_date == when
    assert running.status == ClientOrderStatus.completed
    # Zamówienie, które miało ruszyć po dacie końca, nigdy nie ruszy.
    assert not_started_yet.status == ClientOrderStatus.cancelled


async def test_late_manual_end_uses_the_contracts_historical_end_date():
    """Spóźniona zmiana statusu nie może wydłużyć zamówienia do dzisiaj."""
    today = business_today()
    contract_end = today - timedelta(days=7)
    running = ClientOrder(
        client_id=1,
        order_type=OrderType.periodic.value,
        status=ClientOrderStatus.active,
        start_date=contract_end - timedelta(days=30),
        end_date=today + timedelta(days=90),
    )
    contract = _contract(ContractStatus.active, end_date=contract_end)

    await _apply_contract_status_change(
        _FakeDb([running]),
        contract,
        ContractStatus.ended,
        actor_id=1,
    )

    assert running.end_date == contract_end
    assert running.status == ClientOrderStatus.completed


async def test_reactivating_an_ended_contract_goes_through_reopen_not_activation():
    """Dowód podpisu już istnieje — to powrót, nie świeża aktywacja."""
    contract = _contract(
        ContractStatus.ended,
        end_date=_TODAY + timedelta(days=30),
        start_date=_START,
        rate_candidate=None,
        rate_client=None,
        work_mode=None,
    )
    db = _FakeDb()

    await _apply_contract_status_change(db, contract, ContractStatus.active, actor_id=1)

    assert contract.status == ContractStatus.active
    assert db.added, "reaktywacja musi zostawić ślad w feedzie aktywności"


# ── API: jedna odpowiedź, jedno źródło stawek ──────────────────────────────


async def _seed_scheduled_contract_with_order() -> tuple[int, int, int]:
    """Klient + umowa z krokiem, którego data minęła + zamówienie bez stawki."""
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate
    from app.models.client import Client

    suffix = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        client = Client(name=f"RateWrite-{suffix}")
        cand = Candidate(
            name="Stawka",
            lastname=f"Zapisana-{suffix}",
            email=f"ratewrite-{suffix}@example.com",
        )
        db.add_all([client, cand])
        await db.commit()
        await db.refresh(client)
        await db.refresh(cand)

        contract = Contract(
            candidate_id=cand.id,
            client_id=client.id,
            status=ContractStatus.active,
            start_date=_START,
            end_date=_TODAY + timedelta(days=90),
            rate_candidate=_P1_CANDIDATE,
            rate_client=_P1_CLIENT,
            margin=_P1_CLIENT - _P1_CANDIDATE,
            rate_unit=RateUnit.monthly,
            currency="PLN",
        )
        db.add(contract)
        await db.commit()
        await db.refresh(contract)

        db.add_all(
            [
                ContractCandidateRate(
                    contract_id=contract.id, rate=_P1_CANDIDATE, effective_from=_START
                ),
                ContractCandidateRate(
                    contract_id=contract.id, rate=_P2_CANDIDATE, effective_from=_STEP
                ),
                ContractClientRate(
                    contract_id=contract.id, rate=_P1_CLIENT, effective_from=_START
                ),
                ContractClientRate(
                    contract_id=contract.id, rate=_P2_CLIENT, effective_from=_STEP
                ),
            ]
        )
        order = ClientOrder(
            client_id=client.id,
            contract_id=contract.id,
            title="Zamówienie testowe",
            status=ClientOrderStatus.active,
            start_date=_TODAY - timedelta(days=30),
        )
        db.add(order)
        await db.commit()
        await db.refresh(order)
        return client.id, contract.id, order.id


async def test_contractor_card_reports_one_rate_source_not_two(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
) -> None:
    """Marża i stawka kosztowa na tej samej karcie muszą się do siebie zgadzać.

    Ta sama kolumna wychodzi też do pliku .xlsx z eksportu zamówień, czyli
    nieaktualna liczba krąży poza aplikacją.
    """
    client_id, contract_id, _ = await _seed_scheduled_contract_with_order()

    resp = await app_client.get(
        f"/api/clients/{client_id}/orders", headers=app_auth_headers
    )
    assert resp.status_code == 200, resp.text
    row = next(c for c in resp.json()["contractors"] if c["contract_id"] == contract_id)

    assert Decimal(str(row["rate_candidate"])) == _P2_CANDIDATE, "kolumna cache = 10000"
    assert Decimal(str(row["latest_order_rate_client"])) == _P2_CLIENT
    assert (
        Decimal(str(row["latest_order_monthly_margin"])) == _P2_CLIENT - _P2_CANDIDATE
    )


async def test_patching_the_cost_rate_actually_moves_the_money(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
) -> None:
    """PATCH zmienia snapshot i marżę jednego zamówienia, nie jego Contract."""
    client_id, contract_id, order_id = await _seed_scheduled_contract_with_order()
    new_rate = Decimal("13500.000")

    patch = await app_client.patch(
        f"/api/clients/{client_id}/orders/{order_id}",
        headers=app_auth_headers,
        json={"rate_candidate": float(new_rate)},
    )
    assert patch.status_code == 200, patch.text

    resp = await app_client.get(
        f"/api/clients/{client_id}/orders", headers=app_auth_headers
    )
    assert resp.status_code == 200, resp.text
    row = next(c for c in resp.json()["contractors"] if c["contract_id"] == contract_id)

    # Karta kontraktu nadal pokazuje jego bieżący harmonogram. Ręczna korekta
    # zamówienia nie może przepisać umowy ani sąsiednich zamówień tej osoby.
    assert Decimal(str(row["rate_candidate"])) == _P2_CANDIDATE
    order_row = next(order for order in row["orders"] if order["id"] == order_id)
    assert Decimal(str(order_row["rate_candidate"])) == new_rate
    assert Decimal(str(row["latest_order_monthly_margin"])) == _P2_CLIENT - new_rate
