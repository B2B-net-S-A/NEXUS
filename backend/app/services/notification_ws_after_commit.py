"""Wypchnięcie powiadomienia przez WebSocket dopiero PO commicie.

Runda 9 (R9-N2-5): ``notification_triggers.emit`` (i dwa miejsca, które go
naśladowały — dodanie kandydata i alert zapisanego wyszukiwania) wysyłały
zdarzenie zaraz po ``flush``, a transakcja kończyła się dużo później — pętla
triggerów commituje raz, po WSZYSTKICH triggerach. Dzwonek pokazywał wtedy
powiadomienie, którego nie ma w bazie (rollback = kliknięcie w nieistniejący
wpis), a przy dłuższej transakcji pojawiał się przed zapisem, więc odświeżenie
listy go gubiło.

Teraz zdarzenie trafia do ``session.info`` razem z wierszem ``Notification``
i wychodzi po ``after_commit`` — jak w ``mention_dispatch`` i kalendarzu.
Wiersz, którego zapis został wycofany (savepoint albo cała transakcja),
przestaje być ``persistent`` i jego zdarzenie przepada.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from sqlalchemy import event, inspect
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

_PENDING_KEY = "nexus_pending_ws_notifications"


def queue_ws_notification(db: Any, *, user_id: int, event_payload: dict, row: Any):
    """Zapamiętaj zdarzenie do wysłania po commicie sesji ``db``.

    Zwraca ``False``, gdy ``db`` nie jest prawdziwą sesją SQLAlchemy (atrapa
    w teście) — wołający wysyła wtedy od razu, jak dawniej.
    """
    sync_session = getattr(db, "sync_session", None)
    if not isinstance(sync_session, Session):
        return False
    sync_session.info.setdefault(_PENDING_KEY, []).append(
        (int(user_id), event_payload, row)
    )
    return True


def _row_committed(row: Any) -> bool:
    try:
        return bool(inspect(row).persistent)
    except Exception:  # noqa: BLE001 — obiekt spoza ORM: nie ryzykujemy
        return False


async def _push_all(items: list[tuple[int, dict]]) -> None:
    from app.api import ws as ws_manager

    for user_id, payload in items:
        try:
            await ws_manager.notify_user(user_id, payload)
        except Exception as exc:  # noqa: BLE001 — best-effort, dzwonek i tak odpyta
            logger.warning(
                "WS push failed for user=%s: %s", user_id, type(exc).__name__
            )


@event.listens_for(Session, "after_commit")
def _dispatch_after_commit(session: Session) -> None:
    pending = session.info.pop(_PENDING_KEY, None)
    if not pending:
        return
    items = [(uid, payload) for uid, payload, row in pending if _row_committed(row)]
    if not items:
        return
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return
    from app.core.tasks import spawn

    spawn(_push_all(items), "notification_ws_after_commit")


@event.listens_for(Session, "after_soft_rollback")
def _drop_on_outer_rollback(session: Session, previous_transaction: Any) -> None:
    # ``after_rollback`` odpala się także przy wycofaniu SAVEPOINT-u (dedup
    # w ``emit``), więc nie może czyścić całej kolejki. Wycofanie zewnętrznej
    # transakcji — tak; wycofany savepoint odfiltruje ``_row_committed``.
    if not getattr(previous_transaction, "nested", False):
        session.info.pop(_PENDING_KEY, None)


__all__ = ["queue_ws_notification"]
