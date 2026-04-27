"""Parser @mention'ów dla Job Chat.

Wspiera dwie składnie:
    @user@example.com   — adres email (preferowane, jednoznaczne)
    @123                — user_id (zarezerwowane na future autocomplete)

Zwraca tylko user_ids które są aktualnymi członkami projektu — to chroni
przed mention'owaniem osób spoza zespołu (np. byli pracownicy lub klienci).
"""

import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.services.job_membership import filter_to_members

# @email + @userId.  Email regex z note: dopuszcza znaki specjalne typowe
# w korporacyjnych adresach (kropka, plus, myślnik).
_EMAIL_RE = re.compile(r"@([A-Za-z0-9._+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,})")
_USERID_RE = re.compile(r"@(\d+)\b")


async def parse_mentions(
    db: AsyncSession, content: str, job_id: int
) -> list[int]:
    """Zwraca posortowaną listę user_id dla wszystkich rozpoznanych @mention'ów,
    przefiltrowaną do członków danego projektu (deduplicated).
    """
    if not content:
        return []

    raw_emails = _EMAIL_RE.findall(content)
    raw_user_ids = _USERID_RE.findall(content)

    candidate_ids: set[int] = set()

    if raw_emails:
        rows = await db.execute(
            select(User.id, User.email).where(
                User.email.in_([e.lower() for e in raw_emails])
            )
        )
        for uid, _email in rows.all():
            candidate_ids.add(uid)

    for sid in raw_user_ids:
        try:
            candidate_ids.add(int(sid))
        except ValueError:
            continue

    if not candidate_ids:
        return []

    members = await filter_to_members(db, job_id, candidate_ids)
    return sorted(set(members))
