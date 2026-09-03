"""Contract lifecycle — one guarded state machine, one activation invariant.

The finding (P1-CONTRACT-01): the contract lifecycle had no single hard
invariant. ``status`` was writable from the create/update schemas, ``/activate``
and ``/draft/finalize`` reached ``active`` (and emitted ``contract_signed``) with
no signed evidence, and a hard DELETE could cascade signature evidence away.

This module is the single source of truth for status transitions. Every
side-effectful status change goes through one of the guarded operations below;
no route sets ``status = active`` directly. The rules:

* :data:`ALLOWED_TRANSITIONS` — the only legal (from → to) edges.
* :func:`activate_contract` — the ONLY path to ``active``. It requires the
  operational fields used by reporting, but deliberately does not depend on
  any generated agreement or qualified-signature state. Contract activation is
  an operational decision; the signing rails keep their own lifecycle.
* :func:`auto_activate_complete_draft` — the write-time completeness trigger;
  it delegates to ``activate_contract`` and yields to an explicitly chosen
  status.
* :func:`move_to_ready_for_signature` — a finalized (but unsigned) draft lands
  here, never at ``active``.
* :func:`revert_contract` — the audited replacement for the old free
  ``PATCH {status: draft}`` revert.
* :func:`void_contract` — soft-delete preserving documents + signature hashes.

Isolated from the route handlers so the invariant can be unit-tested without a
FastAPI rig, and reused by the signing pipeline.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Literal, Optional

from fastapi import HTTPException, status as http_status
from sqlalchemy import ColumnElement, and_, not_, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.activity import Activity
from app.models.app_setting import AppSetting
from app.models.contract import Contract, ContractStatus
from app.models.document_signature import DocumentSignature, SignatureStatus
from app.services.contract_service import validate_ready_for_activation


HardDeleteBlocker = Literal["completed_signature", "signed_generated_contract"]


@dataclass(frozen=True)
class HardDeleteResult:
    """Structural outcome of a guarded hard delete.

    The helper never commits. Batch operations such as the one-off duplicate
    merge can therefore use the exact same deletion semantics inside their own
    larger transaction and include these non-sensitive counts in their audit.
    """

    contract_id: int
    detached_generated_contracts: int
    settled_order_group_ids: tuple[int, ...]


class ContractHardDeleteBlocked(HTTPException):
    """Stable 409 raised when deleting a contract would destroy signed proof."""

    _MESSAGES: dict[HardDeleteBlocker, str] = {
        "completed_signature": (
            "Kontrakt ma ukończony podpis kwalifikowany i nie może "
            "zostać usunięty — usunięcie zniszczyłoby dowód podpisu. "
            "Zamiast tego anuluj kontrakt (void), co zachowa dokumenty "
            "i dowody."
        ),
        "signed_generated_contract": (
            "Kontrakt powstał z umowy B2B potwierdzonej jako podpisana "
            "przez obie strony. Admin może wymusić trwałe usunięcie po "
            "dodatkowym potwierdzeniu; alternatywnie anuluj kontrakt (void) "
            "albo zamknij umowę w rejestrze „Wygenerowane umowy”."
        ),
    }

    def __init__(self, contract: Contract, reason: HardDeleteBlocker) -> None:
        self.reason = reason
        detail: dict[str, object] = {
            "code": f"contract_has_{reason}",
            "message": self._MESSAGES[reason],
            "status": contract.status.value,
            "void_endpoint": f"/api/contracts/{contract.id}/void",
        }
        if reason == "signed_generated_contract":
            detail.update(
                {
                    "requires_admin_confirmation": True,
                    "admin_only": True,
                    "force_delete_endpoint": (
                        f"/api/contracts/{contract.id}/force-delete-signed"
                    ),
                    "confirmation_options": ["contractor_name", "contract_id"],
                    "contract_id": contract.id,
                }
            )
        super().__init__(
            status_code=http_status.HTTP_409_CONFLICT,
            detail=detail,
        )


class ContractSignedDeleteConfirmationError(HTTPException):
    """The break-glass signed-delete confirmation did not match exactly."""

    def __init__(self, contract_id: int) -> None:
        super().__init__(
            status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "signed_delete_confirmation_mismatch",
                "message": (
                    "Wpisz pełne imię i nazwisko kontrahenta albo numer "
                    "kontraktu, aby potwierdzić trwałe usunięcie."
                ),
                "confirmation_options": ["contractor_name", "contract_id"],
                "contract_id": contract_id,
            },
        )


class ContractSignedDeleteUnavailable(HTTPException):
    """The dedicated signed-delete endpoint was used for a non-signed row."""

    def __init__(self, contract_id: int) -> None:
        super().__init__(
            status_code=http_status.HTTP_409_CONFLICT,
            detail={
                "code": "contract_not_protected_by_signed_generated_contract",
                "message": (
                    "Ten kontrakt nie wymaga wymuszonego usunięcia podpisanej "
                    "umowy B2B. Użyj zwykłej operacji usunięcia."
                ),
                "delete_endpoint": f"/api/contracts/{contract_id}",
            },
        )


# ── State machine ────────────────────────────────────────────────────────────
#
# The only legal transitions. Keyed by the CURRENT status; the value is the set
# of statuses it may move to. ``void`` is terminal. Reactivation edges
# (ended/ending → active, * → draft) exist for the audited heal/revert paths.
ALLOWED_TRANSITIONS: dict[ContractStatus, frozenset[ContractStatus]] = {
    ContractStatus.draft: frozenset(
        {
            ContractStatus.ready_for_signature,
            ContractStatus.active,
            ContractStatus.ended,
            ContractStatus.void,
        }
    ),
    ContractStatus.ready_for_signature: frozenset(
        {
            ContractStatus.active,
            ContractStatus.draft,
            ContractStatus.ended,
            ContractStatus.void,
        }
    ),
    ContractStatus.active: frozenset(
        {
            ContractStatus.ending,
            ContractStatus.ended,
            ContractStatus.draft,
            ContractStatus.void,
        }
    ),
    ContractStatus.ending: frozenset(
        {
            ContractStatus.active,
            ContractStatus.ended,
            ContractStatus.draft,
            ContractStatus.void,
        }
    ),
    ContractStatus.ended: frozenset(
        {
            ContractStatus.active,
            ContractStatus.draft,
            ContractStatus.void,
        }
    ),
    ContractStatus.void: frozenset(),
}


class ContractTransitionError(HTTPException):
    """A status change the state machine forbids → surfaced to the API as 409."""

    def __init__(self, detail: object) -> None:
        super().__init__(status_code=http_status.HTTP_409_CONFLICT, detail=detail)


def assert_transition(current: ContractStatus, target: ContractStatus) -> None:
    """Raise 409 unless ``current → target`` is a declared legal edge."""
    if target == current:
        return
    if target not in ALLOWED_TRANSITIONS.get(current, frozenset()):
        raise ContractTransitionError(
            {
                "message": "Illegal contract status transition",
                "from": current.value,
                "to": target.value,
            }
        )


# ── Signature evidence ───────────────────────────────────────────────────────


async def _has_completed_signature(db: AsyncSession, contract_id: int) -> bool:
    """True when at least one ``completed`` signature exists for the contract."""
    found = await db.scalar(
        select(DocumentSignature.id)
        .where(
            DocumentSignature.contract_id == contract_id,
            DocumentSignature.status == SignatureStatus.completed,
        )
        .limit(1)
    )
    return found is not None


# ── Guarded operations ───────────────────────────────────────────────────────


def _audit(
    contract_id: int,
    action: str,
    actor_id: Optional[int],
    *,
    from_status: ContractStatus,
    to_status: ContractStatus,
    extra: Optional[dict] = None,
) -> Activity:
    details = {"from_status": from_status.value, "to_status": to_status.value}
    if extra:
        details.update(extra)
    return Activity(
        entity_type="contract",
        entity_id=contract_id,
        action=action,
        user_id=actor_id,
        details=details,
    )


async def activate_contract(
    db: AsyncSession,
    contract: Contract,
    *,
    actor_id: Optional[int],
) -> None:
    """The ONLY path to ``active``. Adds the audit row; the caller commits.

    Enforces a legal transition and the operational completeness check. It does
    not inspect generated agreements or qualified signatures: the register must
    be able to mark a contract active even when no signing state exists (or the
    external signing state cannot be verified). Any field-validation failure
    raises HTTP 409 and leaves state unchanged. Downstream side effects MUST be
    emitted by the caller only AFTER the activation commit.
    """
    previous = contract.status
    assert_transition(previous, ContractStatus.active)

    missing = validate_ready_for_activation(contract)
    if missing:
        raise HTTPException(
            status_code=http_status.HTTP_409_CONFLICT,
            detail={"message": "Missing required fields", "missing": missing},
        )

    contract.status = ContractStatus.active
    db.add(
        _audit(
            contract.id,
            "contract_activated",
            actor_id,
            from_status=previous,
            to_status=ContractStatus.active,
        )
    )


async def auto_activate_complete_draft(
    db: AsyncSession,
    contract: Contract,
    *,
    actor_id: Optional[int],
    status_explicit: bool,
) -> bool:
    """Promote a complete draft after a write unless the caller chose a status.

    Completeness is the canonical operational activation gate shared with the
    explicit ``/activate`` path.  An explicit status always wins, including an
    intentional ``draft`` used while the operator is still preparing the
    record.  Only editable drafts are eligible: ``ready_for_signature`` keeps
    its separate lifecycle and still requires an explicit activation.

    A future ``start_date`` satisfies the gate deliberately, just as it does for
    explicit activation and the established order lifecycle. Financial reports
    apply their separate date-effective window; status-only operational views
    may show the ready contract before work starts.

    Returns ``True`` only when this call performed the transition.  The helper
    deliberately delegates to :func:`activate_contract` so automatic and
    manual activation share transition validation and the same audit event.
    """
    if status_explicit or contract.status != ContractStatus.draft:
        return False
    if validate_ready_for_activation(contract):
        return False

    await activate_contract(db, contract, actor_id=actor_id)
    return True


async def move_to_ready_for_signature(
    db: AsyncSession, contract: Contract, *, actor_id: Optional[int]
) -> None:
    """Finalize an unsigned draft to ``ready_for_signature`` (never ``active``).

    Requires the same complete-draft check as activation, so a contract that
    reaches signing is never missing the fields the signed record depends on.
    """
    previous = contract.status
    assert_transition(previous, ContractStatus.ready_for_signature)

    missing = validate_ready_for_activation(contract)
    if missing:
        raise HTTPException(
            status_code=http_status.HTTP_409_CONFLICT,
            detail={"message": "Missing required fields", "missing": missing},
        )

    contract.status = ContractStatus.ready_for_signature
    db.add(
        _audit(
            contract.id,
            "contract_ready_for_signature",
            actor_id,
            from_status=previous,
            to_status=ContractStatus.ready_for_signature,
        )
    )


async def revert_contract(
    db: AsyncSession,
    contract: Contract,
    *,
    actor_id: Optional[int],
    reason: Optional[str] = None,
) -> None:
    """Audited revert to ``draft`` — the replacement for the old free status write.

    Legitimate cases: a mistakenly activated/finalized contract that needs to go
    back to editing. Terminal metadata (termination reason/lessons) is cleared so
    a reverted contract is a clean draft again.
    """
    previous = contract.status
    if previous == ContractStatus.draft:
        return
    assert_transition(previous, ContractStatus.draft)

    contract.status = ContractStatus.draft
    contract.termination_reason = None
    contract.termination_lessons = None
    contract.terminated_at = None
    db.add(
        _audit(
            contract.id,
            "contract_reverted",
            actor_id,
            from_status=previous,
            to_status=ContractStatus.draft,
            extra={"reason": reason} if reason else None,
        )
    )


async def reopen_contract(
    db: AsyncSession, contract: Contract, *, actor_id: Optional[int]
) -> bool:
    """Heal an ``ended``/``ending`` contract back to ``active`` (e.g. on extend).

    Returns True when a change happened. Reactivating an already-executed
    contract is not a fresh activation, so no signature check applies — the
    evidence already exists from when it was first executed.

    JEDYNE miejsce tej reguły. Do sierpnia 2026 była wklejona ręcznie w dwóch
    kopiach w `app/api/contracts.py` (bulk `/bulk-extend` i `/amendments`);
    obie przestawiały `status` wprost, więc omijały `assert_transition` i NIE
    zapisywały wiersza `Activity` `contract_reopened` — przejście najściślej
    powiązane z przychodem (zakończony konsultant wracający na `active`, bo
    współpracę przedłużono) było jedynym bez śladu `from_status`/`to_status`
    w feedzie aktywności. Nowe ścieżki przedłużania wołają tę funkcję zamiast
    dopisywać trzecią kopię.

    Nie myl jej z `reopen_contract_endpoint` w routerze: mimo nazwy woła on
    `revert_contract` (→ `draft`), a nie tę operację.
    """
    previous = contract.status
    if previous not in (ContractStatus.ended, ContractStatus.ending):
        return False
    assert_transition(previous, ContractStatus.active)
    contract.status = ContractStatus.active
    db.add(
        _audit(
            contract.id,
            "contract_reopened",
            actor_id,
            from_status=previous,
            to_status=ContractStatus.active,
        )
    )
    return True


def order_period_covers(
    start: Optional[date], end: Optional[date], today: date
) -> bool:
    """Czy okres zamówienia OBEJMUJE dzień ``today``.

    Brak daty końca = „bezterminowo", więc okres sięga w prawo bez granicy
    (ta sama semantyka co ``ClientOrder.end_date IS NULL`` w zapytaniach).
    Brak daty startu NIE jest traktowany jak „od zawsze": zamówienie bez daty
    rozpoczęcia nie mówi, że już trwa, a to jest przesłanka wskrzeszenia
    zakończonego kontraktu — zgadywanie tutaj wpuszczałoby ludzi z powrotem
    do MRR na podstawie pustego pola.
    """
    if start is None or start > today:
        return False
    return end is None or end >= today


async def sync_contract_to_live_order(
    db: AsyncSession,
    contract: Contract,
    *,
    order_start: Optional[date],
    order_end: Optional[date],
    actor_id: Optional[int],
    today: Optional[date] = None,
) -> bool:
    """Dopasuj kontrakt do zamówienia, które WŁAŚNIE TRWA. Zwraca True przy zmianie.

    Kanoniczny niezmiennik dla KAŻDEGO writera żywego zamówienia. Aneks
    (``/amendments``) i ``/bulk-extend`` przesuwają ``end_date`` i wołają
    :func:`reopen_contract`; zwykły POST zamówienia deleguje tutaj. Regresja
    powstała, gdy późniejsze writery — import Nordea, PATCH kompletujący draft
    oraz linie zamówień grupowych — zaczęły tworzyć taki sam stan ``active``,
    ale nie użyły tego serwisu. Pigułka czyta ``contract_status``, więc dopóki
    kontrakt jest ``ended``, sama zmiana po stronie zamówień nie przenosi osoby
    z „Zakończonych”; razem z pigułką milczą MRR, rejestr umów i skaner
    wygasania.

    Decyduje WYŁĄCZNIE porównanie dat z dniem dzisiejszym, nie to, z której
    zakładki operator kliknął. Przedłużenie zaczynające się w przyszłości nie
    zmienia więc niczego (ląduje w „Przyszłym zamówieniu”).

    Wskrzeszony kontrakt staje się BEZTERMINOWY (reguła zakładki „Zakończeni",
    09.2026): zamówienie nigdy nie ustawia daty końca umowy — tę wpisuje
    administracja w module Kontrakty. Do 09.2026 kontrakt dostawał tu datę
    końca ZAMÓWIENIA, a gdy jego okres mijał, nocny ``_promote_statuses``
    kończył umowę i osoba lądowała w „Zakończonych" tylko dlatego, że upłynął
    okres zamówienia (VeloBank: 4 z 11 osób na tym samym zamówieniu, w tym
    kontraktor czekający na przedłużenie). Cron pomija ``end_date IS NULL``,
    więc bezterminowa umowa nie jest demotowana „tej samej nocy".
    """
    # Serialize against terminal-state writers before reading any lifecycle
    # field. A caller may hold an identity-map object loaded before a concurrent
    # ``void`` commit; the locked scalar projection reads the committed state
    # after the lock wait, so terminal ``void`` always wins. Suppress autoflush:
    # Nordea and order routes can have unrelated pending Order/rate changes in
    # the same transaction, and acquiring this parent lock must not publish
    # those changes early merely as a side effect of the SELECT.
    if contract.id is None:
        return False
    with db.no_autoflush:
        locked_row = (
            await db.execute(
                select(
                    Contract.status,
                    Contract.end_date,
                    Contract.client_order_end_date,
                )
                .where(Contract.id == contract.id)
                .with_for_update()
            )
        ).one_or_none()
    if locked_row is None:
        return False

    # Copy only the lifecycle scalars read under the row lock. Refreshing the
    # ORM entity with ``populate_existing`` expires eager-loaded relationships
    # (candidate/framework-rate schedule); touching them later in an async
    # writer then attempts forbidden implicit IO and raises MissingGreenlet.
    # A scalar projection preserves those relationships and every unrelated
    # pending field while still making a concurrent terminal ``void`` win.
    (
        contract.status,
        contract.end_date,
        contract.client_order_end_date,
    ) = locked_row

    # WYŁĄCZNIE kontrakt zakończony/kończący się. Trzy powody, każdy osobny:
    #
    #  * ``void`` jest TERMINALNY (soft-delete zachowujący dokumenty i hashe
    #    podpisów, ``ALLOWED_TRANSITIONS[void] == frozenset()``), a zamówienie
    #    da się dopiąć do dowolnego kontraktu klienta — ``create_order_extension``
    #    nie filtruje statusu. Bez tej bramki dodanie zamówienia po cichu
    #    przesuwałoby datę końca umowy UNIEWAŻNIONEJ;
    #  * ``draft`` ma własny walidowany cykl życia (komplet pól + ewentualny
    #    podpis) — wejście do przychodu tylnymi drzwiami przez zamówienie
    #    omijałoby dokładnie te bramki;
    #  * ``active``/``ending`` z dalszą datą końca niż zamówienie: przed tą
    #    zmianą dodanie zamówienia NIE ruszało horyzontu kontraktu i nikt o to
    #    nie prosił. Rozszerzanie tego przy okazji zmieniałoby zachowanie,
    #    którego ticket nie dotyczy.
    #
    # ``ending`` zostaje w zbiorze, bo ``reopen_contract`` obsługuje je razem
    # z ``ended`` i to jest ta sama sytuacja: współpraca miała się skończyć,
    # a zamówienie mówi, że trwa.
    if contract.status not in (ContractStatus.ended, ContractStatus.ending):
        return False

    if not order_period_covers(order_start, order_end, today or date.today()):
        return False

    changed = False
    # Data końca UMOWY nie pochodzi z zamówienia (patrz docstring): kontrakt
    # wraca jako bezterminowy, a od sierpnia 2026 taki kontrakt jest w pełni
    # operacyjny (`ACTIVATION_REQUIRED_FIELDS` bez `end_date`).
    if contract.end_date is not None:
        contract.end_date = None
        changed = True
    # ``client_order_end_date`` („Koniec zamówienia u klienta") is the
    # explicitly tracked mirror of the client-order horizon — THAT is where an
    # order-derived date belongs.  Keep NULL as "not tracked" instead of
    # inventing a date, but never leave a past date next to a revived
    # contract.  This used to live in the ``client_orders`` route adapter,
    # which meant service-level writers such as the Nordea CSV import and
    # scheduled group materializer could not reuse the complete invariant
    # without importing the API layer.
    if (
        contract.client_order_end_date is not None
        and contract.client_order_end_date != order_end
    ):
        contract.client_order_end_date = order_end
        changed = True

    if await reopen_contract(db, contract, actor_id=actor_id):
        changed = True
    return changed


_LIVE_ORDER_REPAIR_MARKER = "0250_live_order_contract_repair"


def _live_order_reconcile_window(
    receipt: object, *, today: date
) -> tuple[date, frozenset[int]]:
    """Resolve the safe catch-up window persisted by migration 0250.

    The migration receipt is the boundary between the deliberately read-only
    historical audit and orders whose future start must be materialized by the
    daily lifecycle.  Contracts already present in that audit remain excluded
    on the cut-over day itself; a later-starting order for the same contract is
    still a new temporal transition and therefore remains eligible.

    Missing or malformed evidence fails closed to the original one-day window.
    """

    if not isinstance(receipt, dict):
        return today, frozenset()
    raw_day = receipt.get("business_day")
    raw_audited_ids = receipt.get("audited_contract_ids")
    if not isinstance(raw_day, str) or not isinstance(raw_audited_ids, list):
        return today, frozenset()
    try:
        cutover_day = date.fromisoformat(raw_day)
    except ValueError:
        return today, frozenset()
    if cutover_day > today or any(
        not isinstance(contract_id, int) or isinstance(contract_id, bool)
        for contract_id in raw_audited_ids
    ):
        return today, frozenset()
    return cutover_day, frozenset(raw_audited_ids)


async def reconcile_contracts_to_live_orders(
    db: AsyncSession,
    *,
    today: date,
) -> int:
    """Heal contracts when any previously future active order starts.

    Writer-time synchronization intentionally ignores a future order: it is
    not evidence that the consultant works today.  Without the complementary
    daily transition, however, an ``ended`` contract would stay ended after
    that order's start date arrived.  This reconciliation covers that temporal
    edge and delegates every mutation and audit row to
    :func:`sync_contract_to_live_order`.

    Every active order which started between the 0250 deployment watermark and
    ``today`` qualifies, whether it is standalone or a line in a
    multi-consultant group.  The latter matters for add/swap lines which may
    begin after their already-active group.  This bounded catch-up survives a
    missed daily run without silently repairing the historical backlog.  The
    migration receipt's audited contracts remain excluded on the cut-over day
    itself; historical analogues stay audit-only and the explicit repair
    migration owns its narrow approved target set.

    Draft, paused, completed, cancelled, future, expired and pre-cut-over legacy
    orders are excluded by the query.  The group materializer may
    synchronize the same line first; this pass remains idempotent because a
    healed contract no longer has an ``ended``/``ending`` status.  When one
    contract has several eligible orders, the open-ended or latest-ending one is
    processed first so the single reopening also captures the widest horizon.
    """

    # Local import keeps the contract state machine independent from the order
    # model during application bootstrap while still putting the invariant in
    # the reusable lifecycle layer rather than in a task-only helper.
    from app.models.client_order import ClientOrder, ClientOrderStatus

    marker = await db.get(AppSetting, _LIVE_ORDER_REPAIR_MARKER)
    cutover_day, audited_on_cutover = _live_order_reconcile_window(
        marker.value if marker is not None else None,
        today=today,
    )
    result = await db.execute(
        select(ClientOrder, Contract)
        .join(Contract, Contract.id == ClientOrder.contract_id)
        .where(
            ClientOrder.status == ClientOrderStatus.active,
            ClientOrder.start_date.between(cutover_day, today),
            or_(ClientOrder.end_date.is_(None), ClientOrder.end_date >= today),
            ClientOrder.client_id == Contract.client_id,
            Contract.status.in_([ContractStatus.ended, ContractStatus.ending]),
        )
        .order_by(
            Contract.id.asc(),
            ClientOrder.end_date.desc().nullsfirst(),
            ClientOrder.id.desc(),
        )
        # Wait for the short writer transaction and serialize the canonical
        # sync.  Avoiding SKIP LOCKED also means the first catch-up pass does not
        # need another day to observe a row concurrently edited at scan time.
        .with_for_update(of=[ClientOrder, Contract])
    )

    reconciled = 0
    seen_contract_ids: set[int] = set()
    for order, contract in result:
        if order.start_date == cutover_day and contract.id in audited_on_cutover:
            continue
        if contract.id in seen_contract_ids:
            continue
        seen_contract_ids.add(contract.id)
        if await sync_contract_to_live_order(
            db,
            contract,
            order_start=order.start_date,
            order_end=order.end_date,
            actor_id=None,
            today=today,
        ):
            reconciled += 1
    return reconciled


async def void_contract(
    db: AsyncSession,
    contract: Contract,
    *,
    actor_id: Optional[int],
    reason: Optional[str] = None,
) -> None:
    """Soft-delete: annul the contract while preserving documents + signatures.

    The safe alternative to a hard DELETE for executed/active contracts. Sets
    ``status = void`` + ``voided_at`` / ``voided_by``; the caller commits.
    """
    previous = contract.status
    if previous == ContractStatus.void:
        raise ContractTransitionError(
            {"message": "Contract is already void", "from": previous.value}
        )
    assert_transition(previous, ContractStatus.void)

    contract.status = ContractStatus.void
    contract.voided_at = datetime.now(timezone.utc)
    contract.voided_by = actor_id
    db.add(
        _audit(
            contract.id,
            "contract_voided",
            actor_id,
            from_status=previous,
            to_status=ContractStatus.void,
            extra={"reason": reason} if reason else None,
        )
    )


def signed_generated_link_filter(contract: Contract) -> ColumnElement[bool]:
    """Kryterium: podpisana umowa B2B, która NAPRAWDĘ chroni TEN kontrakt.

    Zasada: „blokuj, chyba że **wiadomo na pewno**, że to inny projekt". Link
    jest jawnie rozjechany dokładnie wtedy, gdy wygenerowana umowa wskazuje
    swojego klienta i jest to **inny** klient niż klient kontraktu — wtedy jej
    podpis dotyczy innego projektu i nie ma prawa blokować tego wiersza.
    Produkcja pokazuje, skąd taki rozjazd się bierze: reaktywacja umowy
    z zawieszenia przepisywała `client_id`/`client_name` na nowy projekt,
    zostawiając `contract_id` na kontrakcie poprzedniego (patrz przepięcie
    w ``update_generated_contract``) — stary projekt był chroniony cudzym
    podpisem, a nowy nie był chroniony wcale.

    ``client_id IS NULL`` MUSI chronić: umowy standalone dostają klienta
    tylko przy powiązaniu z rekrutacją, a wiersze historyczne (0196 bez
    backfillu) nie mają go wcale. Gołe porównanie kolumn dałoby dla nich FALSE
    i zdjęłoby ochronę z prawidłowo podpisanych umów.

    Zwraca kryterium do doklejenia obok warunku na ``contract_id`` — ta sama
    funkcja opisuje blokadę (``hard_delete_blocker``) i jej dopełnienie
    w odpinaniu przed DELETE (FK jest RESTRICT, więc rozjazd tych dwóch reguł
    kończy się 500-tką zamiast czytelnej odmowy).
    """
    from app.models.b2b_generated_contract import B2BGeneratedContract

    return and_(
        B2BGeneratedContract.signature_status == "signed_both",
        or_(
            B2BGeneratedContract.client_id.is_(None),
            B2BGeneratedContract.client_id == contract.client_id,
        ),
    )


def _normalise_signed_delete_confirmation(value: str) -> str:
    """Normalise casing/whitespace only, never spelling or diacritics.

    NFKC makes visually equivalent Unicode input compare consistently (for
    example a non-breaking space pasted from a document). Collapsing whitespace
    mirrors the confirmation modal and tolerates formatting, not identity
    differences; Polish diacritics and every non-whitespace character remain
    exact. A typo must therefore stay a mismatch: this value authorises an
    irreversible operation.
    """
    normalised_unicode = unicodedata.normalize("NFKC", value)
    return " ".join(normalised_unicode.split()).casefold()


async def _signed_delete_confirmation_method(
    db: AsyncSession,
    contract: Contract,
    confirmation: str,
) -> Optional[Literal["contractor_name", "contract_id"]]:
    """Return the exact confirmation kind, or ``None`` on any mismatch."""
    normalised = _normalise_signed_delete_confirmation(confirmation)
    contract_id = str(contract.id)
    if normalised in {contract_id, f"#{contract_id}"}:
        return "contract_id"

    if contract.candidate_id is None:
        return None

    # Explicit columns avoid an async lazy-load through ``contract.candidate``.
    # The contract parent is already FOR UPDATE-locked by the caller. Candidate
    # deletion can only turn this FK into NULL; the contract number remains a
    # stable confirmation fallback in that rare race.
    from app.models.candidate import Candidate

    candidate_name = await db.execute(
        select(Candidate.name, Candidate.lastname).where(
            Candidate.id == contract.candidate_id
        )
    )
    name_parts = candidate_name.one_or_none()
    if name_parts is None:
        return None
    expected = f"{name_parts.name.strip()} {name_parts.lastname.strip()}"
    if normalised == _normalise_signed_delete_confirmation(expected):
        return "contractor_name"
    return None


async def hard_delete_blocker(
    db: AsyncSession, contract: Contract
) -> Optional[HardDeleteBlocker]:
    """Powód blokady hard delete — ``None`` znaczy „wolno usunąć".

    Decyzja 2026-08-25 (ticket „Usunięcie kontraktu nie działa mimo
    potwierdzenia"): błędnie dodany albo zdublowany kontrakt musi dać się
    skasować z modułu Kontrakty NIEZALEŻNIE OD STATUSU — dawna reguła „tylko
    szkic" czytała się w UI jak „potwierdziłem i nic". Usuwany jest wyłącznie
    wiersz kontraktu i jego pod-zasoby (FK CASCADE); kandydat zostaje, a
    NIEPODPISANE wygenerowane umowy B2B zostają w rejestrze — endpoint DELETE
    odpina je przed kasowaniem (``contract_id`` → NULL, stan „umowa bez
    projektu"). Stara reguła miała tu zresztą dziurę: szkic z niepodpisaną
    wygenerowaną umową przechodził guard i wywracał się dopiero na FK RESTRICT
    przy commicie (nieobsłużony 500).

    Blokują wyłącznie PODPISANE dowody — bo błędny duplikat nie bywa podpisany,
    a podpisany kontrakt to zapis prawnie wykonanego zobowiązania:

    * ``completed_signature`` — ukończony ``DocumentSignature``; FK jest
      CASCADE, więc hard delete zniszczyłby kryptograficzny dowód podpisu.
    * ``signed_generated_contract`` — umowa B2B potwierdzona jako podpisana
      obustronnie (``signed_both``, audytowane ``confirm-fully-signed``);
      wiersz wygenerowany jest w tym stanie nieedytowalny i niekasowalny
      (patrz ``test_b2b_signature_automation``), więc auto-utworzony z niego
      kontrakt chronimy symetrycznie. FK RESTRICT jest strażnikiem ostatniej
      szansy w bazie. Link jawnie wskazujący INNEGO klienta niż kontrakt
      ochrony nie daje — patrz ``signed_generated_link_filter``.

    Zapytanie pyta wyłącznie po ``contract_id == contract.id``, więc jest już
    per PROJEKT: projekt to osobny wiersz ``Contract``, a konsolidacja
    kontraktorów po ``candidate_id`` jest tylko warstwą prezentacji i nie
    zaciąga tu rodzeństwa.

    Zablokowany kontrakt można anulować (``void``) — dokumenty i dowody
    zostają. ``signed_generated_contract`` ma ponadto jawny, admin-only
    break-glass w ``hard_delete_contract``; ta funkcja nadal raportuje blocker,
    aby wymuszenie nigdy nie stało się domyślnym DELETE-em.
    """
    if await _has_completed_signature(db, contract.id):
        return "completed_signature"

    # Import lokalny — jak w innych miejscach tego modułu — żeby nie sprzęgać
    # grafu importów lifecycle'u z generatorem B2B.
    from app.models.b2b_generated_contract import B2BGeneratedContract

    signed_generated_id = await db.scalar(
        select(B2BGeneratedContract.id)
        .where(
            B2BGeneratedContract.contract_id == contract.id,
            signed_generated_link_filter(contract),
        )
        .limit(1)
    )
    if signed_generated_id is not None:
        return "signed_generated_contract"
    return None


async def hard_delete_contract(
    db: AsyncSession,
    contract: Contract,
    *,
    actor_id: Optional[int],
    force_signed_confirmation: Optional[str] = None,
) -> HardDeleteResult:
    """Physically delete one contract under the signed-evidence policy.

    This is the shared implementation behind the HTTP DELETE endpoint and
    trusted batch maintenance. The caller owns the surrounding transaction;
    this helper flushes so FK cascades/SET NULL and cost-order resettlement are
    complete before it returns, but it deliberately never commits.

    Project-owned children follow their declared FK policy (CASCADE or
    SET NULL). Generated B2B rows are detached and preserved in their register.
    Completed qualified signatures remain an unconditional hard blocker because
    their FK would cascade-delete the proof. A protective ``signed_both`` B2B
    can be overridden only when the dedicated admin route supplies an exact
    contractor-name or contract-number confirmation. That forced path is
    recorded with its own durable audit action. Polymorphic Activity/
    Notification history is not rewritten.
    """
    # Lock the FK parent before looking at any deletion blocker. PostgreSQL FK
    # inserts acquire KEY SHARE on the parent, which conflicts with this
    # UPDATE lock: a new signature/generated agreement therefore either
    # commits before this statement (and is included in the child locks below)
    # or waits until the delete transaction ends and then fails its FK check.
    # ``populate_existing`` is intentional because callers may have loaded the
    # object before a concurrent client/status update; blocker predicates must
    # use the values protected by this lock, not a stale identity-map snapshot.
    contract_id = int(contract.id)
    locked_contract = await db.scalar(
        select(Contract)
        .where(Contract.id == contract_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if locked_contract is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail="Contract not found",
        )
    contract = locked_contract

    # Existing children can change status without touching their FK, so the
    # parent lock alone is insufficient. Lock every row in a stable order
    # before evaluating ``completed`` / ``signed_both``. Writers that started
    # first finish before the blocker is evaluated; later writers wait until
    # the hard-delete transaction commits or rolls back.
    (
        await db.scalars(
            select(DocumentSignature.id)
            .where(DocumentSignature.contract_id == contract_id)
            .order_by(DocumentSignature.id)
            .with_for_update()
        )
    ).all()

    # Local imports keep the lifecycle module's import graph independent from
    # the generated-contract and cost-order feature modules.
    from app.models.b2b_generated_contract import B2BGeneratedContract

    (
        await db.scalars(
            select(B2BGeneratedContract.id)
            .where(B2BGeneratedContract.contract_id == contract_id)
            .order_by(B2BGeneratedContract.id)
            .with_for_update()
        )
    ).all()

    blocker = await hard_delete_blocker(db, contract)
    forced_signed_delete = False
    confirmation_method: Optional[Literal["contractor_name", "contract_id"]] = None
    if force_signed_confirmation is not None:
        # A distinct break-glass endpoint must not become a second generic
        # DELETE. Re-check the blocker only after all relevant rows are locked;
        # this is the TOCTOU boundary that matters, not the route's pre-load.
        if blocker != "signed_generated_contract":
            if blocker is not None:
                raise ContractHardDeleteBlocked(contract, blocker)
            raise ContractSignedDeleteUnavailable(contract_id)
        confirmation_method = await _signed_delete_confirmation_method(
            db, contract, force_signed_confirmation
        )
        if confirmation_method is None:
            raise ContractSignedDeleteConfirmationError(contract_id)
        forced_signed_delete = True
    elif blocker is not None:
        raise ContractHardDeleteBlocked(contract, blocker)

    from app.models.client_order import ClientOrder
    from app.models.client_order_group import ClientOrderGroup
    from app.services.cost_orders import settle_group

    # ``order_group_id`` is mutable without touching the contract parent.  Lock
    # every affected line before taking the group snapshot, otherwise a
    # concurrent detach/reassignment can make us settle the old group while the
    # cascade removes a line from the new one.  The stable ID order matches the
    # batch merge's child-lock discipline.
    order_rows = (
        await db.execute(
            select(ClientOrder.id, ClientOrder.order_group_id)
            .where(ClientOrder.contract_id == contract_id)
            .order_by(ClientOrder.id)
            .with_for_update()
        )
    ).all()
    affected_group_ids = tuple(
        sorted(
            {
                int(row.order_group_id)
                for row in order_rows
                if row.order_group_id is not None
            }
        )
    )

    detach_filter = B2BGeneratedContract.contract_id == contract_id
    if not forced_signed_delete:
        detach_filter = and_(
            detach_filter,
            not_(signed_generated_link_filter(contract)),
        )
    detached = await db.execute(
        update(B2BGeneratedContract).where(detach_filter).values(contract_id=None)
    )

    # Same last-chance guard as the endpoint historically used.  On the forced
    # path this is an explicit postcondition for the unconditional detach; on
    # the regular path it also protects any signed row excluded by the filter.
    # Either way, a remaining link is protective evidence and FK RESTRICT must
    # not be bypassed.  Keeping the domain error here also avoids exposing a
    # lower-level FK failure if this UPDATE is narrowed in the future.
    still_linked = await db.scalar(
        select(B2BGeneratedContract.id)
        .where(B2BGeneratedContract.contract_id == contract_id)
        .limit(1)
    )
    if still_linked is not None:
        raise ContractHardDeleteBlocked(contract, "signed_generated_contract")

    audit_details: dict[str, object] = {
        "status": contract.status.value,
        "candidate_id": contract.candidate_id,
        "client_id": contract.client_id,
    }
    audit_action = "deleted"
    if forced_signed_delete:
        audit_action = "force_deleted_signed"
        audit_details.update(
            {
                "contract_id": contract_id,
                "forced_despite_signed": True,
                "blocker": "signed_generated_contract",
                "confirmation_method": confirmation_method,
            }
        )
    db.add(
        Activity(
            entity_type="contract",
            entity_id=contract_id,
            action=audit_action,
            user_id=actor_id,
            details=audit_details,
        )
    )
    await db.delete(contract)
    # Force DELETE + FK actions before settlement and before returning to a
    # batch caller. This also surfaces an unexpected RESTRICT in this helper's
    # transaction rather than at an unrelated later commit.
    await db.flush()

    # Cost settlement writes stored totals on the group.  Take these locks only
    # after the cascade has finished: invoice import acquires consumption-row
    # locks before settling, so group-before-cascade would invert that order and
    # create a deadlock.  Stable group-ID order serializes the recomputation;
    # ``settle_group`` repeats the lock as the central invariant for every
    # caller and refreshes state after any wait.
    locked_groups = (
        (
            await db.scalars(
                select(ClientOrderGroup)
                .where(ClientOrderGroup.id.in_(affected_group_ids))
                .order_by(ClientOrderGroup.id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        ).all()
        if affected_group_ids
        else []
    )
    for group in locked_groups:
        await settle_group(db, group)

    return HardDeleteResult(
        contract_id=contract_id,
        detached_generated_contracts=int(detached.rowcount or 0),
        settled_order_group_ids=affected_group_ids,
    )
