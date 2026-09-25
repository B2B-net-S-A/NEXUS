"""Przepięcie kontraktu na innego klienta (tylko admin).

Po co
-----
Raport ``GET /api/admin/client-mixups`` pokazuje kontrakty zapisane pod
klientem o mylnie podobnej nazwie („BNP Paribas Cardif” zamiast „CARDIF -
ASSURANCES…”). Do tej pory nie dało się ich poprawić: ``ContractUpdate``
świadomie NIE ma ``client_id`` (formularz edycji nie może przepinać klienta
„przy okazji”), a skasowanie i założenie kontraktu od nowa gubi dokumenty,
aneksy, harmonogramy stawek i historię. Ta ścieżka jest jedyną drogą zmiany
klienta kontraktu.

Kształt: podgląd → zgoda → wykonanie
------------------------------------
* :func:`build_plan` liczy, co zostanie przeniesione (zamówienia kontraktu,
  wygenerowane umowy B2B, otwarte braki zamówień), które alerty Delivery Leada
  zostaną zamknięte i co blokuje operację. Plan ma odcisk SHA-256.
* :func:`execute_reassign` blokuje wiersz kontraktu (``FOR UPDATE``), potem jego
  zamówienia — kolejność kontrakt → zamówienia, jak cykl życia kontraktu —
  liczy plan od nowa i porównuje odcisk. Inny odcisk = 409: admin zatwierdzał
  inny stan świata.

Czego ta ścieżka NIE robi (świadomie)
-------------------------------------
* **Nie przepisuje dzienników** — ``order_change_events``,
  ``b2b_generated_contract_status_events``, rozstrzygnięte sprawy offboardingu
  i braki zamówień uzupełnione po terminie (``filled_late``) opisują przeszłość
  i zostają przy kliencie, u którego się wydarzyły.
* **Nie zmienia treści podpisanego dokumentu B2B** — ``client_name`` to nazwa
  WYDRUKOWANA w umowie; przepinamy tylko ``client_id``.
* **Nie przenosi zamówień zakotwiczonych w strukturze starego klienta**
  (umowa ramowa, umowa wykonawcza / część e-Zdrowia, linia zamówienia MD /
  kosztowego) — takie zamówienie po przepięciu wskazywałoby umowę innego
  klienta. To blokery; admin rozstrzyga je najpierw u starego klienta.
* **Nie wystawia alertów nowemu klientowi** — otwarte alerty tej encji
  u starego klienta są zamykane jako ``resolved`` (przyczyna „ustąpiła” —
  wraz z przepięciem), a skaner wystawi nowe właściwym Delivery Leadom.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.activity import Activity
from app.models.b2b_generated_contract import B2BGeneratedContract
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.client_order import ClientOrder
from app.models.client_order_offboarding import ClientOrderOffboardingCase
from app.models.contact import Contact
from app.models.contract import Contract, ContractStatus
from app.models.contract_framework_rate import ContractFrameworkRate
from app.models.dl_alert import (
    DL_ALERT_STATUS_HANDLED,
    DL_ALERT_STATUS_NEW,
    DL_ALERT_STATUS_RESOLVED,
    DlAlert,
)
from app.models.job import Job
from app.models.order_gap import OrderGap
from app.services.client_identity import client_display_name

EVENT_TYPE = "contract.client_reassign"
ACTIVITY_ACTION = "client_reassigned"

# Kody blokerów — front tłumaczy je sam tylko wtedy, gdy brak ``message``.
BLOCKER_ORDER_FRAMEWORK = "order_framework_contract"
BLOCKER_ORDER_EXECUTIVE = "order_executive_contract"
BLOCKER_ORDER_GROUP_LINE = "order_group_line"
BLOCKER_ORDER_OTHER_CLIENT = "order_other_client"
BLOCKER_PM_CONTACT = "pm_contact_other_client"
BLOCKER_OFFBOARDING_PENDING = "offboarding_pending"
BLOCKER_DUPLICATE_AT_TARGET = "duplicate_contract_at_target"

# Lustro ``_DUPLICATE_GUARD_STATUSES`` z ``app/api/contracts.py`` (blokada
# duplikatu kontraktora przy zakładaniu kontraktu) — import routera zamknąłby
# cykl importów; zgodność pilnuje test.
LIVE_CONTRACT_STATUSES = (
    ContractStatus.draft,
    ContractStatus.ready_for_signature,
    ContractStatus.active,
    ContractStatus.ending,
)

WARNING_JOB_CLIENT = "job_client_differs"
WARNING_B2B_PRINTED_NAME = "b2b_printed_client_name"
WARNING_B2B_OTHER_CLIENT = "b2b_other_client"
WARNING_FRAMEWORK_RATE = "framework_rate_schedule"


class ReassignError(Exception):
    """Odmowa przed wyliczeniem planu (404/422)."""

    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


@dataclass
class ReassignPlan:
    contract_id: int
    from_client: dict[str, Any]
    to_client: dict[str, Any]
    contract_status: str
    orders: list[dict[str, Any]] = field(default_factory=list)
    b2b_documents: list[dict[str, Any]] = field(default_factory=list)
    open_gaps: list[dict[str, Any]] = field(default_factory=list)
    alerts: list[dict[str, Any]] = field(default_factory=list)
    blockers: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[dict[str, Any]] = field(default_factory=list)
    # Wiersze alertów, którym trzeba postawić stempel epizodu (odhaczone),
    # żeby odbiorca, który jest też DL nowego klienta, dostał alert ponownie.
    handled_alert_ids: list[int] = field(default_factory=list)
    fingerprint: str = ""

    @property
    def can_apply(self) -> bool:
        return not self.blockers

    def as_dict(self) -> dict[str, Any]:
        return {
            "contract_id": self.contract_id,
            "contract_label": f"Kontrakt #{self.contract_id}",
            "contract_status": self.contract_status,
            "from_client": self.from_client,
            "to_client": self.to_client,
            "orders": self.orders,
            "b2b_documents": self.b2b_documents,
            "open_gaps": self.open_gaps,
            "alerts": self.alerts,
            "blockers": self.blockers,
            "warnings": self.warnings,
            "can_apply": self.can_apply,
            "fingerprint": self.fingerprint,
        }


def _client_ref(client: Client) -> dict[str, Any]:
    return {"id": client.id, "name": client_display_name(client)}


def _enum_text(value: Any) -> Any:
    return getattr(value, "value", value)


def _fingerprint(plan: ReassignPlan) -> str:
    """Odcisk części WYKONAWCZEJ planu — tego, co apply zmieni albo odrzuci.

    Nazwy klientów, tytuły i komunikaty nie wchodzą: zmiana nazwy klienta
    między podglądem a zgodą nie zmienia operacji.
    """

    body = {
        "contract_id": plan.contract_id,
        "from_client_id": plan.from_client["id"],
        "to_client_id": plan.to_client["id"],
        "orders": sorted((o["id"], o["client_id"], o["status"]) for o in plan.orders),
        "b2b": sorted((d["id"], d["client_id"]) for d in plan.b2b_documents),
        "gaps": sorted(g["id"] for g in plan.open_gaps),
        "alerts": sorted(a["id"] for a in plan.alerts),
        "handled_alerts": sorted(plan.handled_alert_ids),
        "blockers": sorted(
            (b["code"], tuple(sorted(b.get("ids") or ()))) for b in plan.blockers
        ),
    }
    encoded = json.dumps(body, sort_keys=True, separators=(",", ":"), default=list)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _alert_matches(
    event_key: Optional[str],
    *,
    contract_id: int,
    order_ids: set[int],
    gap_ids: set[int],
) -> bool:
    """Czy ``event_key`` (``{typ}:{encja}:{odbiorca}``) dotyczy tej encji.

    Encje wystawiane dla kontraktu i jego zamówień: ``contract:{id}:…``,
    ``order:{id}``/``order:{id}:end:…``, ``mail-draft:{id}``, ``gap:{id}``.
    Dwukropek po numerze jest obowiązkowy — ``order:12`` nie może złapać
    ``order:123``.
    """

    if not event_key:
        return False
    if f":contract:{contract_id}:" in event_key:
        return True
    for match in re.finditer(r":(order|mail-draft|gap):(\d+):", event_key):
        kind, raw = match.group(1), int(match.group(2))
        if kind == "gap" and raw in gap_ids:
            return True
        if kind in ("order", "mail-draft") and raw in order_ids:
            return True
    return False


async def _load_target(
    db: AsyncSession, client_id: int, *, lock: bool = False
) -> Client:
    """Klient docelowy — widoczny (``is_client_visible``) i, przy wykonaniu,
    zablokowany do końca transakcji, żeby równoległe usunięcie albo scalenie
    nie przyjęło przepiętego kontraktu (audyt 24.09.2026, N10)."""
    stmt = select(Client).where(Client.id == client_id)
    if lock:
        stmt = stmt.with_for_update().execution_options(populate_existing=True)
    target = await db.scalar(stmt)
    if target is None:
        raise ReassignError(
            404, "target_client_not_found", "Nie znaleziono klienta docelowego."
        )
    if target.deleted_at is not None:
        raise ReassignError(
            422,
            "target_client_deleted",
            "Klient docelowy został usunięty — wybierz innego.",
        )
    if target.merged_into_client_id is not None:
        raise ReassignError(
            422,
            "target_client_merged",
            "Klient docelowy jest scalony z innym rekordem — wybierz rekord główny.",
        )
    if target.hidden:
        raise ReassignError(
            422,
            "target_client_hidden",
            "Klient docelowy jest ukryty (zdublowany wariant) — wybierz widoczny rekord.",
        )
    if target.archived_at is not None:
        raise ReassignError(
            422,
            "target_client_archived",
            "Klient docelowy jest zarchiwizowany — wybierz aktywny rekord.",
        )
    return target


async def _live_contract_at_target(
    db: AsyncSession, contract: Contract, target_client_id: int
) -> Optional[int]:
    """Żywy kontrakt TEJ SAMEJ osoby u klienta docelowego (audyt 25.09.2026).

    Ta sama reguła tożsamości co blokada duplikatu przy zakładaniu kontraktu
    (``_assert_no_duplicate_contract``): ``candidate_id`` albo e-mail bez
    wielkości liter i białych znaków. Dotyczy tylko przepinania kontraktu
    żywego — zakończony obok żywego to historia, nie duplikat.
    """
    if contract.status not in LIVE_CONTRACT_STATUSES:
        return None
    email = await db.scalar(
        select(Candidate.email).where(Candidate.id == contract.candidate_id)
    )
    email_norm = (email or "").strip().lower()
    identity = [Contract.candidate_id == contract.candidate_id]
    if email_norm:
        identity.append(
            func.lower(func.btrim(Candidate.email, " \t\r\n")) == email_norm
        )
    return await db.scalar(
        select(Contract.id)
        .join(Candidate, Candidate.id == Contract.candidate_id)
        .where(
            Contract.client_id == target_client_id,
            Contract.id != contract.id,
            Contract.status.in_(LIVE_CONTRACT_STATUSES),
            or_(*identity),
        )
        .order_by(Contract.id)
        .limit(1)
    )


async def build_plan(
    db: AsyncSession,
    contract: Contract,
    target_client_id: int,
    *,
    orders: Optional[list[ClientOrder]] = None,
) -> ReassignPlan:
    """Plan przepięcia. Niczego nie zapisuje.

    ``orders`` przekazuje wykonanie, które zablokowało już wiersze zamówień —
    plan liczy się wtedy z tych samych obiektów.
    """

    if contract.client_id == target_client_id:
        raise ReassignError(
            422, "same_client", "Kontrakt jest już przypisany do tego klienta."
        )
    # Wykonanie (``orders`` z zablokowanymi wierszami) blokuje też klienta
    # docelowego; podgląd niczego nie blokuje.
    target = await _load_target(db, target_client_id, lock=orders is not None)
    source = await db.get(Client, contract.client_id)
    from_ref = (
        _client_ref(source)
        if source is not None
        else {"id": contract.client_id, "name": f"Klient #{contract.client_id}"}
    )
    to_ref = _client_ref(target)
    old_id = contract.client_id

    plan = ReassignPlan(
        contract_id=contract.id,
        from_client=from_ref,
        to_client=to_ref,
        contract_status=str(_enum_text(contract.status)),
    )

    if orders is None:
        orders = list(
            (
                await db.scalars(
                    select(ClientOrder)
                    .where(ClientOrder.contract_id == contract.id)
                    .order_by(ClientOrder.id)
                )
            ).all()
        )

    framework_ids: list[int] = []
    executive_ids: list[int] = []
    group_line_ids: list[int] = []
    other_client_ids: list[int] = []
    for order in orders:
        plan.orders.append(
            {
                "id": order.id,
                "title": order.title,
                "status": str(_enum_text(order.status)),
                "client_id": order.client_id,
                "start_date": order.start_date.isoformat()
                if order.start_date
                else None,
                "end_date": order.end_date.isoformat() if order.end_date else None,
            }
        )
        if order.framework_contract_id is not None:
            framework_ids.append(order.id)
        if order.executive_contract_id is not None or order.project_part is not None:
            executive_ids.append(order.id)
        if order.order_group_id is not None:
            group_line_ids.append(order.id)
        if order.client_id not in (old_id, target.id):
            other_client_ids.append(order.id)

    def _titles(ids: list[int]) -> str:
        by_id = {o["id"]: o["title"] for o in plan.orders}
        return ", ".join(f"„{by_id[i]}” (#{i})" for i in ids)

    if framework_ids:
        plan.blockers.append(
            {
                "code": BLOCKER_ORDER_FRAMEWORK,
                "ids": framework_ids,
                "message": (
                    "Zamówienia wiszą pod umową ramową starego klienta: "
                    f"{_titles(framework_ids)}. Odepnij umowę ramową w zamówieniu "
                    "albo załóż zamówienie u właściwego klienta."
                ),
            }
        )
    if executive_ids:
        plan.blockers.append(
            {
                "code": BLOCKER_ORDER_EXECUTIVE,
                "ids": executive_ids,
                "message": (
                    "Zamówienia są przypisane do umowy wykonawczej (części umowy) "
                    f"starego klienta: {_titles(executive_ids)}."
                ),
            }
        )
    if group_line_ids:
        plan.blockers.append(
            {
                "code": BLOCKER_ORDER_GROUP_LINE,
                "ids": group_line_ids,
                "message": (
                    "Konsultant jest linią zamówienia MD / kosztowego starego klienta: "
                    f"{_titles(group_line_ids)}. Usuń go z tego zamówienia albo "
                    "zakończ jego udział, zanim przepniesz kontrakt."
                ),
            }
        )
    if other_client_ids:
        plan.blockers.append(
            {
                "code": BLOCKER_ORDER_OTHER_CLIENT,
                "ids": other_client_ids,
                "message": (
                    "Zamówienia tego kontraktu są zapisane u jeszcze innego klienta: "
                    f"{_titles(other_client_ids)}. Wyjaśnij je przed przepięciem."
                ),
            }
        )

    if contract.client_pm_contact_id is not None:
        contact_client_id = await db.scalar(
            select(Contact.client_id).where(Contact.id == contract.client_pm_contact_id)
        )
        if contact_client_id is not None and contact_client_id != target.id:
            plan.blockers.append(
                {
                    "code": BLOCKER_PM_CONTACT,
                    "ids": [contract.client_pm_contact_id],
                    "message": (
                        "PM po stronie klienta jest kontaktem innego klienta "
                        f"(kontakt #{contract.client_pm_contact_id}). Zmień albo usuń "
                        "PM w edycji kontraktu przed przepięciem."
                    ),
                }
            )

    duplicate_id = await _live_contract_at_target(db, contract, target.id)
    if duplicate_id is not None:
        plan.blockers.append(
            {
                "code": BLOCKER_DUPLICATE_AT_TARGET,
                "ids": [duplicate_id],
                "message": (
                    "Ta osoba ma już żywy kontrakt u klienta docelowego "
                    f"(Kontrakt #{duplicate_id}). Przepięcie dałoby dwa "
                    "kontrakty tej samej osoby u jednego klienta — najpierw "
                    "zakończ albo scal jeden z nich."
                ),
            }
        )

    pending_cases = list(
        (
            await db.scalars(
                select(ClientOrderOffboardingCase.id)
                .where(
                    ClientOrderOffboardingCase.contract_id == contract.id,
                    ClientOrderOffboardingCase.status == "pending",
                )
                .order_by(ClientOrderOffboardingCase.id)
            )
        ).all()
    )
    if pending_cases:
        plan.blockers.append(
            {
                "code": BLOCKER_OFFBOARDING_PENDING,
                "ids": pending_cases,
                "message": (
                    "Czeka decyzja Delivery Leada po zakończeniu współpracy na "
                    "zamówieniu MD starego klienta — rozstrzygnij ją najpierw."
                ),
            }
        )

    documents = list(
        (
            await db.scalars(
                select(B2BGeneratedContract)
                .where(B2BGeneratedContract.contract_id == contract.id)
                .order_by(B2BGeneratedContract.id)
            )
        ).all()
    )
    other_docs: list[int] = []
    printed_mismatch = False
    for doc in documents:
        if doc.client_id == old_id:
            plan.b2b_documents.append(
                {
                    "id": doc.id,
                    "contract_number": doc.contract_number,
                    "contract_status": doc.contract_status,
                    "client_id": doc.client_id,
                    "printed_client_name": doc.client_name,
                }
            )
            printed_mismatch = True
        elif doc.client_id not in (None, target.id):
            other_docs.append(doc.id)
    if printed_mismatch:
        plan.warnings.append(
            {
                "code": WARNING_B2B_PRINTED_NAME,
                "message": (
                    "Umowy B2B zostaną przypisane do nowego klienta, ale nazwa "
                    "klienta WYDRUKOWANA w dokumencie się nie zmieni — to zapis "
                    "tego, co strony podpisały."
                ),
            }
        )
    if other_docs:
        plan.warnings.append(
            {
                "code": WARNING_B2B_OTHER_CLIENT,
                "message": (
                    f"{len(other_docs)} umowa(-y) B2B tego kontraktu jest zapisana "
                    "u jeszcze innego klienta i nie zostanie przeniesiona."
                ),
            }
        )

    order_ids = {o["id"] for o in plan.orders}
    gaps = list(
        (
            await db.scalars(
                select(OrderGap)
                .where(OrderGap.contract_id == contract.id)
                .order_by(OrderGap.id)
            )
        ).all()
    )
    all_gap_ids = {g.id for g in gaps}
    for gap in gaps:
        if gap.status == "open" and gap.client_id == old_id:
            plan.open_gaps.append(
                {
                    "id": gap.id,
                    "order_number": gap.order_number,
                    "ended_on": gap.ended_on.isoformat(),
                }
            )

    alert_rows = list(
        (
            await db.scalars(
                select(DlAlert)
                .where(
                    DlAlert.client_id == old_id,
                    DlAlert.episode_closed_at.is_(None),
                )
                .order_by(DlAlert.id)
            )
        ).all()
    )
    for alert in alert_rows:
        matches = (alert.order_id is not None and alert.order_id in order_ids) or (
            _alert_matches(
                alert.event_key,
                contract_id=contract.id,
                order_ids=order_ids,
                gap_ids=all_gap_ids,
            )
        )
        if not matches:
            continue
        if alert.status == DL_ALERT_STATUS_NEW:
            plan.alerts.append(
                {"id": alert.id, "alert_type": alert.alert_type, "title": alert.title}
            )
        elif alert.status in (DL_ALERT_STATUS_HANDLED, DL_ALERT_STATUS_RESOLVED):
            plan.handled_alert_ids.append(alert.id)

    if contract.job_id is not None:
        job_client_id = await db.scalar(
            select(Job.client_id).where(Job.id == contract.job_id)
        )
        if job_client_id is not None and job_client_id != target.id:
            plan.warnings.append(
                {
                    "code": WARNING_JOB_CLIENT,
                    "message": (
                        "Rekrutacja, z której powstał kontrakt, należy do innego "
                        "klienta niż docelowy — raport pomylonych klientów dalej "
                        "pokaże ten kontrakt jako rozjazd."
                    ),
                }
            )

    has_framework_rate = await db.scalar(
        select(ContractFrameworkRate.id)
        .where(ContractFrameworkRate.contract_id == contract.id)
        .limit(1)
    )
    if has_framework_rate is not None:
        plan.warnings.append(
            {
                "code": WARNING_FRAMEWORK_RATE,
                "message": (
                    "Kontrakt ma harmonogram stawki z umowy ramowej starego "
                    "klienta — sprawdź go po przepięciu."
                ),
            }
        )

    plan.fingerprint = _fingerprint(plan)
    return plan


async def lock_contract(db: AsyncSession, contract_id: int) -> Optional[Contract]:
    return await db.scalar(
        select(Contract).where(Contract.id == contract_id).with_for_update()
    )


async def lock_orders(db: AsyncSession, contract_id: int) -> list[ClientOrder]:
    """Zamówienia kontraktu pod blokadą — PO blokadzie kontraktu."""

    from app.services.contract_lifecycle import lock_contract_then_orders

    await lock_contract_then_orders(db, contract_ids=[contract_id])
    return list(
        (
            await db.scalars(
                select(ClientOrder)
                .where(ClientOrder.contract_id == contract_id)
                .order_by(ClientOrder.id)
                .with_for_update()
            )
        ).all()
    )


class FingerprintMismatch(Exception):
    def __init__(self, plan: ReassignPlan) -> None:
        super().__init__("fingerprint mismatch")
        self.plan = plan


class ReassignBlocked(Exception):
    def __init__(self, plan: ReassignPlan) -> None:
        super().__init__("reassign blocked")
        self.plan = plan


async def execute_reassign(
    db: AsyncSession,
    *,
    contract_id: int,
    target_client_id: int,
    fingerprint: str,
    user_id: Optional[int],
    now: Optional[datetime] = None,
) -> ReassignPlan:
    """Blokady (kontrakt → zamówienia), ponowny plan, porównanie odcisku, zapis.

    Rzuca :class:`ReassignError` (404/422), :class:`FingerprintMismatch`
    i :class:`ReassignBlocked`. Commit należy do wołającego.
    """

    contract = await lock_contract(db, contract_id)
    if contract is None:
        raise ReassignError(404, "contract_not_found", "Nie znaleziono kontraktu.")
    orders = await lock_orders(db, contract.id)
    plan = await build_plan(db, contract, target_client_id, orders=orders)
    if plan.fingerprint != fingerprint:
        raise FingerprintMismatch(plan)
    if plan.blockers:
        raise ReassignBlocked(plan)

    moment = now or datetime.now(timezone.utc)
    old_id = contract.client_id
    new_id = plan.to_client["id"]

    contract.client_id = new_id
    moved_order_ids = [o["id"] for o in plan.orders if o["client_id"] == old_id]
    if moved_order_ids:
        await db.execute(
            update(ClientOrder)
            .where(ClientOrder.id.in_(moved_order_ids))
            .values(client_id=new_id)
            .execution_options(synchronize_session=False)
        )
        for order in orders:
            if order.id in moved_order_ids:
                order.client_id = new_id
    moved_doc_ids = [d["id"] for d in plan.b2b_documents]
    if moved_doc_ids:
        await db.execute(
            update(B2BGeneratedContract)
            .where(B2BGeneratedContract.id.in_(moved_doc_ids))
            .values(client_id=new_id)
            .execution_options(synchronize_session=False)
        )
    gap_ids = [g["id"] for g in plan.open_gaps]
    if gap_ids:
        await db.execute(
            update(OrderGap)
            .where(OrderGap.id.in_(gap_ids), OrderGap.status == "open")
            .values(client_id=new_id)
            .execution_options(synchronize_session=False)
        )
    alert_ids = [a["id"] for a in plan.alerts]
    if alert_ids:
        await db.execute(
            update(DlAlert)
            .where(DlAlert.id.in_(alert_ids), DlAlert.status == DL_ALERT_STATUS_NEW)
            .values(
                status=DL_ALERT_STATUS_RESOLVED,
                handled_at=moment,
                episode_closed_at=moment,
            )
            .execution_options(synchronize_session=False)
        )
    if plan.handled_alert_ids:
        await db.execute(
            update(DlAlert)
            .where(
                DlAlert.id.in_(plan.handled_alert_ids),
                DlAlert.episode_closed_at.is_(None),
            )
            .values(episode_closed_at=moment)
            .execution_options(synchronize_session=False)
        )

    db.add(
        Activity(
            entity_type="contract",
            entity_id=contract.id,
            action=ACTIVITY_ACTION,
            user_id=user_id,
            details={
                "from_client_id": old_id,
                "from_client_name": plan.from_client["name"],
                "to_client_id": new_id,
                "to_client_name": plan.to_client["name"],
                "moved_order_ids": moved_order_ids,
                "moved_b2b_ids": moved_doc_ids,
                "moved_gap_ids": gap_ids,
                "closed_alerts": len(alert_ids),
            },
        )
    )
    await db.flush()
    return plan
