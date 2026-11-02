"""Rozdzielanie maili i zgłoszeń z portalu: reguły, potem AI, potem człowiek.

Reguła jest pierwsza, bo jest darmowa i przewidywalna. Bez reguły pyta model, ale
jego wynik to tylko propozycja: awaria albo niepewność kończy się kartą „Do
rozdzielenia” u kierownika, a sprawa nigdy nie ginie. Rozstrzyga się raz na kartę
(``lane_locked``), więc kolejne przebiegi nie płacą za model ponownie.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.models.admin_case import AdminCaseMessage
from app.models.ai_feature import AIFeatureKey
from app.models.back_office import BoCard, BoCardEvent
from app.services.admin_cases.rules import fold
from app.services.ai_quota import ai_feature
from app.services.back_office_schema import TEAM_LANES, TRIAGE_LANE
from app.services.llm_prompts import CASE_TRIAGE

logger = logging.getLogger(__name__)

FEATURE = AIFeatureKey.case_triage
#: Poniżej tej pewności modelu decyduje człowiek.
MIN_CONFIDENCE = 0.8
BODY_LIMIT = 4_000
MAX_PER_RUN = 25
#: Zgłoszenia, które rozdzielamy. Sprawy z kontraktu i ręczne mają swoją kolumnę.
ROUTED_SOURCES = ("mail", "portal")

# Kolejność ma znaczenie tylko przy remisie: pierwszy pasujący zespół wygrywa
# wyłącznie, gdy nie pasuje żaden inny. Dwa różne zespoły = „Do rozdzielenia”.
_RULES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("finance", "invoice", ("faktur", "rozliczeni", "przelew", "platnosc")),
    ("finance", "timesheet", ("raport godzin", "timesheet", "ewidencj")),
    ("contracts", "annex", ("aneks", "stawk", "podwyzk", "negocjac")),
    ("contracts", "ending", ("wypowiedzeni", "rozwiazanie umowy")),
    ("contracts", "sign", ("podpis", "umowa do podpisu")),
    ("orders", "mail", ("zamowieni", "purchase order")),
    (
        "care",
        "exit",
        ("odejscie", "zakonczenie wspolpracy", "zwrot sprzetu", "offboarding"),
    ),
    (
        "care",
        "entry",
        ("onboarding", "pierwszy dzien", "nowy konsultant", "start wspolpracy"),
    ),
    ("care", "help", ("dostep", "vpn", "laptop", "haslo", "zaswiadczeni")),
)


@dataclass(frozen=True)
class Route:
    team: str
    lane: str


def rule_routes(subject: Optional[str], body: Optional[str]) -> list[Route]:
    """Kolumny wskazane przez reguły, po jednej na zespół."""

    folded = fold(f"{subject or ''}\n{body or ''}")
    seen: dict[str, Route] = {}
    for team, lane, needles in _RULES:
        if team not in seen and any(needle in folded for needle in needles):
            seen[team] = Route(team, lane)
    return list(seen.values())


def parse_model_answer(raw: str) -> tuple[Optional[Route], float]:
    """Odpowiedź modelu po walidacji; zły JSON albo kolumna spoza listy = brak."""

    try:
        data = json.loads(raw)
        team, lane = str(data["team"]), str(data["lane"])
        confidence = float(data.get("confidence", 0))
    except (ValueError, KeyError, TypeError):
        return None, 0.0
    if lane not in TEAM_LANES.get(team, ()):
        return None, 0.0
    return Route(team, lane), confidence


def decide(
    rules: list[Route], model: Optional[Route], confidence: float
) -> tuple[Optional[Route], Optional[Route]]:
    """Zwraca ``(kolumna, propozycja)``; brak kolumny = „Do rozdzielenia”."""

    if len(rules) == 1:
        rule = rules[0]
        if (
            model is not None
            and model.team != rule.team
            and confidence >= MIN_CONFIDENCE
        ):
            return None, rule  # reguła i pewny model się różnią
        return rule, rule
    if len(rules) > 1:
        return None, model or rules[0]
    if model is not None and confidence >= MIN_CONFIDENCE:
        return model, model
    return None, model


def _call_model(prompt: str) -> str:
    """Jedno wywołanie modelu (w wątku). Osobna funkcja: testy ją podmieniają."""

    from app.services.ai_models import fallbacks_for, model_for  # noqa: PLC0415
    from app.services.claude_client import call_claude_text  # noqa: PLC0415

    return call_claude_text(
        model=model_for(FEATURE),
        fallback_models=fallbacks_for(FEATURE),
        max_tokens=120,
        thinking={"type": "disabled"},
        system=CASE_TRIAGE.system_prompt or "",
        messages=[{"role": "user", "content": prompt}],
    )


async def _ask_model(
    db: AsyncSession, subject: Optional[str], body: Optional[str]
) -> tuple[Optional[Route], float]:
    from app.services.ai_models import model_for  # noqa: PLC0415
    from app.services.llm_providers import api_key_configured  # noqa: PLC0415

    if not api_key_configured(model_for(FEATURE)):
        return None, 0.0
    prompt = CASE_TRIAGE.render(
        subject=subject or "(bez tematu)", body=(body or "")[:BODY_LIMIT]
    )
    try:
        async with ai_feature(db, FEATURE):
            raw = await run_in_threadpool(_call_model, prompt)
    except Exception as exc:  # noqa: BLE001 — wynik modelu nigdy nie blokuje ścieżki
        logger.warning("back_office_triage: model niedostępny (%s)", type(exc).__name__)
        return None, 0.0
    return parse_model_answer(raw)


async def _first_message(
    db: AsyncSession, case_id: int
) -> tuple[Optional[str], Optional[str]]:
    row = (
        await db.execute(
            select(AdminCaseMessage.subject, AdminCaseMessage.body_text)
            .where(AdminCaseMessage.case_id == case_id)
            .order_by(
                AdminCaseMessage.received_at.asc().nulls_last(), AdminCaseMessage.id
            )
            .limit(1)
        )
    ).first()
    return (row[0], row[1]) if row else (None, None)


async def route_new_cards(db: AsyncSession) -> dict[str, int]:
    """Rozdziela nowe karty spraw z maila i portalu."""

    cards = (
        await db.scalars(
            select(BoCard)
            .where(
                BoCard.source_kind == "case",
                BoCard.state == "new",
                BoCard.lane_locked.is_(False),
                BoCard.needs_review.is_(False),
                BoCard.meta["case_source"].astext.in_(ROUTED_SOURCES),
            )
            .order_by(BoCard.id)
            .limit(MAX_PER_RUN)
        )
    ).all()
    routed = triaged = 0
    now = datetime.now(timezone.utc)
    for card in cards:
        subject, body = (
            await _first_message(db, card.case_id) if card.case_id else (None, None)
        )
        rules = rule_routes(subject or card.title, body)
        model: Optional[Route] = None
        confidence = 0.0
        if len(rules) != 1:
            model, confidence = await _ask_model(db, subject or card.title, body)
        target, guess = decide(rules, model, confidence)
        meta: dict[str, Any] = dict(card.meta or {})
        if guess is not None:
            meta["triage_guess"] = {"team": guess.team, "lane": guess.lane}
        if target is not None:
            card.team, card.lane = target.team, target.lane
            routed += 1
        else:
            card.team, card.lane = "care", TRIAGE_LANE
            triaged += 1
        card.meta = meta
        card.lane_locked = True
        card.updated_at = now
        db.add(
            BoCardEvent(
                card_id=card.id,
                action="triaged" if target is None else "routed",
                details={"lane": card.lane},
                created_at=now,
            )
        )
    await db.flush()
    return {"routed": routed, "triaged": triaged}
