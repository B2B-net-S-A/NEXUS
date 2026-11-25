"""Asystent prawny — API fundamentu (część A planu, 25.11.2026).

Trasy (``/api/legal``):

* ``GET /sources`` — stan korpusu prawa (akty, wersje, liczby przepisów),
  liczniki pozostałych źródeł (orzeczenia, wzory, wzory własne, umowy ramowe
  i aneksy) i zadań „Przejrzyj wzór” (część H; karta w Przepisach),
* ``GET /provisions/search?q=&acts=&on_date=&limit=`` — przepisy pasujące do
  pytania (po słowach i po znaczeniu),
* ``POST /verify`` — sprawdzenie cytatów w tekście z korpusem i podanymi
  fragmentami umów (bez modelu, niczego nie zapisuje),
* ``POST /draft`` — szkic pisma (funkcja AI ``legal_assistant``, F56; niczego
  nie zapisuje i nie wysyła).

**Bramka = Generator umów B2B** (``B2BGeneratorAccess`` za sekcją Sourcing,
jak ``/api/b2b-generator/documents``). Asystent działa w tle Generatora
(kreator aneksu i nowej umowy, Dokumenty) i ekranów kontraktów; każdy, kto
pracuje na kontrakcie (Delivery Lead z klientami, Back office, Finanse,
administrator), ma Generator, a rekruter ma go od dawna do umów
przedwstępnych. Kontrakty (sekcja Delivery) nie dają tu dostępu osobno, bo
trasy nie czytają żadnego kontraktu: fragmenty umów podaje ekran, który sam
przeszedł swoją bramkę (``LegalDocsReader``, Dokumenty kontraktu). Szkic pisma
woła model, więc wymaga poziomu „generowanie” Generatora i zapisu w sekcji
Sourcing; ``/verify`` jest odczytem (``READ_ONLY_POST_ROUTE_TEMPLATES``).
Reguły: ``docs/claude/asystent-prawny/fundament-korpus-prawa-weryfikator-cytatow.md``.
"""

# UWAGA: bez `from __future__ import annotations` — PEP 563 + slowapi #579
# (ciało żądania trafiłoby do parametrów query → 422).

from datetime import date
from typing import Any, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.contract_access import (
    B2BGeneratorAccess,
    assert_b2b_generator_action_access,
    require_b2b_generator_access,
)
from app.api.section_access import SOURCING_SECTION_DEPENDENCIES
from app.core.database import get_db
from app.core.rate_limit import limiter
from app.models.user import User
from app.services.action_permissions import ActionAccess
from app.services.legal import assistant, citations, corpus, sources, template_review
from app.services.legal.acts import ACT_KEYS
from app.services.legal.pseudonymize import Entity

router = APIRouter(dependencies=SOURCING_SECTION_DEPENDENCIES)

TEXT_MAX = 60_000
PASSAGE_TEXT_MAX = 60_000
HIT_TEXT_CHARS = 2_000


async def require_legal_draft(
    current_user: User = Depends(require_b2b_generator_access),
) -> User:
    """Szkic pisma woła model: poziom „generowanie” Generatora umów B2B."""
    assert_b2b_generator_action_access(current_user, ActionAccess.generate)
    return current_user


class PassageIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["law", "contract", "client", "template", "case"]
    ref: str = Field(min_length=1, max_length=120)
    text: str = Field(min_length=1, max_length=PASSAGE_TEXT_MAX)
    url: Optional[str] = Field(default=None, max_length=500)
    label: Optional[str] = Field(default=None, max_length=200)
    act_key: Optional[str] = Field(default=None, max_length=32)

    def passage(self) -> citations.SourcePassage:
        return citations.SourcePassage(
            self.kind, self.ref, self.text, self.url, self.label, self.act_key
        )


class VerifyIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=TEXT_MAX)
    passages: list[PassageIn] = Field(default_factory=list, max_length=50)
    on_date: Optional[date] = None


class EntityIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str = Field(min_length=2, max_length=32, pattern=r"^[A-Z_]+$")
    value: str = Field(min_length=1, max_length=300)
    inflect: bool = False


class DraftIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["termination", "annex", "reply", "letter"]
    instruction: str = Field(min_length=3, max_length=assistant.INSTRUCTION_MAX)
    passages: list[PassageIn] = Field(
        default_factory=list, max_length=assistant.PASSAGES_MAX
    )
    entities: list[EntityIn] = Field(default_factory=list, max_length=40)
    on_date: Optional[date] = None


