"""Kuracja słownika umiejętności (Ustawienia → Rekrutacja → „Słownik umiejętności").

Admin i Head of Recruitment mogą: zmapować nieznany termin na istniejący skill
(dodaje alias), utworzyć nowy canonical, dodać alias, oznaczyć termin jako
ignorowany — z audytem (kto/kiedy). Po każdej zmianie odświeżamy in-memory
ALIAS_MAP scoringu, żeby nowe aliasy działały od razu.

Do 23.09.2026 moduł żył w Cortexie (``services/cortex/curation.py``). Cortex
został usunięty, a nieznane terminy (tabela ``cortex_unmatched_terms``) przestały
przybywać — kolejka zawiera to, co ekstrakcja zebrała do tego dnia.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.cortex import CortexUnmatchedTerm
from app.models.skill import Skill, SkillAlias
from app.services.skill_taxonomy_loader import refresh_alias_map


class CurationError(Exception):
    """Błąd domenowy kuracji (mapowany na 4xx w API)."""


class CurationConflict(CurationError):
    """Nazwa albo alias koliduje z inną umiejętnością (409 w API)."""


# ── Kategorie i role (etap 2 słownika, 06.11.2026) ──────────────────────────
# Kategoria decyduje, czy hasło jest technologią (pogrubianie CV, QC, bramka
# must), więc nowe hasło bez kategorii działało tylko w połowie. Role
# (`role_*`) to stanowiska, nie umiejętności: nie przyjmują aliasów i nie są
# do wyboru przy nowym haśle.
ROLE_PREFIX = "role_"
EXTRA_CATEGORIES = ("practice", "domain")


def is_role(category: Optional[str]) -> bool:
    return (category or "").startswith(ROLE_PREFIX)


def allowed_categories(categories: Iterable[Optional[str]]) -> set[str]:
    """Kategorie do wyboru: te ze słownika bez ról + praktyki i wiedza domenowa."""
    return {c for c in categories if c and not is_role(c)} | set(EXTRA_CATEGORIES)


async def category_choices(db: AsyncSession) -> list[str]:
    used = (await db.scalars(select(Skill.category).distinct())).all()
    return sorted(allowed_categories(used))


async def _check_category(db: AsyncSession, category: Optional[str]) -> str:
    value = (category or "").strip()
    if not value:
        raise CurationError("Wybierz kategorię hasła.")
    if value not in await category_choices(db):
        raise CurationError(f"Nieznana kategoria „{value}”.")
    return value


# ── Zapamiętane wyniki dopasowania po zmianie słownika ──────────────────────
# Klucz pamięci wyników (`scoring_algorithm_version`) nie zależy od treści
# słownika, a pamięć nie ma TTL: po dodaniu aliasu wynik sprzed zmiany żył dalej.
# Zmiana hasła dotyczy tylko rekrutacji, które go wymagają (w dowolnym zapisie),
# więc unieważniamy punktowo te rekrutacje, jak `mark_stale_for_profile`.
_JOB_VARIANTS = re.compile(r"\s+(?:lub|or)\s+|\s+/\s+", re.IGNORECASE)
_PARENS = re.compile(r"\s*\([^)]*\)")


def _job_name_forms(raw: object) -> set[str]:
    from app.services.skill_normalize import strip_version

    if not isinstance(raw, str):
        return set()
    forms: set[str] = set()
    for part in _JOB_VARIANTS.split(raw):
        low = " ".join(part.split()).lower()
        if not low:
            continue
        bare = _PARENS.sub("", low).strip()
        forms |= {low, bare, strip_version(bare)[0].strip().lower()}
    forms.discard("")
    return forms


async def skill_forms(db: AsyncSession, skill_ids: Iterable[int]) -> set[str]:
    """Nazwa i aliasy haseł małymi literami."""
    ids = sorted(set(skill_ids))
    if not ids:
        return set()
    names = (
        await db.scalars(select(Skill.canonical_name).where(Skill.id.in_(ids)))
    ).all()
    aliases = (
        await db.scalars(select(SkillAlias.alias).where(SkillAlias.skill_id.in_(ids)))
    ).all()
    return {" ".join(n.split()).lower() for n in [*names, *aliases] if n}


async def invalidate_scores(db: AsyncSession, forms: Iterable[str]) -> int:
    """Unieważnia wyniki rekrutacji, których wymagania wymieniają któryś zapis.

    Nie commituje. Zwraca liczbę unieważnionych rekrutacji."""
    from app.models.job import Job
    from app.services.match_score_cache import mark_stale_for_jobs

    wanted = {f for f in forms if f}
    if not wanted:
        return 0
    job_ids: list[int] = []
    for job_id, must, nice in (
        await db.execute(select(Job.id, Job.must_skills, Job.nice_skills))
    ).all():
        items = [
            *(must if isinstance(must, list) else []),
            *(nice if isinstance(nice, list) else []),
        ]
        for item in items:
            name = item.get("name") if isinstance(item, dict) else item
            if _job_name_forms(name) & wanted:
                job_ids.append(job_id)
                break
    await mark_stale_for_jobs(db, job_ids)
    return len(job_ids)


async def after_dictionary_change(
    db: AsyncSession, skill_ids: Iterable[int], extra_forms: Iterable[str] = ()
) -> int:
    """Po zatwierdzonej zmianie: najpierw nowa mapa aliasów, potem unieważnienie.

    Kolejność ma znaczenie: wynik policzony między zapisem a odświeżeniem mapy
    (starą mapą) zostaje unieważniony, a każde przeliczenie po unieważnieniu
    widzi już nową mapę."""
    await refresh_alias_map()
    forms = await skill_forms(db, skill_ids) | {
        " ".join(f.split()).lower() for f in extra_forms if f
    }
    count = await invalidate_scores(db, forms)
    await db.commit()
    return count


async def _skill_by_id(db: AsyncSession, skill_id: int) -> Skill:
    skill = await db.get(Skill, skill_id)
    if skill is None:
        raise CurationError(f"Skill {skill_id} nie istnieje")
    return skill


async def _term_by_id(db: AsyncSession, term_id: int) -> CortexUnmatchedTerm:
    term = await db.get(CortexUnmatchedTerm, term_id)
    if term is None:
        raise CurationError(f"Term {term_id} nie istnieje")
    return term


async def _other_skill_named(
    db: AsyncSession, name_lc: str, *, exclude_skill_id: Optional[int] = None
) -> Optional[Skill]:
    query = select(Skill).where(func.lower(Skill.canonical_name) == name_lc)
    if exclude_skill_id is not None:
        query = query.where(Skill.id != exclude_skill_id)
    return await db.scalar(query.limit(1))


async def _alias_owner(db: AsyncSession, alias_lc: str) -> Optional[Skill]:
    return await db.scalar(
        select(Skill)
        .join(SkillAlias, SkillAlias.skill_id == Skill.id)
        .where(func.lower(SkillAlias.alias) == alias_lc)
        .limit(1)
    )


async def _add_alias(db: AsyncSession, skill_id: int, alias: str) -> bool:
    """Dodaj alias (lowercase) do skilla. Zwraca True jeśli wstawiono nowy,
    False jeśli ten skill już go ma.

    Runda 9 (R9-N13-3): alias równy nazwie INNEJ umiejętności albo należący do
    innej umiejętności to konflikt (409), nie ciche pominięcie. Mapa aliasów
    scoringu (``refresh_alias_map``) daje aliasowi pierwszeństwo przed nazwą
    kanoniczną, więc alias „java” dopisany do JavaScriptu przepinał Javę
    w całym dopasowaniu."""
    alias_lc = alias.strip().lower()
    if not alias_lc:
        raise CurationError("Alias nie może być pusty")
    target = await _skill_by_id(db, skill_id)
    if is_role(target.category):
        raise CurationError(
            f"„{target.canonical_name}” to rola, nie umiejętność — rola nie przyjmuje aliasów."
        )
    named = await _other_skill_named(db, alias_lc, exclude_skill_id=skill_id)
    if named is not None:
        raise CurationConflict(
            f"„{alias_lc}” to nazwa innej umiejętności ({named.canonical_name}) "
            "— nie może być aliasem."
        )
    stmt = (
        pg_insert(SkillAlias)
        .values(skill_id=skill_id, alias=alias_lc)
        .on_conflict_do_nothing(index_elements=["alias"])
        .returning(SkillAlias.id)
    )
    if (await db.execute(stmt)).scalar() is not None:
        return True
    owner = await _alias_owner(db, alias_lc)
    if owner is not None and owner.id != skill_id:
        raise CurationConflict(
            f"Alias „{alias_lc}” należy już do umiejętności {owner.canonical_name}."
        )
    return False


async def map_term_to_skill(
    db: AsyncSession, term_id: int, skill_id: int, *, curated_by: Optional[str]
) -> dict:
    """Zmapuj unmatched term na istniejący skill (dodaj jako alias) + status mapped.

    Fakty dla kandydatów z tym termem powstaną przy następnym backfillu/sync
    (idempotentnie) — nie re-ekstrahujemy tu synchronicznie."""
    term = await _term_by_id(db, term_id)
    await _skill_by_id(db, skill_id)
    await _add_alias(db, skill_id, term.term)
    term.status = "mapped"
    term.curated_by = curated_by
    term.curated_at = func.now()
    await db.commit()
    await after_dictionary_change(db, [skill_id])
    return {"term": term.term, "status": "mapped", "skill_id": skill_id}


async def ignore_term(
    db: AsyncSession, term_id: int, *, curated_by: Optional[str]
) -> dict:
    term = await _term_by_id(db, term_id)
    term.status = "ignored"
    term.curated_by = curated_by
    term.curated_at = func.now()
    await db.commit()
    return {"term": term.term, "status": "ignored"}


async def create_skill(
    db: AsyncSession,
    *,
    canonical_name: str,
    category: Optional[str] = None,
    aliases: Optional[list[str]] = None,
    curated_by: Optional[str] = None,
    from_term_id: Optional[int] = None,
) -> dict:
    """Utwórz nowy canonical skill (case-insensitive dedup) + opcjonalne aliasy.

    Jeśli ``from_term_id`` podany — oznacz ten unmatched term jako mapped i dodaj
    go jako alias nowego skilla."""
    skill_id, name = await create_skill_rows(
        db, canonical_name=canonical_name, category=category, aliases=aliases
    )

    term_note = None
    if from_term_id is not None:
        term = await _term_by_id(db, from_term_id)
        await _add_alias(db, skill_id, term.term)
        term.status = "mapped"
        term.curated_by = curated_by
        term.curated_at = func.now()
        term_note = term.term

    await db.commit()
    await after_dictionary_change(db, [skill_id])
    return {"id": skill_id, "canonical_name": name, "mapped_term": term_note}


async def create_skill_rows(
    db: AsyncSession,
    *,
    canonical_name: str,
    category: Optional[str] = None,
    aliases: Optional[list[str]] = None,
) -> tuple[int, str]:
    """Nowa umiejętność z aliasami BEZ commita i odświeżenia mapy.

    Dla wołających, którzy zapisują kilka zmian w jednej transakcji
    (propozycje do słownika, „Zatwierdź pewne”) i odświeżają mapę raz."""
    name = canonical_name.strip()
    if not name:
        raise CurationError("Nazwa kanoniczna nie może być pusta")

    existing = await db.scalar(
        select(Skill).where(func.lower(Skill.canonical_name) == name.lower())
    )
    if existing is not None:
        raise CurationError(f"Skill o nazwie '{name}' już istnieje (id={existing.id})")
    # Runda 9 (R9-N13-3): nazwa równa istniejącemu aliasowi dawała umiejętność
    # nieosiągalną — mapa scoringu kieruje ten tekst na właściciela aliasu.
    alias_owner = await _alias_owner(db, name.lower())
    if alias_owner is not None:
        raise CurationConflict(
            f"„{name}” jest już aliasem umiejętności {alias_owner.canonical_name}."
        )

    skill = Skill(canonical_name=name, category=category)
    db.add(skill)
    await db.flush()
    skill_id = skill.id

    for alias in aliases or []:
        await _add_alias(db, skill_id, alias)
    return skill_id, name


async def add_alias(
    db: AsyncSession, skill_id: int, alias: str, *, curated_by: Optional[str] = None
) -> dict:
    await _skill_by_id(db, skill_id)
    inserted = await _add_alias(db, skill_id, alias)
    await db.commit()
    await after_dictionary_change(db, [skill_id])
    return {"skill_id": skill_id, "alias": alias.strip().lower(), "inserted": inserted}


async def add_alias_rows(db: AsyncSession, skill_id: int, aliases: list[str]) -> int:
    """Kilka aliasów naraz BEZ commita; zwraca liczbę nowych.

    Nazwa równa nazwie samej umiejętności jest pomijana (nie jest wariantem)."""
    skill = await _skill_by_id(db, skill_id)
    inserted = 0
    for alias in aliases:
        if alias.strip().lower() == skill.canonical_name.strip().lower():
            continue
        if await _add_alias(db, skill_id, alias):
            inserted += 1
    return inserted


async def add_aliases(
    db: AsyncSession,
    skill_id: int,
    aliases: list[str],
    *,
    curated_by: Optional[str] = None,
) -> dict:
    """Kilka aliasów jednej umiejętności w jednej transakcji, mapa odświeżona raz.

    Konflikt któregokolwiek aliasu (należy do innej umiejętności) cofa całość."""
    inserted = await add_alias_rows(db, skill_id, aliases)
    await db.commit()
    await after_dictionary_change(db, [skill_id])
    return {"skill_id": skill_id, "inserted": inserted}


async def update_skill(
    db: AsyncSession,
    skill_id: int,
    *,
    canonical_name: Optional[str] = None,
    category: Optional[str] = None,
) -> dict:
    """Popraw nazwę albo kategorię hasła (etap 2, np. „nosql” → „NoSQL”).

    Stara nazwa zostaje aliasem, gdy zmienia się coś więcej niż wielkość liter
    — inaczej profile i wymagania z tym zapisem przestałyby trafiać w hasło.
    Rola zachowuje swoją kategorię roli albo przechodzi na kategorię z listy."""
    skill = await _skill_by_id(db, skill_id)
    old_name = skill.canonical_name
    if category is not None and category != skill.category:
        skill.category = await _check_category(db, category)
    keep_old = False
    if canonical_name is not None:
        name = " ".join(canonical_name.split())
        if not name:
            raise CurationError("Nazwa kanoniczna nie może być pusta")
        if name.lower() != old_name.lower():
            other = await _other_skill_named(
                db, name.lower(), exclude_skill_id=skill_id
            )
            if other is not None:
                raise CurationConflict(f"Hasło „{other.canonical_name}” już istnieje.")
            owner = await _alias_owner(db, name.lower())
            if owner is not None and owner.id != skill_id:
                raise CurationConflict(
                    f"„{name}” jest już aliasem umiejętności {owner.canonical_name}."
                )
            keep_old = not is_role(skill.category)
        skill.canonical_name = name
    await db.flush()
    if keep_old:
        await _add_alias(db, skill_id, old_name)
    await db.commit()
    count = await after_dictionary_change(db, [skill_id], extra_forms=[old_name])
    return {
        "id": skill_id,
        "canonical_name": skill.canonical_name,
        "category": skill.category,
        "jobs_rescored": count,
    }
