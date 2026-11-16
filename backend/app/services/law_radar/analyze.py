"""Grok Analityk (``analyze``): polecenie, raport zmian, zapis.

Analityk dostaje **tylko pozycje po bramce** (``verified`` i ``unverified``,
dane publiczne), profil tematów, tytuły i numery otwartych zmian oraz katalog
sond (klucz i opis, bez liczb). Odsyła zmiany: tytuł, skrót, role, etap,
pilność, daty, pozycje, sondy z katalogu i zadania.

Zapis: zmiana z ``change_ref`` z listy otwartych dostaje nową treść i etap,
**nigdy status ani decyzję** (to robi człowiek); zmiana etapu trafia do
dziennika. Zmiana bez ``change_ref`` to nowa zmiana z zadaniami i wpisem
``created``. Pozycja spoza zlecenia biegu, nieznana sonda i ``change_ref``
spoza listy odpadają bez 422 (liczby w podsumowaniu).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Iterable, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.law_radar import (
    LawChange,
    LawChangeEvent,
    LawChangeTask,
    LawRadarItem,
    LawRadarRun,
)
from app.services.law_radar import probes, schema
from app.services.sales.bot_tasks.base import CleanText, RequiredText

logger = logging.getLogger(__name__)

KIND = "analyze"
MAX_CHANGES = 50
MAX_REQUEST_ITEMS = 200
MAX_OPEN_CHANGES = 100
MAX_SUMMARY = 5
MAX_ROLES = 5
MAX_ITEMS_PER_CHANGE = 50
MAX_PROBES = 5
MAX_TODO = 6
SUMMARY_LINE_MAX = 300

Role = Literal[schema.ROLES]  # type: ignore[valid-type]
Urgency = Literal[schema.URGENCIES]  # type: ignore[valid-type]
Stage = Literal[schema.STAGES]  # type: ignore[valid-type]
SummaryLine = RequiredText


class TodoReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: RequiredText = Field(min_length=1, max_length=schema.TASK_TEXT_MAX)
    role: Role


class ChangeReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    change_ref: Optional[int] = None
    title: RequiredText = Field(min_length=1, max_length=schema.CHANGE_TITLE_MAX)
    summary: list[SummaryLine] = Field(min_length=1, max_length=MAX_SUMMARY)
    roles: list[Role] = Field(min_length=1, max_length=MAX_ROLES)
    urgency: Urgency
    stage: Stage
    effective_on: Optional[date] = None
    deadline: Optional[date] = None
    legal_ref: Optional[CleanText] = Field(
        default=None, max_length=schema.LEGAL_REF_MAX
    )
    item_ids: list[int] = Field(min_length=1, max_length=MAX_ITEMS_PER_CHANGE)
    probes: list[str] = Field(default_factory=list, max_length=MAX_PROBES)
    todo: list[TodoReport] = Field(default_factory=list, max_length=MAX_TODO)

    @field_validator("summary")
    @classmethod
    def _summary_lines(cls, lines: list[str]) -> list[str]:
        if any(len(line) > SUMMARY_LINE_MAX for line in lines):
            raise ValueError(f"Punkt skrótu ma najwyżej {SUMMARY_LINE_MAX} znaków.")
        return lines

    @field_validator("roles")
    @classmethod
    def _unique_roles(cls, roles: list[str]) -> list[str]:
        return list(dict.fromkeys(roles))

    @field_validator("probes")
    @classmethod
    def _probe_keys(cls, keys: list[str]) -> list[str]:
        # Nieznany klucz odpada bez 422: sonda to dodatek do zmiany.
        return probes.known_keys(key for key in keys if isinstance(key, str))

    @field_validator("legal_ref")
    @classmethod
    def _empty_is_none(cls, value: Optional[str]) -> Optional[str]:
        return value or None


class AnalyzeReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    changes: list[ChangeReport] = Field(default_factory=list, max_length=MAX_CHANGES)


# ── Zlecenie ────────────────────────────────────────────────────────────


def item_payload(item: LawRadarItem) -> dict[str, Any]:
    """Pozycja dla Analityka: dane publiczne z bramki, bez danych firmy."""

    official = item.official or {}
    return {
        "id": item.id,
        "source": item.source,
        "klass": item.klass,
        "gate": item.gate,
        "title": item.title,
        "url": item.url,
        "published": item.published.isoformat(),
        "act_ref": item.act_ref,
        "print_no": item.print_no,
        "stage": item.stage,
        "official_stage": official.get("official_stage"),
        "entry_into_force": official.get("entry_into_force"),
        "quote": item.quote,
    }


def build_request(
    items: Iterable[dict[str, Any]],
    open_changes: Iterable[dict[str, Any]],
    *,
    topics: Iterable[str],
) -> dict[str, Any]:
    return {
        "items": list(items)[:MAX_REQUEST_ITEMS],
        "topics": list(topics),
        "open_changes": list(open_changes)[:MAX_OPEN_CHANGES],
        "probes": probes.catalog(),
        "roles": list(schema.ROLES),
        "stages": list(schema.STAGES),
        "urgencies": list(schema.URGENCIES),
        "max_changes": MAX_CHANGES,
    }


def task_text(request: dict[str, Any]) -> str:
    return (
        "Jesteś Analitykiem radaru przepisów. W request.items są pozycje sprawdzone "
        "przez NEXUS (gate = verified: numer aktu albo druku potwierdzony w API Sejmu; "
        "gate = unverified: bez potwierdzonego numeru, klass mówi, czy to strona "
        "urzędowa, LEX czy praktyka). Pogrupuj je w zmiany w prawie, które dotyczą "
        "tematów z request.topics.\n\n"
        "Dla każdej zmiany podaj:\n"
        "- title: krótki tytuł po polsku; summary: od 1 do 5 punktów, co się zmienia "
        "i od kiedy (każdy do 300 znaków),\n"
        "- roles: kogo dotyczy (board = zarząd, accounting = księgowość, payroll = "
        "płace i kadry, contracts = umowy, recruitment = rekrutacja),\n"
        "- stage: project, sejm, senate, president, journal (opublikowana, jeszcze nie "
        "obowiązuje) albo in_force; urgency: now (działać teraz), soon (w ciągu "
        "kwartału), watch (obserwować),\n"
        "- effective_on: data wejścia w życie, deadline: termin na działanie firmy "
        "(RRRR-MM-DD, tylko gdy wynika z pozycji),\n"
        "- legal_ref: numer aktu albo druku, tylko z pozycji (nie zgaduj),\n"
        "- item_ids: id pozycji z request.items, na których opierasz zmianę "
        "(co najmniej jedna; inne id zostaną pominięte),\n"
        "- probes: do 5 kluczy z request.probes, które pokażą, co zmiana znaczy "
        "u nas (tylko klucze z listy),\n"
        "- todo: do 6 konkretnych zadań dla ról (text do 200 znaków, role).\n\n"
        "Gdy pozycja dotyczy zmiany z request.open_changes, podaj jej id jako "
        "change_ref i opisz zmianę na nowo (nowy etap, daty), zamiast zakładać drugą. "
        "Nie oceniaj, czy firma już coś zrobiła: tego nie wiesz. Fakt urzędowy tylko "
        "z pozycji gate = verified; z pozycji unverified pisz ostrożnie („według …”). "
        "Pozycje, które nie dotyczą tematów, pomiń. Gdy nic nie pasuje, odeślij pustą "
        "listę changes. Najwyżej request.max_changes zmian."
    )


def report_format() -> dict[str, Any]:
    return {
        "changes": [
            {
                "change_ref": None,
                "title": "PIP może decyzją uznać umowę B2B za umowę o pracę",
                "summary": [
                    "Inspektor pracy może decyzją stwierdzić stosunek pracy przy "
                    "umowie cywilnej albo B2B."
                ],
                "roles": ["contracts", "payroll", "board"],
                "urgency": "now",
                "stage": "in_force",
                "effective_on": "2026-07-08",
                "deadline": None,
                "legal_ref": "Dz.U. 2026 poz. 473",
                "item_ids": [1],
                "probes": ["b2b_long_contracts"],
                "todo": [
                    {
                        "text": "Lista kontraktów z czynnikami ryzyka",
                        "role": "contracts",
                    }
                ],
            }
        ]
    }


# ── Plan zapisu (bez bazy) ──────────────────────────────────────────────


@dataclass
class PlannedChange:
    change_ref: Optional[int]
    values: dict[str, Any]
    item_ids: list[int]
    todo: list[dict[str, str]]


@dataclass
class AnalysisPlan:
    changes: list[PlannedChange] = field(default_factory=list)
    unknown_change: int = 0
    duplicate_change: int = 0
    no_items: int = 0
    foreign_items: int = 0


def change_values(change: ChangeReport) -> dict[str, Any]:
    """Treść zmiany od Analityka: to, co może nadpisać kolejny bieg."""

    return {
        "title": change.title,
        "summary": list(change.summary),
        "roles": list(change.roles),
        "urgency": change.urgency,
        "stage": change.stage,
        "effective_on": change.effective_on,
        "deadline": change.deadline,
        "legal_ref": change.legal_ref,
        "probe_keys": list(change.probes),
    }


def plan_analysis(
    report: AnalyzeReport, *, allowed_items: set[int], open_changes: set[int]
) -> AnalysisPlan:
    """Co z raportu trafi do bazy.

    ``allowed_items`` to id pozycji ze zlecenia biegu; pozycja przypisana do
    jednej zmiany nie przechodzi do następnej. ``open_changes`` to id zmian
    z listy wysłanej Analitykowi; inne ``change_ref`` odpadają.
    """

    plan = AnalysisPlan()
    used_items: set[int] = set()
    used_refs: set[int] = set()
    for change in report.changes:
        ref = change.change_ref
        if ref is not None:
            if ref not in open_changes:
                plan.unknown_change += 1
                continue
            if ref in used_refs:
                plan.duplicate_change += 1
                continue
        item_ids: list[int] = []
        for item_id in change.item_ids:
            if item_id not in allowed_items:
                plan.foreign_items += 1
            elif item_id not in used_items and item_id not in item_ids:
                item_ids.append(item_id)
        if not item_ids:
            plan.no_items += 1
            continue
        used_items.update(item_ids)
        if ref is not None:
            used_refs.add(ref)
        plan.changes.append(
            PlannedChange(
                change_ref=ref,
                values=change_values(change),
                item_ids=item_ids,
                todo=[{"text": t.text, "role": t.role} for t in change.todo],
            )
        )
    return plan


def content_changed(change: LawChange, values: dict[str, Any]) -> bool:
    return any(
        getattr(change, key) != value for key, value in values.items() if key != "stage"
    )


def new_todo(
    existing: Iterable[str], todo: list[dict[str, str]]
) -> list[dict[str, str]]:
    """Zadania, których zmiana jeszcze nie ma (porównanie bez wielkości liter)."""

    seen = {text.casefold() for text in existing}
    out = []
    for task in todo:
        key = task["text"].casefold()
        if key not in seen:
            seen.add(key)
            out.append(task)
    return out


# ── Zapis ───────────────────────────────────────────────────────────────


def _request_ids(run: LawRadarRun) -> tuple[set[int], set[int]]:
    request = run.request or {}
    items = {
        int(item["id"])
        for item in request.get("items", [])
        if isinstance(item, dict) and isinstance(item.get("id"), int)
    }
    changes = {
        int(change["id"])
        for change in request.get("open_changes", [])
        if isinstance(change, dict) and isinstance(change.get("id"), int)
    }
    return items, changes


async def ingest(
    db: AsyncSession, run: LawRadarRun, report: AnalyzeReport, *, now: datetime
) -> dict[str, Any]:
    from app.services.law_radar.runs import mark_received

    allowed_items, open_ids = _request_ids(run)
    plan = plan_analysis(report, allowed_items=allowed_items, open_changes=open_ids)
    refs = [p.change_ref for p in plan.changes if p.change_ref is not None]
    existing = (
        {
            change.id: change
            for change in (
                await db.execute(
                    select(LawChange).where(LawChange.id.in_(refs)).with_for_update()
                )
            ).scalars()
        }
        if refs
        else {}
    )
    created = updated = stage_changes = tasks_added = 0
    touched: list[int] = []
    for planned in plan.changes:
        change = existing.get(planned.change_ref) if planned.change_ref else None
        if planned.change_ref is not None and change is None:
            # Zmiana skasowana między zleceniem a raportem.
            plan.unknown_change += 1
            continue
        if change is None:
            change = LawChange(
                **planned.values,
                status="new",
                first_run_id=run.id,
                last_run_id=run.id,
                created_at=now,
                updated_at=now,
            )
            db.add(change)
            await db.flush()
            db.add(LawChangeEvent(change_id=change.id, kind="created", run_id=run.id))
            todo = planned.todo
            created += 1
        else:
            # Status, decyzja i zadania ludzi zostają; bot zmienia treść i etap.
            old_stage = change.stage
            if content_changed(change, planned.values):
                db.add(
                    LawChangeEvent(change_id=change.id, kind="updated", run_id=run.id)
                )
                updated += 1
            if old_stage != planned.values["stage"]:
                db.add(
                    LawChangeEvent(
                        change_id=change.id,
                        kind="stage",
                        from_value=old_stage,
                        to_value=planned.values["stage"],
                        run_id=run.id,
                    )
                )
                stage_changes += 1
            for key, value in planned.values.items():
                setattr(change, key, value)
            change.last_run_id = run.id
            change.updated_at = now
            texts = (
                await db.execute(
                    select(LawChangeTask.text).where(
                        LawChangeTask.change_id == change.id
                    )
                )
            ).scalars()
            todo = new_todo(texts, planned.todo)
        for task in todo:
            db.add(
                LawChangeTask(
                    change_id=change.id,
                    text=task["text"],
                    role=task["role"],
                    source="bot",
                )
            )
            tasks_added += 1
        await db.execute(
            update(LawRadarItem)
            .where(LawRadarItem.id.in_(planned.item_ids))
            .values(change_id=change.id)
        )
        touched.append(change.id)
    if allowed_items:
        await db.execute(
            update(LawRadarItem)
            .where(LawRadarItem.id.in_(sorted(allowed_items)))
            .values(analyzed_at=now, analyze_run_id=run.id)
        )
    summary = {
        "changes_in": len(report.changes),
        "created": created,
        "updated": updated,
        "stage_changes": stage_changes,
        "tasks_added": tasks_added,
        "items_sent": len(allowed_items),
        "dropped": {
            "unknown_change": plan.unknown_change,
            "duplicate_change": plan.duplicate_change,
            "no_items": plan.no_items,
            "foreign_items": plan.foreign_items,
        },
        "change_ids": touched,
    }
    mark_received(run, summary, now)
    logger.info(
        "law_radar run=%s analyze received changes=%d created=%d updated=%d stage=%d "
        "tasks=%d unknown=%d no_items=%d foreign_items=%d",
        run.id,
        len(report.changes),
        created,
        updated,
        stage_changes,
        tasks_added,
        plan.unknown_change,
        plan.no_items,
        plan.foreign_items,
    )
    return summary
