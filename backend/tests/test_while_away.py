"""„Gdy Cię nie było” — podsumowanie pracy z nieobecności (16.11.2026).

Bez bazy: co trafia do spraw do załatwienia, jak liczy się reszta, kto może
oznaczyć sprawę jako załatwioną.
"""

from datetime import date, datetime, timezone
from types import SimpleNamespace

import pytest

from app.models.notification import NotificationType as T
from app.services import while_away
from app.services.while_away import AwayRow

OWNER = 140
SUBSTITUTE = 91


def _row(
    row_id: int,
    ntype: T,
    when: datetime,
    *,
    handled: bool = False,
    substitute: int = SUBSTITUTE,
) -> AwayRow:
    return AwayRow(
        id=row_id,
        notification_type=ntype,
        title="t",
        message="m",
        link=None,
        created_at=when,
        substitute_id=substitute,
        seen_by_substitute=True,
        handled_at=when if handled else None,
        handled_by_id=SUBSTITUTE if handled else None,
    )


def test_nothing_from_absence_means_no_section() -> None:
    assert while_away.summarize([]) is None


def test_closures_go_on_top_and_the_rest_is_counted() -> None:
    rows = [
        _row(
            1,
            T.job_closed_people_waiting,
            datetime(2026, 11, 10, 8, 24, tzinfo=timezone.utc),
        ),
        _row(2, T.stage_rule, datetime(2026, 11, 10, 8, 24, tzinfo=timezone.utc)),
        _row(3, T.stage_rule, datetime(2026, 11, 13, 16, 0, tzinfo=timezone.utc)),
        _row(4, T.new_application, datetime(2026, 11, 12, 12, 1, tzinfo=timezone.utc)),
        _row(
            5,
            T.job_closed_people_waiting,
            datetime(2026, 11, 13, 16, 0, tzinfo=timezone.utc),
        ),
    ]
    summary = while_away.summarize(rows)
    assert summary is not None
    assert [row.id for row in summary.actions] == [5, 1]
    assert summary.total == 5
    assert sum(group.count for group in summary.others) == 3
    assert ("Ruchy kandydatów", 2) in [(g.label, g.count) for g in summary.others]


def test_parked_recruiter_is_not_called_a_mention() -> None:
    """Kategoria dzwonka nazywa zejście z P1 „Wzmianką” — w podsumowaniu nie."""
    when = datetime(2026, 11, 10, 8, 40, tzinfo=timezone.utc)
    summary = while_away.summarize([_row(1, T.recruiter_parked, when)])
    assert summary is not None
    assert [(g.label, g.count) for g in summary.others] == [("Zejścia z P1", 1)]
    assert summary.substitute_ids == (SUBSTITUTE,)


def test_handled_closure_drops_below_open_ones() -> None:
    rows = [
        _row(
            1,
            T.job_closed_people_waiting,
            datetime(2026, 11, 13, 16, 3, tzinfo=timezone.utc),
            handled=True,
        ),
        _row(
            2,
            T.job_closed_people_waiting,
            datetime(2026, 11, 10, 8, 24, tzinfo=timezone.utc),
        ),
    ]
    summary = while_away.summarize(rows)
    assert summary is not None
    assert [row.id for row in summary.actions] == [2, 1]


def test_period_is_counted_in_the_company_calendar() -> None:
    """23:30 UTC 12.11 to już 13.11 w Warszawie."""
    rows = [
        _row(1, T.stage_rule, datetime(2026, 11, 9, 7, 0, tzinfo=timezone.utc)),
        _row(2, T.stage_rule, datetime(2026, 11, 12, 23, 30, tzinfo=timezone.utc)),
    ]
    summary = while_away.summarize(rows)
    assert summary is not None
    assert (summary.since, summary.until) == (date(2026, 11, 9), date(2026, 11, 13))


class _Db:
    def __init__(self, note: object) -> None:
        self.note = note

    async def get(self, _model: object, _id: int) -> object:
        return self.note


def _note(*, on_behalf_of: int | None = OWNER) -> SimpleNamespace:
    return SimpleNamespace(
        user_id=SUBSTITUTE,
        on_behalf_of_user_id=on_behalf_of,
        handled_at=None,
        handled_by_user_id=None,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("actor", [OWNER, SUBSTITUTE])
async def test_owner_or_substitute_can_mark_handled(actor: int) -> None:
    note = _note()
    assert await while_away.mark_handled(_Db(note), 1, actor_id=actor) is note
    assert note.handled_by_user_id == actor
    assert note.handled_at is not None


@pytest.mark.asyncio
async def test_someone_else_cannot_mark_handled() -> None:
    note = _note()
    assert await while_away.mark_handled(_Db(note), 1, actor_id=7) is None
    assert note.handled_at is None


@pytest.mark.asyncio
async def test_own_row_without_substitution_is_not_an_away_case() -> None:
    assert (
        await while_away.mark_handled(
            _Db(_note(on_behalf_of=None)), 1, actor_id=SUBSTITUTE
        )
        is None
    )
