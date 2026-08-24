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


def test_initial_status_uses_the_same_boundary_as_the_materializer(monkeypatch):
    """Stempel przy zakładaniu grupy i promocja muszą czytać JEDEN zegar.

    Materializator liczy granicę dniem biznesowym, a `_initial_group_status`
    czytał `date.today()`. Między 22:00 UTC a północą (latem) zamówienie
    zaczynające się „jutro" wg kontenera — czyli DZIŚ wg firmy — wracało
    z POST-a jako `scheduled`, po czym pierwszy odczyt listy natychmiast
    przestawiał je na `active`: dwa mechanizmy tego samego modułu datowały się
    różnymi dobami. Podmieniamy helper, bo przez większość doby obie odpowiedzi
    są identyczne i test oparty na realnym zegarze przespałby regres.
    """
    import app.api.client_order_groups as mod

    monkeypatch.setattr(mod, "business_today", lambda: _TODAY)
    assert mod._initial_group_status(_TODAY) == GROUP_STATUS_ACTIVE
    assert mod._initial_group_status(_TODAY + timedelta(days=1)) == (
        GROUP_STATUS_SCHEDULED
    )

    # Granica cofnięta o dobę (dokładnie to robi zegar UTC przed północą
    # warszawską) — start „dziś" wg firmy przestaje być bieżący.
    monkeypatch.setattr(mod, "business_today", lambda: _TODAY - timedelta(days=1))
    assert mod._initial_group_status(_TODAY) == GROUP_STATUS_SCHEDULED


# ── 5. Ticket „Draft → Aktywne”: bezterminowy okres nie blokuje aktywacji ───


def test_open_ended_period_activates_with_start_date_only():
    """Komplet 4 pól + brak daty końcowej = aktywacja (Bogusiak / Contract 570).

    Zamówienie bezterminowe to w body-leasingu stan docelowy, nie brak danych —
    poprzednia bramka wymagała obu granic i więziła taki rekord w Draft na
    stałe, bo daty końcowej z definicji nigdy nie będzie.
    """
    order = _complete_draft_order(_contract_with_future_progressive_rate())
    order.end_date = None
    assert _order_has_required_activation_data(order) is True
    assert (
        _auto_activate_unless_status_explicit(order, explicit_fields={"start_date"})
        is True
    )
    assert order.status == ClientOrderStatus.active


def test_open_ended_relaxation_does_not_loosen_the_other_requirements():
    """Zdjęcie wymogu end_date nie może rozluźnić pozostałych czterech pól."""
    contract = _contract_with_future_progressive_rate()

    missing_start = _complete_draft_order(contract)
    missing_start.end_date = None
    missing_start.start_date = None
    assert _order_has_required_activation_data(missing_start) is False

    placeholder_title = _complete_draft_order(contract)
    placeholder_title.end_date = None
    placeholder_title.title = "(bez numeru)"
    assert _order_has_required_activation_data(placeholder_title) is False

    missing_revenue = _complete_draft_order(contract)
    missing_revenue.end_date = None
    missing_revenue.rate_client = None
    assert _order_has_required_activation_data(missing_revenue) is False


# ── 6. Polkomtel (klient kosztowy): hook zatrudnienia bez auto-zamówienia ───


def test_cost_order_clients_skip_the_auto_order(monkeypatch):
    from app.core.config import settings
    from app.services.b2b_contract_automation import should_auto_create_order

    monkeypatch.setattr(settings, "COST_ORDER_CLIENT_IDS", "15")
    assert should_auto_create_order(15) is False
    assert should_auto_create_order(12) is True
    assert should_auto_create_order(None) is True

    # Pusta lista = zachowanie sprzed zmiany: auto-szkic u każdego klienta.
    monkeypatch.setattr(settings, "COST_ORDER_CLIENT_IDS", "")
    assert should_auto_create_order(15) is True


# ── 7. „Liczba MD zamówienia” na szkicu klienta MD ──────────────────────────


def _md_client(monkeypatch, *, multi: str = "12,18", cost: str = "15"):
    from app.core.config import settings

    monkeypatch.setattr(settings, "MULTI_CONSULTANT_ORDER_CLIENT_IDS", multi)
    monkeypatch.setattr(settings, "COST_ORDER_CLIENT_IDS", cost)


def _standalone_draft(client_id: int) -> ClientOrder:
    return ClientOrder(
        client_id=client_id,
        contract_id=1,
        title="445/2026",
        status=ClientOrderStatus.draft,
        start_date=_TODAY,
        rate_client=Decimal("1550.000"),
    )


