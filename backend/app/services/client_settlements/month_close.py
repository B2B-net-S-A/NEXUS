"""„Przebieg miesiąca” — wszyscy klienci rozliczeń w jednym widoku.

Ekran Finanse → Przychody → Przebieg miesiąca (makiety Artura z 23.11.2026).
Wiersz klienta liczy się z tego samego ``service.month_view`` co ekran
jednego klienta, więc statusy, faktury kontraktorów i faktury do klienta są
identyczne w obu miejscach. Nic nie zapisuje.

Kolejka „do decyzji” grupuje osoby po powodzie: pierwszy błąd albo uwaga
z ``checks`` rozliczenia (ta sama kolejność co ``service._row``), brak raportu
i plik bez MD. Klient rozliczany z raportu klienta (reguła
``report.time_for_teams``, Nordea) ma własne liczniki z ``time_reports``
i nie trafia do kolejki osób, bo jego „brak RCP” nie jest brakiem.
"""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.client import Client
from app.models.client_settlement import ClientSettlement
from app.models.contract import Contract
from app.services.client_order_lines import month_bounds
from app.services.client_settlements import service, time_reports

T4T_RULE = "report.time_for_teams"
MISSING_REASON = "missing"
UNREAD_REASON = "no_md"
#: Ile osób na powód oddajemy do listy (reszta jest liczbą).
PEOPLE_PER_REASON = 30

#: Faktura kontraktora jest w KSeF (także z różnicą kwoty albo NIP-em do zatwierdzenia).
INVOICE_IN_KSEF = ("in_ksef", "differs", "nip_check")
#: Rozliczenie z MD, od którego liczy się rezerwa kosztu, gdy faktury jeszcze nie ma.
RESERVE_STATUSES = ("ok", "accepted", "warnings")
#: Faktura do klienta gotowa po przyjęciu RCP, ale jeszcze niewystawiona.
SALES_WAITING = ("ready", "awaiting_signature", "awaiting_client")

DECIDE_STATUSES = ("warnings", "needs_fix")
UNREAD_STATUSES = ("checking", "no_md")
CLEAN_STATUSES = ("ok", "accepted")
#: Faktura do klienta czeka na podpis, akceptację albo raport klienta, nie na nas.
CLIENT_WAITS = ("awaiting_signature", "awaiting_client", "awaiting_t4t")


