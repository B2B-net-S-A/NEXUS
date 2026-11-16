"""Parser @mention'ów dla Job Chat, Candidate Chat i notatek.

Składnia: ``@user@example.com`` — adres e-mail (to wstawia autocomplete).

Runda 10 (R10-N6-4): składnia ``@<liczba>`` usunięta — nikt jej nie wstawiał,
a „spotkanie @10:00” oznaczało użytkownika nr 10 (powiadomienie + mail
z fragmentem notatki).

Oznaczyć można każdą osobę, która może przeczytać to, w czym ją oznaczono
(08.10.2026). Od 23.09.2026 rekrutacje, notatki i czaty czyta każda rola
wewnętrzna, a wzmianki zostały przy starej regule „tylko zespół rekrutacji”:
oznaczenie osoby spoza zespołu zapisywało się jako zwykły tekst, bez
powiadomienia. Jedna reguła: `mentionable_users`.

- `parse_mentions(db, content, job_id)` — czat i notatki rekrutacji
- `parse_mentions_candidate(db, content, candidate_id)` — czat kandydata
- `parse_mentions_global(db, content)` — notatki kandydata bez rekrutacji

Wszystkie wracają posortowaną deduplikowaną listę user_id.

`@wszyscy` (13.11.2026, zgłoszenie z czatu rekrutacji): w czacie i notatkach
rekrutacji oznacza osoby przypisane do niej (`list_job_assigned_ids`) — bez
adminów spoza zespołu, uczestników kategorii i poprzednich rekruterów, czyli
nie cały „zespół” z nagłówka czatu. Lista liczona w chwili zapisu; każda
osoba dostaje zwykłą wzmiankę. Poza rekrutacją (czat kandydata, notatka bez
rekrutacji) to zwykły tekst.
"""

import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.candidate_access import user_can_access_candidate_domain
from app.models.user import User
from app.services.section_permissions import (
    ProductSection,
    SectionAccess,
    resolve_effective_section_access_for_users,
    section_access_for_user,
)

# @email. Regex dopuszcza znaki specjalne typowe w korporacyjnych adresach
# (kropka, plus, myślnik).
_EMAIL_RE = re.compile(r"@([A-Za-z0-9._+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,})")

# `@wszyscy` jako osobne słowo: nie część adresu (`biuro@wszyscy.pl`) ani
# początek adresu (`@wszyscy@firma.pl`). Ten sam wzorzec co na froncie
# (`renderMentions.tsx`).
_EVERYONE_RE = re.compile(r"(?<![\w@.])@wszyscy(?![\w@.\-])", re.IGNORECASE)


def has_everyone_mention(content: str) -> bool:
    """Czy tekst ma `@wszyscy` — wszyscy przypisani do rekrutacji."""
    return bool(_EVERYONE_RE.search(content or ""))


def has_mention(content: str) -> bool:
    """Czy tekst ma składnię wzmianki — bez bazy, także dla adresu spoza zespołu."""
    return bool(_EMAIL_RE.search(content or "")) or has_everyone_mention(content)


async def _assigned_ids(db: AsyncSession, job_id: int) -> list[int]:
    from app.services.job_membership import list_job_assigned_ids  # noqa: PLC0415

    return await list_job_assigned_ids(db, job_id)


async def _extract_candidate_user_ids(db: AsyncSession, content: str) -> set[int]:
    """Resolves adresy e-mail z treści do zbioru user_id.

    NIE filtruje po scope ani aktywności — to zadanie callera.
    """
    if not content:
        return set()

    raw_emails = _EMAIL_RE.findall(content)

    candidate_ids: set[int] = set()

    if raw_emails:
        rows = await db.execute(
            select(User.id).where(User.email.in_([e.lower() for e in raw_emails]))
        )
        for (uid,) in rows.all():
            candidate_ids.add(uid)

    return candidate_ids


async def mentionable_users(
    db: AsyncSession,
    *,
    section: ProductSection | None = None,
    user_ids: set[int] | None = None,
) -> list[User]:
    """Aktywne konta, które wolno oznaczyć: odczyt danych kandydatów i —
    gdy podano — odczyt sekcji, w której leży notatka albo czat."""
    query = select(User).where(User.is_active.is_(True))
    if user_ids is not None:
        if not user_ids:
            return []
        query = query.where(User.id.in_(user_ids))
    users = list((await db.execute(query)).scalars().all())
    await resolve_effective_section_access_for_users(db, users)
    return [
        user
        for user in users
        if user_can_access_candidate_domain(user)
        and (
            section is None
            or section_access_for_user(user, section) >= SectionAccess.read
        )
    ]


async def _mentioned_ids(
    db: AsyncSession,
    content: str,
    section: ProductSection | None,
    *,
    job_id: int | None = None,
) -> list[int]:
    candidate_ids = await _extract_candidate_user_ids(db, content)
    if job_id is not None and has_everyone_mention(content):
        candidate_ids |= set(await _assigned_ids(db, job_id))
    users = await mentionable_users(db, section=section, user_ids=candidate_ids)
    return sorted({user.id for user in users})


async def parse_mentions(db: AsyncSession, content: str, job_id: int) -> list[int]:
    """Wzmianki w czacie i notatce rekrutacji — każda osoba z odczytem
    rekrutacji, nie tylko jej zespół. `job_id` wyznacza, kogo oznacza
    `@wszyscy` (osoby przypisane do tej rekrutacji)."""
    return await _mentioned_ids(db, content, ProductSection.pipeline, job_id=job_id)


async def parse_mentions_candidate(
    db: AsyncSession, content: str, candidate_id: int
) -> list[int]:
    """Wzmianki w czacie kandydata — każda osoba z odczytem kandydatów."""
    return await _mentioned_ids(db, content, ProductSection.sourcing)


async def parse_mentions_global(db: AsyncSession, content: str) -> list[int]:
    """Mentions bez scope projektu/kandydata — np. notatka candidate-only.

    Resolve full User objects and apply the canonical candidate-domain guard:
    primary-role SQL alone misses malformed/historical Finance hybrids and can
    fan candidate snippets out through notification/email/Teams.
    """
    return await _mentioned_ids(db, content, None)


__all__ = [
    "has_everyone_mention",
    "has_mention",
    "mentionable_users",
    "parse_mentions",
    "parse_mentions_candidate",
    "parse_mentions_global",
]
