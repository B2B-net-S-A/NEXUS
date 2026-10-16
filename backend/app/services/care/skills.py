"""Technologie karty = słownik umiejętności NEXUSA (``skills`` + aliasy).

Decyzja D7 (16.10.2026): jeden słownik dla wymagań rekrutacji, profili
kandydatów i mapy klienta. Compass miał własny (270 pozycji), do którego każdy
dopisywał „niezweryfikowane” nazwy. Tu nazwa wpisana tekstem:

* trafia w nazwę kanoniczną albo alias → karta dostaje tę umiejętność,
* nie trafia → wiersz ``skill_review_queue`` (jeden na nazwę), a karta trzyma
  tekst w ``unrecognized_skills`` do czasu decyzji: „zmapuj na istniejącą”
  (alias), „dodaj do słownika” albo „odrzuć” (tekst zostaje na karcie).

Decyzje w kolejce zmieniają słownik całej aplikacji (alias działa od razu
w wyszukiwaniu i dopasowaniu), więc podejmują je ci sami ludzie, którzy
prowadzą „Słownik umiejętności” (admin, Head of Recruitment) — przez
``skill_curation``, z tymi samymi kontrolami konfliktów.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.contract_care import SkillReviewItem, TechCard, TechCardSkill
from app.models.skill import Skill, SkillAlias
from app.services import skill_curation
from app.services.contract_care_schema import NAME_MAX

_SPACES = re.compile(r"\s+")


def name_key(raw: str) -> str:
    """Klucz nazwy: bez wielkości liter i podwójnych spacji."""

    return _SPACES.sub(" ", (raw or "").strip()).lower()[:NAME_MAX]


def display_name(canonical: str, raw_forms: Iterable[str] = ()) -> str:
    """Nazwa do pokazania: najczęstszy zapis ze źródeł, inaczej z wielkiej litery."""

    counts: dict[str, int] = {}
    for form in raw_forms:
        cleaned = _SPACES.sub(" ", (form or "").strip())
        if (
            cleaned
            and cleaned.lower() == canonical.lower()
            and cleaned != cleaned.lower()
        ):
            counts[cleaned] = counts.get(cleaned, 0) + 1
    if counts:
        return max(counts.items(), key=lambda item: (item[1], item[0]))[0]
    if canonical and canonical == canonical.lower() and canonical[:1].isalpha():
        return canonical[:1].upper() + canonical[1:]
    return canonical


@dataclass(frozen=True)
class SkillDictionary:
    """Słownik w pamięci jednego żądania: nazwa/alias → id oraz id → nazwa."""

    by_key: dict[str, int]
    names: dict[int, str]
    categories: dict[int, Optional[str]]

    def resolve(self, raw: str) -> Optional[int]:
        return self.by_key.get(name_key(raw))


async def load_dictionary(db: AsyncSession) -> SkillDictionary:
    by_key: dict[str, int] = {}
    names: dict[int, str] = {}
    categories: dict[int, Optional[str]] = {}
    for skill_id, canonical, category in (
        await db.execute(select(Skill.id, Skill.canonical_name, Skill.category))
    ).all():
        names[skill_id] = canonical
        categories[skill_id] = category
        by_key[name_key(canonical)] = skill_id
    # Alias ma pierwszeństwo przed nazwą kanoniczną — tak samo jak mapa
    # scoringu (``skill_taxonomy_loader``), żeby karta i wyszukiwanie
    # rozumiały tę samą nazwę tak samo.
    for skill_id, alias in (
        await db.execute(select(SkillAlias.skill_id, SkillAlias.alias))
    ).all():
        by_key[name_key(alias)] = skill_id
    return SkillDictionary(by_key=by_key, names=names, categories=categories)


async def existing_skill_ids(db: AsyncSession, skill_ids: Iterable[int]) -> set[int]:
    ids = sorted(set(skill_ids))
    if not ids:
        return set()
    return set((await db.scalars(select(Skill.id).where(Skill.id.in_(ids)))).all())


@dataclass(frozen=True)
class ResolvedNames:
    skill_ids: set[int]
    unrecognized: list[str]


async def resolve_card_names(
    db: AsyncSession,
    names: Iterable[str],
    *,
    previous_unrecognized: Iterable[str],
    actor_id: Optional[int],
) -> ResolvedNames:
    """Nazwy wpisane na karcie → umiejętności ze słownika i nazwy do przejrzenia.

    Licznik ``occurrences`` rośnie tylko, gdy nazwa jest na tej karcie nowa
    (ponowny zapis karty nie nabija wystąpień).
    """

    dictionary = await load_dictionary(db)
    already = {name_key(value) for value in previous_unrecognized}
    skill_ids: set[int] = set()
    unrecognized: list[str] = []
    seen: set[str] = set()
    for raw in names:
        key = name_key(raw)
        if not key or key in seen:
            continue
        seen.add(key)
        known = dictionary.by_key.get(key)
        if known is not None:
            skill_ids.add(known)
            continue
        display = _SPACES.sub(" ", raw.strip())[:NAME_MAX]
        if key in already:
            row = await db.scalar(
                select(SkillReviewItem).where(SkillReviewItem.name_key == key)
            )
        else:
            statement = insert(SkillReviewItem).values(
                name=display,
                name_key=key,
                status="open",
                occurrences=1,
                reported_by=actor_id,
            )
            statement = statement.on_conflict_do_update(
                index_elements=[SkillReviewItem.name_key],
                set_={
                    "occurrences": SkillReviewItem.occurrences + 1,
                    "updated_at": func.now(),
                },
            ).returning(SkillReviewItem.id)
            review_id = (await db.execute(statement)).scalar_one()
            row = await db.get(SkillReviewItem, review_id)
        if (
            row is not None
            and row.skill_id is not None
            and row.status in {"mapped", "created"}
        ):
            skill_ids.add(row.skill_id)
        else:
            unrecognized.append(key)
    return ResolvedNames(skill_ids=skill_ids, unrecognized=unrecognized)


class ReviewError(Exception):
    """Błąd decyzji w kolejce (422 albo 409 w API)."""

    def __init__(self, message: str, *, conflict: bool = False) -> None:
        super().__init__(message)
        self.conflict = conflict


async def _link_cards(db: AsyncSession, key: str, skill_id: int) -> set[int]:
    """Karty z tą nazwą dostają umiejętność; zwraca klientów do odświeżenia mapy."""

    cards = (
        await db.scalars(
            select(TechCard).where(TechCard.unrecognized_skills.contains([key]))
        )
    ).all()
    clients: set[int] = set()
    for card in cards:
        await db.execute(
            insert(TechCardSkill)
            .values(card_id=card.id, skill_id=skill_id)
            .on_conflict_do_nothing()
        )
        card.unrecognized_skills = [
            value for value in (card.unrecognized_skills or []) if value != key
        ]
        clients.add(card.client_id)
    return clients


async def _open_item(db: AsyncSession, review_id: int) -> SkillReviewItem:
    item = await db.get(SkillReviewItem, review_id, with_for_update=True)
    if item is None:
        raise ReviewError("Nie ma takiej pozycji do przejrzenia.")
    if item.status in {"mapped", "created"}:
        raise ReviewError("Ta nazwa ma już decyzję.", conflict=True)
    return item


async def map_to_skill(
    db: AsyncSession, review_id: int, skill_id: int, *, actor_id: int, now: datetime
) -> set[int]:
    """Nazwa staje się aliasem istniejącej umiejętności (commit w ``skill_curation``)."""

    item = await _open_item(db, review_id)
    if await db.get(Skill, skill_id) is None:
        raise ReviewError("Nie ma takiej umiejętności w słowniku.")
    item.status = "mapped"
    item.skill_id = skill_id
    item.resolved_by = actor_id
    item.resolved_at = now
    clients = await _link_cards(db, item.name_key, skill_id)
    try:
        await skill_curation.add_alias(db, skill_id, item.name_key)
    except skill_curation.CurationConflict as exc:
        raise ReviewError(str(exc), conflict=True) from exc
    except skill_curation.CurationError as exc:
        raise ReviewError(str(exc)) from exc
    return clients


async def create_skill(
    db: AsyncSession,
    review_id: int,
    *,
    canonical_name: str,
    category: Optional[str],
    actor_id: int,
    now: datetime,
) -> set[int]:
    """Nowa umiejętność w słowniku (z nazwą z kolejki jako aliasem, jeśli inna)."""

    item = await _open_item(db, review_id)
    name = canonical_name.strip()
    aliases = [item.name_key] if name_key(name) != item.name_key else []
    try:
        created = await skill_curation.create_skill(
            db, canonical_name=name, category=category, aliases=aliases
        )
    except skill_curation.CurationConflict as exc:
        raise ReviewError(str(exc), conflict=True) from exc
    except skill_curation.CurationError as exc:
        raise ReviewError(str(exc), conflict=True) from exc
    # ``create_skill`` zrobił commit — pozycję czytamy na nowo.
    item = await db.get(SkillReviewItem, review_id, populate_existing=True)
    item.status = "created"
    item.skill_id = int(created["id"])
    item.resolved_by = actor_id
    item.resolved_at = now
    return await _link_cards(db, item.name_key, item.skill_id)


async def dismiss(
    db: AsyncSession, review_id: int, *, actor_id: int, now: datetime
) -> None:
    """Nazwa zostaje tekstem na kartach i nie wraca do kolejki."""

    item = await _open_item(db, review_id)
    item.status = "dismissed"
    item.resolved_by = actor_id
    item.resolved_at = now