def _hit_out(hit: corpus.ProvisionHit) -> dict[str, Any]:
    return {
        "id": hit.id,
        "act_key": hit.act_key,
        "act": hit.act_short_name,
        "ref": hit.ref,
        "kind": hit.kind,
        "heading": hit.heading,
        "text": hit.text[:HIT_TEXT_CHARS],
        "truncated": len(hit.text) > HIT_TEXT_CHARS,
        "repealed": hit.repealed,
        "version": hit.version_ident,
        "valid_from": hit.valid_from.isoformat(),
        "valid_to": hit.valid_to.isoformat() if hit.valid_to else None,
        "exact_date": hit.exact_date,
        "url": hit.url,
    }


def _passage_out(
    passage: Optional[citations.SourcePassage],
) -> Optional[dict[str, Any]]:
    if passage is None:
        return None
    return {
        "kind": passage.kind,
        "ref": passage.ref,
        "label": passage.label,
        "url": passage.url,
        "act_key": passage.act_key,
        "text": passage.text[:HIT_TEXT_CHARS],
    }


def _check_out(check: citations.CitationCheck) -> dict[str, Any]:
    citation = check.citation
    return {
        "status": check.status,
        "reason": check.reason,
        "message": check.message,
        "citation": {
            "kind": citation.kind,
            "raw": citation.raw,
            "ref": citation.ref,
            "act_key": citation.act_key,
            "start": citation.start,
            "end": citation.end,
            "quote": citation.quote,
            "range_to": citation.range_to,
            "document": citation.document,
        },
        "source": _passage_out(check.passage),
    }


@router.get("/sources")
async def legal_sources(
    _user: B2BGeneratorAccess, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    """Stan korpusu i liczniki pozostałych źródeł (same liczby, bez nazw)."""
    status = await corpus.sources_status(db)
    return {
        **status,
        "documents": await sources.documents_status(db),
        "template_review": await template_review.review_status(db),
    }


@router.get("/provisions/search")
async def search_provisions(
    _user: B2BGeneratorAccess,
    q: str = Query(..., min_length=2, max_length=300),
    acts: Optional[str] = Query(None, max_length=300),
    on_date: Optional[date] = None,
    limit: int = Query(8, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    keys = [k.strip() for k in (acts or "").split(",") if k.strip()]
    unknown = [k for k in keys if k not in ACT_KEYS]
    if unknown:
        raise HTTPException(
            status_code=422,
            detail=f"Nieznany akt: {', '.join(unknown)}. Dostępne: {', '.join(ACT_KEYS)}.",
        )
    result = await corpus.search(db, q, acts=keys or None, on_date=on_date, limit=limit)
    return {"retrieval": result.retrieval, "hits": [_hit_out(h) for h in result.hits]}


@router.post("/verify")
async def verify_citations(
    body: VerifyIn, _user: B2BGeneratorAccess, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    """Cytaty w tekście porównane ze źródłami (bez modelu, bez zapisu)."""
    checks = await corpus.verify_text(
        db, body.text, [p.passage() for p in body.passages], on_date=body.on_date
    )
    return {
        "checks": [_check_out(c) for c in checks],
        "blocked": citations.blocking(checks),
        "counts": {
            status: sum(1 for c in checks if c.status == status)
            for status in (
                citations.STATUS_OK,
                citations.STATUS_MISSING,
                citations.STATUS_MISMATCH,
            )
        },
    }


@router.post("/draft")
@limiter.limit("20/minute")
async def draft_letter(
    request: Request,
    body: DraftIn,
    user: User = Depends(require_legal_draft),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Szkic pisma ze sprawdzonymi cytatami. ``request`` — wymóg slowapi."""
    result = await assistant.draft(
        db,
        kind=body.kind,
        instruction=body.instruction,
        passages=[p.passage() for p in body.passages],
        entities=[Entity(e.label, e.value, e.inflect) for e in body.entities],
        user_id=user.id,
        on_date=body.on_date,
    )
    return {
        "text": result.text,
        "blocked": result.blocked,
        "checks": [_check_out(c) for c in result.checks],
        "issues": result.issues,
        "lawyer_review": result.lawyer_review,
        "passages": [_passage_out(p) for p in result.passages],
        "model": result.model,
        "error": result.error,
        "disclaimer": "Szkic asystenta nie jest poradą prawną. Pismo zatwierdza człowiek.",
    }
