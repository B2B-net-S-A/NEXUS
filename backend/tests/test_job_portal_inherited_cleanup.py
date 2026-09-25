"""Sprzątanie po niepewnej publikacji przechodzi na nową publikację (bez bazy).

Audyt 25.09.2026, runda 2: `_cancel_stale_cleanup` anuluje zaległe zamknięcie
wiersza `failed` przy nowej publikacji tej pary. Nowy wiersz dziedziczy wtedy
sprzątanie — wycofany przed workerem albo odrzucony pewną odmową nie może
porzucić ogłoszenia, które mogło powstać w poprzedniej próbie.
"""

from __future__ import annotations

from app.models.job_posting import JobPosting, Portal, PostingStatus
from app.services.job_portals import service


def _fresh(*, inherited: bool) -> JobPosting:
    return JobPosting(
        job_id=1,
        portal=Portal.rocketjobs,
        status=PostingStatus.publishing,
        attempts=0,
        pending_action=service.ACTION_PUBLISH,
        remote_state=service._INHERITED_CLEANUP if inherited else None,  # noqa: SLF001
    )


def test_never_sent_posting_is_dropped_without_inherited_cleanup() -> None:
    posting = _fresh(inherited=False)
    service._close_or_drop(posting)  # noqa: SLF001
    assert posting.status == PostingStatus.removed
    assert posting.pending_action is None


def test_never_sent_posting_with_inherited_cleanup_queues_close() -> None:
    posting = _fresh(inherited=True)
    service._close_or_drop(posting)  # noqa: SLF001
    assert posting.status == PostingStatus.publishing
    assert posting.pending_action == service.ACTION_CLOSE


def test_certain_refusal_keeps_inherited_cleanup() -> None:
    posting = _fresh(inherited=True)
    service._give_up(posting, service.ACTION_PUBLISH, "Brak kodów")  # noqa: SLF001
    assert posting.status == PostingStatus.failed
    assert posting.pending_action == service.ACTION_CLOSE


def test_certain_refusal_without_inheritance_does_not_queue_cleanup() -> None:
    posting = _fresh(inherited=False)
    service._give_up(posting, service.ACTION_PUBLISH, "Brak kodów")  # noqa: SLF001
    assert posting.status == PostingStatus.failed
    assert posting.pending_action is None
