"""Parser @mention'ów dla Job Chat, Candidate Chat i notatek.

Wspiera dwie składnie:
    @user@example.com   — adres email (preferowane, jednoznaczne)
    @123                — user_id (zarezerwowane na future autocomplete)

Trzy warianty scope filtrowania:
- `parse_mentions(db, content, job_id)` — tylko members projektu (job chat,
  notatki przy projekcie)
- `parse_mentions_candidate(db, content, candidate_id)` — tylko members chatu
  kandydata (candidate chat)
- `parse_mentions_global(db, content)` — każdy aktywny user z bieżącym
  candidate-domain read access (notatki kandydata bez projektu)

Wszystkie wracają posortowaną deduplikowaną listę user_id.
"""

import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.candidate_access import user_can_access_candidate_domain
from app.models.user import User
from app.services.candidate_membership import filter_to_candidate_members
from app.services.job_membership import filter_to_members

# @email + @userId.  Email regex z note: dopuszcza znaki specjalne typowe
# w korporacyjnych adresach (kropka, plus, myślnik).
_EMAIL_RE = re.compile(r"@([A-Za-z0-9._+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,})")
_USERID_RE = re.compile(r"@(\d+)\b")


async def _extract_candidate_user_ids(db: AsyncSession, content: str) -> set[int]:
    """Resolves emails+user_ids z treści do zbioru user_id.

    NIE filtruje po scope ani aktywności — to zadanie callera.
    """
    if not content:
        return set()

    raw_emails = _EMAIL_RE.findall(content)
    raw_user_ids = _USERID_RE.findall(content)

    candidate_ids: set[int] = set()

    if raw_emails:
        rows = await db.execute(
            select(User.id).where(User.email.in_([e.lower() for e in raw_emails]))
        )
        for (uid,) in rows.all():
            candidate_ids.add(uid)

    for sid in raw_user_ids:
        try:
            candidate_ids.add(int(sid))
        except ValueError:
            continue

    return candidate_ids


async def parse_mentions(db: AsyncSession, content: str, job_id: int) -> list[int]:
    """Mentions w job-scoped contentcie. Filtruje do members projektu.

    Backward-compatible signature — używana w job_chat.py i (po refactor)
    w notes.py gdy notatka ma `job_id`.
    """
    candidate_ids = await _extract_candidate_user_ids(db, content)
    if not candidate_ids:
        return []
    members = await filter_to_members(db, job_id, candidate_ids)
    return sorted(set(members))


async def parse_mentions_candidate(
    db: AsyncSession, content: str, candidate_id: int
) -> list[int]:
    """Mentions w candidate-chat-scoped contentcie. Filtruje do members
    chatu kandydata (kompleksowa logika rola+collab w
    `candidate_membership`)."""
    candidate_ids = await _extract_candidate_user_ids(db, content)
    if not candidate_ids:
        return []
    members = await filter_to_candidate_members(db, candidate_id, candidate_ids)
    return sorted(set(members))


async def parse_mentions_global(db: AsyncSession, content: str) -> list[int]:
    """Mentions bez scope projektu/kandydata — np. notatka candidate-only.

    Resolve full User objects and apply the canonical candidate-domain guard:
    primary-role SQL alone misses malformed/historical Finance hybrids and can
    fan candidate snippets out through notification/email/Teams.
    """
    candidate_ids = await _extract_candidate_user_ids(db, content)
    if not candidate_ids:
        return []
    rows = await db.execute(
        select(User).where(
            User.id.in_(candidate_ids),
            User.is_active.is_(True),
        )
    )
    return sorted(
        {
            user.id
            for user in rows.scalars().all()
            if user_can_access_candidate_domain(user)
        }
    )


__all__ = [
    "parse_mentions",
    "parse_mentions_candidate",
    "parse_mentions_global",
]
