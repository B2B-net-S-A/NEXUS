"""Słownik umiejętności — kuracja taksonomii (admin + Head of Recruitment).

Ustawienia → Rekrutacja → „Słownik umiejętności". Jedyne, co zostało
z Cortexa (usunięty 23.09.2026): dodanie umiejętności, aliasy i mapowanie
nieznanych terminów. Każdy zapis odświeża in-memory ``ALIAS_MAP`` scoringu
(``skill_curation``), więc nowy alias działa od razu w wyszukiwarce i dopasowaniu.

Bramka sekcji: Sourcing — słownik służy wyszukiwaniu kandydatów, a zapis
wymaga zapisu w tej sekcji (osoba z odebranym Sourcingiem słownika nie zmieni).
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import HeadOfRecruitmentPlus, get_db
from app.api.section_access import SOURCING_SECTION_DEPENDENCIES
from app.models.cortex import CortexUnmatchedTerm
from app.models.skill import Skill, SkillAlias
from app.services import skill_curation

router = APIRouter(dependencies=SOURCING_SECTION_DEPENDENCIES)


class CreateSkillRequest(BaseModel):
    canonical_name: str = Field(min_length=1, max_length=255)
    category: Optional[str] = Field(default=None, max_length=64)
    aliases: Optional[list[str]] = None
    from_term_id: Optional[int] = None


class AddAliasRequest(BaseModel):
    alias: str = Field(min_length=1, max_length=255)


class MapTermRequest(BaseModel):
    skill_id: int


def _curation_error(exc: skill_curation.CurationError) -> HTTPException:
    status_code = 409 if isinstance(exc, skill_curation.CurationConflict) else 400
    return HTTPException(status_code=status_code, detail=str(exc))


@router.get("/skills")
async def list_skills(
    _user: HeadOfRecruitmentPlus,
    db: AsyncSession = Depends(get_db),
    q: str = Query("", max_length=100, description="Szukaj po nazwie albo aliasie."),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    """Umiejętności z aliasami — przeszukiwalne, stronicowane."""
    ids = select(Skill.id)
    needle = q.strip().lower()
    if needle:
        pattern = f"%{needle}%"
        ids = ids.outerjoin(SkillAlias, SkillAlias.skill_id == Skill.id).where(
            or_(
                func.lower(Skill.canonical_name).like(pattern),
                func.lower(SkillAlias.alias).like(pattern),
            )
        )
    ids = ids.distinct().subquery()
    total = await db.scalar(select(func.count()).select_from(ids)) or 0
    rows = (
        (
            await db.execute(
                select(Skill)
                .where(Skill.id.in_(select(ids.c.id)))
                .order_by(func.lower(Skill.canonical_name).asc(), Skill.id.asc())
                .limit(limit)
                .offset(offset)
            )
        )
        .scalars()
        .all()
    )
    return {
        "items": [
            {
                "id": skill.id,
                "name": skill.canonical_name,
                "category": skill.category,
                "aliases": sorted(a.alias for a in skill.aliases),
            }
            for skill in rows
        ],
        "total": int(total),
    }


@router.post("/skills")
async def create_skill(
    payload: CreateSkillRequest,
    user: HeadOfRecruitmentPlus,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Nowa umiejętność (+ opcjonalne aliasy / z nieznanego terminu)."""
    try:
        return await skill_curation.create_skill(
            db,
            canonical_name=payload.canonical_name,
            category=payload.category,
            aliases=payload.aliases,
            from_term_id=payload.from_term_id,
            curated_by=getattr(user, "email", None),
        )
    except skill_curation.CurationError as exc:
        raise _curation_error(exc) from exc


