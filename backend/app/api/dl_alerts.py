"""Router `/api/dl-alerts` — powiadomienia Delivery Leada z logiem obsłużenia.

Sekcja „Powiadomienia" w dashboardzie DL. W odróżnieniu od dzwonka
(``/api/notifications``, tylko ``is_read``) każdy wpis ma trwały ślad: kto go
dostał, kto i kiedy go obsłużył oraz ile to trwało — i to ten ślad jest
raportem, który ticket każe eksportować.

**Wpisy nie są kasowane.** Ani przy obsłużeniu, ani gdy przyczyna ustąpi.
Powtórka co 7 dni jest NOWYM wierszem, więc historia pokazuje, ile tygodni
sprawa czekała, a nie tylko że kiedyś istniała.

Zakres dostępu:

* Delivery Lead widzi i eksportuje WYŁĄCZNIE własne wpisy,
* ``admin`` i ``finance`` mogą dodatkowo pobrać eksport zbiorczy
  (``scope=all``) — to jedyne miejsce, gdzie te wpisy przekraczają granicę
  jednej osoby, i wymaga jawnego parametru, żeby nie zdarzyło się przypadkiem.

Uwaga przy dokładaniu tras: ten moduł ma ``from __future__ import
annotations``, więc NIE wolno tu wprowadzać ``@limiter.limit`` razem
z ``Annotated`` w ciele — PEP 563 + slowapi #579 zamieniają body na parametr
Query (ten sam trap co w ``candidate_activity_summary.py``).
"""

from __future__ import annotations

from datetime import datetime, timezone
from io import BytesIO
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import require_roles
from app.core.database import get_db
from app.models.dl_alert import (
    DL_ALERT_STATUS_HANDLED,
    DL_ALERT_STATUS_LABELS,
    DL_ALERT_STATUS_NEW,
    DL_ALERT_TYPE_LABELS,
    DlAlert,
)
from app.models.user import User, UserRole
from app.schemas.dl_alert import DlAlertListResponse, DlAlertRead
from app.services.dl_alerts import format_reaction, reaction_seconds

router = APIRouter()

#: Bramka ZALEŻNOŚCIOWA, nie tylko filtr w ciele handlera.
#:
#: Filtrowanie po `user_id == current_user.id` jest poprawne, ale niewidoczne
#: w OpenAPI i nieegzekwowane dla następnego handlera dopisanego do tego
#: routera — dokładnie to wychwycił `test_route_authz_contract`. Lista ról jest
#: wąska celowo: alert dostaje wyłącznie Delivery Lead przypisany do klienta
#: (`dl_user_ids_for_client`), a eksport zbiorczy admin i Finanse. Recruiter,
#: sourcer, TAC i deprecated `user` nie mają tu czego szukać.
DlAlertsUser = Annotated[
    User,
    Depends(
        require_roles(
            UserRole.admin,
            UserRole.head_of_recruitment,
            UserRole.delivery_lead,
            UserRole.finance,
        )
    ),
]

_XLSX_MEDIA = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

# Kto może pobrać eksport ZBIORCZY (wszyscy DL naraz). Świadomie inne role niż
# odbiorcy alertów: to jest raport nadzorczy, nie skrzynka.
_EXPORT_ALL_ROLES = (UserRole.admin, UserRole.finance)


def _can_export_all(user: User) -> bool:
    return user.has_any_role(*_EXPORT_ALL_ROLES)


def _display_name(user: Optional[User]) -> str:
    if user is None:
        return "—"
    return (user.name or "").strip() or user.email or f"#{user.id}"


def _to_read(alert: DlAlert) -> DlAlertRead:
    return DlAlertRead(
        id=alert.id,
        alert_type=alert.alert_type,
        alert_type_label=DL_ALERT_TYPE_LABELS.get(alert.alert_type, alert.alert_type),
        status=alert.status,
        status_label=DL_ALERT_STATUS_LABELS.get(alert.status, alert.status),
        client_id=alert.client_id,
        client_name=alert.client.name if alert.client else "—",
        order_group_id=alert.order_group_id,
        order_id=alert.order_id,
        title=alert.title,
        message=alert.message,
        link=alert.link,
        recipient_user_id=alert.user_id,
        recipient_name=_display_name(alert.recipient),
        created_at=alert.created_at,
        handled_at=alert.handled_at,
        handled_by_user_id=alert.handled_by_user_id,
        handled_by_name=_display_name(alert.handler) if alert.handled_at else None,
        reaction_seconds=reaction_seconds(alert),
        reaction_label=format_reaction(alert),
    )


def _base_query():
    return select(DlAlert).options(
        selectinload(DlAlert.client),
        selectinload(DlAlert.recipient),
        selectinload(DlAlert.handler),
    )