def test_md_quantity_requires_an_md_client(monkeypatch):
    from fastapi import HTTPException

    from app.api.client_orders import _apply_md_order_quantity

    _md_client(monkeypatch)
    with pytest.raises(HTTPException) as excinfo:
        _apply_md_order_quantity(_standalone_draft(99), Decimal("20"))
    assert excinfo.value.status_code == 422

    # Klient kosztowy (Polkomtel) — pole nie istnieje także od strony API.
    with pytest.raises(HTTPException) as excinfo:
        _apply_md_order_quantity(_standalone_draft(15), Decimal("20"))
    assert excinfo.value.status_code == 422


def test_md_quantity_needs_the_revenue_rate_first(monkeypatch):
    """CHECK budżetu wymaga stawki > 0 — komunikat po polsku zamiast IntegrityError."""
    from fastapi import HTTPException

    from app.api.client_orders import _apply_md_order_quantity

    _md_client(monkeypatch)
    order = _standalone_draft(12)
    order.rate_client = None
    with pytest.raises(HTTPException) as excinfo:
        _apply_md_order_quantity(order, Decimal("20"))
    assert excinfo.value.status_code == 422
    assert "stawkę przychodową" in excinfo.value.detail


def test_md_quantity_sets_the_complete_budget_and_mirrors_the_rate(monkeypatch):
    from app.api.client_orders import _apply_md_order_quantity

    _md_client(monkeypatch)
    order = _standalone_draft(12)
    order.rate_client = Decimal("164.375")
    _apply_md_order_quantity(order, Decimal("20"))
    assert order.md_input_mode == "md"
    assert order.md_input_value == Decimal("20")
    assert order.md_total == Decimal("20")
    # Lustro stawki jest kwantyzowane JAWNIE do skali kolumn linii (12,2).
    assert order.md_rate_revenue == Decimal("164.38")


def test_md_quantity_none_clears_the_whole_budget(monkeypatch):
    """CHECK dopuszcza tylko komplet albo nic — czyszczenie musi być zupełne."""
    from app.api.client_orders import _apply_md_order_quantity

    _md_client(monkeypatch)
    order = _standalone_draft(12)
    _apply_md_order_quantity(order, Decimal("20"))
    _apply_md_order_quantity(order, None)
    assert order.md_total is None
    assert order.md_remaining is None
    assert order.md_input_mode is None
    assert order.md_input_value is None
    # Sama stawka bez budżetu jest legalna od 0233 — zostaje.
    assert order.md_rate_revenue == Decimal("1550.00")


def test_md_quantity_zero_is_rejected(monkeypatch):
    from fastapi import HTTPException

    from app.api.client_orders import _apply_md_order_quantity

    _md_client(monkeypatch)
    with pytest.raises(HTTPException) as excinfo:
        _apply_md_order_quantity(_standalone_draft(12), Decimal("0"))
    assert excinfo.value.status_code == 422


# ── 8. Materializacja grupy dla aktywowanego szkicu ─────────────────────────


from app.models.candidate import Candidate as _Candidate  # noqa: E402
from app.services.order_group_materializer import (  # noqa: E402
    group_number_from_order,
    materialize_group_for_activated_order,
    md_rate_from_order_rate,
)


class _DraftMaterializerSession:
    """Sesja pod materializer szkicu: scalar routowany po encji zapytania.

    Trzy zapytania: grupa (ClientOrderGroup), kandydat (Candidate) oraz suma
    konsumpcji z ``recompute_remaining`` (kolumna funkcyjna, entity=None) —
    dla świeżego szkicu zawsze zero.
    """

    def __init__(self, *, group=None, candidate=None):
        self._group = group
        self._candidate = candidate
        self.added = []
        self.flushes = 0

    async def scalar(self, stmt):
        entity = stmt.column_descriptions[0].get("entity")
        if entity is ClientOrderGroup:
            # Kontrakt zapytania: materializer dołącza WYŁĄCZNIE do grup
            # aktywnych (WHERE status == active) — fake to emuluje, żeby test
            # „scheduled ignorowane" ćwiczył realną gałąź tworzenia.
            if self._group is not None and self._group.status == GROUP_STATUS_ACTIVE:
                return self._group
            return None
        if entity is _Candidate:
            return self._candidate
        return 0

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        self.flushes += 1
        for obj in self.added:
            if isinstance(obj, ClientOrderGroup) and getattr(obj, "id", None) is None:
                obj.id = 777


def _activated_standalone_order(client_id: int = 12) -> ClientOrder:
    order = _standalone_draft(client_id)
    order.status = ClientOrderStatus.active
    order.end_date = None
    return order


