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

from collections import defaultdict
from datetime import date, datetime, timezone
from io import BytesIO
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import require_roles
from app.api.section_access import DELIVERY_SECTION_DEPENDENCIES
from app.core.database import get_db
from app.core.scheduling import business_today
from app.models.activity import Activity
from app.models.dl_alert import (
    DL_ALERT_PRIORITY_HIGH,
    DL_ALERT_SECTION_BY_TYPE,
    DL_ALERT_SECTION_ENDING,
    DL_ALERT_STATUS_HANDLED,
    DL_ALERT_STATUS_LABELS,
    DL_ALERT_STATUS_NEW,
    DL_ALERT_STATUS_RESOLVED,
    DL_ALERT_TYPE_LABELS,
    DlAlert,
)
from app.models.client_order_offboarding import OFFBOARDING_STATUS_PENDING
from app.models.user import User, UserRole
from app.services.client_identity import client_display_name
from app.schemas.dl_alert import (
    DlAlertCard,
    DlAlertCardsResponse,
    DlAlertListResponse,
    DlAlertRead,
)
from app.services.dl_alerts import format_reaction, reaction_seconds

router = APIRouter(dependencies=DELIVERY_SECTION_DEPENDENCIES)

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
        client_name=client_display_name(alert.client) if alert.client else "—",
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
        selectinload(DlAlert.offboarding_case),
    )


