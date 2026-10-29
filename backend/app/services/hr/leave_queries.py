"""Odczyty wniosków urlopowych: wiersz wniosku, moje wnioski, kolejki, historia.

Wiersz wniosku (``serialize``) jest tylko dla kręgu D6 (osoba, przełożony,
Kadry); kolejki dokładają oznaczenie zastępstwa (``_mark_cover``) i kontekst
(dział, przełożony, praca w NEXUSIE, nieobecni z działu) zbiorczo.
Załączniki (``leave_proofs``): liczbę widzi cały krąg D6, listę z pobraniem
— osoba i Kadry; zastępca przy rodzaju ukrytym nie widzi nawet liczby.

Dni wniosku — razem, płatne i bezpłatne — liczy jedna reguła
(``leave_policy.split_days``) z wierszy ``leave_request_days``; kolumny
``paid_days`` / ``unpaid_days`` wniosku to jej zapisany wynik, odczyt ich nie
miesza z wierszami dni.

Zakres przełożonego (``scope_user_ids``): jego podwładni i osoby jego pionu
bez żywego przełożonego, gdy jest headem (``recipients.division_charges`` —
ta sama reguła, która kieruje do niego ich wnioski).
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from collections.abc import Iterable
from datetime import date
from typing import Any, Optional

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.hr_leave import LeaveRequest, LeaveRequestDay
from app.models.hr_ops import HrAuditEvent
from app.models.hr_profile import EmployeeProfile
from app.models.user import User
from app.services.hr import leave_proofs, leave_substitute, people
from app.services.hr.employment_terms import REPORT_FORMS, reports_absence
from app.services.hr.leave_context import (
    RequestWindow,
    department_absences_many,
    work_summaries,
)
from app.services.hr.leave_policy import (
    PaidSplit,
    actor_of,
    own_cancel_refusal,
    split_days,
    substitute_sees_type,
    type_label,
)
from app.services.hr.recipients import division_charges
from app.services.hr_leave_schema import ACTIVE_STATUSES

#: Kolizja zgłoszona przez koordynatora (D5) — wpis śladu HR przy wniosku.
CONFLICT_ACTION = "leave_conflict_reported"


async def names_of(db: AsyncSession, ids: set[int]) -> dict[int, str]:
    ids = {uid for uid in ids if uid}
    if not ids:
        return {}
    return dict(
        (await db.execute(select(User.id, User.name).where(User.id.in_(ids)))).all()
    )


async def request_splits(
    db: AsyncSession, requests: Iterable[LeaveRequest]
) -> dict[uuid.UUID, PaidSplit]:
    """Dni wniosków (razem, płatne, bezpłatne) z ``leave_request_days`` —
    jedno zapytanie dla wszystkich wniosków."""

    types = {request.id: request.leave_type for request in requests}
    if not types:
        return {}
    rows = await db.execute(
        select(
            LeaveRequestDay.leave_request_id,
            LeaveRequestDay.paid,
            func.sum(LeaveRequestDay.fraction),
        )
        .where(LeaveRequestDay.leave_request_id.in_(list(types)))
        .group_by(LeaveRequestDay.leave_request_id, LeaveRequestDay.paid)
    )
    grouped: dict[uuid.UUID, list[tuple[Any, bool]]] = defaultdict(list)
    for request_id, paid, total in rows.all():
        grouped[request_id].append((total or 0, bool(paid)))
    return {
        request_id: split_days(grouped.get(request_id, ()), leave_type=leave_type)
        for request_id, leave_type in types.items()
    }


async def _forms_of(db: AsyncSession, user_ids: set[int]) -> dict[int, str]:
    if not user_ids:
        return {}
    return dict(
        (
            await db.execute(
                select(EmployeeProfile.user_id, EmployeeProfile.employment_type).where(
                    EmployeeProfile.user_id.in_(user_ids)
                )
            )
        ).all()
    )


async def _latest_conflicts(
    db: AsyncSession, request_ids: list[uuid.UUID]
) -> dict[str, HrAuditEvent]:
    """Ostatnia kolizja zgłoszona przez koordynatora per wniosek (ślad HR)."""

    if not request_ids:
        return {}
    rows = await db.scalars(
        select(HrAuditEvent)
        .where(
            HrAuditEvent.entity_type == "leave_request",
            HrAuditEvent.action == CONFLICT_ACTION,
            HrAuditEvent.entity_id.in_([str(rid) for rid in request_ids]),
        )
        .order_by(HrAuditEvent.created_at, HrAuditEvent.id)
    )
    return {row.entity_id: row for row in rows if row.entity_id}


async def serialize(
    db: AsyncSession,
    requests: list[LeaveRequest],
    *,
    viewer: User,
    today: date,
) -> list[dict[str, Any]]:
    """Pełny wiersz wniosku — tylko dla kręgu D6 (osoba, przełożony, Kadry)."""

    conflicts = await _latest_conflicts(db, [r.id for r in requests])
    names = await names_of(
        db,
        {r.user_id for r in requests}
        | {r.substitute_user_id for r in requests if r.substitute_user_id}
        | {r.cpro_substitute_user_id for r in requests if r.cpro_substitute_user_id}
        | {r.decided_by for r in requests if r.decided_by}
        | {c.actor_user_id for c in conflicts.values() if c.actor_user_id},
    )
    splits = await request_splits(db, requests)
    forms = await _forms_of(db, {r.user_id for r in requests})
    # Treść załącznika (akt zgonu, dokument dziecka) widzą osoba i Kadry;
    # przełożony tylko liczbę (D6).
    sees_files = actor_of(viewer).sees_everyone
    with_files = {r.id for r in requests if sees_files or r.user_id == viewer.id}
    proofs = await leave_proofs.proofs_by_request(db, with_files)
    counts = await leave_proofs.proof_counts(
        db, [r.id for r in requests if r.id not in with_files]
    )
    items = []
    for r in requests:
        own = r.user_id == viewer.id
        files = proofs.get(r.id, []) if own or sees_files else None
        conflict = conflicts.get(str(r.id))
        split = splits[r.id]
        items.append(
            {
                "id": str(r.id),
                "user_id": r.user_id,
                "user_name": names.get(r.user_id),
                "leave_type": r.leave_type,
                "leave_type_label": type_label(r.leave_type, forms.get(r.user_id)),
                "status": r.status,
                "start_date": r.start_date.isoformat(),
                "end_date": r.end_date.isoformat(),
                "half_day": r.half_day,
                "days_total": f"{split.total:.1f}",
                "paid_days": f"{split.paid:.1f}",
                "unpaid_days": f"{split.unpaid:.1f}",
                "note": r.note,
                "substitute_user_id": r.substitute_user_id,
                "substitute_name": names.get(r.substitute_user_id)
                if r.substitute_user_id
                else None,
                "cpro_substitute_name": names.get(r.cpro_substitute_user_id)
                if r.cpro_substitute_user_id
                else None,
                "forward_mail_consent": r.forward_mail_consent,
                "oof_internal_message": r.oof_internal_message if own else None,
                "oof_external_message": r.oof_external_message if own else None,
                "decided_by_name": names.get(r.decided_by) if r.decided_by else None,
                "decided_at": r.decided_at.isoformat() if r.decided_at else None,
                "decision_note": r.decision_note,
                "source": r.source,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "proof_count": len(files) if files is not None else counts.get(r.id, 0),
                "proofs": None
                if files is None
                else [
                    leave_proofs.proof_payload(doc, viewer_id=viewer.id)
                    for doc in files
                ],
                "can_add_proof": own and r.status in ACTIVE_STATUSES,
                "can_cancel": own
                and own_cancel_refusal(
                    status=r.status,
                    start=r.start_date,
                    today=today,
                    reported=reports_absence(forms.get(r.user_id)),
                )
                is None,
                # D5: zgłoszenie z B2B albo zlecenia (bez akceptacji, z kolizją).
                "is_report": reports_absence(forms.get(r.user_id)),
                "employment_type": forms.get(r.user_id),
                "conflict": None
                if conflict is None
                else {
                    "at": conflict.created_at.isoformat()
                    if conflict.created_at
                    else None,
                    "by_name": names.get(conflict.actor_user_id)
                    if conflict.actor_user_id
                    else None,
                    "note": (conflict.details or {}).get("note"),
                },
            }
        )
    return items


async def my_requests(
    db: AsyncSession, *, user: User, today: date, limit: int = 200
) -> list[dict[str, Any]]:
    rows = list(
        await db.scalars(
            select(LeaveRequest)
            .where(LeaveRequest.user_id == user.id)
            .order_by(LeaveRequest.start_date.desc(), LeaveRequest.created_at.desc())
            .limit(limit)
        )
    )
    return await serialize(db, rows, viewer=user, today=today)


async def scope_user_ids(db: AsyncSession, actor: User) -> Optional[set[int]]:
    """Kogo dotyczą akceptacje osoby: ``None`` = wszyscy (Kadry, admin).

    Podwładni z kartoteki i — gdy osoba jest headem pionu — osoby pionu bez
    żywego przełożonego (ich wnioski trafiają do niej, ``supervisor_of``).
    """

    if actor_of(actor).sees_everyone:
        return None
    return await people.direct_report_ids(db, actor.id) | await division_charges(
        db, actor.id
    )


def _mark_cover(
    item: dict[str, Any],
    row: LeaveRequest,
    cover: Optional[leave_substitute.Cover],
) -> None:
    """Wiersz kolejki: czy decyduje patrzący i czy widzi rodzaj (D6).

    Zastępca nie należy do kręgu D6: notatki nie widzi nigdy (bywa o zdrowiu),
    rodzaj — tylko planowy; L4 i pokrewne przyjmuje do wiadomości.
    """

    item["as_substitute_for"] = cover.manager_name if cover else None
    item["as_substitute_until"] = cover.until.isoformat() if cover else None
    if cover is None:
        item["type_visible"] = True
        item["can_decide"] = True
        return
    visible = substitute_sees_type(row.leave_type)
    item["type_visible"] = visible
    item["can_decide"] = visible
    item["note"] = None
    item["proofs"] = None
    if not visible:
        # Załącznik przy L4 i pokrewnych zdradzałby rodzaj.
        item["proof_count"] = None
    if not visible:
        item["leave_type"] = None
        item["leave_type_label"] = "Nieobecność"


async def mask_for_viewer(
    db: AsyncSession, item: dict[str, Any], row: LeaveRequest, viewer: User, today: date
) -> None:
    """Jeden wiersz po decyzji albo kolizji: zastępca widzi go jak w kolejce.

    Trasy zwracające pojedynczy wiersz oddawały zastępcy notatkę wniosku,
    choć kolejka ją maskowała (D6; przegląd bezpieczeństwa 17.10.2026).
    """

    if row.user_id == viewer.id:
        return
    _, covered = await _pending_scope(db, viewer, today)
    cover = covered.get(row.user_id)
    if cover is not None:
        _mark_cover(item, row, cover)


async def _pending_scope(
    db: AsyncSession, actor: User, today: date
) -> tuple[Optional[set[int]], dict[int, leave_substitute.Cover]]:
    """Czyje wnioski widzi akceptujący: ``None`` = wszyscy (Kadry, admin).

    Zastępca przełożonego, który jest dziś na urlopie, widzi też wnioski jego
    podwładnych (własny zespół wygrywa — tam jest pełnym przełożonym).
    """

    scope = await scope_user_ids(db, actor)
    covered: dict[int, leave_substitute.Cover] = {}
    if scope is not None:
        covered = {
            user_id: cover
            for user_id, cover in (
                await leave_substitute.covered_reports(db, actor.id, today)
            ).items()
            if user_id not in scope
        }
        scope = scope | set(covered)
    return scope, covered


def _pending_statement(actor_id: int, scope: Optional[set[int]]) -> Optional[Select]:
    """Wnioski czekające na decyzję patrzącego — jedno źródło listy i licznika.

    Zgłoszenia z B2B i zlecenia (D5) są od razu ``approved``, więc tu nie trafiają.
    """

    if scope is not None and not scope:
        return None
    statement = select(LeaveRequest).where(
        LeaveRequest.status == "pending", LeaveRequest.user_id != actor_id
    )
    if scope is not None:
        statement = statement.where(LeaveRequest.user_id.in_(scope))
    return statement


async def pending_count(db: AsyncSession, *, actor: User, today: date) -> int:
    """Liczba z ``pending_queue`` jednym ``count()`` (licznik „Akceptacji”)."""

    scope, _ = await _pending_scope(db, actor, today)
    statement = _pending_statement(actor.id, scope)
    if statement is None:
        return 0
    total = await db.scalar(select(func.count()).select_from(statement.subquery()))
    return int(total or 0)


async def pending_queue(
    db: AsyncSession, *, actor: User, today: date
) -> list[dict[str, Any]]:
    scope, covered = await _pending_scope(db, actor, today)
    statement = _pending_statement(actor.id, scope)
    if statement is None:
        return []
    rows = list(
        await db.scalars(statement.order_by(LeaveRequest.start_date).limit(300))
    )
    items = await serialize(db, rows, viewer=actor, today=today)
    for item, row in zip(items, rows, strict=True):
        _mark_cover(item, row, covered.get(row.user_id))
    await _with_context(db, items, rows)
    return items


async def _with_context(
    db: AsyncSession, items: list[dict[str, Any]], rows: list[LeaveRequest]
) -> None:
    """Dział, przełożony, praca w NEXUSIE i nieobecni z działu przy wierszu.

    Zbiorczo (audyt wydajności 17.10.2026): kontekst wszystkich wierszy
    kilkoma zapytaniami, nie pięcioma na wiersz — Kadry widzą całą firmę.
    """

    profiles = {
        p.user_id: p
        for p in await db.scalars(
            select(EmployeeProfile).where(
                EmployeeProfile.user_id.in_({r.user_id for r in rows} or {-1})
            )
        )
    }
    managers = await names_of(
        db, {p.manager_user_id for p in profiles.values() if p.manager_user_id}
    )
    windows = [
        RequestWindow(
            user_id=row.user_id,
            department=profiles[row.user_id].department
            if row.user_id in profiles
            else None,
            start=row.start_date,
            end=row.end_date,
        )
        for row in rows
    ]
    work = await work_summaries(db, windows)
    absent = await department_absences_many(db, windows)
    for index, (item, row) in enumerate(zip(items, rows, strict=True)):
        profile = profiles.get(row.user_id)
        item["department"] = profile.department if profile else None
        item["manager_name"] = (
            managers.get(profile.manager_user_id)
            if profile and profile.manager_user_id
            else None
        )
        item["work_total"] = work[index]["total"]
        item["work_by_kind"] = work[index]["by_kind"]
        item["department_absent"] = absent[index]


async def reported_queue(
    db: AsyncSession, *, actor: User, today: date
) -> list[dict[str, Any]]:
    """Zgłoszenia z B2B i zlecenia „do wiadomości” (D5): trwające i przyszłe.

    Zakres jak w kolejce wniosków (zespół, osoby pionu bez przełożonego u heada,
    zastępstwo za nieobecnego przełożonego, Kadry i admin wszystkich). Nie
    liczą się do „Akceptacji”.
    """

    scope, covered = await _pending_scope(db, actor, today)
    if scope is not None and not scope:
        return []
    statement = (
        select(LeaveRequest)
        .join(EmployeeProfile, EmployeeProfile.user_id == LeaveRequest.user_id)
        .where(
            LeaveRequest.status == "approved",
            LeaveRequest.end_date >= today,
            LeaveRequest.user_id != actor.id,
            EmployeeProfile.employment_type.in_(sorted(REPORT_FORMS)),
        )
    )
    if scope is not None:
        statement = statement.where(LeaveRequest.user_id.in_(scope))
    rows = list(
        await db.scalars(statement.order_by(LeaveRequest.start_date).limit(300))
    )
    items = await serialize(db, rows, viewer=actor, today=today)
    for item, row in zip(items, rows, strict=True):
        _mark_cover(item, row, covered.get(row.user_id))
        item["can_report_conflict"] = True
    await _with_context(db, items, rows)
    return items


def _history_statement(
    scope: Optional[set[int]],
    *,
    user_id: Optional[int],
    date_from: Optional[date],
    date_to: Optional[date],
) -> Optional[Select]:
    """Wnioski z „Wszystkich wniosków” bez filtra statusu — lista i liczniki."""

    if scope is not None and not scope:
        return None
    statement = select(LeaveRequest)
    if scope is not None:
        statement = statement.where(LeaveRequest.user_id.in_(scope))
    if user_id is not None:
        statement = statement.where(LeaveRequest.user_id == user_id)
    if date_from is not None:
        statement = statement.where(LeaveRequest.end_date >= date_from)
    if date_to is not None:
        statement = statement.where(LeaveRequest.start_date <= date_to)
    return statement


async def history_counts(
    db: AsyncSession,
    *,
    actor: User,
    user_id: Optional[int] = None,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
) -> dict[str, int]:
    """Liczba wniosków per status (i ``all``) w tym samym zakresie co lista.

    Liczniki przy filtrach statusu: zakres patrzącego i filtry osoby oraz dat,
    bez filtra statusu i bez limitu listy.
    """

    statement = _history_statement(
        await scope_user_ids(db, actor),
        user_id=user_id,
        date_from=date_from,
        date_to=date_to,
    )
    counts = {"all": 0, "pending": 0, "approved": 0, "rejected": 0, "cancelled": 0}
    if statement is None:
        return counts
    sub = statement.subquery()
    rows = await db.execute(select(sub.c.status, func.count()).group_by(sub.c.status))
    for status, total in rows.all():
        counts[status] = int(total or 0)
        counts["all"] += int(total or 0)
    return counts


async def history(
    db: AsyncSession,
    *,
    actor: User,
    today: date,
    status: Optional[str] = None,
    user_id: Optional[int] = None,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    statement = _history_statement(
        await scope_user_ids(db, actor),
        user_id=user_id,
        date_from=date_from,
        date_to=date_to,
    )
    if statement is None:
        return []
    if status:
        statement = statement.where(LeaveRequest.status == status)
    rows = list(
        await db.scalars(
            statement.order_by(
                LeaveRequest.start_date.desc(), LeaveRequest.created_at.desc()
            ).limit(limit)
        )
    )
    return await serialize(db, rows, viewer=actor, today=today)


async def on_behalf_people(db: AsyncSession, *, actor: User) -> list[dict[str, Any]]:
    """Osoby, którym przełożony (zespół) albo Kadry (wszyscy) wpisują nieobecność."""

    scope = await scope_user_ids(db, actor)
    statement = (
        select(User, EmployeeProfile)
        .join(EmployeeProfile, EmployeeProfile.user_id == User.id)
        .where(
            User.is_active.is_(True),
            User.id != actor.id,
            EmployeeProfile.employment_status != "exited",
        )
        .order_by(User.name, User.id)
    )
    if scope is not None:
        if not scope:
            return []
        statement = statement.where(User.id.in_(scope))
    rows = (await db.execute(statement)).all()
    sees_everyone = actor_of(actor).sees_everyone
    return [
        {
            "user_id": user.id,
            "name": user.name,
            "employment_type": profile.employment_type,
            "department": profile.department,
            # D5: za osobę na B2B/zleceniu wpisują tylko Kadry i admin
            # (``leave_service.subject_for_on_behalf``); lista służy też
            # filtrowi historii, więc osoba zostaje, tylko bez wpisu.
            "can_enter": sees_everyone or not reports_absence(profile.employment_type),
        }
        for user, profile in rows
    ]


__all__ = [
    "CONFLICT_ACTION",
    "history",
    "history_counts",
    "my_requests",
    "names_of",
    "on_behalf_people",
    "pending_count",
    "pending_queue",
    "reported_queue",
    "request_splits",
    "scope_user_ids",
    "serialize",
]
