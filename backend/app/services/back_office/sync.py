"""Synchronizacja kart ze źródłami (pętla ``back_office_sync`` i „Odśwież”).

Idempotentna po ``source_key``. Awaria jednego adaptera nie domyka jego kart ani
nie wstrzymuje reszty: każdy biegnie w swoim punkcie zapisu. Osoba, stan
i termin przejęcia należą do karty; przy karcie sprawy stan i osoba są lustrem
``admin_cases``.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import Any, Iterable, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.back_office import BoCard, BoCardEvent
from app.services.back_office import access, escalation, service, steps, triage
from app.services.back_office.sources import ADAPTERS, CardSpec
from app.services.hr import modules as hr_modules

logger = logging.getLogger(__name__)

_OPEN_STATES = ("new", "in_progress", "waiting")
_SPEC_FIELDS = (
    "title",
    "person",
    "client_label",
    "due_on",
    "href",
    "case_id",
    "contract_id",
    "client_id",
    "subject_user_id",
    "meta",
)


def _clean_title(value: str) -> str:
    return " ".join((value or "").replace("\x00", "").split())[:200] or "Bez tytułu"


def apply_spec(card: BoCard, spec: CardSpec, *, now: datetime) -> bool:
    """Przepisuje pola źródła; zwraca, czy coś się zmieniło."""

    changed = False
    values: dict[str, Any] = {name: getattr(spec, name) for name in _SPEC_FIELDS}
    values["title"] = _clean_title(spec.title)
    values["meta"] = {**(card.meta or {}), **spec.meta}
    if not card.lane_locked:
        values["team"] = spec.team
        values["lane"] = spec.lane
    if spec.mirrors_case:
        values["assignee_user_id"] = spec.mirror_assignee
        values["state"] = spec.mirror_state
    for name, value in values.items():
        if getattr(card, name) != value:
            setattr(card, name, value)
            changed = True
    if spec.mirrors_case and card.assignee_user_id is None:
        card.taken_at = None
        card.substituting = False
    if card.closed_at is not None and not (card.meta or {}).get("dismissed"):
        # Źródło wróciło (np. cofnięty akcept): karta wraca jako otwarta.
        card.closed_at = None
        if card.state == "done":
            card.state = "new"
        changed = True
    if changed:
        card.updated_at = now
    return changed


async def _sync_kind(
    db: AsyncSession, kind: str, *, today: date, now: datetime, review_open: bool
) -> dict[str, int]:
    specs = await ADAPTERS[kind](db, today)
    wanted = {spec.source_key: spec for spec in specs}
    existing = {
        card.source_key: card
        for card in (
            await db.scalars(
                select(BoCard).where(
                    BoCard.source_kind == kind,
                    BoCard.parent_card_id.is_(None),
                )
            )
        ).all()
    }
    created = updated = closed = 0
    for key, spec in wanted.items():
        card = existing.get(key)
        if card is None:
            card = BoCard(
                source_kind=kind,
                source_key=key,
                team=spec.team,
                lane=spec.lane,
                title=_clean_title(spec.title),
                state=spec.mirror_state if spec.mirrors_case else "new",
                assignee_user_id=spec.mirror_assignee if spec.mirrors_case else None,
                needs_review=kind == "case" and review_open,
                created_at=now,
                updated_at=now,
                meta={},
            )
            apply_spec(card, spec, now=now)
            db.add(card)
            created += 1
        elif apply_spec(card, spec, now=now):
            updated += 1
    for key, card in existing.items():
        if key not in wanted and card.state != "done":
            card.state = "done"
            card.closed_at = now
            card.updated_at = now
            db.add(
                BoCardEvent(
                    card_id=card.id,
                    action="closed_by_source",
                    details={},
                    created_at=now,
                )
            )
            closed += 1
    await db.flush()
    return {"created": created, "updated": updated, "closed": closed}


async def sync_kinds(
    db: AsyncSession,
    kinds: Optional[Iterable[str]] = None,
    *,
    today: date,
    now: Optional[datetime] = None,
) -> dict[str, Any]:
    """Przebieg po adapterach bez commita. Porażka adaptera ląduje w ``failed``."""

    moment = now or datetime.now(timezone.utc)
    settings = await access.load_settings(db)
    review_open = not settings.get("review_done_at")
    stats: dict[str, Any] = {}
    failed: list[str] = []
    for kind in kinds if kinds is not None else ADAPTERS:
        try:
            async with db.begin_nested():
                stats[kind] = await _sync_kind(
                    db, kind, today=today, now=moment, review_open=review_open
                )
        except Exception:  # noqa: BLE001 — jedno źródło nie zatrzymuje reszty
            # Klasa błędu w logu wystarczy: treść bywa z danymi osobowymi.
            logger.exception("back_office_sync: adapter %s failed", kind)
            failed.append(kind)
    return {"kinds": stats, "failed": failed}


async def run_once(db: AsyncSession, *, today: date) -> dict[str, Any]:
    """Pełny przebieg pętli: karty, kroki, eskalacja."""

    modules = await hr_modules.load_modules(db)
    if not modules.get(hr_modules.HrModule.back_office):
        return {"status": "disabled"}
    result = await sync_kinds(db, today=today)
    result["triage"] = await triage.route_new_cards(db)
    result["steps"] = await steps.sync_steps(db, today=today)
    result["priorities"] = await service.apply_priorities(db, today=today)
    result["escalation"] = await escalation.run(db, today=today)
    await db.commit()
    return {"status": "ok", **result}
