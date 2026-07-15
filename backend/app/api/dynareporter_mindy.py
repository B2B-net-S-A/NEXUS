"""DynaReporter B.2.10 — MINDY AI chatbot z kontekstem KPI.

Asystent AI dla DynaReportera. Dwa endpointy:
- POST /commentary — generuje insight z kontekstem KPI usera (placement, sales,
  liga mistrzów). One-shot, no history.
- POST /chat — interactive chat. User dostarcza message history, dostaje
  odpowiedź. History trzymana po stronie frontu (localStorage), backend
  stateless.

Używa modelu z CLAUDE_MODEL_CV (domyślnie Claude Sonnet 5) do generacji
quick analytical insight'ów.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser
from app.core.config import settings
from app.core.database import get_db
from app.models.dr_kpi_body_leasing import DrKpiBodyLeasing
from app.models.dr_kpi_sales import DrKpiSales

logger = logging.getLogger(__name__)
router = APIRouter()


MINDY_SYSTEM_PROMPT = """Jesteś MINDY — AI asystentką w DynaReporter (system raportowania KPI
firmy IT staffing DynaMinds / B2B Network).

Twoje role:
- Analizujesz KPI rekruterów i sprzedawców (placements, leads, offers).
- Dajesz krótkie, konkretne insighty (3-5 zdań) zamiast generic motywacji.
- Mówisz po polsku, profesjonalnie ale nieformalnie (per "Ty").
- Bazujesz na dostarczonych liczbach — NIE wymyślasz danych.
- Jeśli brakuje danych — przyznaj to.
- Sugestie są actionable (konkretne kroki), nie ogólne.

Kontekst firmy:
- Body Leasing channel: weryfikacje → rekomendacje → interviews → placementy
- Sales channel: leady → wysłane oferty → wygrane (offers_won) lub przegrane
- Liga Mistrzów: ranking kwartalny per placementy
- KPI Coach: agregaty miesięczne per user / per dział
"""


class MindyCommentaryRequest(BaseModel):
    period: str = Field(default="month", pattern="^(week|month|quarter)$")


class MindyChatMessage(BaseModel):
    role: str = Field(pattern="^(user|assistant)$")
    content: str


class MindyChatRequest(BaseModel):
    messages: list[MindyChatMessage] = Field(min_length=1, max_length=20)


class MindyResponse(BaseModel):
    content: str
    model: str
    context_summary: Optional[str] = None


def _build_user_context(
    placements: int,
    interviews: int,
    recommendations: int,
    verifications: int,
    leads: int,
    offers_sent: int,
    offers_won: int,
    offers_lost: int,
    period: str,
) -> str:
    """Zbuduj zwięzły kontekst KPI dla Claude."""
    return (
        f"Statystyki użytkownika za okres: {period}\n"
        f"- Body Leasing: weryfikacje={verifications}, rekomendacje={recommendations}, "
        f"interviews={interviews}, placementy={placements}\n"
        f"- Sales: leady={leads}, wysłane={offers_sent}, "
        f"wygrane={offers_won}, przegrane={offers_lost}\n"
        f"- Win rate sales: "
        f"{(offers_won / (offers_won + offers_lost) * 100) if (offers_won + offers_lost) > 0 else 0:.0f}%"
    )


async def _fetch_user_kpi(
    db: AsyncSession, user_id: int, days: int
) -> tuple[int, int, int, int, int, int, int, int]:
    """Pobiera agregaty user'a z dr_kpi_body_leasing + dr_kpi_sales."""
    from_d = date.today() - timedelta(days=days)

    bl_stmt = select(
        func.coalesce(func.sum(DrKpiBodyLeasing.placements), 0),
        func.coalesce(func.sum(DrKpiBodyLeasing.interviews), 0),
        func.coalesce(func.sum(DrKpiBodyLeasing.recommendations), 0),
        func.coalesce(func.sum(DrKpiBodyLeasing.verifications), 0),
    ).where(
        DrKpiBodyLeasing.user_id == user_id,
        DrKpiBodyLeasing.report_date >= from_d,
    )
    bl = (await db.execute(bl_stmt)).first()

    sales_stmt = select(
        func.coalesce(func.sum(DrKpiSales.leads), 0),
        func.coalesce(func.sum(DrKpiSales.offers_sent), 0),
        func.coalesce(func.sum(DrKpiSales.offers_won), 0),
        func.coalesce(func.sum(DrKpiSales.offers_lost), 0),
    ).where(
        DrKpiSales.user_id == user_id,
        DrKpiSales.report_date >= from_d,
    )
    s = (await db.execute(sales_stmt)).first()

    return (
        bl[0] or 0,
        bl[1] or 0,
        bl[2] or 0,
        bl[3] or 0,
        s[0] or 0,
        s[1] or 0,
        s[2] or 0,
        s[3] or 0,
    )


