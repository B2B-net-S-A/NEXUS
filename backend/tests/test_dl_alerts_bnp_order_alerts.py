"""BNP: dwa NIEZALEŻNE powiadomienia o kończącym się zamówieniu.

Ticket (09.2026): u BNP jedno zamówienie ma i twardą datę końca (zwykle koniec
roku), i budżet MD per konsultant. Delivery Lead ma dostawać osobny sygnał
o każdym z tych warunków i nigdy nie łączyć ich w jedną kartę.

Stan sprzed tej rewizji, który te testy pilnują, żeby nie wrócił:

* ``rule_periodic_order_ending`` pomijała WSZYSTKIE linie zamówień
  wielo-konsultantowych (``order_group_id IS NULL``), więc zamówienie BNP nie
  dawało karty w panelu „Moi klienci" — a to ona niesie maila i powtórkę co
  7 dni (dzwonek daje jeden sygnał na próg);
* jedynym alertem o MD był ``md_budget_low`` — próg BEZWZGLĘDNY 21 MD liczony
  od podstawy razem z zakresem opcjonalnym. Przy zamówieniu na 220 MD to ~90%
  zużycia.

Bramka ``EXTENDED_ORDER_ALERT_CLIENT_IDS`` jest fail-closed: pusta lista musi
zostawiać obie reguły w stanie sprzed rewizji, u wszystkich klientów.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select

_TODAY = date(2026, 10, 1)
#: Daleko poza oknem 30 dni — „długi okres" z kryterium akceptacji nr 1.
_FAR_END = date(2026, 12, 31)


# ── Seedy ───────────────────────────────────────────────────────────────────


async def _seed_client() -> int:
    from app.core.database import AsyncSessionLocal
    from app.models.client import Client

    async with AsyncSessionLocal() as db:
        client = Client(name=f"BNP-{uuid.uuid4().hex[:8]}")
        db.add(client)
        await db.commit()
        await db.refresh(client)
        return client.id


async def _seed_dl(client_id: int) -> int:
    from app.core.database import AsyncSessionLocal
    from app.core.security import hash_password
    from app.models.team_structure import DeliveryLeadClientAssignment
    from app.models.user import User, UserRole

    suffix = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        user = User(
            email=f"bnp-dl-{suffix}@example.com",
            password_hash=hash_password(f"T3st_{suffix}!PassX"),
            name="DL BNP",
            role=UserRole.delivery_lead,
            is_active=True,
            profile_completed=True,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        db.add(
            DeliveryLeadClientAssignment(
                client_id=client_id, delivery_lead_user_id=user.id
            )
        )
        await db.commit()
        return user.id


async def _seed_contract(client_id: int) -> int:
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate
    from app.models.contract import Contract, ContractStatus

    async with AsyncSessionLocal() as db:
        cand = Candidate(
            name="Piotr",
            lastname=f"Wzorowy-{uuid.uuid4().hex[:6]}",
            email=f"bnp-{uuid.uuid4().hex[:8]}@example.com",
        )
        db.add(cand)
        await db.commit()
        await db.refresh(cand)
        contract = Contract(
            candidate_id=cand.id,
            client_id=client_id,
            status=ContractStatus.active,
            rate_candidate=Decimal("100.000"),
        )
        db.add(contract)
        await db.commit()
        await db.refresh(contract)
        return contract.id


async def _seed_group_line(
    client_id: int,
    contract_id: int,
    *,
    end: date | None,
    md_total: str = "220",
    consumed: str | None = None,
    md_optional_total: str | None = None,
    md_manual_adjustment: str = "0",
    group_status: str | None = None,
) -> int:
    """Linia zamówienia wielo-konsultantowego z własnym budżetem MD."""
    from app.core.database import AsyncSessionLocal
    from app.models.client_order import ClientOrder, ClientOrderStatus
    from app.models.client_order_group import GROUP_STATUS_ACTIVE, ClientOrderGroup
    from app.models.md_consumption import ClientOrderMdConsumption

    base = Decimal(md_total)
    optional = Decimal(md_optional_total) if md_optional_total else None
    used = Decimal(consumed) if consumed else Decimal("0")
    adjustment = Decimal(md_manual_adjustment)
    async with AsyncSessionLocal() as db:
        group = ClientOrderGroup(
            client_id=client_id,
            order_number=f"4500{uuid.uuid4().hex[:6]}",
            start_date=date(2026, 9, 1),
            end_date=end,
            status=group_status or GROUP_STATUS_ACTIVE,
            # CHECK `ck_client_order_groups_closure` wymaga daty przy
            # zamówieniu zakończonym.
            closure_date=(end or _TODAY) if group_status == "completed" else None,
            order_type="md",
        )
        db.add(group)
        await db.flush()
        line = ClientOrder(
            client_id=client_id,
            contract_id=contract_id,
            title=group.order_number,
            status=ClientOrderStatus.active,
            order_group_id=group.id,
            start_date=date(2026, 9, 1),
            end_date=end,
            md_rate_revenue=Decimal("1200"),
            md_input_mode="md",
            md_input_value=base,
            md_total=base,
            md_optional_total=optional,
            md_manual_adjustment=adjustment,
            md_remaining=base + (optional or Decimal("0")) - used + adjustment,
        )
        db.add(line)
        await db.flush()
        if used:
            db.add(
                ClientOrderMdConsumption(
                    order_id=line.id,
                    period_month="2026-09",
                    md_reported=used,
                    source="manual",
                )
            )
        await db.commit()
        return line.id


async def _alerts(user_id: int, alert_type: str):
    from app.core.database import AsyncSessionLocal
    from app.models.dl_alert import DlAlert

    async with AsyncSessionLocal() as db:
        return list(
            (
                await db.scalars(
                    select(DlAlert)
                    .where(DlAlert.user_id == user_id, DlAlert.alert_type == alert_type)
                    .order_by(DlAlert.id)
                )
            ).all()
        )


async def _run(rule, monkeypatch, today: date = _TODAY):
    from app.core.database import AsyncSessionLocal
    import app.tasks.dl_alerts_scanner as scanner

    monkeypatch.setattr(scanner, "business_today", lambda: today)
    async with AsyncSessionLocal() as db:
        await rule(db)
        await db.commit()


def _emit_clock(monkeypatch):
    """Przestaw zegar EMISJI (okno powtórki), nie tylko dzień skanera.

    ``_run`` podmienia ``business_today`` — czyli to, co reguła uważa za dziś —
    ale numer okna powtórki liczy ``emit`` z ``datetime.now``. Bez podmiany obu
    „skok o tydzień" nie tworzy nowego wiersza i test przechodziłby pusto.
    Ten sam wzorzec co w ``test_dl_alerts_my_clients_panel``.
    """
    from datetime import datetime as _dt
    from datetime import timezone as _tz

    import app.services.dl_alerts as svc

    moment = _dt.now(_tz.utc)

    class _Clock(_dt):
        current = moment

        @classmethod
        def now(cls, tz=None):
            return cls.current

    monkeypatch.setattr(svc, "datetime", _Clock)
    return _Clock, moment


def _gate(monkeypatch, client_id: int) -> None:
    """Włącz rozszerzone alerty dla tego jednego klienta."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "EXTENDED_ORDER_ALERT_CLIENT_IDS", str(client_id))