def _assert_manual_handling_allowed(alert: DlAlert) -> None:
    """MD departure alerts close only with the versioned order decision."""

    case = alert.offboarding_case
    if (
        alert.offboarding_case_id is not None
        and case is not None
        and case.status == OFFBOARDING_STATUS_PENDING
    ):
        raise HTTPException(
            409,
            detail={
                "code": "offboarding_decision_required",
                "message": (
                    "To powiadomienie zostanie obsłużone po podjęciu decyzji "
                    "o puli MD w zamówieniu."
                ),
                "link": alert.link,
            },
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
    if alert_status not in (
        DL_ALERT_STATUS_NEW,
        DL_ALERT_STATUS_HANDLED,
        DL_ALERT_STATUS_RESOLVED,
    ):
        raise HTTPException(
            422, detail="Status musi być 'new', 'handled' albo 'resolved'"
        )

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


def _parse_date(raw: object) -> Optional[date]:
    if not isinstance(raw, str):
        return None
    try:
        return date.fromisoformat(raw[:10])
    except ValueError:
        return None


def _build_cards(alerts: list[DlAlert], today: date) -> list[DlAlertCard]:
    """Złóż otwarte wiersze w karty — jedna na sprawę (``event_key``)."""
    grouped: dict[str, list[DlAlert]] = defaultdict(list)
    for alert in alerts:
        grouped[alert.event_key or f"row:{alert.id}"].append(alert)

    cards: list[DlAlertCard] = []
    for key, rows in grouped.items():
        rows.sort(key=lambda a: (a.created_at, a.id))
        latest = rows[-1]
        payload = latest.payload or {}
        end_date = _parse_date(payload.get("end_date"))
        missing = payload.get("missing_fields")
        case = latest.offboarding_case
        cards.append(
            DlAlertCard(
                id=latest.id,
                event_key=latest.event_key,
                alert_type=latest.alert_type,
                alert_type_label=DL_ALERT_TYPE_LABELS.get(
                    latest.alert_type, latest.alert_type
                ),
                section=DL_ALERT_SECTION_BY_TYPE.get(
                    latest.alert_type, DL_ALERT_SECTION_ENDING
                ),
                priority=(
                    DL_ALERT_PRIORITY_HIGH
                    if any(r.priority == DL_ALERT_PRIORITY_HIGH for r in rows)
                    else latest.priority
                ),
                client_id=latest.client_id,
                client_name=(
                    client_display_name(latest.client) if latest.client else "—"
                ),
                order_group_id=latest.order_group_id,
                order_id=latest.order_id,
                title=latest.title,
                message=latest.message,
                link=latest.link,
                candidate_name=payload.get("candidate_name")
                or payload.get("consultant")
                or payload.get("consultant_name"),
                end_date=end_date,
                days_left=(end_date - today).days if end_date else None,
                missing_fields=[str(m) for m in missing]
                if isinstance(missing, list)
                else [],
                source=payload.get("source"),
                received_at=payload.get("received_at"),
                first_alert_at=rows[0].created_at,
                last_alert_at=latest.created_at,
                repeat_count=len(rows),
                email_sent=any(r.email_sent_at is not None for r in rows),
                email_requested=any(bool((r.payload or {}).get("email")) for r in rows),
                can_mark_handled=not (
                    latest.offboarding_case_id is not None
                    and case is not None
                    and case.status == OFFBOARDING_STATUS_PENDING
                ),
            )
        )

    cards.sort(
        key=lambda c: (
            0 if c.priority == DL_ALERT_PRIORITY_HIGH else 1,
            c.days_left if c.days_left is not None else 10_000,
            -c.last_alert_at.timestamp(),
        )
    )
    return cards


@router.get("/cards", response_model=DlAlertCardsResponse)
async def list_cards(
    user: DlAlertsUser,
    db: AsyncSession = Depends(get_db),
):
    """Otwarte sprawy zalogowanego użytkownika jako karty panelu „Moi klienci".

    Wyłącznie własne — jak ``GET ""``. Bez limitu wierszy po stronie klienta:
    liczba otwartych spraw jednej osoby jest mała, a obcięcie listy chowałoby
    sprawy bez śladu.
    """
    result = await db.execute(
        _base_query()
        .where(DlAlert.user_id == user.id, DlAlert.status == DL_ALERT_STATUS_NEW)
        .order_by(DlAlert.created_at.asc(), DlAlert.id.asc())
    )
    cards = _build_cards(list(result.scalars()), business_today())
    return DlAlertCardsResponse(cards=cards, total=len(cards))


_ACTIVITY_ENTITY_BY_PAYLOAD = (
    ("framework_contract_id", "client_framework_contract"),
    ("document_id", "order_mail_document"),
    ("contract_id", "contract"),
)


def _activity_target(alert: DlAlert) -> tuple[str, int]:
    """Na czym zapisać ślad odhaczenia: zamówienie > grupa > umowa > klient."""
    payload = alert.payload or {}
    if alert.order_id is not None:
        return "client_order", alert.order_id
    if alert.order_group_id is not None:
        return "client_order_group", alert.order_group_id
    for field, entity_type in _ACTIVITY_ENTITY_BY_PAYLOAD:
        value = payload.get(field)
        if isinstance(value, int):
            return entity_type, value
    return "client", alert.client_id


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
    _assert_manual_handling_allowed(alert)
    if alert.status in (DL_ALERT_STATUS_HANDLED, DL_ALERT_STATUS_RESOLVED):
        # Już zamknięte (odhaczone albo przyczyna ustąpiła w nocy) — karta
        # z nieodświeżonego panelu nie może dopisać fałszywego odhaczenia.
        return _to_read(alert)

    moment = datetime.now(timezone.utc)
    # Odhaczenie zamyka CAŁĄ sprawę (wszystkie wiersze powtórek), nie jeden
    # wiersz — inaczej karta wracałaby z treścią starszej powtórki.
    if alert.event_key:
        closed_ids = list(
            (
                await db.execute(
                    update(DlAlert)
                    .where(
                        DlAlert.user_id == user.id,
                        DlAlert.event_key == alert.event_key,
                        DlAlert.status == DL_ALERT_STATUS_NEW,
                    )
                    .values(
                        status=DL_ALERT_STATUS_HANDLED,
                        handled_at=moment,
                        handled_by_user_id=user.id,
                    )
                    .returning(DlAlert.id)
                    .execution_options(synchronize_session=False)
                )
            ).scalars()
        )
    else:
        alert.status = DL_ALERT_STATUS_HANDLED
        alert.handled_at = moment
        alert.handled_by_user_id = user.id
        closed_ids = [alert.id]

    if not closed_ids:
        # Wyścig z nocnym zamknięciem: nic nie odhaczono, więc nie ma śladu.
        await db.commit()
        db.expire_all()
        refreshed = await db.scalar(_base_query().where(DlAlert.id == alert_id))
        return _to_read(refreshed or alert)

    payload = alert.payload or {}
    entity_type, entity_id = _activity_target(alert)
    db.add(
        Activity(
            entity_type=entity_type,
            entity_id=entity_id,
            action="dl_alert_handled",
            user_id=user.id,
            details={
                "alert_type": alert.alert_type,
                "alert_type_label": DL_ALERT_TYPE_LABELS.get(
                    alert.alert_type, alert.alert_type
                ),
                "event_key": alert.event_key,
                "client_id": alert.client_id,
                "order_id": alert.order_id,
                "order_group_id": alert.order_group_id,
                "candidate_name": payload.get("candidate_name")
                or payload.get("consultant"),
                "title": alert.title,
                "dl_alert_ids": closed_ids,
                "handled_at": moment.isoformat(),
            },
        )
    )
    await db.commit()
    db.expire_all()
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