@router.post("/commentary", response_model=MindyResponse)
async def commentary(
    payload: MindyCommentaryRequest,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> MindyResponse:
    """Jednorazowy insight MINDY o KPI usera."""
    if not settings.ANTHROPIC_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="ANTHROPIC_API_KEY not configured",
        )

    days_map = {"week": 7, "month": 30, "quarter": 90}
    days = days_map[payload.period]
    plc, intv, rec, ver, leads, sent, won, lost = await _fetch_user_kpi(
        db, current_user.id, days
    )
    context = _build_user_context(
        plc, intv, rec, ver, leads, sent, won, lost, payload.period
    )

    user_prompt = (
        f"Dla użytkownika {current_user.name} ({current_user.email}):\n\n"
        f"{context}\n\n"
        "Daj zwięzły (3-5 zdań) komentarz o jego performance i 1 konkretną sugestię."
    )

    from app.services.claude_client import call_claude  # local: avoid load-time cost

    try:
        # Shared resilient helper (explicit timeout + transient-retry backoff),
        # offloaded off the single-worker event loop.
        message = await run_in_threadpool(
            call_claude,
            model=settings.CLAUDE_MODEL_CV,
            max_tokens=400,
            system=MINDY_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
        )
        content = "".join(
            block.text for block in message.content if hasattr(block, "text")
        )
        return MindyResponse(
            content=content, model=settings.CLAUDE_MODEL_CV, context_summary=context
        )
    except Exception as e:
        logger.exception("MINDY commentary failed")
        raise HTTPException(status_code=502, detail=f"AI call failed: {e}")


@router.post("/chat", response_model=MindyResponse)
async def chat(
    payload: MindyChatRequest,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> MindyResponse:
    """Interactive chat z MINDY. History trzymana po stronie frontendu."""
    if not settings.ANTHROPIC_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="ANTHROPIC_API_KEY not configured",
        )

    # Dodaj kontekst KPI usera do system prompt
    plc, intv, rec, ver, leads, sent, won, lost = await _fetch_user_kpi(
        db, current_user.id, 30
    )
    context = _build_user_context(plc, intv, rec, ver, leads, sent, won, lost, "month")
    full_system = (
        f"{MINDY_SYSTEM_PROMPT}\n\n"
        f"Aktualne KPI rozmówcy ({current_user.name}):\n{context}"
    )

    # Convert messages format
    api_messages = [{"role": m.role, "content": m.content} for m in payload.messages]

    from app.services.claude_client import call_claude  # local: avoid load-time cost

    try:
        # Shared resilient helper (explicit timeout + transient-retry backoff),
        # offloaded off the single-worker event loop.
        message = await run_in_threadpool(
            call_claude,
            model=settings.CLAUDE_MODEL_CV,
            max_tokens=800,
            system=full_system,
            messages=api_messages,
        )
        content = "".join(
            block.text for block in message.content if hasattr(block, "text")
        )
        return MindyResponse(content=content, model=settings.CLAUDE_MODEL_CV)
    except Exception as e:
        logger.exception("MINDY chat failed")
        raise HTTPException(status_code=502, detail=f"AI call failed: {e}")