# ── Bramka klienta ──────────────────────────────────────────────────────────


def test_gate_is_fail_closed_and_tolerates_typos(monkeypatch):
    from app.core.config import settings
    from app.services.order_alert_policy import (
        extended_order_alert_client_ids,
        uses_extended_order_alerts,
    )

    monkeypatch.setattr(settings, "EXTENDED_ORDER_ALERT_CLIENT_IDS", "")
    assert extended_order_alert_client_ids() == frozenset()
    assert uses_extended_order_alerts(12) is False
    assert uses_extended_order_alerts(None) is False

    # Literówka wyłącza funkcję jednemu wpisowi, nie wysadza reguły.
    monkeypatch.setattr(
        settings, "EXTENDED_ORDER_ALERT_CLIENT_IDS", "12, nie-liczba ,13"
    )
    assert extended_order_alert_client_ids() == frozenset({12, 13})
    assert uses_extended_order_alerts(12) is True
    assert uses_extended_order_alerts(99) is False


# ── Alert o zużyciu podstawy MD ─────────────────────────────────────────────


async def test_md_base_usage_fires_at_80_percent_not_at_79(monkeypatch):
    from app.models.dl_alert import ALERT_MD_BASE_USAGE_HIGH
    from app.tasks.dl_alerts_scanner import rule_md_base_usage_high

    client_id = await _seed_client()
    user_id = await _seed_dl(client_id)
    contract_id = await _seed_contract(client_id)
    _gate(monkeypatch, client_id)

    # 79% podstawy — cisza.
    await _seed_group_line(
        client_id, contract_id, end=_FAR_END, md_total="100", consumed="79"
    )
    await _run(rule_md_base_usage_high, monkeypatch)
    assert await _alerts(user_id, ALERT_MD_BASE_USAGE_HIGH) == []

    # Dokładnie 80% — karta. Próg jest domknięty (``>=``), bo „osiągnie 80%"
    # z ticketu znaczy 80%, nie 80% i jeden MD.
    contract_b = await _seed_contract(client_id)
    await _seed_group_line(
        client_id, contract_b, end=_FAR_END, md_total="100", consumed="80"
    )
    await _run(rule_md_base_usage_high, monkeypatch)
    alerts = await _alerts(user_id, ALERT_MD_BASE_USAGE_HIGH)
    assert len(alerts) == 1
    assert "80%" in alerts[0].title
    assert alerts[0].payload["md_base_used"].startswith("80")
    assert alerts[0].payload["md_base_total"].startswith("100")
    # Bez eskalacji: pilny sygnał (mail + wysoki priorytet) ma `md_budget_low`.
    assert alerts[0].priority == "standard"
    assert alerts[0].payload.get("email") is not True