@pytest.mark.asyncio
async def test_materializer_creates_an_active_group_from_the_order_number(
    monkeypatch,
):
    _md_client(monkeypatch)
    db = _DraftMaterializerSession(
        candidate=_Candidate(name="Jan", lastname="Kowalski")
    )
    order = _activated_standalone_order()
    group = await materialize_group_for_activated_order(
        db, order, actor_id=7, candidate_rate=Decimal("1260.000")
    )
    assert group is not None
    assert group.order_number == "445/2026"
    # Semantyka Ticketu 1: komplet pól = Aktywne — także dla grupy, niezależnie
    # od daty startu (inaczej świeżo uzupełnione zamówienie chowałoby się
    # przed pigułką „Aktywne” jako scheduled).
    assert group.status == GROUP_STATUS_ACTIVE
    assert group.is_cost_based is False
    assert order.order_group_id == 777
    assert order.title == "Zamówienie 445/2026 — Jan Kowalski"
    assert order.md_rate_revenue == Decimal("1550.00")
    assert order.md_rate_cost == Decimal("1260.00")
    events = [type(o).__name__ for o in db.added]
    assert "ClientOrderGroupEvent" in events


@pytest.mark.asyncio
async def test_materializer_attaches_to_the_existing_open_group(monkeypatch):
    """BIK prowadzi grupy wieloosobowe — ten sam numer dokleja linię, nie dubluje grupy."""
    _md_client(monkeypatch)
    existing = _group(55, status=GROUP_STATUS_ACTIVE, start=_TODAY)
    existing.order_number = "445/2026"
    db = _DraftMaterializerSession(
        group=existing, candidate=_Candidate(name="Maciej", lastname="Koc")
    )
    order = _activated_standalone_order()
    group = await materialize_group_for_activated_order(
        db, order, actor_id=7, candidate_rate=None
    )
    assert group is existing
    assert order.order_group_id == 55
    assert not any(isinstance(o, ClientOrderGroup) for o in db.added)


@pytest.mark.asyncio
async def test_materializer_skips_everything_out_of_scope(monkeypatch):
    _md_client(monkeypatch)
    db = _DraftMaterializerSession()

    still_draft = _standalone_draft(12)
    assert (
        await materialize_group_for_activated_order(
            db, still_draft, actor_id=7, candidate_rate=None
        )
        is None
    )

    cost_client = _activated_standalone_order(15)
    assert (
        await materialize_group_for_activated_order(
            db, cost_client, actor_id=7, candidate_rate=None
        )
        is None
    )

    ordinary_client = _activated_standalone_order(99)
    assert (
        await materialize_group_for_activated_order(
            db, ordinary_client, actor_id=7, candidate_rate=None
        )
        is None
    )

    already_grouped = _activated_standalone_order()
    already_grouped.order_group_id = 3
    assert (
        await materialize_group_for_activated_order(
            db, already_grouped, actor_id=7, candidate_rate=None
        )
        is None
    )
    assert db.added == []


def test_group_number_comes_from_the_title_and_rejects_the_placeholder():
    order = _standalone_draft(12)
    assert group_number_from_order(order) == "445/2026"
    order.title = "(bez numeru)"
    assert group_number_from_order(order) is None
    order.title = "  "
    assert group_number_from_order(order) is None


def test_md_rate_quantization_is_explicit_half_up():
    assert md_rate_from_order_rate(Decimal("164.375")) == Decimal("164.38")
    assert md_rate_from_order_rate(Decimal("1550.000")) == Decimal("1550.00")
    assert md_rate_from_order_rate(None) is None


def test_md_quantity_is_rejected_on_a_group_line(monkeypatch):
    """Linia w grupie ma własny tor budżetu (update_line + historia zamówienia)."""
    from fastapi import HTTPException

    from app.api.client_orders import _apply_md_order_quantity

    _md_client(monkeypatch)
    order = _standalone_draft(12)
    order.order_group_id = 10
    with pytest.raises(HTTPException) as excinfo:
        _apply_md_order_quantity(order, Decimal("20"))
    assert excinfo.value.status_code == 422
    assert "linia zamówienia grupowego" in excinfo.value.detail


def test_rate_change_refreshes_the_md_rate_mirror(monkeypatch):
    """Korekta stawki na szkicu z budżetem MD nie może zostawić starej kopii —
    materializacja poniosłaby do linii stawkę sprzed korekty."""
    from app.api.client_orders import (
        _apply_md_order_quantity,
        _refresh_md_rate_mirror,
    )

    _md_client(monkeypatch)
    order = _standalone_draft(12)
    _apply_md_order_quantity(order, Decimal("20"))
    assert order.md_rate_revenue == Decimal("1550.00")

    order.rate_client = Decimal("1600.000")
    _refresh_md_rate_mirror(order, explicit_fields={"rate_client"})
    assert order.md_rate_revenue == Decimal("1600.00")

    # Bez budżetu — lustro nieobowiązkowe, nic się nie dzieje.
    bare = _standalone_draft(12)
    bare.rate_client = Decimal("1700.000")
    _refresh_md_rate_mirror(bare, explicit_fields={"rate_client"})
    assert bare.md_rate_revenue is None


