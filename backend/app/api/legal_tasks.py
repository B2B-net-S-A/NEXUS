"""Zadania asystenta prawnego — pasek na liście i stronie kontraktu (część F).

* ``GET /api/legal/tasks`` — suma dostawców ``TASK_PROVIDERS``
  (``services/legal/tasks.py``); każdy dostawca sam pilnuje zakresu klientów
  i bramek, więc osoba bez podglądu kwot dostaje pustą listę, nie 403.
  ``?contract_id=`` zawęża do jednego kontraktu (wiersz pod „Co się dzieje”).
* ``POST /api/legal/tasks/{key}/dismiss`` — „Pomiń”: zadanie znika z paska
  wszystkim. Tylko zadanie, które pytający widzi (inaczej 404).

Sekcja Delivery — pasek stoi na ekranach kontraktów, nie w Generatorze
(trasy ``/api/legal`` fundamentu są za Sourcingiem i Generatorem).
"""

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.permission_access import DeliveryViewUser
from app.api.section_access import DELIVERY_SECTION_DEPENDENCIES
from app.core.database import get_db
from app.services.legal import tasks
from app.services.legal.tasks_schema import STATUS_DISMISSED

router = APIRouter(dependencies=DELIVERY_SECTION_DEPENDENCIES)


def _row_out(row: tasks.LegalTaskRow) -> dict[str, Any]:
    return {
        "key": row.key,
        "kind": row.kind,
        "severity": row.severity,
        "title": row.title,
        "detail": row.detail,
        "action_label": row.action_label,
        "href": row.href,
        "client_id": row.client_id,
        "contract_id": row.contract_id,
        "created_at": row.created_at.isoformat(),
    }


@router.get("/tasks")
async def legal_tasks(
    current_user: DeliveryViewUser,
    contract_id: Optional[int] = Query(None, ge=1),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    rows = await tasks.collect(db, current_user)
    if contract_id is not None:
        rows = [row for row in rows if row.contract_id == contract_id]
    return {"items": [_row_out(row) for row in rows]}


@router.post("/tasks/{key}/dismiss")
async def dismiss_legal_task(
    key: str,
    current_user: DeliveryViewUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    if len(key) > 160:
        raise HTTPException(status_code=404, detail="Nie ma takiego zadania.")
    row = next((r for r in await tasks.collect(db, current_user) if r.key == key), None)
    if row is None:
        raise HTTPException(
            status_code=404, detail="Nie ma takiego zadania albo jest już zamknięte."
        )
    await tasks.close_task(
        db,
        key=row.key,
        kind=row.kind,
        status=STATUS_DISMISSED,
        user_id=current_user.id,
        contract_id=row.contract_id,
        client_id=row.client_id,
    )
    await db.commit()
    return {"dismissed": True, "key": row.key}