async def test_md_base_usage_is_gated_by_client(monkeypatch):
    from app.models.dl_alert import ALERT_MD_BASE_USAGE_HIGH
    from app.tasks.dl_alerts_scanner import rule_md_base_usage_high

    client_id = await _seed_client()
    user_id = await _seed_dl(client_id)
    contract_id = await _seed_contract(client_id)
    await _seed_group_line(
        client_id, contract_id, end=_FAR_END, md_total="100", consumed="95"
    )

    # Klient spoza listy — nawet 95% podstawy nie daje karty.
    _gate(monkeypatch, client_id + 10_000)
    await _run(rule_md_base_usage_high, monkeypatch)
    assert await _alerts(user_id, ALERT_MD_BASE_USAGE_HIGH) == []


async def test_optional_scope_counts_to_neither_side_of_the_ratio(monkeypatch):
    """Zakres opcjonalny nie rozcieńcza procentu ani go nie zawyża.

    Zużycie 80 MD przy podstawie 100 i opcji 100 to 80% PODSTAWY (karta), a nie
    40% budżetu łącznego. Odwrotnie niż `md_budget_low`, które liczy od
    `md_remaining`, czyli od podstawy razem z opcją.
    """
    from app.models.dl_alert import ALERT_MD_BASE_USAGE_HIGH
    from app.tasks.dl_alerts_scanner import rule_md_base_usage_high

    client_id = await _seed_client()
    user_id = await _seed_dl(client_id)
    contract_id = await _seed_contract(client_id)
    _gate(monkeypatch, client_id)
    await _seed_group_line(
        client_id,
        contract_id,
        end=_FAR_END,
        md_total="100",
        md_optional_total="100",
        consumed="80",
    )
    await _run(rule_md_base_usage_high, monkeypatch)
    alerts = await _alerts(user_id, ALERT_MD_BASE_USAGE_HIGH)
    assert len(alerts) == 1
    assert alerts[0].payload["usage_percent"] == "80"


