"""Raport bota Cpro: sprawdzenie, zapis wyniku kart i ruch na „Wysłane do Cpro”.

Raport to dane niezaufane: ``extra=forbid``, limity długości, tylko karty
z biegu, link do oferty tylko ``https://*.onevms.se``, znaki sterujące wycięte.

Karta, którą bot wysłał (``submitted`` w biegu z ``submit``), przechodzi na
„Wysłane do Cpro” tym samym ruchem co „✓ Wrzucone” w oknie kolejki
(``apply_move`` z polityką osoby od Cpro, jak ``api/dl_match.py``): te same
bramki, powiadomienia i dzwonki. Ruch nie przejdzie (karta ruszona w tym
czasie, brak osoby od Cpro, bramka) — wynik zostaje „wysłane”, a kolejka
pokazuje, że kartę trzeba przesunąć ręcznie. Bot nigdy nie wyśle jej drugi raz.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Literal, Optional
from urllib.parse import urlparse

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.activity import Activity
from app.models.cpro_bot import CproBotRun
from app.models.user import User
from app.services import cpro_sender
from app.services.cpro_bot import runs
from app.services.cpro_bot import items as bot_items

logger = logging.getLogger(__name__)

MAX_ITEMS = 20
URL_MAX = 500


def _clean(value: Optional[str], limit: int) -> Optional[str]:
    if value is None:
        return None
    text = "".join(ch if ch.isprintable() else " " for ch in str(value))
    text = " ".join(text.split())[:limit]
    return text or None


def offer_link(value: Optional[str]) -> Optional[str]:
    """Link do oferty tylko na portal Cpro (https, domena onevms.se)."""

    text = _clean(value, URL_MAX)
    if not text:
        return None
    parsed = urlparse(text)
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or not (
        host == "onevms.se" or host.endswith(".onevms.se")
    ):
        return None
    return text


class ReportItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ref: int
    outcome: Literal["submitted", "draft", "failed", "skipped"]
    cpro_status: Optional[str] = Field(None, max_length=60)
    offer_url: Optional[str] = Field(None, max_length=URL_MAX)
    reason: Optional[str] = Field(None, max_length=40)
    message: Optional[str] = Field(None, max_length=400)

    @field_validator("cpro_status", "reason", "message", "offer_url", mode="before")
    @classmethod
    def _empty_is_none(cls, value: Any) -> Any:
        if isinstance(value, str) and not value.strip():
            return None
        return value


class CproReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[ReportItem] = Field(default_factory=list, max_length=MAX_ITEMS)


def summarize(run: CproBotRun, report: CproReport) -> dict[str, Any]:
    """Wynik kart z raportu (czysta reguła): tylko karty z biegu, ostatni wpis wygrywa."""

    known = {int(s) for s in run.stage_ids or []}
    out: dict[str, dict[str, Any]] = {}
    unknown = 0
    draft_only = runs.draft_only(run)
    for item in report.items:
        if item.ref not in known:
            unknown += 1
            continue
        outcome = item.outcome
        reason = _clean(item.reason, 40)
        reported_outcome = None
        cpro_status = _clean(item.cpro_status, 60)
        if draft_only and outcome == "submitted":
            # Nie oznaczaj niedozwolonej wysyłki jako udanego szkicu.
            # Zachowaj prawdziwe zgłoszenie do audytu i deduplikacji.
            reported_outcome, outcome = outcome, "failed"
            reason = "submit_disallowed"
        elif draft_only and outcome == "draft" and cpro_status != "DRAFT":
            reported_outcome, outcome = outcome, "failed"
            reason = "draft_unconfirmed"
        elif outcome == "submitted" and not run.submit:
            # Próba bez wysyłki: „wysłane” od bota to błąd bota, nie wysyłka.
            outcome = "draft"
        out[str(item.ref)] = {
            "outcome": outcome,
            "cpro_status": cpro_status,
            "offer_url": offer_link(item.offer_url),
            "reason": reason,
            "message": _clean(item.message, 400),
            **({"reported_outcome": reported_outcome} if reported_outcome else {}),
        }
    counts = {
        key: sum(1 for v in out.values() if v["outcome"] == key)
        for key in ("submitted", "draft", "failed", "skipped")
    }
    counts["missing"] = len(known) - len(out)
    counts["unknown"] = unknown
    return {"items": out, "counts": counts}


async def _move_sent(
    db: AsyncSession, run: CproBotRun, stage_id: int, sender: Optional[User]
) -> Optional[str]:
    """Ruch karty na „Wysłane do Cpro”. ``None`` = przesunięta, inaczej powód."""

    if runs.draft_only(run) or not run.submit:
        return "Tryb szkiców nie przesuwa kart do „Wysłane do Cpro”."

    from app.api.pipeline import MoveApplied, apply_move, run_move_effects  # noqa: PLC0415
    from app.schemas.pipeline import StageMove  # noqa: PLC0415
    from app.services.recruitment_move_policy import UserMovePolicy  # noqa: PLC0415

    card = ((run.request or {}).get("cards") or {}).get(str(stage_id)) or {}
    target = card.get("target_stage_def_id")
    if sender is None:
        return "Brak osoby od Cpro — przesuń kartę ręcznie."
    if target is None:
        return "Rekrutacja nie ma etapu „Wysłane do Cpro”."
    stage = await bot_items.stage_still_queued(db, stage_id)
    if stage is None:
        return "Karta była już przesunięta."
    move = StageMove(
        candidate_id=stage.candidate_id,
        job_id=stage.job_id,
        stage_def_id=int(target),
        notes="Wrzucone do Cpro przez bota.",
    )
    try:
        async with db.begin_nested():
            outcome = await apply_move(db, move, policy=UserMovePolicy(sender, db))
            if not isinstance(outcome, MoveApplied):
                raise HTTPException(409, "Ruch nie został zapisany.")
            db.add(
                Activity(
                    entity_type="pipeline",
                    entity_id=outcome.stage.id,
                    action="cpro_bot_submitted",
                    user_id=None,
                    details={
                        "candidate_id": stage.candidate_id,
                        "job_id": stage.job_id,
                        "run_id": run.id,
                        "source": "cpro_bot",
                    },
                )
            )
    except HTTPException as exc:
        detail = exc.detail if isinstance(exc.detail, str) else "bramka ruchu"
        return f"Nie przesunięto karty: {detail}"[:200]
    except Exception:  # noqa: BLE001 — wynik bota zostaje, kartę przesunie człowiek
        logger.exception("cpro_bot run=%s move stage=%s", run.id, stage_id)
        return "Nie przesunięto karty — przesuń ją ręcznie."
    await db.commit()
    try:
        await run_move_effects(db, outcome, mover=sender)
    except Exception:  # noqa: BLE001 — efekty nigdy nie cofają ruchu
        logger.exception("cpro_bot run=%s move effects stage=%s", run.id, stage_id)
    return None


def closed_request_numbers(run: CproBotRun, summary: dict[str, Any]) -> list[str]:
    """Numery requestów, które robot zastał zamknięte (czysta reguła)."""

    refs = {
        ref
        for ref, item in summary["items"].items()
        if item["outcome"] == "failed" and item["reason"] == "request_closed"
    }
    numbers = {
        str(item["request_number"])
        for item in (run.request or {}).get("items", [])
        if str(item.get("ref")) in refs and item.get("request_number")
    }
    return sorted(numbers)


async def close_requests_seen_closed(
    db: AsyncSession, run: CproBotRun, summary: dict[str, Any]
) -> None:
    """Zamknięty request w CPro zamyka rekrutację w NEXUSIE (Artur, 27.11.2026).

    Błąd zamknięcia nie cofa zapisanego raportu: savepoint, log, dalej.
    """
    from app.services import cpro_mail  # noqa: PLC0415
    from app.services.job_lifecycle import PostCommit, run_post_commit  # noqa: PLC0415

    for number in closed_request_numbers(run, summary):
        effects = PostCommit()
        try:
            async with db.begin_nested():
                result = await cpro_mail.close_from_robot(db, number, effects)
            await db.commit()
        except Exception:  # noqa: BLE001 — raport biegu już zapisany
            logger.exception(
                "cpro_bot run=%s request=%s: zamknięcie nie wyszło", run.id, number
            )
            continue
        logger.info(
            "cpro_bot run=%s request=%s closed_request outcome=%s job=%s",
            run.id,
            number,
            result.outcome,
            result.job_id,
        )
        await run_post_commit(effects)


async def apply_report(
    db: AsyncSession, run: CproBotRun, report: CproReport, *, now: datetime
) -> dict[str, Any]:
    """Zapisz wynik biegu, potem przesuń wysłane karty. Zwraca podsumowanie."""

    summary = summarize(run, report)
    run.status = "received"
    run.received_at = now
    run.token_hash = None
    run.report = summary
    await db.commit()
    await close_requests_seen_closed(db, run, summary)

    # Osobny bezpiecznik obok normalizacji raportu: również wcześniejszy bieg
    # submit=true nie przesunie karty po włączeniu trybu szkiców.
    if runs.draft_only(run) or not run.submit:
        return summary

    sent = [
        int(ref)
        for ref, item in summary["items"].items()
        if item["outcome"] == "submitted"
    ]
    if not sent:
        return summary
    state = await cpro_sender.effective_sender(db, now)
    sender = await db.get(User, state.user_id) if state.user_id else None
    if sender is not None:
        from app.services.effective_access import resolve_effective_access  # noqa: PLC0415

        await resolve_effective_access(db, [sender])
    moved = 0
    items = dict(summary["items"])
    for stage_id in sent:
        problem = await _move_sent(db, run, stage_id, sender)
        entry = dict(items[str(stage_id)])
        entry["moved"] = problem is None
        if problem:
            entry["move_problem"] = problem
        else:
            moved += 1
        items[str(stage_id)] = entry
    fresh = await db.get(CproBotRun, run.id, populate_existing=True)
    if fresh is not None:
        fresh.report = {
            **summary,
            "items": items,
            "counts": {**summary["counts"], "moved": moved},
        }
        await db.commit()
        return fresh.report
    return summary
