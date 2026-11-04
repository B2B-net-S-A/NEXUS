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
    db: AsyncSession, content: str, section: ProductSection | None
) -> list[int]:
    candidate_ids = await _extract_candidate_user_ids(db, content)
    users = await mentionable_users(db, section=section, user_ids=candidate_ids)
    return sorted({user.id for user in users})


async def parse_mentions(db: AsyncSession, content: str, job_id: int) -> list[int]:
    """Wzmianki w czacie i notatce rekrutacji — każda osoba z odczytem
    rekrutacji, nie tylko jej zespół (`job_id` zostaje w sygnaturze dla
    wołających; zakres nie zależy już od konkretnej rekrutacji)."""
    return await _mentioned_ids(db, content, ProductSection.pipeline)


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
    "mentionable_users",
    "parse_mentions",
    "parse_mentions_candidate",
    "parse_mentions_global",
]