async def test_manual_budget_adjustment_does_not_move_the_threshold(monkeypatch):
    """`md_manual_adjustment` koryguje BUDŻET, nie zużycie.

    Gdyby zużycie wyprowadzać z `md_remaining`, korekta +50 MD przesunęłaby
    próg o te 50 MD. Liczymy z sumy zejść, więc 79 z 100 to nadal 79%.
    """
    from app.models.dl_alert import ALERT_MD_BASE_USAGE_HIGH
    from app.tasks.dl_alerts_scanner import rule_md_base_usage_high

    client_id = await _seed_client()
    user_id = await _seed_dl(client_id)
    contract_id = await _seed_contract(client_id)
    _gate(monkeypatch, client_id)
    await _seed_group_line(
        client_id,
        contract_id,
        end=_FAR_END,
        md_total="100",
        consumed="79",
        md_manual_adjustment="50",
    )
    await _run(rule_md_base_usage_high, monkeypatch)
    assert await _alerts(user_id, ALERT_MD_BASE_USAGE_HIGH) == []


async def test_card_closes_when_budget_grows_back_above_the_threshold(monkeypatch):
    from app.core.database import AsyncSessionLocal
    from app.models.client_order import ClientOrder
    from app.models.dl_alert import ALERT_MD_BASE_USAGE_HIGH
    from app.tasks.dl_alerts_scanner import rule_md_base_usage_high

    client_id = await _seed_client()
    user_id = await _seed_dl(client_id)
    contract_id = await _seed_contract(client_id)
    _gate(monkeypatch, client_id)
    line_id = await _seed_group_line(
        client_id, contract_id, end=_FAR_END, md_total="100", consumed="85"
    )
    await _run(rule_md_base_usage_high, monkeypatch)
    assert len(await _alerts(user_id, ALERT_MD_BASE_USAGE_HIGH)) == 1

    # Klient dosypał podstawy — 85 z 200 to 42,5%, sprawa ustała.
    async with AsyncSessionLocal() as db:
        line = await db.get(ClientOrder, line_id)
        line.md_total = Decimal("200")
        await db.commit()
    await _run(rule_md_base_usage_high, monkeypatch)
    alerts = await _alerts(user_id, ALERT_MD_BASE_USAGE_HIGH)
    assert len(alerts) == 1
    assert alerts[0].status == "resolved"
    # `resolved` to NIE odhaczenie Delivery Leada.
    assert alerts[0].handled_by_user_id is None


# ── Karta o końcu okresu na linii zamówienia grupowego ──────────────────────


async def test_group_line_gets_the_ending_card_only_for_gated_clients(monkeypatch):
    from app.models.dl_alert import ALERT_PERIODIC_ORDER_ENDING
    from app.tasks.dl_alerts_scanner import rule_periodic_order_ending

    client_id = await _seed_client()
    user_id = await _seed_dl(client_id)
    contract_id = await _seed_contract(client_id)
    end = _TODAY + timedelta(days=30)
    await _seed_group_line(client_id, contract_id, end=end, consumed="10")

    # Bramka pusta — zachowanie sprzed rewizji: linia grupy nie daje karty.
    from app.core.config import settings

    monkeypatch.setattr(settings, "EXTENDED_ORDER_ALERT_CLIENT_IDS", "")
    await _run(rule_periodic_order_ending, monkeypatch)
    assert await _alerts(user_id, ALERT_PERIODIC_ORDER_ENDING) == []

    # Klient na liście — karta jest.
    _gate(monkeypatch, client_id)
    await _run(rule_periodic_order_ending, monkeypatch)
    alerts = await _alerts(user_id, ALERT_PERIODIC_ORDER_ENDING)
    assert len(alerts) == 1
    assert alerts[0].payload["end_date"] == end.isoformat()
    # Pierwszy wiersz sprawy idzie mailem — to miesięczne uprzedzenie.
    assert alerts[0].payload.get("email") is True