@router.post("/skills/{skill_id}/aliases")
async def add_alias(
    skill_id: int,
    payload: AddAliasRequest,
    user: HeadOfRecruitmentPlus,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Dodaj alias do istniejącej umiejętności."""
    try:
        return await skill_curation.add_alias(
            db, skill_id, payload.alias, curated_by=getattr(user, "email", None)
        )
    except skill_curation.CurationError as exc:
        raise _curation_error(exc) from exc


@router.get("/unmatched-terms")
async def unmatched_terms(
    _user: HeadOfRecruitmentPlus,
    db: AsyncSession = Depends(get_db),
    term_status: str = Query(
        default="new", alias="status", pattern="^(new|mapped|ignored|all)$"
    ),
    limit: int = Query(default=50, ge=1, le=500),
) -> list[dict[str, Any]]:
    """Nieznane terminy — najczęstsze tokeny spoza słownika."""
    query = select(CortexUnmatchedTerm).order_by(
        CortexUnmatchedTerm.occurrences.desc(), CortexUnmatchedTerm.id.asc()
    )
    if term_status != "all":
        query = query.where(CortexUnmatchedTerm.status == term_status)
    rows = (await db.execute(query.limit(limit))).scalars().all()
    return [
        {
            "id": row.id,
            "term": row.term,
            "occurrences": row.occurrences,
            "status": row.status,
            "curated_by": row.curated_by,
            "curated_at": row.curated_at.isoformat() if row.curated_at else None,
            "last_seen_at": row.last_seen_at.isoformat() if row.last_seen_at else None,
        }
        for row in rows
    ]


@router.post("/unmatched-terms/{term_id}/map")
async def map_term(
    term_id: int,
    payload: MapTermRequest,
    user: HeadOfRecruitmentPlus,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Zmapuj nieznany termin na istniejącą umiejętność (dodaje alias)."""
    try:
        return await skill_curation.map_term_to_skill(
            db, term_id, payload.skill_id, curated_by=getattr(user, "email", None)
        )
    except skill_curation.CurationError as exc:
        raise _curation_error(exc) from exc


@router.post("/unmatched-terms/{term_id}/ignore")
async def ignore_term(
    term_id: int,
    user: HeadOfRecruitmentPlus,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Oznacz nieznany termin jako ignorowany."""
    try:
        return await skill_curation.ignore_term(
            db, term_id, curated_by=getattr(user, "email", None)
        )
    except skill_curation.CurationError as exc:
        raise _curation_error(exc) from exc


# ── Słowniczek „po ludzku” (0402) ───────────────────────────────────────────
# Definicje technologii dla rekruterów (blok „Po ludzku” w Podglądzie
# Championa). Poprawiają admin i Head of Recruitment (decyzja 29.09.2026);
# zapis ustawia `origin=manual`, więc ani zasiew z repo, ani research go nie
# nadpiszą. „Ze słownika” = hasło jest nazwą kanoniczną umiejętności.


class PlainTermUpdate(BaseModel):
    display_name: Optional[str] = Field(default=None, max_length=200)
    summary: Optional[str] = Field(default=None, max_length=2000)
    does: Optional[str] = Field(default=None, max_length=2000)
    cv_hints: Optional[list[str]] = None
    confused_with: Optional[str] = Field(default=None, max_length=2000)


async def _plain_term_payload(db: AsyncSession, row: Any) -> dict[str, Any]:
    from app.models.user import User
    from app.services.plain_knowledge import library

    in_dictionary = bool(
        await db.scalar(
            select(func.count(Skill.id)).where(
                func.lower(Skill.canonical_name) == row.term_key
            )
        )
    )
    editor = await db.get(User, row.updated_by) if row.updated_by else None
    return library.term_row_payload(
        row, in_dictionary=in_dictionary, updated_by_name=getattr(editor, "name", None)
    )


@router.get("/plain-terms")
async def list_plain_terms(
    _user: HeadOfRecruitmentPlus,
    db: AsyncSession = Depends(get_db),
    q: str = Query("", max_length=100),
    scope: str = Query("all", pattern="^(all|dictionary|outside)$"),
    limit: int = Query(100, ge=1, le=500),
) -> dict[str, Any]:
    from app.models.plain_knowledge import PlainTerm
    from app.models.user import User
    from app.services.plain_knowledge import library

    in_dict = (
        select(Skill.id)
        .where(func.lower(Skill.canonical_name) == PlainTerm.term_key)
        .exists()
    )
    stmt = select(PlainTerm, in_dict.label("in_dictionary"), User.name).outerjoin(
        User, User.id == PlainTerm.updated_by
    )
    needle = q.strip()
    if needle:
        like = f"%{needle}%"
        stmt = stmt.where(
            or_(PlainTerm.display_name.ilike(like), PlainTerm.term_key.ilike(like))
        )
    if scope == "dictionary":
        stmt = stmt.where(in_dict)
    elif scope == "outside":
        stmt = stmt.where(~in_dict)
    rows = (await db.execute(stmt.order_by(PlainTerm.display_name).limit(limit))).all()
    return {
        "items": [
            library.term_row_payload(
                row, in_dictionary=bool(flag), updated_by_name=name
            )
            for row, flag, name in rows
        ]
    }


@router.put("/plain-terms/{term_id}")
async def update_plain_term(
    term_id: int,
    payload: PlainTermUpdate,
    user: HeadOfRecruitmentPlus,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    from app.models.plain_knowledge import PlainTerm
    from app.services.plain_knowledge import library

    row = await db.get(PlainTerm, term_id, with_for_update=True)
    if row is None:
        raise HTTPException(status_code=404, detail="Nie ma takiego hasła.")
    if await library.apply_changes(
        db,
        row,
        "term",
        library.TERM_FIELDS,
        payload.model_dump(exclude_unset=True),
        user,
    ):
        await db.commit()
    row = await db.get(PlainTerm, term_id, populate_existing=True)
    return await _plain_term_payload(db, row)


@router.get("/plain-terms/{term_id}/history")
async def plain_term_history(
    term_id: int,
    _user: HeadOfRecruitmentPlus,
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    from app.services.plain_knowledge import library

    return await library.history(db, "term", term_id)
