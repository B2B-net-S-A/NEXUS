"""Adaptery źródeł: co zakłada kartę i co ją zamyka.

Każdy adapter zwraca karty, które POWINNY stać na tablicy; synchronizacja
domyka te, które z listy zniknęły. Rekord źródłowy zostaje prawdą. Adapter nie
liczy własnych reguł tam, gdzie ekran już je ma: braki i zmiany w zamówieniach
biorą się z ``build_order_changes``, bo liczby z surowych tabel potrafią się
różnić od ekranu Finansów (przerwy: 14 w tabeli, 6 na ekranie). Tytuły bez kwot.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

_MONTHS = (
    "styczeń",
    "luty",
    "marzec",
    "kwiecień",
    "maj",
    "czerwiec",
    "lipiec",
    "sierpień",
    "wrzesień",
    "październik",
    "listopad",
    "grudzień",
)
#: Ławka: tyle dni przed końcem zamówienia staje karta decyzji (decyzja 02.11).
BENCH_DAYS = 60
#: Przedłużenia: tyle dni przed końcem zamówienia (decyzja 02.11).
EXTEND_DAYS = 45
#: Punkt planu po terminie starszy niż to nie wraca na tablicę: zaległości
#: sprzed startu zamyka jednorazowy skrypt (``close_overdue_contact_plan``).
CONTACT_LOOKBACK_DAYS = 14
CONTACT_HORIZON_DAYS = 7
MAIL_LOOKBACK_DAYS = 45
SIGN_LOOKBACK_DAYS = 90
GAP_MONTHS_BACK = 3

AREA_LANE = {
    "onboarding": ("care", "entry"),
    "offboarding": ("care", "exit"),
    "negotiation": ("contracts", "annex"),
    "administration": ("care", "help"),
    "marketing": ("care", "help"),
    "other": ("care", "help"),
}

_PERSON = "nullif(trim(coalesce(ca.name, '') || ' ' || coalesce(ca.lastname, '')), '')"
_CLIENT = "coalesce(cl.display_name, cl.name)"
_CONTRACT_JOIN = (
    "LEFT JOIN candidates ca ON ca.id = k.candidate_id "
    "LEFT JOIN clients cl ON cl.id = k.client_id"
)


@dataclass(frozen=True)
class CardSpec:
    source_kind: str
    source_key: str
    team: str
    lane: str
    title: str
    person: Optional[str] = None
    client_label: Optional[str] = None
    due_on: Optional[date] = None
    href: Optional[str] = None
    case_id: Optional[int] = None
    contract_id: Optional[int] = None
    client_id: Optional[int] = None
    subject_user_id: Optional[int] = None
    #: Tylko dla kart spraw: stan i osoba są lustrem sprawy.
    mirror_state: Optional[str] = None
    mirror_assignee: Optional[int] = None
    mirrors_case: bool = False
    meta: dict[str, Any] = field(default_factory=dict)


async def _rows(db: AsyncSession, sql: str, **params: Any) -> list[Any]:
    return list((await db.execute(text(sql), params)).mappings().all())


async def case_cards(db: AsyncSession, today: date) -> list[CardSpec]:
    rows = await _rows(
        db,
        f"""
        SELECT c.id, c.title, c.area, c.status, c.due_on, c.contract_id,
               c.subject_user_id, c.assignee_user_id, c.source, c.source_key,
               k.client_id, coalesce({_PERSON}, su.name) AS person,
               {_CLIENT} AS client
        FROM admin_cases c
        LEFT JOIN contracts k ON k.id = c.contract_id
        {_CONTRACT_JOIN}
        LEFT JOIN users su ON su.id = c.subject_user_id
        WHERE c.status NOT IN ('done', 'closed')
        """,
    )
    return [
        CardSpec(
            source_kind="case",
            source_key=f"case:{row['id']}",
            team=AREA_LANE[row["area"]][0],
            lane=AREA_LANE[row["area"]][1],
            title=row["title"],
            person=row["person"],
            client_label=row["client"],
            due_on=row["due_on"],
            href=f"/people/cases/{row['id']}",
            case_id=row["id"],
            contract_id=row["contract_id"],
            client_id=row["client_id"],
            subject_user_id=row["subject_user_id"],
            mirror_state=row["status"],
            mirror_assignee=row["assignee_user_id"],
            mirrors_case=True,
            meta={"area": row["area"], "case_source": row["source"]},
        )
        for row in rows
    ]


async def contact_cards(db: AsyncSession, today: date) -> list[CardSpec]:
    """Kontakt 7. dnia i kontakt przed końcem: rytm „tylko ważne punkty”."""

    rows = await _rows(
        db,
        f"""
        SELECT p.id, p.kind, p.due_on, p.contract_id, k.client_id,
               {_PERSON} AS person, {_CLIENT} AS client
        FROM contract_care_plan_items p
        JOIN contracts k ON k.id = p.contract_id
        {_CONTRACT_JOIN}
        WHERE p.kind IN ('day_7', 'pre_end') AND p.status = 'open'
          AND p.due_on BETWEEN :since AND :until
          AND k.status IN ('active', 'ending')
        """,
        since=today - timedelta(days=CONTACT_LOOKBACK_DAYS),
        until=today + timedelta(days=CONTACT_HORIZON_DAYS),
    )
    labels = {"day_7": "Kontakt 7. dnia", "pre_end": "Kontakt przed końcem"}
    return [
        CardSpec(
            source_kind="contact",
            source_key=f"contact:{row['id']}",
            team="care",
            lane="help",
            title=labels[row["kind"]],
            person=row["person"],
            client_label=row["client"],
            due_on=row["due_on"],
            href=f"/care?contract={row['contract_id']}",
            contract_id=row["contract_id"],
            client_id=row["client_id"],
        )
        for row in rows
    ]


async def bench_cards(db: AsyncSession, today: date) -> list[CardSpec]:
    """Jedna karta na kontrakt: aktywny wpis „Do przepięcia” albo koniec w 60 dni.

    Rozstrzygnięty „koniec projektu” na tę samą datę kończy kartę (ta sama
    reguła co ``care.board.order_end_contracts``); sprawa wyjścia przejmuje dalej.
    """

    rows = await _rows(
        db,
        f"""
        WITH active AS (
            SELECT DISTINCT ON (r.contract_id) r.contract_id, r.id, r.reason,
                   r.status, r.due_on
            FROM redeploy_queue_items r
            WHERE r.status IN ('open', 'in_progress')
            ORDER BY r.contract_id, r.due_on NULLS LAST, r.id
        ),
        ending AS (
            SELECT k.id AS contract_id
            FROM contracts k
            WHERE k.status IN ('active', 'ending')
              AND k.end_date BETWEEN :today AND :horizon
              AND NOT EXISTS (
                  SELECT 1 FROM redeploy_queue_items d
                  WHERE d.contract_id = k.id
                    AND d.status IN ('done', 'dismissed')
                    AND (d.due_on = k.end_date OR d.resolved_at >= :resolved_since)
              )
        )
        SELECT k.id AS contract_id, k.client_id, k.end_date, a.id AS item_id,
               a.reason, a.status AS item_status, a.due_on,
               {_PERSON} AS person, {_CLIENT} AS client
        FROM contracts k
        LEFT JOIN active a ON a.contract_id = k.id
        {_CONTRACT_JOIN}
        WHERE (a.contract_id IS NOT NULL
               OR k.id IN (SELECT contract_id FROM ending))
          AND k.status IN ('active', 'ending')
        """,
        today=today,
        horizon=today + timedelta(days=BENCH_DAYS),
        resolved_since=today - timedelta(days=120),
    )
    return [
        CardSpec(
            source_kind="bench",
            source_key=f"bench:{row['contract_id']}",
            team="care",
            lane="bench",
            title="Co dalej po projekcie",
            person=row["person"],
            client_label=row["client"],
            due_on=row["end_date"] or row["due_on"],
            href=f"/care?contract={row['contract_id']}",
            contract_id=row["contract_id"],
            client_id=row["client_id"],
            meta={"redeploy_id": row["item_id"], "reason": row["reason"]},
        )
        for row in rows
    ]


async def timesheet_cards(db: AsyncSession, today: date) -> list[CardSpec]:
    rows = await _rows(
        db,
        """
        SELECT t.id, t.user_id, t.year, t.month, u.name AS person
        FROM timesheets t JOIN users u ON u.id = t.user_id
        WHERE t.status = 'submitted'
        """,
    )
    out = []
    for row in rows:
        next_year = row["year"] + (row["month"] == 12)
        next_month = row["month"] % 12 + 1
        out.append(
            CardSpec(
                source_kind="timesheet",
                source_key=f"timesheet:{row['id']}",
                team="finance",
                lane="timesheet",
                title=f"Raport godzin · {_MONTHS[row['month'] - 1]}",
                person=row["person"],
                client_label="Zespół wewnętrzny",
                due_on=date(next_year, next_month, 5),
                href="/people/approvals?kind=timesheet",
                subject_user_id=row["user_id"],
                meta={"timesheet_id": row["id"]},
            )
        )
    return out


async def bonus_cards(db: AsyncSession, today: date) -> list[CardSpec]:
    """Jedna karta na okres (decyzja 02.11); bez kwot, liczba wystarczy."""

    rows = await _rows(
        db,
        """
        SELECT b.period_year AS y, b.period_month AS m, count(*) AS n
        FROM hr_bonuses b
        WHERE b.status = 'proposed'
          AND (b.period_year, b.period_month) < (:year, :month)
        GROUP BY 1, 2
        """,
        year=today.year,
        month=today.month,
    )
    return [
        CardSpec(
            source_kind="bonus",
            source_key=f"bonus:{row['y']}-{row['m']:02d}",
            team="finance",
            lane="bonus",
            title=f"Premie {row['m']:02d}.{row['y']}",
            person=f"{row['n']} do akceptu",
            href="/people/approvals",
            meta={"year": row["y"], "month": row["m"], "count": row["n"]},
        )
        for row in rows
    ]


def _previous_month(today: date, back: int = 1) -> tuple[int, int]:
    index = today.year * 12 + today.month - 1 - back
    return index // 12, index % 12 + 1


_CHANGE_TABS = {
    "changes": "Zmiana",
    "entries": "Wejście",
    "exits": "Wyjście",
    "ending_orders": "Kończy się",
}


async def _decorated_changes(db: AsyncSession, year: int, month: int) -> Any:
    from app.services import order_change_checks  # noqa: PLC0415
    from app.services.finance_order_changes import build_order_changes  # noqa: PLC0415

    full = await build_order_changes(db, year, month)
    return await order_change_checks.decorate(db, full, can_check=False)


async def change_cards(db: AsyncSession, today: date) -> list[CardSpec]:
    """Audyt poprzedniego miesiąca: pozycje nieodhaczone w Finansach."""

    year, month = _previous_month(today)
    response = await _decorated_changes(db, year, month)
    out = []
    for tab, label in _CHANGE_TABS.items():
        for item in getattr(response, tab):
            if getattr(item, "done", None):
                continue
            out.append(
                CardSpec(
                    source_kind="changes",
                    source_key=f"changes:{year}-{month:02d}:{item.item_key}"[:160],
                    team="finance",
                    lane="changes",
                    title=f"{label} · {_MONTHS[month - 1]}",
                    person=item.consultant_name or item.order_number,
                    client_label=item.client_name,
                    href=f"/finance?view=changes&year={year}&month={month}",
                    meta={"year": year, "month": month, "item_key": item.item_key},
                )
            )
    return out


async def draft_cards(db: AsyncSession, today: date) -> list[CardSpec]:
    rows = await _rows(
        db,
        f"""
        SELECT k.id, k.client_id, {_PERSON} AS person, {_CLIENT} AS client
        FROM contracts k {_CONTRACT_JOIN}
        WHERE k.status = 'draft'
        """,
    )
    return [
        CardSpec(
            source_kind="draft",
            source_key=f"draft:{row['id']}",
            team="contracts",
            lane="draft",
            title="Kontrakt w szkicu",
            person=row["person"],
            client_label=row["client"],
            href=f"/contracts/{row['id']}",
            contract_id=row["id"],
            client_id=row["client_id"],
        )
        for row in rows
    ]


async def sign_cards(db: AsyncSession, today: date) -> list[CardSpec]:
    rows = await _rows(
        db,
        """
        SELECT g.id, g.partner_name, g.client_name, g.contract_number, g.contract_id
        FROM b2b_generated_contracts g
        WHERE g.signature_status = 'unsigned' AND g.created_at >= :since
        """,
        since=today - timedelta(days=SIGN_LOOKBACK_DAYS),
    )
    return [
        CardSpec(
            source_kind="sign",
            source_key=f"sign:{row['id']}",
            team="contracts",
            lane="sign",
            title=f"Umowa {row['contract_number'] or ''}".strip(),
            person=row["partner_name"],
            client_label=row["client_name"],
            href="/contracts/b2b-generator",
            contract_id=row["contract_id"],
        )
        for row in rows
    ]


async def ending_cards(db: AsyncSession, today: date) -> list[CardSpec]:
    """Kontrakt „kończy się” bez sprawy wyjścia; ze sprawą pracę niesie jej krok."""

    rows = await _rows(
        db,
        f"""
        SELECT k.id, k.client_id, coalesce(k.agreement_last_day, k.end_date) AS due,
               {_PERSON} AS person, {_CLIENT} AS client
        FROM contracts k {_CONTRACT_JOIN}
        WHERE k.status = 'ending'
          AND NOT EXISTS (
              SELECT 1 FROM admin_cases c
              WHERE c.source_key = 'contract:' || k.id || '\\:end'
                AND c.status NOT IN ('done', 'closed')
          )
        """,
    )
    return [
        CardSpec(
            source_kind="ending",
            source_key=f"ending:{row['id']}",
            team="contracts",
            lane="ending",
            title="Kontrakt się kończy",
            person=row["person"],
            client_label=row["client"],
            due_on=row["due"],
            href=f"/contracts/{row['id']}",
            contract_id=row["id"],
            client_id=row["client_id"],
        )
        for row in rows
    ]


async def mail_cards(db: AsyncSession, today: date) -> list[CardSpec]:
    rows = await _rows(
        db,
        f"""
        SELECT d.id, d.subject, d.outcome, d.sender_domain, d.client_id,
               d.received_at, {_CLIENT} AS client
        FROM order_mail_documents d LEFT JOIN clients cl ON cl.id = d.client_id
        WHERE d.outcome IN ('needs_review', 'unrecognized_client')
          AND d.created_at >= :since
        """,
        since=today - timedelta(days=MAIL_LOOKBACK_DAYS),
    )
    labels = {
        "needs_review": "Do przejrzenia",
        "unrecognized_client": "Nierozpoznany klient",
    }
    return [
        CardSpec(
            source_kind="mail",
            source_key=f"mail:{row['id']}",
            team="orders",
            lane="mail",
            title=labels[row["outcome"]],
            person=row["client"] or row["sender_domain"] or "Nieznany nadawca",
            client_label=(row["subject"] or "")[:200] or None,
            href="/contracts?view=order-mail",
            client_id=row["client_id"],
        )
        for row in rows
    ]


async def gap_cards(db: AsyncSession, today: date) -> list[CardSpec]:
    """Otwarte przerwy z ekranu Finansów (reguła ukrywania zostaje jedna)."""

    from app.services.finance_order_changes import build_order_changes  # noqa: PLC0415

    seen: dict[int, Any] = {}
    for back in range(GAP_MONTHS_BACK, -1, -1):
        year, month = _previous_month(today, back)
        response = await build_order_changes(db, year, month)
        for gap in response.gaps:
            if gap.status == "open":
                seen[gap.gap_id] = gap
    return [
        CardSpec(
            source_kind="gap",
            source_key=f"gap:{gap_id}",
            team="orders",
            lane="gap",
            title=f"Przerwa po {gap.order_number or 'zamówieniu'}",
            person=gap.consultant_name,
            client_label=gap.client_name,
            due_on=gap.ended_on,
            href="/finance?view=changes",
            meta={"gap_id": gap_id},
        )
        for gap_id, gap in seen.items()
    ]


async def extend_cards(db: AsyncSession, today: date) -> list[CardSpec]:
    rows = await _rows(
        db,
        f"""
        SELECT g.id, g.order_number, g.end_date, g.client_id, {_CLIENT} AS client,
               (SELECT count(*) FROM client_orders o
                WHERE o.order_group_id = g.id AND o.status = 'active') AS people
        FROM client_order_groups g LEFT JOIN clients cl ON cl.id = g.client_id
        WHERE g.status = 'active' AND g.end_date BETWEEN :today AND :horizon
        """,
        today=today,
        horizon=today + timedelta(days=EXTEND_DAYS),
    )
    return [
        CardSpec(
            source_kind="extend",
            source_key=f"extend:{row['id']}",
            team="orders",
            lane="extend",
            title=f"Przedłużenie {row['order_number'] or ''}".strip(),
            person=row["client"],
            client_label=f"{row['people']} os. na zamówieniu",
            due_on=row["end_date"],
            href=f"/clients/{row['client_id']}?tab=orders",
            client_id=row["client_id"],
        )
        for row in rows
    ]


async def md_cards(db: AsyncSession, today: date) -> list[CardSpec]:
    rows = await _rows(
        db,
        """
        SELECT i.id, i.period_month, i.rows_total,
               coalesce(i.rows_ambiguous, 0) + coalesce(i.rows_unmatched, 0) AS open_rows
        FROM md_consumption_imports i
        ORDER BY i.created_at DESC LIMIT 1
        """,
    )
    return [
        CardSpec(
            source_kind="md",
            source_key=f"md:{row['id']}",
            team="orders",
            lane="md",
            title=f"Import MD {row['period_month']}",
            person=f"{row['open_rows']} wierszy bez przypisania",
            client_label=f"{row['rows_total']} wierszy w pliku",
            href="/finance?view=md",
            meta={"import_id": row["id"], "open_rows": row["open_rows"]},
        )
        for row in rows
        if row["open_rows"] > 0
    ]


Adapter = Callable[[AsyncSession, date], Awaitable[list[CardSpec]]]

ADAPTERS: dict[str, Adapter] = {
    "case": case_cards,
    "contact": contact_cards,
    "bench": bench_cards,
    "timesheet": timesheet_cards,
    "bonus": bonus_cards,
    "changes": change_cards,
    "draft": draft_cards,
    "sign": sign_cards,
    "ending": ending_cards,
    "mail": mail_cards,
    "gap": gap_cards,
    "extend": extend_cards,
    "md": md_cards,
}