async def test_ending_card_skips_lines_of_a_closed_group(monkeypatch):
    from app.models.client_order_group import GROUP_STATUS_COMPLETED
    from app.models.dl_alert import ALERT_PERIODIC_ORDER_ENDING
    from app.tasks.dl_alerts_scanner import rule_periodic_order_ending

    client_id = await _seed_client()
    user_id = await _seed_dl(client_id)
    contract_id = await _seed_contract(client_id)
    _gate(monkeypatch, client_id)
    await _seed_group_line(
        client_id,
        contract_id,
        end=_TODAY + timedelta(days=20),
        consumed="10",
        group_status=GROUP_STATUS_COMPLETED,
    )
    await _run(rule_periodic_order_ending, monkeypatch)
    assert await _alerts(user_id, ALERT_PERIODIC_ORDER_ENDING) == []


async def test_standalone_periodic_orders_are_untouched_by_the_gate(monkeypatch):
    """Regresja: zamówienie okresowe działa jak dotąd, także przy pustej liście."""
    from app.core.config import settings
    from app.core.database import AsyncSessionLocal
    from app.models.client_order import ClientOrder, ClientOrderStatus
    from app.models.dl_alert import ALERT_PERIODIC_ORDER_ENDING
    from app.tasks.dl_alerts_scanner import rule_periodic_order_ending

    client_id = await _seed_client()
    user_id = await _seed_dl(client_id)
    contract_id = await _seed_contract(client_id)
    end = _TODAY + timedelta(days=10)
    async with AsyncSessionLocal() as db:
        db.add(
            ClientOrder(
                client_id=client_id,
                contract_id=contract_id,
                title=f"ZAM-{uuid.uuid4().hex[:6]}",
                status=ClientOrderStatus.active,
                start_date=date(2026, 1, 1),
                end_date=end,
                rate_client=Decimal("150.000"),
            )
        )
        await db.commit()

    monkeypatch.setattr(settings, "EXTENDED_ORDER_ALERT_CLIENT_IDS", "")
    await _run(rule_periodic_order_ending, monkeypatch)
    assert len(await _alerts(user_id, ALERT_PERIODIC_ORDER_ENDING)) == 1


# ── Kryteria akceptacji: oba warunki są niezależne ──────────────────────────


async def test_long_period_with_high_md_usage_gives_only_the_md_card(monkeypatch):
    """Kryterium akceptacji nr 1: koniec 31.12.2026, 85% podstawy → karta MD."""
    from app.models.dl_alert import (
        ALERT_MD_BASE_USAGE_HIGH,
        ALERT_PERIODIC_ORDER_ENDING,
    )
    from app.tasks.dl_alerts_scanner import (
        rule_md_base_usage_high,
        rule_periodic_order_ending,
    )

    client_id = await _seed_client()
    user_id = await _seed_dl(client_id)
    contract_id = await _seed_contract(client_id)
    _gate(monkeypatch, client_id)
    await _seed_group_line(
        client_id, contract_id, end=_FAR_END, md_total="220", consumed="187"
    )
    await _run(rule_md_base_usage_high, monkeypatch)
    await _run(rule_periodic_order_ending, monkeypatch)

    assert len(await _alerts(user_id, ALERT_MD_BASE_USAGE_HIGH)) == 1
    assert await _alerts(user_id, ALERT_PERIODIC_ORDER_ENDING) == []


async def test_near_end_with_low_md_usage_gives_only_the_period_card(monkeypatch):
    """Kryterium akceptacji nr 2: 30 dni do końca, 20% podstawy → karta okresu."""
    from app.models.dl_alert import (
        ALERT_MD_BASE_USAGE_HIGH,
        ALERT_PERIODIC_ORDER_ENDING,
    )
    from app.tasks.dl_alerts_scanner import (
        rule_md_base_usage_high,
        rule_periodic_order_ending,
    )

    client_id = await _seed_client()
    user_id = await _seed_dl(client_id)
    contract_id = await _seed_contract(client_id)
    _gate(monkeypatch, client_id)
    await _seed_group_line(
        client_id,
        contract_id,
        end=_TODAY + timedelta(days=30),
        md_total="220",
        consumed="44",
    )
    await _run(rule_md_base_usage_high, monkeypatch)
    await _run(rule_periodic_order_ending, monkeypatch)

    assert await _alerts(user_id, ALERT_MD_BASE_USAGE_HIGH) == []
    assert len(await _alerts(user_id, ALERT_PERIODIC_ORDER_ENDING)) == 1


