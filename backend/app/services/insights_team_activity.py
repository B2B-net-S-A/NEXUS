"""Ranking aktywności zespołu — jedna implementacja dla dwóch powierzchni.

Moduł powstał, bo `/api/activities/leaderboard` (capability
``VIEW_RECRUITMENT_RANKING``) i nowy `/api/insights/recruitment/team-activity`
(D7: każdy zalogowany) muszą pokazywać TE SAME liczby. Jedynym sposobem na to
jest jedno zapytanie, nie dwa podobne — kopia SQL rozjeżdża się cicho, bo obie
odpowiedzi wyglądają wiarygodnie i nikt ich obok siebie nie kładzie.

Trzy rzeczy, które ten moduł ŚWIADOMIE zostawia routerom:

1. **Guard.** ``capabilities.py`` steruje 40+ innymi powierzchniami; jego
   poszerzenie otworzyłoby imienne rankingi wszędzie tam, gdzie nikt na to nie
   dawał zgody. Dlatego bramka zostaje w routerze, a tutaj jest wyłącznie
   liczenie.

2. **Górna granica okna.** ``until=None`` odtwarza kroczące okno legacy
   (``now - 30 dni`` BEZ sufitu), a ``until=period.end`` daje półotwarte
   ``[start, end)`` z ``resolve_period``. Gdyby serwis narzucił jedną z tych
   semantyk, druga powierzchnia zmieniłaby liczby bez zmiany kodu u siebie.

3. **Procenty.** Legacy liczy je ``_safe_pct`` (zero przy zerowym mianowniku),
   Insights ``_ratio`` (``None``). Serwis zwraca WYŁĄCZNIE surowe liczniki,
   więc żadna z tych konwencji nie wycieka do drugiej powierzchni.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.models.user_activity import UserActionType, UserActivity

__all__ = ["TeamActivityRow", "compute_team_activity"]


@dataclass(frozen=True)
class TeamActivityRow:
    """Jeden wiersz rankingu — liczniki bez żadnej pochodnej."""

    user_id: int
    user_name: str
    candidates_added: int
    screenings: int
    interviews: int
    placements: int
    calls: int
    total_actions: int


def _sum_of(action: UserActionType):
    return func.sum(case((UserActivity.action_type == action, 1), else_=0))


async def compute_team_activity(
    db: AsyncSession,
    *,
    since: datetime,
    until: datetime | None = None,
    limit: int,
) -> list[TeamActivityRow]:
    """Ranking aktywności per użytkownik, malejąco po sumie akcji.

    Args:
        since: dolna granica okna (włącznie).
        until: górna granica WYŁĄCZNIE (półotwarte ``[since, until)``).
            ``None`` = brak sufitu, czyli kroczące okno legacy. To NIE jest
            szczegół techniczny: bez górnej granicy „poprzedni miesiąc" znaczy
            w praktyce „od poprzedniego miesiąca do dziś".
        limit: ilu użytkowników zwrócić.
    """
    window = [UserActivity.created_at >= since]
    if until is not None:
        window.append(UserActivity.created_at < until)

    per_user = (
        select(
            UserActivity.user_id,
            _sum_of(UserActionType.candidate_added).label("candidates_added"),
            _sum_of(UserActionType.screening_done).label("screenings"),
            _sum_of(UserActionType.interview_scheduled).label("interviews"),
            _sum_of(UserActionType.placement_closed).label("placements"),
            _sum_of(UserActionType.call_made).label("calls"),
            func.count(UserActivity.id).label("total_actions"),
        )
        .where(*window)
        .group_by(UserActivity.user_id)
        .subquery()
    )

    rows = (
        await db.execute(
            select(User.id, User.name, per_user)
            .join(per_user, User.id == per_user.c.user_id)
            .order_by(per_user.c.total_actions.desc())
            .limit(limit)
        )
    ).all()

    return [
        TeamActivityRow(
            user_id=int(r.id),
            user_name=r.name,
            candidates_added=int(r.candidates_added or 0),
            screenings=int(r.screenings or 0),
            interviews=int(r.interviews or 0),
            placements=int(r.placements or 0),
            calls=int(r.calls or 0),
            total_actions=int(r.total_actions or 0),
        )
        for r in rows
    ]
