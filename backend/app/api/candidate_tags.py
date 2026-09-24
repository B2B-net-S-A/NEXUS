"""Tagi kandydata: dodaj / usuń JEDEN tag + podpowiedzi (PR2).

Endpoints (montowane pod ``/api/candidates`` PRZED routerem kandydatów —
``/tags/suggest`` nie może trafić w ``/{candidate_id}``):

    GET    /api/candidates/tags/suggest?q=      → najczęstsze tagi-napisy
    POST   /api/candidates/{id}/tags            → dodaj tag (idempotentnie)
    DELETE /api/candidates/{id}/tags?tag=       → usuń tag (idempotentnie)

Dlaczego osobne trasy zamiast ``PATCH /api/candidates/{id}`` z całą listą:
kolumna ``tags`` miesza napisy z obiektami importu Traffita
(``{type: "traffit_source", …}`` — z nich szybki podgląd czyta źródło), a
PATCH ZASTĘPUJE listę. Klient, który wysłałby listę zbudowaną ze swojego
(starego) widoku, kasowałby tag dodany w międzyczasie przez kolegę albo
obiekty importu (UAT B60). Tutaj serwer zmienia jeden wpis pod blokadą
wiersza, a obiekty zostają nietknięte.

Tag porównywany bez wielkości liter (``Java`` = ``java``) — tak samo jak
filtr listy (``candidate_search_predicates.tag_match``).
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.candidate_access import CandidateSearchAccess, CandidateWriteAccess
from app.api.section_access import SOURCING_SECTION_DEPENDENCIES
from app.core.database import get_db
from app.models.activity import Activity
from app.models.candidate import Candidate

logger = logging.getLogger(__name__)

router = APIRouter(dependencies=SOURCING_SECTION_DEPENDENCIES)

TAG_MAX_LEN = 64
MAX_STRING_TAGS = 50
SUGGEST_LIMIT_MAX = 30


class TagPayload(BaseModel):
    tag: str = Field(..., min_length=1, max_length=200)

    @field_validator("tag")
    @classmethod
    def _clean(cls, value: str) -> str:
        cleaned = " ".join(value.split())
        if not cleaned:
            raise ValueError("Tag nie może być pusty.")
        if len(cleaned) > TAG_MAX_LEN:
            raise ValueError(f"Tag może mieć najwyżej {TAG_MAX_LEN} znaków.")
        if "," in cleaned:
            raise ValueError("Tag nie może zawierać przecinka — dodaj tagi osobno.")
        return cleaned


class TagsResponse(BaseModel):
    tags: list[Any]
    changed: bool


class TagSuggestion(BaseModel):
    """Kształt jak ``/companies/suggest`` i ``/titles/suggest`` — ten sam
    komponent podpowiedzi (``CompanyAutocomplete``) obsługuje filtr listy."""

    name: str
    count: int


def _current_tags(candidate: Candidate) -> list[Any]:
    raw = candidate.tags
    return list(raw) if isinstance(raw, list) else []


def _string_tags(tags: list[Any]) -> list[str]:
    return [t for t in tags if isinstance(t, str)]


async def _lock_candidate(db: AsyncSession, candidate_id: int) -> Candidate:
    candidate = await db.scalar(
        select(Candidate)
        .where(Candidate.id == candidate_id)
        .with_for_update(of=Candidate)
        .execution_options(populate_existing=True)
    )
    if candidate is None:
        raise HTTPException(status_code=404, detail="Nie znaleziono kandydata.")
    return candidate


async def _after_change(
    db: AsyncSession, candidate: Candidate, *, user_id: int, details: dict
) -> None:
    """Ten sam ogon co PATCH: dziennik, cache dopasowań, wektor."""
    db.add(
        Activity(
            entity_type="candidate",
            entity_id=candidate.id,
            action="tags_changed",
            user_id=user_id,
            details=details,
        )
    )
    from app.services.match_score_cache import mark_stale_for_candidate

    await mark_stale_for_candidate(db, candidate.id)
    await db.flush()
    try:
        from app.services.index_outbox_service import schedule_or_embed_candidate

        async with db.begin_nested():
            await schedule_or_embed_candidate(candidate.id, db)
    except Exception as exc:  # noqa: BLE001 — reindeks nie cofa edycji
        logger.warning(
            "[candidate_tags] reindex failed id=%s: %s",
            candidate.id,
            type(exc).__name__,
        )


@router.get("/tags/suggest", response_model=list[TagSuggestion])
async def suggest_tags(
    current_user: CandidateSearchAccess,
    q: str = Query("", max_length=TAG_MAX_LEN),
    limit: int = Query(15, ge=1, le=SUGGEST_LIMIT_MAX),
    db: AsyncSession = Depends(get_db),
) -> list[TagSuggestion]:
    """Najczęstsze tagi-napisy zaczynające się od ``q`` (bez wielkości liter).

    Obiekty importu (``traffit_source``) pomijane — nie da się ich dodać ręcznie.
    Pisownia w odpowiedzi = najczęstsza (przy remisie alfabetycznie pierwsza).
    """
    prefix = " ".join(q.split()).lower()
    escaped = prefix.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    rows = await db.execute(
        text(
            """
            WITH tag_values AS (
                SELECT btrim(e.value #>> '{}') AS tag
                FROM candidates c
                CROSS JOIN LATERAL jsonb_array_elements(
                    CASE WHEN jsonb_typeof(c.tags) = 'array'
                         THEN c.tags ELSE '[]'::jsonb END
                ) AS e(value)
                WHERE jsonb_typeof(e.value) = 'string'
            ),
            spelled AS (
                SELECT lower(tag) AS folded, tag, count(*) AS n
                FROM tag_values
                WHERE tag <> '' AND lower(tag) LIKE :pattern ESCAPE '\\'
                GROUP BY lower(tag), tag
            )
            SELECT (array_agg(tag ORDER BY n DESC, tag))[1] AS tag,
                   sum(n)::int AS total
            FROM spelled
            GROUP BY folded
            ORDER BY total DESC, folded
            LIMIT :limit
            """
        ),
        {"pattern": f"{escaped}%", "limit": limit},
    )
    return [TagSuggestion(name=row.tag, count=row.total) for row in rows]


@router.post("/{candidate_id}/tags", response_model=TagsResponse)
async def add_candidate_tag(
    candidate_id: int,
    payload: TagPayload,
    current_user: CandidateWriteAccess,
    db: AsyncSession = Depends(get_db),
) -> TagsResponse:
    candidate = await _lock_candidate(db, candidate_id)
    tags = _current_tags(candidate)
    folded = {t.casefold() for t in _string_tags(tags)}
    if payload.tag.casefold() in folded:
        return TagsResponse(tags=tags, changed=False)
    if len(folded) >= MAX_STRING_TAGS:
        raise HTTPException(
            status_code=422,
            detail=f"Kandydat może mieć najwyżej {MAX_STRING_TAGS} tagów.",
        )
    # NOWA lista → ORM widzi zmianę JSONB bez flag_modified.
    candidate.tags = [*tags, payload.tag]
    await _after_change(
        db, candidate, user_id=current_user.id, details={"added": payload.tag}
    )
    await db.commit()
    return TagsResponse(tags=list(candidate.tags), changed=True)


@router.delete("/{candidate_id}/tags", response_model=TagsResponse)
async def remove_candidate_tag(
    candidate_id: int,
    current_user: CandidateWriteAccess,
    tag: str = Query(..., min_length=1, max_length=200),
    db: AsyncSession = Depends(get_db),
) -> TagsResponse:
    wanted = " ".join(tag.split()).casefold()
    candidate = await _lock_candidate(db, candidate_id)
    tags = _current_tags(candidate)
    kept = [
        t
        for t in tags
        if not (isinstance(t, str) and " ".join(t.split()).casefold() == wanted)
    ]
    if len(kept) == len(tags):
        return TagsResponse(tags=tags, changed=False)
    candidate.tags = kept
    await _after_change(
        db, candidate, user_id=current_user.id, details={"removed": tag.strip()}
    )
    await db.commit()
    return TagsResponse(tags=list(kept), changed=True)