async def test_both_conditions_give_two_separate_cards(monkeypatch):
    """Kryterium akceptacji nr 4: nigdy jedna karta łącząca oba warunki."""
    from app.models.dl_alert import (
        ALERT_MD_BASE_USAGE_HIGH,
        ALERT_PERIODIC_ORDER_ENDING,
    )
    from app.tasks.dl_alerts_scanner import (
        rule_md_base_usage_high,
        rule_periodic_order_ending,
    )

    client_id = await _seed_client()
    user_id = await _seed_dl(client_id)
    contract_id = await _seed_contract(client_id)
    _gate(monkeypatch, client_id)
    line_id = await _seed_group_line(
        client_id,
        contract_id,
        end=_TODAY + timedelta(days=20),
        md_total="220",
        consumed="200",
    )
    await _run(rule_md_base_usage_high, monkeypatch)
    await _run(rule_periodic_order_ending, monkeypatch)

    md = await _alerts(user_id, ALERT_MD_BASE_USAGE_HIGH)
    ending = await _alerts(user_id, ALERT_PERIODIC_ORDER_ENDING)
    assert len(md) == 1 and len(ending) == 1
    # Obie o TYM SAMYM zamówieniu, ale osobne sprawy — inny klucz zdarzenia
    # i inny klucz deduplikacji, więc żadna nie wypiera drugiej.
    assert md[0].order_id == ending[0].order_id == line_id
    assert md[0].event_key != ending[0].event_key
    assert md[0].dedupe_key != ending[0].dedupe_key


async def test_md_card_coexists_with_the_absolute_low_md_card(monkeypatch):
    """80% i „zostało ≤ 21 MD" to dwa różne komunikaty, nie jeden."""
    from app.models.dl_alert import ALERT_MD_BASE_USAGE_HIGH, ALERT_MD_BUDGET_LOW
    from app.tasks.dl_alerts_scanner import (
        rule_md_base_usage_high,
        rule_md_budget_low,
    )

    client_id = await _seed_client()
    user_id = await _seed_dl(client_id)
    contract_id = await _seed_contract(client_id)
    _gate(monkeypatch, client_id)
    # 210 z 220 MD podstawy: 95% (karta 80%) i 10 MD pozostałych (karta 21 MD).
    await _seed_group_line(
        client_id, contract_id, end=_FAR_END, md_total="220", consumed="210"
    )
    await _run(rule_md_base_usage_high, monkeypatch)
    await _run(rule_md_budget_low, monkeypatch)

    assert len(await _alerts(user_id, ALERT_MD_BASE_USAGE_HIGH)) == 1
    assert len(await _alerts(user_id, ALERT_MD_BUDGET_LOW)) == 1


# ── Powtórki i zamknięcie sprawy ────────────────────────────────────────────


