"""Contract lifecycle — one guarded state machine, one activation invariant.

The finding (P1-CONTRACT-01): the contract lifecycle had no single hard
invariant. ``status`` was writable from the create/update schemas, ``/activate``
and ``/draft/finalize`` reached ``active`` (and emitted ``contract_signed``) with
no signed evidence, and a hard DELETE could cascade signature evidence away.

This module is the single source of truth for status transitions. Every
side-effectful status change goes through one of the guarded operations below;
no route sets ``status = active`` directly. The rules:

* :data:`ALLOWED_TRANSITIONS` — the only legal (from → to) edges.
* :func:`activate_contract` — the ONLY path to ``active``. It always requires
  the draft to be complete and, for guarded signing flows, a *completed*
  qualified ``DocumentSignature``. Manual contract creation explicitly
  disables only that signature gate because it also records offline agreements;
  later status changes keep the guarded default.
* :func:`move_to_ready_for_signature` — a finalized (but unsigned) draft lands
  here, never at ``active``.
* :func:`revert_contract` — the audited replacement for the old free
  ``PATCH {status: draft}`` revert.
* :func:`void_contract` — soft-delete preserving documents + signature hashes.

Isolated from the route handlers so the invariant can be unit-tested without a
FastAPI rig, and reused by the signing pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Literal, Optional

from fastapi import HTTPException, status as http_status
from sqlalchemy import ColumnElement, and_, not_, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.activity import Activity
from app.models.contract import Contract, ContractStatus, ContractType
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
            "przez obie strony i nie może zostać usunięty. Zamiast tego "
            "anuluj kontrakt (void) albo zamknij umowę w rejestrze "
            "„Wygenerowane umowy”."
        ),
    }

    def __init__(self, contract: Contract, reason: HardDeleteBlocker) -> None:
        self.reason = reason
        super().__init__(
            status_code=http_status.HTTP_409_CONFLICT,
            detail={
                "code": f"contract_has_{reason}",
                "message": self._MESSAGES[reason],
                "status": contract.status.value,
                "void_endpoint": f"/api/contracts/{contract.id}/void",
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


async def _has_any_signature(db: AsyncSession, contract_id: int) -> bool:
    """True when any ``DocumentSignature`` row exists for the contract.

    Once a signing process is initiated, activation must wait for a *completed*
    signature — you cannot start signing and then bypass it via ``/activate``.
    """
    found = await db.scalar(
        select(DocumentSignature.id)
        .where(DocumentSignature.contract_id == contract_id)
        .limit(1)
    )
    return found is not None


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


def signature_required(contract: Contract, *, has_signatures: bool) -> bool:
    """Whether a completed qualified signature is required to activate.

    Required when:
      * a signing process was ever initiated for the contract (``has_signatures``)
        — you must finish what you started, or
      * the draft was finalized for signing (``ready_for_signature``) AND the
        in-house rail is enabled, or
      * the in-house signing rail is enabled for this signature-requiring type
        (B2B).

    When signing is disabled (``SIGNING_ENABLED=false``, the prod default) and no
    signature was ever started, activation proceeds on field validation alone —
    the legacy manual/offline flow is preserved, no regression.
    """
    if has_signatures:
        return True
    if not settings.SIGNING_ENABLED:
        return False
    if contract.status == ContractStatus.ready_for_signature:
        return True
    return contract.contract_type == ContractType.b2b


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
    enforce_signature_gate: bool = True,
) -> None:
    """The ONLY path to ``active``. Adds the audit row; the caller commits.

    Enforces, in order: a legal transition, a complete draft, and — when
    ``enforce_signature_gate`` is true and a signature is required — verified
    signed evidence (a ``completed`` ``DocumentSignature``). Any failure raises
    HTTP 409 and leaves state unchanged. Downstream side effects
    (``contract_signed`` notification) MUST be emitted by the caller only AFTER
    the activation commit.
    """
    previous = contract.status
    assert_transition(previous, ContractStatus.active)

    missing = validate_ready_for_activation(contract)
    if missing:
        raise HTTPException(
            status_code=http_status.HTTP_409_CONFLICT,
            detail={"message": "Missing required fields", "missing": missing},
        )

    # The manual register stores contracts backed by offline agreements and
    # amendments, so its caller opts out before either signature lookup runs.
    # Guarded signing endpoints keep the default and therefore the hard gate.
    if enforce_signature_gate:
        has_sig = await _has_any_signature(db, contract.id)
        if signature_required(contract, has_signatures=has_sig):
            if not await _has_completed_signature(db, contract.id):
                raise HTTPException(
                    status_code=http_status.HTTP_409_CONFLICT,
                    detail={
                        "message": (
                            "Contract requires a completed qualified signature "
                            "before it can be activated"
                        ),
                        "reason": "signature_required",
                    },
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

    Trzecia — i do tej pory jedyna pominięta — ścieżka przedłużania współpracy.
    Aneks (``/amendments``) i ``/bulk-extend`` przesuwają ``end_date``
    i wołają :func:`reopen_contract`; dodanie zamówienia pod istniejący
    kontrakt nie robiło ani jednego, ani drugiego. Skutek zgłoszony przez
    użytkownika: przedłużenie dodane do kontraktora z zakładki „Zakończeni”
    zostawiało go w „Zakończonych”, mimo że okres nowego zamówienia obejmuje
    dziś. Pigułka czyta ``contract_status``, więc dopóki kontrakt jest
    ``ended``, żadna zmiana po stronie zamówień tego nie ruszy — a razem
    z pigułką milczą MRR, rejestr umów i skaner wygasania.

    Decyduje WYŁĄCZNIE porównanie dat z dniem dzisiejszym, nie to, z której
    zakładki operator kliknął. Przedłużenie zaczynające się w przyszłości nie
    zmienia więc niczego (ląduje w „Przyszłym zamówieniu”), a data końca
    kontraktu rośnie razem ze statusem: bez tego nocny ``_promote_statuses``
    zdemotowałby wskrzeszony kontrakt z powrotem do ``ended`` jeszcze tej nocy
    i poprawka kasowałaby samą siebie.
    """
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
    # Horyzont kontraktu musi sięgać co najmniej tak daleko jak zamówienie.
    # Zamówienie bezterminowe czyni bezterminowym także kontrakt — to jest
    # dosłownie to, co mówią dane, a od sierpnia 2026 taki kontrakt jest
    # aktywowalny (`ACTIVATION_REQUIRED_FIELDS` bez `end_date`).
    if order_end is None:
        if contract.end_date is not None:
            contract.end_date = None
            changed = True
    elif contract.end_date is not None and order_end > contract.end_date:
        contract.end_date = order_end
        changed = True

    if await reopen_contract(db, contract, actor_id=actor_id):
        changed = True
    return changed


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
    zostają.
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
) -> HardDeleteResult:
    """Physically delete one contract without destroying signed evidence.

    This is the shared implementation behind the HTTP DELETE endpoint and
    trusted batch maintenance. The caller owns the surrounding transaction;
    this helper flushes so FK cascades/SET NULL and cost-order resettlement are
    complete before it returns, but it deliberately never commits.

    Project-owned children follow their declared FK policy (CASCADE or
    SET NULL). Generated B2B rows that do not legally protect this project are
    detached and preserved in their register. Completed qualified signatures
    and a ``signed_both`` B2B that belongs to this client remain hard blockers.
    Polymorphic Activity/Notification history is not rewritten.
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
    if blocker is not None:
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

    detached = await db.execute(
        update(B2BGeneratedContract)
        .where(
            B2BGeneratedContract.contract_id == contract_id,
            not_(signed_generated_link_filter(contract)),
        )
        .values(contract_id=None)
    )

    # Same last-chance guard as the endpoint historically used: a row left
    # linked after the complementary UPDATE is protective signed evidence (or
    # became protective concurrently), so FK RESTRICT must not be bypassed.
    still_linked = await db.scalar(
        select(B2BGeneratedContract.id)
        .where(B2BGeneratedContract.contract_id == contract_id)
        .limit(1)
    )
    if still_linked is not None:
        raise ContractHardDeleteBlocked(contract, "signed_generated_contract")

    db.add(
        Activity(
            entity_type="contract",
            entity_id=contract_id,
            action="deleted",
            user_id=actor_id,
            details={
                "status": contract.status.value,
                "candidate_id": contract.candidate_id,
                "client_id": contract.client_id,
            },
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