def stage_counts(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Liczniki pięciu kroków miesiąca dla listy osób (wiersze ``month_view``).

    Raport → kontrola (odczyt MD i reguły) → przyjęcie RCP → faktura kontraktora
    z KSeF → faktura do klienta. Każda osoba jest w każdym kroku dokładnie raz,
    więc liczby kroku sumują się do liczby osób. „Błąd” to reguła, która blokuje
    przyjęcie (``fail``), „uwaga” — to, co Finanse mogą przyjąć na karcie osoby.
    """

    def n(pred: Any) -> int:
        return sum(1 for r in rows if pred(r))

    def status(*names: str) -> Any:
        return lambda r: r["status"] in names

    return {
        "people": len(rows),
        "report": {
            "in": n(lambda r: r["status"] != "missing"),
            "missing": n(status("missing")),
        },
        "check": {
            "clean": n(status(*CLEAN_STATUSES)),
            "warn": n(
                lambda r: r["status"] == "warnings" and r.get("issue_level") != "fail"
            ),
            "fail": n(
                lambda r: r["status"] == "warnings" and r.get("issue_level") == "fail"
            ),
            "returned": n(status("needs_fix")),
            "unread": n(status("checking")),
            "no_md": n(status("no_md")),
            "missing": n(status("missing")),
        },
        "accept": {
            "done": n(status("accepted")),
            "auto": n(lambda r: bool(r.get("accepted_auto"))),
            "ready": n(status("ok")),
        },
        "contractor_invoice": {
            "match": n(lambda r: r["contractor_invoice"] == "in_ksef"),
            "differs": n(
                lambda r: r["contractor_invoice"] in ("differs", "extra_pending")
            ),
            "nip": n(lambda r: r["contractor_invoice"] == "nip_check"),
            "can_issue": n(lambda r: r["contractor_invoice"] == "can_issue"),
            "none": n(lambda r: r["contractor_invoice"] == "none"),
        },
        "client_invoice": {
            "issued": n(lambda r: r["client_invoice"] == "issued"),
            "ready": n(lambda r: r["client_invoice"] == "ready"),
            "waiting_client": n(lambda r: r["client_invoice"] in CLIENT_WAITS),
            "waiting": n(lambda r: r["client_invoice"] == "waiting"),
            # Faktura sprzedaży w KSeF, choć RCP w NEXUS-ie nieprzyjęte.
            "issued_early": n(
                lambda r: r["client_invoice"] == "issued" and r["status"] != "accepted"
            ),
        },
        "missing_order": n(lambda r: not r.get("order_number")),
    }


def add_stages(total: dict[str, Any], part: dict[str, Any]) -> dict[str, Any]:
    """Suma dwóch wyników ``stage_counts`` (liczby w zagnieżdżonych słownikach)."""

    out: dict[str, Any] = {}
    for key in total.keys() | part.keys():
        a, b = total.get(key), part.get(key)
        if isinstance(a, dict) or isinstance(b, dict):
            out[key] = add_stages(a or {}, b or {})
        else:
            out[key] = (a or 0) + (b or 0)
    return out


def reason_level(row: dict[str, Any]) -> str:
    """Rodzaj sprawy w kolejce: kto ją rozstrzyga i czy blokuje przyjęcie."""

    status = row["status"]
    if status == "missing":
        return "missing"
    if status == "checking":
        return "unread"
    if status == "no_md":
        return "order"
    if status == "needs_fix":
        return "returned"
    return "fail" if row.get("issue_level") == "fail" else "warn"


async def _client_ids(db: AsyncSession, month: str) -> list[int]:
    """Klienci z kontraktem, który mógł pracować w miesiącu, albo z rozliczeniem."""

    first, last = month_bounds(month)
    working = select(Contract.client_id).where(
        Contract.client_id.is_not(None),
        and_(
            Contract.status.in_(service.WORKING_CONTRACT_STATUSES),
            or_(Contract.start_date.is_(None), Contract.start_date <= last),
            or_(Contract.end_date.is_(None), Contract.end_date >= first),
        ),
    )
    settled = select(ClientSettlement.client_id).where(
        ClientSettlement.period_month == month
    )
    ids = set((await db.scalars(working)).all()) | set(
        (await db.scalars(settled)).all()
    )
    return sorted(ids)


def first_issue(s: Optional[ClientSettlement]) -> Optional[tuple[Optional[str], str]]:
    """(klucz reguły, tytuł) pierwszego błędu, a bez błędu pierwszej uwagi."""

    if s is None:
        return None
    if s.status == "needs_fix":
        return ("needs_fix", s.fix_reason or "Odesłane do poprawy")
    found = [
        check
        for group in (s.checks or [])
        if isinstance(group, dict)
        for check in (group.get("checks") or [])
        if isinstance(check, dict) and check.get("state") in ("warn", "fail")
    ]
    found.sort(key=lambda check: check.get("state") != "fail")
    if not found:
        return None
    return (found[0].get("rule"), str(found[0].get("title") or ""))


def _reason_for(
    row: dict[str, Any], s: Optional[ClientSettlement]
) -> Optional[tuple[str, str]]:
    status = row["status"]
    if status == "missing":
        return (MISSING_REASON, "Brak raportu w poczcie rozliczeń")
    if status in UNREAD_STATUSES:
        issue = first_issue(s)
        if issue and issue[1]:
            return (issue[0] or issue[1], issue[1])
        return (UNREAD_REASON, "Plik jest, NEXUS nie odczytał MD")
    if status in DECIDE_STATUSES:
        issue = first_issue(s)
        if issue and issue[1]:
            return (issue[0] or issue[1], issue[1])
        return ("other", "Inna uwaga — otwórz kartę osoby")
    return None


def closing_rows(
    rows: list[dict[str, Any]], client_id: int, client_name: str
) -> dict[str, list[dict[str, Any]]]:
    """Trzy pytania księgowej na zamknięcie (mail „Rozliczenie lipca”, 24.08.2026):
    faktury z KSeF nieprzyjęte przez Finanse, brakujące faktury (rezerwa kosztu)
    i przyjęte RCP bez faktury sprzedaży."""

    def person(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "client_id": client_id,
            "client": client_name,
            "contract_id": row["contract_id"],
            "person": row["person"],
            "md": row.get("md_regular"),
            "cost": row.get("amount_cost"),
        }

    return {
        "ksef_not_accepted": [
            person(r)
            for r in rows
            if r["contractor_invoice"] in INVOICE_IN_KSEF and r["status"] != "accepted"
        ],
        "reserve": [
            person(r)
            for r in rows
            if r["status"] in RESERVE_STATUSES
            and r["contractor_invoice"] not in INVOICE_IN_KSEF
        ],
        "sales_waiting": [
            person(r)
            for r in rows
            if r["status"] == "accepted" and r["client_invoice"] in SALES_WAITING
        ],
    }


def _money(rows: list[dict[str, Any]]) -> Optional[str]:
    total = Decimal("0")
    seen = False
    for row in rows:
        if row["status"] in CLEAN_STATUSES and row.get("amount_revenue") is not None:
            total += Decimal(row["amount_revenue"])
            seen = True
    return f"{total:.2f}" if seen else None


async def overview(db: AsyncSession, month: str, *, amounts: bool) -> dict[str, Any]:
    """Stan miesiąca dla wszystkich klientów i kolejka decyzji po powodzie."""

    client_ids = await _client_ids(db, month)
    names = (
        dict(
            (
                await db.execute(
                    select(Client.id, Client.name).where(Client.id.in_(client_ids))
                )
            ).all()
        )
        if client_ids
        else {}
    )
    settlements = {
        s.contract_id: s
        for s in (
            await db.scalars(
                select(ClientSettlement).where(
                    ClientSettlement.period_month == month,
                    ClientSettlement.kind == service.ACTUAL,
                )
            )
        ).all()
    }

    clients: list[dict[str, Any]] = []
    # Klucz grupy to powód i rodzaj: ta sama reguła u jednego klienta blokuje,
    # a u innego tylko ostrzega (poziom reguły jest per klient).
    reasons: dict[tuple[str, str], dict[str, Any]] = {}
    closing: dict[str, list[dict[str, Any]]] = {
        "ksef_not_accepted": [],
        "reserve": [],
        "sales_waiting": [],
    }
    for client_id in client_ids:
        view = await service.month_view(db, client_id, month, amounts=amounts)
        rows = view["rows"]
        if not rows:
            continue
        rules = await service.rules_for(db, client_id, month)
        client_report = rules.get(T4T_RULE, {}).get("level", "off") != "off"
        top: dict[str, int] = defaultdict(int)
        entry: dict[str, Any] = {
            "client_id": client_id,
            "name": names.get(client_id) or view["client_name"],
            "people": len(rows),
            "clean": sum(1 for r in rows if r["status"] == "ok"),
            "accepted": sum(1 for r in rows if r["status"] == "accepted"),
            "decide": sum(1 for r in rows if r["status"] in DECIDE_STATUSES),
            "unread": sum(1 for r in rows if r["status"] in UNREAD_STATUSES),
            "missing": sum(1 for r in rows if r["status"] == "missing"),
            "contractor_in_ksef": sum(
                1 for r in rows if r["contractor_invoice"] == "in_ksef"
            ),
            "client_invoice_issued": sum(
                1 for r in rows if r["client_invoice"] == "issued"
            ),
            "client_invoice_ready": sum(
                1 for r in rows if r["client_invoice"] == "ready"
            ),
            "revenue_ready": _money(rows) if amounts else None,
            "client_report": None,
            "top_reason": None,
            "auto_accept": view.get("auto_accept"),
            "stages": stage_counts(rows),
        }
        for key, found in closing_rows(rows, client_id, entry["name"]).items():
            closing[key].extend(found)
        if client_report:
            report = await time_reports.month_view(db, client_id, month)
            counts = report.get("counts") or {}
            entry["client_report"] = {
                "all": counts.get("all", 0),
                "ok": counts.get("ok", 0),
                "differs": counts.get("differs", 0) + counts.get("other_amount", 0),
                "unmatched": counts.get(time_reports.UNMATCHED, 0),
                "no_invoice": counts.get("no_invoice", 0),
            }
            clients.append(entry)
            continue
        for row in rows:
            found = _reason_for(row, settlements.get(row["contract_id"]))
            if found is None:
                continue
            key, title = found
            if key != MISSING_REASON:
                top[title] += 1
            level = reason_level(row)
            group = reasons.setdefault(
                (key, level),
                {
                    "key": key,
                    "title": title,
                    "level": level,
                    "count": 0,
                    "clients": {},
                    "people": [],
                },
            )
            group["count"] += 1
            group["clients"][client_id] = group["clients"].get(client_id, 0) + 1
            if len(group["people"]) < PEOPLE_PER_REASON:
                group["people"].append(
                    {
                        "contract_id": row["contract_id"],
                        "person": row["person"],
                        "client_id": client_id,
                    }
                )
        if top:
            entry["top_reason"] = max(top.items(), key=lambda kv: kv[1])[0]
        clients.append(entry)

    clients.sort(
        key=lambda c: (
            -(c["decide"] + c["unread"] + c["missing"]),
            c["name"].lower(),
        )
    )
    ordered = sorted(reasons.values(), key=lambda g: (-g["count"], g["title"]))
    for group in ordered:
        group["clients"] = [
            {"client_id": cid, "name": names.get(cid, ""), "count": n}
            for cid, n in sorted(group["clients"].items(), key=lambda kv: -kv[1])
        ]
    by_person = [c for c in clients if c["client_report"] is None]
    stages: dict[str, Any] = {}
    for c in by_person:
        stages = add_stages(stages, c["stages"])
    return {
        "month": month,
        "can_see_amounts": amounts,
        "totals": {
            "people": sum(c["people"] for c in by_person),
            "clean": sum(c["clean"] for c in by_person),
            "accepted": sum(c["accepted"] for c in by_person),
            "decide": sum(c["decide"] for c in by_person),
            "unread": sum(c["unread"] for c in by_person),
            "missing": sum(c["missing"] for c in by_person),
            "contractor_in_ksef": sum(c["contractor_in_ksef"] for c in by_person),
            "client_invoice_issued": sum(c["client_invoice_issued"] for c in by_person),
        },
        "stages": stages or stage_counts([]),
        "clients": clients,
        "reasons": ordered,
        "closing": _closing_summary(closing, amounts),
    }


def _closing_summary(
    closing: dict[str, list[dict[str, Any]]], amounts: bool
) -> dict[str, Any]:
    """Liczby i listy dla księgowej; kwoty i osoby tylko z uprawnieniem do kwot."""

    reserve_total = sum(
        (Decimal(r["cost"]) for r in closing["reserve"] if r["cost"] is not None),
        Decimal("0"),
    )
    reserve_unknown = sum(1 for r in closing["reserve"] if r["cost"] is None)
    out: dict[str, Any] = {
        "ksef_not_accepted": len(closing["ksef_not_accepted"]),
        "reserve_count": len(closing["reserve"]),
        "reserve_total": f"{reserve_total:.2f}" if amounts else None,
        "reserve_without_cost": reserve_unknown,
        "sales_waiting": len(closing["sales_waiting"]),
        "rows": None,
    }
    if amounts:
        out["rows"] = {
            key: sorted(found, key=lambda r: (r["client"].lower(), r["person"]))
            for key, found in closing.items()
        }
    return out
