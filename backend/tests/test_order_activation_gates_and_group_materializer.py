"""Trzy ciche awarie w module zamówień: bramka aktywacji, reguła Nordei, materializer grup.

Wspólny mianownik: żadna z nich nie zgłasza błędu. Żądanie kończy się 200,
ekran wygląda poprawnie, a system robi coś innego, niż operator zobaczył.

1. **Bramka auto-aktywacji** pytała cache'owaną kolumnę
   ``contracts.rate_candidate``, więc umowa ze stawką progresywną zaczynającą
   się w przyszłości nigdy nie wypychała zamówienia z Draftu. Dwa identycznie
   wypełnione formularze dawały różny wynik, a draftowa linia nie wchodzi ani
   do ``active_md_lines``, ani do licznika konsultantów.
2. **Ten sam mechanizm nadpisywał jawny ``status: draft``**, czyli pierwszy
   krok jedynej udokumentowanej drogi twardego usunięcia zamówienia
   (``PATCH {"status": "draft"}`` → ``DELETE``).
3. **Reguła numeru zamówienia Nordei** dopasowywała klienta po PODCIĄGU
   wolnotekstowej nazwy, którą nadpisuje import z Traffita.
4. **Materializer przyszłych grup** datował się zegarem kontenera (UTC) i
   domykał poprzednika bez wpisu w historii oraz bez dociągnięcia ``end_date``.

Testy są jednostkowe (bez bazy) świadomie: schemat testowej bazy w tym
środowisku jest starszy niż migracje modułu zamówień, więc ścieżka HTTP nie
daje się tu uruchomić, a te reguły dają się dowieść na obiektach w pamięci.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest

from app.api.client_orders import (
    _activation_candidate_rate,
    _auto_activate_unless_status_explicit,
    _is_nordea_order_number_client,
    _order_has_required_activation_data,
)
from app.core.scheduling import business_today
from app.models.client_order import ClientOrder, ClientOrderStatus
from app.models.client_order_group import (
    GROUP_STATUS_ACTIVE,
    GROUP_STATUS_COMPLETED,
    GROUP_STATUS_SCHEDULED,
    ClientOrderGroup,
)
from app.models.contract import Contract
from app.models.contract_candidate_rate import ContractCandidateRate
from app.services.multi_consultant_orders import EVENT_ORDER_CLOSED
from app.services.order_group_lifecycle import materialize_scheduled_order_groups

_TODAY = business_today()


# ── 1. Bramka aktywacji: stawka OBOWIĄZUJĄCA, nie cache ─────────────────────


def _contract_with_future_progressive_rate() -> Contract:
    """Umowa zakładana „od przyszłego miesiąca" ze stawką progresywną.

    Odwzorowuje realny zapis z dialogu rejestru: pierwszy krok harmonogramu ma
    ``effective_from`` = data rozpoczęcia kontraktu, a ``create_contract``
    ustawia kolumnę na ``effective_candidate_rate(dziś)``, czyli — dla startu
    w przyszłości — na ``None``.
    """
    start = _TODAY + timedelta(days=30)
    contract = Contract(
        candidate_id=1,
        client_id=1,
        start_date=start,
        rate_candidate=None,
        candidate_rate_schedule=[
            ContractCandidateRate(rate=Decimal("100.000"), effective_from=start),
            ContractCandidateRate(
                rate=Decimal("120.000"), effective_from=start + timedelta(days=180)
            ),
        ],
    )
    return contract


def _complete_draft_order(contract: Contract) -> ClientOrder:
    return ClientOrder(
        client_id=1,
        contract_id=1,
        contract=contract,
        title="445/2026",
        status=ClientOrderStatus.draft,
        start_date=_TODAY,
        end_date=_TODAY + timedelta(days=365),
        rate_client=Decimal("150.000"),
    )


def test_future_progressive_rate_counts_as_filled_in():
    """Kolumna jest pusta, ale stawka ISTNIEJE — bramka musi to widzieć."""
    contract = _contract_with_future_progressive_rate()
    assert contract.rate_candidate is None  # cache milczy…
    assert _activation_candidate_rate(contract) == Decimal(
        "100.000"
    )  # …harmonogram nie
    assert _order_has_required_activation_data(_complete_draft_order(contract)) is True


def test_flat_rate_without_schedule_still_reads_the_column():
    """Umowa bez harmonogramu: kolumna JEST prawdą i nic się dla niej nie zmienia."""
    contract = Contract(
        candidate_id=1,
        client_id=1,
        start_date=_TODAY,
        rate_candidate=Decimal("100.000"),
        candidate_rate_schedule=[],
    )
    assert _activation_candidate_rate(contract) == Decimal("100.000")
    assert _order_has_required_activation_data(_complete_draft_order(contract)) is True


def test_missing_rate_everywhere_keeps_the_order_in_draft():
    """Bramka nie może się rozluźnić: brak stawki to nadal niekompletny draft."""
    contract = Contract(
        candidate_id=1,
        client_id=1,
        start_date=_TODAY,
        rate_candidate=None,
        candidate_rate_schedule=[],
    )
    assert _activation_candidate_rate(contract) is None
    assert _order_has_required_activation_data(_complete_draft_order(contract)) is False


def test_unloaded_schedule_falls_back_to_the_column_instead_of_500():
    """Relacja niezaładowana → kolumna, nie ``MissingGreenlet``.

    Ścieżka atomowa Flow B tworzy kontrakt bez harmonogramu i nigdy go nie
    dotyka, więc bramka nie może na niej wybuchnąć.
    """
    contract = Contract(
        candidate_id=1, client_id=1, start_date=_TODAY, rate_candidate=Decimal("90.000")
    )
    assert _activation_candidate_rate(contract) == Decimal("90.000")


# ── 2. Jawny ``status`` wygrywa z heurystyką kompletności ───────────────────


def test_explicit_draft_survives_the_completeness_heuristic():
    """Pierwszy krok usuwania zamówienia nie może być cofany przez automat."""
    order = _complete_draft_order(_contract_with_future_progressive_rate())
    assert (
        _auto_activate_unless_status_explicit(order, explicit_fields={"status"})
        is False
    )
    assert order.status == ClientOrderStatus.draft


def test_completing_a_draft_without_touching_status_still_activates():
    """Bez jawnego statusu automat działa jak dotąd — inaczej regres w drugą stronę."""
    order = _complete_draft_order(_contract_with_future_progressive_rate())
    assert (
        _auto_activate_unless_status_explicit(order, explicit_fields={"rate_client"})
        is True
    )
    assert order.status == ClientOrderStatus.active


# ── 3. Nordea: lista ID z ENV, nie podciąg nazwy ────────────────────────────


def test_nordea_policy_is_keyed_by_client_id(monkeypatch):
    monkeypatch.setenv("NORDEA_ORDER_NUMBER_CLIENT_IDS", "7, 9")
    assert _is_nordea_order_number_client(7) is True
    assert _is_nordea_order_number_client(9) is True
    assert _is_nordea_order_number_client(8) is False
    assert _is_nordea_order_number_client(None) is False


def test_nordea_policy_is_fail_closed_and_typo_tolerant(monkeypatch):
    """Pusto = nieaktywne dla wszystkich; literówka gasi jeden wpis, nie request."""
    monkeypatch.delenv("NORDEA_ORDER_NUMBER_CLIENT_IDS", raising=False)
    assert _is_nordea_order_number_client(7) is False
    monkeypatch.setenv("NORDEA_ORDER_NUMBER_CLIENT_IDS", "7,nordea,,9")
    assert _is_nordea_order_number_client(7) is True
    assert _is_nordea_order_number_client(9) is True


# ── 4. Materializer przyszłych grup ─────────────────────────────────────────


class _Scalars:
    def __init__(self, rows):
        self._rows = list(rows)

    def all(self):
        return list(self._rows)

    def __iter__(self):
        return iter(self._rows)


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return _Scalars(self._rows)


class _FakeSession:
    """Minimalna sesja: materializer robi tylko SELECT-y, ``add`` i ``flush``.

    Baza testowa w tym środowisku ma schemat starszy niż migracje modułu
    zamówień, więc obiekty ORM budujemy w pamięci. Rozróżnienie zapytań idzie
    po encji i po literale w ``WHERE`` — dokładnie tak, jak buduje je kod.
    """

    def __init__(self, groups, lines):
        self.groups = groups
        self.lines = lines
        self.added = []
        self.flushes = 0

    async def execute(self, stmt):
        entity = stmt.column_descriptions[0]["entity"]
        if entity is ClientOrderGroup:
            return _Result(self.groups)
        group_id = stmt.whereclause.right.value
        return _Result([ln for ln in self.lines if ln.order_group_id == group_id])

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        self.flushes += 1


def _group(gid, *, status, start, end=None, predecessor=None):
    group = ClientOrderGroup(
        client_id=1,
        order_number=f"NR-{gid}",
        start_date=start,
        end_date=end,
        status=status,
        predecessor_group_id=predecessor,
    )
    group.id = gid
    return group


def _line(lid, gid, *, status, end=None):
    line = ClientOrder(
        client_id=1, contract_id=1, order_group_id=gid, title=f"L{lid}", status=status
    )
    line.end_date = end
    return line


@pytest.mark.asyncio
async def test_successor_promotion_closes_predecessor_with_history_and_end_date():
    """Automatyczne domknięcie musi zostawić ten sam ślad co ręczne.

    Bez wpisu w dzienniku dialog „Historia statusów" nie pokazuje NIC między
    przedłużeniem a stanem obecnym (``closure_reason`` kasuje pierwsze
    przywrócenie), a bez dociągnięcia ``end_date`` karta zakończonego
    zamówienia głosi „do 31.12", choć jego linie są już przycięte.
    """
    start = _TODAY
    previous = _group(
        1,
        status=GROUP_STATUS_ACTIVE,
        start=start - timedelta(days=365),
        end=start + timedelta(days=200),
    )
    current = _group(2, status=GROUP_STATUS_SCHEDULED, start=start, predecessor=1)
    lines = [
        _line(10, 1, status=ClientOrderStatus.active, end=start + timedelta(days=200)),
        _line(20, 2, status=ClientOrderStatus.draft),
    ]
    db = _FakeSession([previous, current], lines)

    changed = await materialize_scheduled_order_groups(db, today=start)

    assert changed == 2
    assert current.status == GROUP_STATUS_ACTIVE
    assert previous.status == GROUP_STATUS_COMPLETED
    # Dzień przed startem następcy — jak `closure_date`, jak linie.
    assert previous.end_date == start - timedelta(days=1)
    assert lines[0].end_date == start - timedelta(days=1)
    assert lines[1].status == ClientOrderStatus.active

    events = [obj for obj in db.added if getattr(obj, "event_type", None)]
    assert len(events) == 1
    assert events[0].event_type == EVENT_ORDER_CLOSED
    assert events[0].group_id == previous.id
    # Przejście systemowe — brak autora jest informacją, nie brakiem danych.
    assert events[0].created_by_user_id is None
    assert events[0].payload["successor_group_id"] == current.id


@pytest.mark.asyncio
async def test_same_day_replacement_never_writes_an_end_date_before_start():
    """``ck_client_order_groups_dates`` wymaga ``end_date >= start_date``.

    Następca startujący tego samego dnia daje granicę historii sprzed startu
    poprzednika. Materializer jest wołany z ``list_order_groups``, więc
    naruszenie CHECK-a byłoby 500 przy KAŻDYM otwarciu zakładki.
    """
    start = _TODAY
    previous = _group(1, status=GROUP_STATUS_ACTIVE, start=start)
    current = _group(2, status=GROUP_STATUS_SCHEDULED, start=start, predecessor=1)
    db = _FakeSession([previous, current], [])

    await materialize_scheduled_order_groups(db, today=start)

    assert previous.end_date == previous.start_date
    assert previous.end_date >= previous.start_date


@pytest.mark.asyncio
async def test_materializer_is_idempotent_and_logs_the_closure_once():
    """Wołane z każdego odczytu listy — powtórka nie może dokładać wpisów."""
    start = _TODAY
    previous = _group(1, status=GROUP_STATUS_ACTIVE, start=start - timedelta(days=90))
    current = _group(2, status=GROUP_STATUS_SCHEDULED, start=start, predecessor=1)
    db = _FakeSession([previous, current], [])

    assert await materialize_scheduled_order_groups(db, today=start) == 2
    assert await materialize_scheduled_order_groups(db, today=start) == 0
    events = [obj for obj in db.added if getattr(obj, "event_type", None)]
    assert len(events) == 1


@pytest.mark.asyncio
async def test_boundary_defaults_to_the_business_day_not_the_container_clock(
    monkeypatch,
):
    """Domyślne „dziś" bierze się z doby warszawskiej, nie z zegara kontenera.

    Między północą warszawską a UTC (1 h zimą, 2 h latem) ``date.today()``
    zwraca WCZORAJ, więc zamówienie startujące dziś zostawało ``scheduled``
    z liniami w ``draft`` — poza ``active_md_lines`` i poza licznikiem
    konsultantów — podczas gdy bliźniaczy cron kontraktów był już na nowym
    dniu. Podmieniamy helper, bo przez większość doby obie odpowiedzi są
    identyczne i test oparty na realnym zegarze przespałby regres.
    """
    import app.services.order_group_lifecycle as mod

    start = _TODAY
    monkeypatch.setattr(mod, "business_today", lambda: start)
    current = _group(1, status=GROUP_STATUS_SCHEDULED, start=start)
    db = _FakeSession([current], [])

    assert await materialize_scheduled_order_groups(db) == 1
    assert current.status == GROUP_STATUS_ACTIVE

    # A gdyby granica cofnęła się o dobę (dokładnie to robi zegar UTC przed
    # północą warszawską), promocja NIE zachodzi — czyli helper jest tym,
    # który o niej decyduje.
    monkeypatch.setattr(mod, "business_today", lambda: start - timedelta(days=1))
    later = _group(2, status=GROUP_STATUS_SCHEDULED, start=start)
    db2 = _FakeSession([later], [])
    assert await materialize_scheduled_order_groups(db2) == 0
    assert later.status == GROUP_STATUS_SCHEDULED