def test_clearing_the_rate_with_a_budget_present_is_a_422_not_integrity_error(
    monkeypatch,
):
    from fastapi import HTTPException

    from app.api.client_orders import (
        _apply_md_order_quantity,
        _refresh_md_rate_mirror,
    )

    _md_client(monkeypatch)
    order = _standalone_draft(12)
    _apply_md_order_quantity(order, Decimal("20"))
    order.rate_client = None
    with pytest.raises(HTTPException) as excinfo:
        _refresh_md_rate_mirror(order, explicit_fields={"rate_client"})
    assert excinfo.value.status_code == 422
    assert "wyczyść ją" in excinfo.value.detail


@pytest.mark.asyncio
async def test_materializer_ignores_a_scheduled_group_and_creates_a_fresh_active_one(
    monkeypatch,
):
    """Aktywna linia w grupie ``scheduled`` łamałaby kontrakt modułu
    (add_line w scheduled tworzy linie draft), chowała zamówienie przed
    pigułką „Aktywne" i przed alertem progu MD — zaplanowany dubel numeru
    dostaje więc osobną, świeżą grupę aktywną."""
    _md_client(monkeypatch)
    scheduled = _group(66, status=GROUP_STATUS_SCHEDULED, start=_TODAY)
    scheduled.order_number = "445/2026"
    db = _DraftMaterializerSession(
        group=scheduled, candidate=_Candidate(name="Jan", lastname="Kowalski")
    )
    order = _activated_standalone_order()
    group = await materialize_group_for_activated_order(
        db, order, actor_id=7, candidate_rate=None
    )
    assert group is not scheduled
    assert group is not None and group.status == GROUP_STATUS_ACTIVE
    assert order.order_group_id == 777


@pytest.mark.asyncio
async def test_materializer_skips_the_revenue_mirror_for_a_zero_rate(monkeypatch):
    """CHECK żąda md_rate_revenue > 0 także bez budżetu — zero zostaje poza
    lustrem (linia dostanie alert „brak stawki przychodowej", nie 500)."""
    _md_client(monkeypatch)
    db = _DraftMaterializerSession(candidate=_Candidate(name="Jan", lastname="Nowak"))
    order = _activated_standalone_order()
    order.rate_client = Decimal("0")
    group = await materialize_group_for_activated_order(
        db, order, actor_id=7, candidate_rate=None
    )
    assert group is not None
    assert order.md_rate_revenue is None


@pytest.mark.asyncio
async def test_materializer_sanitizes_inverted_dates_on_the_new_group(monkeypatch):
    """`ck_client_order_groups_dates` wymaga end >= start; zamówienie takiej
    walidacji nie ma — grupa dostaje „bezterminowo" zamiast IntegrityError."""
    _md_client(monkeypatch)
    db = _DraftMaterializerSession(candidate=_Candidate(name="Jan", lastname="Nowak"))
    order = _activated_standalone_order()
    order.start_date = _TODAY
    order.end_date = _TODAY - timedelta(days=30)
    group = await materialize_group_for_activated_order(
        db, order, actor_id=7, candidate_rate=None
    )
    assert group is not None
    assert group.end_date is None
    # Daty ZAMÓWIENIA zostają nietknięte — są do poprawienia w wierszu.
    assert order.end_date == _TODAY - timedelta(days=30)


def test_md_quantity_and_mirror_reject_a_zero_rate(monkeypatch):
    from fastapi import HTTPException

    from app.api.client_orders import (
        _apply_md_order_quantity,
        _refresh_md_rate_mirror,
    )

    _md_client(monkeypatch)
    order = _standalone_draft(12)
    order.rate_client = Decimal("0")
    with pytest.raises(HTTPException) as excinfo:
        _apply_md_order_quantity(order, Decimal("20"))
    assert excinfo.value.status_code == 422

    budgeted = _standalone_draft(12)
    _apply_md_order_quantity(budgeted, Decimal("20"))
    budgeted.rate_client = Decimal("0")
    with pytest.raises(HTTPException) as excinfo:
        _refresh_md_rate_mirror(budgeted, explicit_fields={"rate_client"})
    assert excinfo.value.status_code == 422