@router.get("", response_model=DlAlertListResponse)
async def list_alerts(
    user: DlAlertsUser,
    db: AsyncSession = Depends(get_db),
    alert_status: str = Query(DL_ALERT_STATUS_NEW, alias="status"),
    limit: int = Query(50, ge=1, le=200),
):
    """Powiadomienia zalogowanego użytkownika.

    Zawsze wyłącznie własne — również dla admina. Podgląd cudzych skrzynek nie
    ma tu zastosowania operacyjnego, a raport zbiorczy ma osobną, jawną trasę.
    """
    if alert_status not in (DL_ALERT_STATUS_NEW, DL_ALERT_STATUS_HANDLED):
        raise HTTPException(422, detail="Status musi być 'new' albo 'handled'")

    result = await db.execute(
        _base_query()
        .where(DlAlert.user_id == user.id, DlAlert.status == alert_status)
        .order_by(DlAlert.created_at.desc(), DlAlert.id.desc())
        .limit(limit)
    )
    alerts = [_to_read(a) for a in result.scalars()]

    counts = await db.execute(
        select(DlAlert.status, func.count(DlAlert.id))
        .where(DlAlert.user_id == user.id)
        .group_by(DlAlert.status)
    )
    by_status = {s: int(c) for s, c in counts}
    return DlAlertListResponse(
        alerts=alerts,
        total_new=by_status.get(DL_ALERT_STATUS_NEW, 0),
        total_handled=by_status.get(DL_ALERT_STATUS_HANDLED, 0),
    )


@router.post("/{alert_id}/handled", response_model=DlAlertRead)
async def mark_handled(
    alert_id: int,
    user: DlAlertsUser,
    db: AsyncSession = Depends(get_db),
):
    """Oznacz powiadomienie jako obsłużone.

    Wpis NIE znika — zmienia status i dostaje znacznik kto/kiedy. To on jest
    treścią raportu, więc usunięcie go zabrałoby jedyny dowód, że sprawa
    w ogóle była zgłoszona.

    Obsłużenie wstrzymuje też dalsze powtórki tej sprawy (patrz
    ``app/services/dl_alerts.py``).
    """
    alert = await db.scalar(_base_query().where(DlAlert.id == alert_id))
    if alert is None or alert.user_id != user.id:
        # 404, nie 403 — cudzy wpis nie ma prawa nawet potwierdzić swojego
        # istnienia komuś, kto go nie dostał.
        raise HTTPException(404, detail="Powiadomienie nie istnieje")
    if alert.status == DL_ALERT_STATUS_HANDLED:
        return _to_read(alert)

    alert.status = DL_ALERT_STATUS_HANDLED
    alert.handled_at = datetime.now(timezone.utc)
    alert.handled_by_user_id = user.id
    await db.commit()
    await db.refresh(alert)
    refreshed = await db.scalar(_base_query().where(DlAlert.id == alert_id))
    return _to_read(refreshed or alert)


@router.get("/export")
async def export_alerts(
    user: DlAlertsUser,
    db: AsyncSession = Depends(get_db),
    scope: str = Query("mine", pattern="^(mine|all)$"),
    limit: int = Query(10000, ge=1, le=50000),
):
    """Raport powiadomień w XLSX.

    ``scope=all`` (wszyscy DL naraz) jest zarezerwowany dla ról ``admin``
    i ``finance``. Parametr jest JAWNY, a nie wywnioskowany z roli: admin
    otwierający raport swojej własnej skrzynki nie może przypadkiem wyeksportować
    cudzych spraw.
    """
    if scope == "all" and not _can_export_all(user):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail="Eksport zbiorczy jest dostępny dla ról Administrator i Finanse",
        )

    query = _base_query().order_by(DlAlert.created_at.desc(), DlAlert.id.desc())
    if scope == "mine":
        query = query.where(DlAlert.user_id == user.id)
    result = await db.execute(query.limit(limit))
    alerts = list(result.scalars())

    from openpyxl import Workbook
    from openpyxl.styles import Font

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Powiadomienia"
    sheet.append(
        [
            "Delivery Lead",
            "Klient",
            "Typ",
            "Treść",
            "Data wygenerowania",
            "Data obsłużenia",
            "Czas reakcji",
            "Status",
        ]
    )
    for cell in sheet[1]:
        cell.font = Font(bold=True)
    sheet.freeze_panes = "A2"

    for alert in alerts:
        read = _to_read(alert)
        sheet.append(
            [
                _formula_safe(read.recipient_name),
                _formula_safe(read.client_name),
                _formula_safe(read.alert_type_label),
                _formula_safe(read.message),
                read.created_at.isoformat(timespec="seconds"),
                (
                    read.handled_at.isoformat(timespec="seconds")
                    if read.handled_at
                    else ""
                ),
                read.reaction_label,
                read.status_label,
            ]
        )

    buffer = BytesIO()
    workbook.save(buffer)
    buffer.seek(0)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    filename = f"powiadomienia-dl_{stamp}.xlsx"
    return StreamingResponse(
        buffer,
        media_type=_XLSX_MEDIA,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# Ta sama osłona co w eksporcie katalogu klientów: komórka tekstowa zaczynająca
# się od =, +, -, @ (albo tabulatora/CR, którymi da się je przemycić) jest
# wykonywana jako formuła po otwarciu pliku. Treść alertu zawiera nazwy
# klientów i numery zamówień wpisane przez ludzi, więc jest tekstem obcym.
_FORMULA_INJECTION_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def _formula_safe(value):
    if isinstance(value, str) and value[:1] in _FORMULA_INJECTION_PREFIXES:
        return "'" + value
    return value
