"""Uchwały Rady w trybie pisemnym (R6): skład, wynik, dzwonki.

Reguły z projektu statutu (akt NWZ z 16.09.2025, § 25) — do potwierdzenia
z tekstem przyjętym 24.11.2025 (Rep. A 8533/2025):

* ust. 4 — ważna, gdy projekt dostali **wszyscy** członkowie Rady (skład
  zapisany w chwili wysłania, każdy dostaje dzwonek) i głosowała co najmniej
  **połowa** członków,
* ust. 1 — **zwykła większość głosów oddanych** (więcej „za” niż „przeciw”;
  wstrzymujący się nie przesądzają), przy **remisie** rozstrzyga głos
  Przewodniczącego,
* ust. 5 — wybór Przewodniczącego / Wiceprzewodniczącego Rady oraz
  powołanie, odwołanie i zawieszenie członka Zarządu nie idą tym trybem
  (admin potwierdza to przy wysyłce; NEXUS nie zgaduje treści uchwały).

Członek Rady = aktywne konto z rolą ``board`` (główną albo dodatkową).
"""

from __future__ import annotations

from dataclasses import dataclass
from math import ceil
from typing import Any, Iterable, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.notification import NotificationType
from app.models.user import User, UserRole
from app.services.board.notify import recipient_ids
from app.services.hr.notify import notify_each

LINK = "/rada?tab=uchwaly"
EXCLUDED_MATTERS = (
    "wybór Przewodniczącego albo Wiceprzewodniczącego Rady",
    "powołanie członka Zarządu",
    "odwołanie albo zawieszenie członka Zarządu",
)


@dataclass(frozen=True)
class Tally:
    members: int
    voted: int
    votes_for: int
    against: int
    abstain: int
    quorum: int
    quorum_met: bool
    tie_broken_by_chair: bool
    passed: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "members": self.members,
            "voted": self.voted,
            "for": self.votes_for,
            "against": self.against,
            "abstain": self.abstain,
            "quorum": self.quorum,
            "quorum_met": self.quorum_met,
            "tie_broken_by_chair": self.tie_broken_by_chair,
            "passed": self.passed,
        }


def tally(
    member_ids: Iterable[int],
    ballots: dict[int, str],
    chair_user_id: Optional[int],
) -> Tally:
    """Wynik z głosów członków ze składu (głos spoza składu się nie liczy)."""

    members = list(dict.fromkeys(member_ids))
    counted = {uid: choice for uid, choice in ballots.items() if uid in members}
    votes_for = sum(1 for c in counted.values() if c == "for")
    against = sum(1 for c in counted.values() if c == "against")
    abstain = sum(1 for c in counted.values() if c == "abstain")
    quorum = ceil(len(members) / 2) if members else 1
    quorum_met = len(counted) >= quorum and len(members) > 0
    tie = votes_for == against and votes_for > 0
    chair_choice = counted.get(chair_user_id) if chair_user_id is not None else None
    if votes_for > against:
        majority = True
    elif tie and chair_choice in ("for", "against"):
        majority = chair_choice == "for"
    else:
        majority = False
    return Tally(
        members=len(members),
        voted=len(counted),
        votes_for=votes_for,
        against=against,
        abstain=abstain,
        quorum=quorum,
        quorum_met=quorum_met,
        tie_broken_by_chair=tie and chair_choice in ("for", "against"),
        passed=quorum_met and majority,
    )


async def board_member_ids(db: AsyncSession) -> list[int]:
    users = await db.scalars(
        select(User).where(User.is_active.is_(True)).order_by(User.id)
    )
    return [user.id for user in users if user.has_role(UserRole.board)]


async def board_members(db: AsyncSession, ids: list[int]) -> list[dict[str, Any]]:
    if not ids:
        return []
    users = await db.scalars(select(User).where(User.id.in_(ids)))
    names = {user.id: user.name or user.email for user in users}
    return [{"id": uid, "name": names.get(uid, f"#{uid}")} for uid in ids]


async def notify_opened(db: AsyncSession, vote: Any) -> int:
    day = vote.deadline.strftime("%d.%m.%Y")
    return await notify_each(
        db,
        vote.member_ids,
        title=f"Uchwała Rady do głosowania: {vote.title}",
        message=f"Tryb pisemny (§ 25 ust. 4 statutu). Głos do {day} w NEXUSIE.",
        ntype=NotificationType.board_vote,
        link=f"{LINK}&uchwala={vote.id}",
        related_entity_type="board_vote",
        related_entity_id=vote.id,
        log_tag="board",
    )


async def notify_closed(db: AsyncSession, vote: Any, result: Tally) -> int:
    verdict = "podjęta" if result.passed else "niepodjęta"
    return await notify_each(
        db,
        await recipient_ids(db),
        title=f"Uchwała Rady {verdict}: {vote.title}",
        message=(
            f"Za {result.votes_for}, przeciw {result.against}, wstrzymało się "
            f"{result.abstain}; głosowało {result.voted} z {result.members}."
        ),
        ntype=NotificationType.board_vote,
        link=f"{LINK}&uchwala={vote.id}",
        related_entity_type="board_vote",
        related_entity_id=vote.id,
        log_tag="board",
        fresh=True,  # ten sam dzień i ta sama uchwała co dzwonek o projekcie
    )