async def test_period_card_repeats_weekly_until_the_order_is_extended(monkeypatch):
    """Kryterium akceptacji nr 3: powtórka co 7 dni, aż sprawa się rozwiąże.

    Cykl datowy jako taki pokrywa ``test_dl_alerts_my_clients_panel``; tutaj
    chodzi o to, że działa on tak samo na LINII zamówienia grupowego, czyli na
    tym, co u BNP jest jedynym kształtem zamówienia.
    """
    from app.core.database import AsyncSessionLocal
    from app.models.client_order import ClientOrder
    from app.models.dl_alert import ALERT_PERIODIC_ORDER_ENDING
    from app.tasks.dl_alerts_scanner import rule_periodic_order_ending

    client_id = await _seed_client()
    user_id = await _seed_dl(client_id)
    contract_id = await _seed_contract(client_id)
    _gate(monkeypatch, client_id)
    clock, moment = _emit_clock(monkeypatch)
    end = _TODAY + timedelta(days=30)
    line_id = await _seed_group_line(client_id, contract_id, end=end, consumed="10")

    await _run(rule_periodic_order_ending, monkeypatch, _TODAY)
    assert len(await _alerts(user_id, ALERT_PERIODIC_ORDER_ENDING)) == 1

    # Nazajutrz nic nowego — okno tygodniowe jeszcze trwa.
    clock.current = moment + timedelta(days=1)
    await _run(rule_periodic_order_ending, monkeypatch, _TODAY + timedelta(days=1))
    assert len(await _alerts(user_id, ALERT_PERIODIC_ORDER_ENDING)) == 1

    # Ponad tydzień później — nowy wiersz, żeby raport pokazał, ile sprawa
    # czeka (+8 d, bo `created_at` bazy jest o ułamek sekundy późniejszy).
    clock.current = moment + timedelta(days=8)
    await _run(rule_periodic_order_ending, monkeypatch, _TODAY + timedelta(days=8))
    rows = await _alerts(user_id, ALERT_PERIODIC_ORDER_ENDING)
    assert len(rows) == 2
    assert len({r.event_key for r in rows}) == 1, "jedna sprawa = jeden klucz karty"
    # Powtórka tygodniowa nie prosi o maila — mail był przy pierwszym wierszu.
    assert not (rows[-1].payload or {}).get("email")

    # Przedłużenie = nowa data końca = nowa sprawa; stara zamyka się sama.
    async with AsyncSessionLocal() as db:
        line = await db.get(ClientOrder, line_id)
        line.end_date = end + timedelta(days=365)
        await db.commit()
    clock.current = moment + timedelta(days=9)
    await _run(rule_periodic_order_ending, monkeypatch, _TODAY + timedelta(days=9))
    alerts = await _alerts(user_id, ALERT_PERIODIC_ORDER_ENDING)
    assert {a.status for a in alerts} == {"resolved"}
    # `resolved` to NIE odhaczenie Delivery Leada.
    assert all(a.handled_by_user_id is None for a in alerts)


async def test_md_card_repeats_weekly_and_handling_stops_it(monkeypatch):
    from datetime import datetime, timezone

    from app.core.database import AsyncSessionLocal
    from app.models.dl_alert import ALERT_MD_BASE_USAGE_HIGH, DlAlert
    from app.tasks.dl_alerts_scanner import rule_md_base_usage_high

    client_id = await _seed_client()
    user_id = await _seed_dl(client_id)
    contract_id = await _seed_contract(client_id)
    _gate(monkeypatch, client_id)
    clock, moment = _emit_clock(monkeypatch)
    await _seed_group_line(
        client_id, contract_id, end=_FAR_END, md_total="100", consumed="90"
    )
    await _run(rule_md_base_usage_high, monkeypatch)
    rows = await _alerts(user_id, ALERT_MD_BASE_USAGE_HIGH)
    assert len(rows) == 1

    clock.current = moment + timedelta(days=8)
    await _run(rule_md_base_usage_high, monkeypatch, _TODAY + timedelta(days=8))
    assert len(await _alerts(user_id, ALERT_MD_BASE_USAGE_HIGH)) == 2

    # Odhaczenie zamyka sprawę: dalsze przebiegi nie dokładają już wierszy.
    async with AsyncSessionLocal() as db:
        for row in await _alerts(user_id, ALERT_MD_BASE_USAGE_HIGH):
            live = await db.get(DlAlert, row.id)
            live.status = "handled"
            live.handled_at = datetime.now(timezone.utc)
            live.handled_by_user_id = user_id
        await db.commit()

    clock.current = moment + timedelta(days=16)
    await _run(rule_md_base_usage_high, monkeypatch, _TODAY + timedelta(days=16))
    assert len(await _alerts(user_id, ALERT_MD_BASE_USAGE_HIGH)) == 2
