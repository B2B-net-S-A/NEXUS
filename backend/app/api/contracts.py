import calendar
import logging
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from io import BytesIO
from typing import Annotated, Any, List, Literal, Optional

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    UploadFile,
    status,
)
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from starlette.concurrency import run_in_threadpool
from jinja2 import TemplateError
from sqlalchemy import String, case, cast, distinct, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.analytics.capabilities import AnalyticsCapability, user_has_capability
from app.api.contract_templates import _contract_vars, _jinja_env
from app.core.printable_html import (
    AUTOPRINT_HASH,
    AUTOPRINT_JS,
    PRINTABLE_CSP,
    printable_document,
)
from app.core.database import get_db
from app.core.scheduling import business_today
from app.core.work_time import HOURS_PER_MONTH, MD_PER_MONTH
from app.models.activity import Activity
from app.models.call import Call
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.client_order import ClientOrder, ClientOrderStatus
from app.models.contract import (
    Contract,
    ContractStatus,
    ContractTerminationReason,
    EngagementModel,
    RateUnit,
)
from app.models.contract_amendment import ContractAmendment, ContractAmendmentType
from app.models.contract_candidate_rate import ContractCandidateRate
from app.models.contract_client_rate import ContractClientRate
from app.models.contract_framework_rate import ContractFrameworkRate
from app.models.contract_equipment import ContractEquipment, EquipmentReturnStatus
from app.models.contract_onboarding import ContractOnboardingItem
from app.models.contract_document import ContractDocument, ContractDocumentType
from app.models.contract_template import ContractTemplate
from app.models.b2b_contract_detail import B2BContractDetail
from app.models.job import Job
from app.models.note import Note
from app.models.rate_benchmark import RateBenchmark
from app.models.rate_history import RateHistory
from app.models.user import User, UserRole
from app.schemas.contract import (
    ContractActivateRequest,
    ContractActivityEntry,
    ContractBenchmarkComparison,
    ContractCandidateRateEntry,
    ContractClientRateEntry,
    ContractFrameworkRateEntry,
    ContractCreate,
    AgreementTerminationPayload,
    ContractDetailResponse,
    ContractEurPlnRate,
    ContractDraftFinalizeResponse,
    ContractDraftResponse,
    ContractDraftUpdate,
    ContractGroupMember,
    ContractList,
    ContractRateHistoryEntry,
    ContractSiblingRef,
    ContractSignedDeleteRequest,
    ContractStatusUpdate,
    ContractReopenRequest,
    ContractResponse,
    ContractReturnAfterBreakRequest,
    ContractReturnAfterBreakResponse,
    ContractTerminationReversalPlanRead,
    ContractBulkTerminateRequest,
    ContractTemplateBrief,
    ContractTerminateRequest,
    ContractTimelineItem,
    ContractUpdate,
    ContractVoidRequest,
    RegisterSubcategoriesResponse,
)
from app.schemas.contract_amendment import (
    ContractAmendmentCreate,
    ContractAmendmentResponse,
)
from app.schemas.contract_document import (
    ContractDocumentResponse,
    ContractDocumentUpdate,
)
from app.schemas.contract_equipment import (
    ContractEquipmentCreate,
    ContractEquipmentResponse,
    ContractEquipmentUpdate,
)
from app.schemas.contract_onboarding import (
    OnboardingItemCreate,
    OnboardingItemResponse,
    OnboardingItemUpdate,
)
from app.services import storage_service
from app.services.b2b_contract_end_date import (
    B2B_END_DATE_MESSAGE,
    B2B_END_DATE_REASON,
    end_date_allowed,
    has_early_termination_amendment,
    is_b2b,
    is_manually_terminated,
)
from app.services.critical_events import DeletionAudit, audited_deletion
from app.services.contract_lifecycle import (
    activate_contract as lifecycle_activate_contract,
    assert_transition,
    auto_activate_complete_draft,
    hard_delete_contract,
    move_to_ready_for_signature,
    reopen_contract,
    revert_contract,
    void_contract,
)
from app.services.contract_order_sync import (
    _switch_contract_unit,
    apply_contract_hourly_policy,
    apply_manual_client_rate,
    resync_contract_safely,
)
from app.services.client_identity import (
    client_display_name,
    client_display_name_expression,
)
from app.services.contract_candidate_contact import (
    email_too_long,
    normalize_email,
    normalize_phone,
    phone_too_long,
    resolve_for_contract as resolve_candidate_contact,
)
from app.services.contract_rates import effective_rate_fields
from app.services.contractor_identity import contractor_identity_sql_expression
from app.services.contract_service import (
    ACTIVATION_REQUIRED_FIELDS,
    validate_ready_for_activation,
)
from app.services.contract_order_offboarding import apply_contract_order_offboarding
from app.services.contract_termination_snapshot import ContractStateBefore
from app.services.contract_return_after_break import (
    create_return_after_break,
    existing_return,
)
from app.services.contract_termination_reversal import (
    ReversalBlocked,
    ReversalUnavailable,
    build_reversal_plan,
    execute_reversal,
    latest_reversal,
    reversal_available,
)
from app.services.order_write_errors import commit_order_write
from app.services.contract_termination_sync import (
    AgreementTermination,
    contract_agreement_termination,
    set_contract_agreement_termination,
    sync_generator_after_contract_ended,
)
from app.services.cost_orders import is_cost_order_client
from app.services.order_rate_snapshots import (
    CONTRACT_RATE_SCALE,
    convert_order_rate,
    inherited_order_rate_fields,
)
from app.services.order_types import suggested_order_type
from app.services.polish_ilike import (
    fold_polish_query,
    polish_folded,
    polish_folded_ilike,
)
from app.tasks.contract_alerts import run_contract_alerts_cycle
from app.api.deps import AdminUser, DeliveryLeadPlus, get_current_user, require_roles
from app.api.financial_access import (
    FinanceReadUser,
    assert_finance_manager_touches_only_amounts,
    can_manage_finance_amounts,
    can_read_client_finance,
    has_financial_access,
    require_financial_access,
    require_roles_or_finance_manager,
    redact_feed_activity,
    redact_financial_fields,
)
from app.api.section_access import DELIVERY_SECTION_DEPENDENCIES
from app.services.access_scope import (
    apply_delivery_lead_client_scope,
    assert_delivery_lead_client_visible,
    resolve_delivery_lead_assigned_client_ids,
    resolve_delivery_lead_client_ids,
    resolve_delivery_lead_finance_client_ids,
)

router = APIRouter(dependencies=DELIVERY_SECTION_DEPENDENCIES)

# Mutacje kontraktów stoją na `DeliveryLeadPlus` (admin + Delivery Lead). Do
# 22.09.2026 było tu `TacPlus`, ale TAC nie ma sekcji Delivery, więc bramka
# routera i tak go odcinała (audyt U7) — alias mówił coś, czego kod nie robił.
logger = logging.getLogger(__name__)

# Structured contract readers admitted by the Delivery section. TCM receives a
# finance-redacted projection; the organization-wide Finance business reader
# keeps its existing access. This alias is used only by GET handlers; contract
# commands keep their existing ``DeliveryLeadPlus``/``AdminUser`` dependencies and the
# section-level write gate narrows their effective audience to Admin/DL.
ContractReadUser = Annotated[
    User,
    Depends(
        require_roles(
            UserRole.admin,
            UserRole.delivery_lead,
            UserRole.talent_community_manager,
            UserRole.tac,
            UserRole.finance,
        )
    ),
]

# „Cofnij zakończenie" i „Powrót po przerwie" (ticket 09.2026): Admin, Finanse
# i Talent Community Manager. Świadomie BEZ Delivery Leada — to korekta
# administracyjna (pomyłka albo nowy kontrakt), nie decyzja o obsadzie.
# Finanse i TCM mają Delivery do odczytu, więc bramka sekcji przepuszcza te
# dwa polecenia wprost (``section_access._is_contract_termination_recovery``).
ContractTerminationRecoveryUser = Annotated[
    User,
    Depends(
        require_roles(
            UserRole.admin,
            UserRole.finance,
            UserRole.talent_community_manager,
        )
    ),
]


ContractStatusWriteUser = Annotated[
    User,
    Depends(
        require_roles(
            UserRole.admin,
            UserRole.delivery_lead,
            UserRole.talent_community_manager,
        )
    ),
]


# Contract drafts and uploaded files are opaque legal artefacts: their HTML or
# binary content can contain rates even when the structured API response is
# redacted. TCM may read the operational Delivery register, but cannot cross
# the Finance boundary through an unstructured document. Delivery Lead keeps
# document access but opaque content remains scoped to assigned clients by the
# dedicated guard below.
async def require_contract_document_read_access(
    current_user: User = Depends(get_current_user),
) -> User:
    """Guard opaque contract documents without making Finance a role shortcut.

    Admin and Delivery Lead keep their established legal-document personas.
    Finance is admitted only while its effective Finance section still grants
    read access.  An individual Finance grant does not by itself expose legal
    documents to a recruiter/sourcer: the document persona remains a separate
    boundary and the concrete client scope is resolved by the handler.
    """

    if current_user.has_any_role(UserRole.admin, UserRole.delivery_lead):
        return current_user
    if current_user.has_role(UserRole.finance):
        require_financial_access(current_user)
        return current_user
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Contract documents require Admin, Delivery Lead or Finance access",
    )


ContractDocumentReadUser = Annotated[
    User,
    Depends(require_contract_document_read_access),
]

# Upload limit — nothing fancy, we're storing contracts + PDFs, not media.
MAX_UPLOAD_BYTES = 20 * 1024 * 1024  # 20 MB

EXPIRY_WARNING_DAYS = 30

# A draft is promoted only when a PATCH closes its canonical completeness gap.
# This makes the transition write-time (no retroactive sweep on deployment)
# without letting an incidental edit activate a legacy draft that was already
# complete. The candidate schedule is included because it can satisfy
# ``rate_candidate`` without a separate scalar-field write.
_AUTO_ACTIVATION_INPUTS = frozenset(
    (
        *ACTIVATION_REQUIRED_FIELDS,
        "candidate_rate_schedule",
    )
)
# Resolver stawek efektywnych mieszka w ``app.services.contract_rates`` — czytają
# go analityka, raporty, /my-clients, zamówienia i profil klienta, a moduł api.*
# importowany przez inny moduł api.* tylko po to, żeby policzyć marżę, prędzej
# czy później zostaje skopiowany i rozjeżdża się cicho (temat 1 audytu 21.08.2026).
# Alias zostaje, żeby nie ruszać istniejących wywołań w tym pliku i w api/clients.py.
_effective_rate_fields = effective_rate_fields


def _schedule_entries(contract: Contract) -> list[ContractCandidateRateEntry]:
    """Serialize a contract's candidate-rate schedule (oldest → newest)."""
    return [
        ContractCandidateRateEntry.model_validate(e)
        for e in sorted(
            contract.candidate_rate_schedule or [], key=lambda e: e.effective_from
        )
    ]


def _client_schedule_entries(contract: Contract) -> list[ContractClientRateEntry]:
    """Serialize a contract's client-rate schedule (oldest → newest)."""
    return [
        ContractClientRateEntry.model_validate(e)
        for e in sorted(
            contract.client_rate_schedule or [], key=lambda e: e.effective_from
        )
    ]


def _framework_schedule_entries(
    contract: Contract,
) -> list[ContractFrameworkRateEntry]:
    """Serialize a contract's framework-rate schedule (oldest → newest)."""
    return [
        ContractFrameworkRateEntry.model_validate(e)
        for e in sorted(
            contract.framework_rate_schedule or [], key=lambda e: e.effective_from
        )
    ]


def _synced_client_order_end(
    current: Optional[date], new_end_date: date
) -> Optional[date]:
    """Client-order end date after a contract extension.

    Extending a contract means the client renewed the underlying purchase order,
    so "Koniec zamówienia u klienta" follows the new contract horizon instead of
    lingering on the old date. Contracts that never tracked an order end
    (``current is None``) stay untracked — we don't invent an order end where the
    user deliberately left one out. Shared by the amendment and bulk-extend paths.
    """
    return new_end_date if current is not None else None


DAILY_CONTRACT_UNIT_REASON = "contract_rates_are_hourly"
DAILY_CONTRACT_UNIT_MESSAGE = (
    "Stawki w module Kontrakty są godzinowe (zł/h). Stawkę dzienną (MD) "
    "przelicz na godzinową: stawka za MD ÷ 8. Zamówienia w MD prowadzisz "
    "w module Klienci — kontrakt przeliczy się sam. Kontrakt, który jest "
    "jeszcze w MD, zapisz bez zmiany jednostki — zapis przeliczy go na zł/h. "
    "Jeśli widzisz ten komunikat po zapisie formularza, odśwież stronę."
)


def _reject_daily_contract_unit() -> None:
    """422 dla przejścia kontraktu na jednostkę dzienną (decyzja 14.09.2026).

    Odmowa zamiast przeliczenia: zmiana samej jednostki na MD opisuje kwoty,
    które operator podał w innej jednostce niż zapisane w harmonogramach —
    przeliczenie połowy kontraktu byłoby zgadywaniem. Kontrakt, który JEST
    jeszcze w MD (sprzed korekty 0309), przelicza się przy zapisie w całości.
    """
    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail={
            "message": DAILY_CONTRACT_UNIT_MESSAGE,
            "reason": DAILY_CONTRACT_UNIT_REASON,
            "field": "rate_unit",
        },
    )


def _reject_b2b_end_date() -> None:
    """422 dla daty zakończenia umowy B2B spoza „Zakończ współpracę".

    Odmowa, nie ciche wyzerowanie: pole przysłane z formularza znika wtedy na
    oczach operatora, a on nie wie dlaczego. ``field`` pozwala formularzom
    podświetlić właściwe pole. Reguła: ``app.services.b2b_contract_end_date``.
    """
    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail={
            "message": B2B_END_DATE_MESSAGE,
            "reason": B2B_END_DATE_REASON,
            "field": "end_date",
        },
    )


async def _assert_b2b_end_date_update(
    contract: Contract,
    updates: dict,
    status_target: Optional[str],
    db: AsyncSession,
) -> None:
    """PATCH: odmowa, gdy TO żądanie daje umowie B2B datę bez zakończenia.

    Sprawdzamy wyłącznie zmianę daty albo typu umowy — zapis innego pola
    (formularz odsyła też nieruszaną datę) nie może się wywrócić na wierszu,
    którego żądanie w tym miejscu nie dotyka. Status liczymy WYNIKOWY:
    „Zakończony" z datą w przyszłości samoleczenie cofa na „Aktywny", więc
    taka zmiana daty też wymaga zakończenia.
    """
    end_changed = "end_date" in updates and updates["end_date"] != contract.end_date
    type_changed = updates.get("contract_type") is not None and is_b2b(
        updates["contract_type"]
    ) != is_b2b(contract.contract_type)
    if not (end_changed or type_changed):
        return
    new_type = updates.get("contract_type") or contract.contract_type
    new_end = updates["end_date"] if "end_date" in updates else contract.end_date
    if status_target is not None:
        resulting_status = ContractStatus(status_target)
    else:
        resulting_status = _status_after_end_date_change(
            contract.status, new_end, business_today()
        )
    if end_date_allowed(
        contract_type=new_type,
        status=resulting_status,
        end_date=new_end,
        manually_terminated=False,
    ):
        return
    # Ślad wypowiedzenia liczymy po TYM żądaniu — PATCH niesie też pola
    # `terminated_at`/`termination_reason` i może je ustawić albo wyczyścić.
    terminated_fields = [
        updates[field] if field in updates else getattr(contract, field)
        for field in ("terminated_at", "termination_reason")
    ]
    if any(value is not None for value in terminated_fields):
        return
    if not await has_early_termination_amendment(db, contract.id):
        _reject_b2b_end_date()


def _status_after_end_date_change(
    status: ContractStatus, end_date: Optional[date], today: date
) -> ContractStatus:
    """Keep the contract status coherent with its end date.

    "Zakończony" (``ended``) must never outlive the end date: a contract that is
    indefinite ("bezterminowo", ``end_date is None``) or still runs into the
    future (``end_date > today``) has not ended yet, so a stored ``ended`` is
    stale — reset it to ``active``. An indefinite contract can't be "Kończący
    się" (``ending``) either. Downgrade only — promotion to ``ending``/``ended``
    stays the daily ``_promote_statuses`` cron's job (mirrors the
    extension-amendment flip-back in ``create_contract_amendment``).
    """
    if status == ContractStatus.ended and (end_date is None or end_date > today):
        return ContractStatus.active
    if status == ContractStatus.ending and end_date is None:
        return ContractStatus.active
    return status


def _status_after_termination(
    current: ContractStatus, end_date: Optional[date], today: date
) -> ContractStatus:
    """Status po zakończeniu współpracy (``/terminate``, aneks ``early_termination``).

    Do 09.2026 obie ścieżki liczyły status z samej daty końca, bez patrzenia na
    stan umowy (audyt 14.09.2026, F03):

    * ``void`` jest terminalny — jedno „Zakończ współpracę” wskrzeszało
      unieważnioną umowę na ``ended``/``active``. Teraz 409 z maszyny stanów.
    * ``draft``/``ready_for_signature`` z datą końca w przyszłości dostawały
      ``active`` z pominięciem bramki aktywacji. Teraz status zostaje, a dzień
      po dacie końca nadal można je zakończyć (``→ ended`` jest legalne).

    Od 09.2026 (ticket „Zakończenie współpracy — obowiązkowy formularz”)
    o statusie decyduje DATA ZAKOŃCZENIA PROJEKTU: do tego dnia włącznie
    „Kończący się”, od następnego „Zakończony” (materializuje nocny
    ``_promote_statuses``), a data z przeszłości daje „Zakończony” od razu.
    Wcześniej przyszła data zostawiała „Aktywny” aż do okna 30 dni, a data
    dzisiejsza kończyła umowę w dniu, w którym konsultant jeszcze pracuje.
    Ostatni dzień UMOWY (okres wypowiedzenia) statusu nie wydłuża.
    """
    if end_date is not None and end_date < today:
        target = ContractStatus.ended
    elif end_date is not None:
        target = ContractStatus.ending
    else:
        target = ContractStatus.active
    if current in (ContractStatus.draft, ContractStatus.ready_for_signature):
        # Szkic nie ma fazy „Kończący się” (nie pracuje w MRR, a nocny cron
        # szkiców nie promuje): dzień zakończenia i wcześniej = „Zakończony”
        # od razu, data przyszła zostawia status.
        if end_date is not None and end_date <= today:
            target = ContractStatus.ended
        else:
            return current
    if current == target:
        return target
    if current == ContractStatus.ended and target == ContractStatus.ending:
        # Korekta daty zakończonej umowy na przyszłą: maszyna stanów nie zna
        # krawędzi `ended → ending`, ale zna `ended → active → ending` — to
        # ta sama droga co reaktywacja, tylko od razu z datą końca.
        assert_transition(current, ContractStatus.active)
        return target
    assert_transition(current, target)
    return target


async def _sync_client_orders_to_contract_end(
    db: AsyncSession,
    contract_id: int,
    when: date,
    *,
    actor_id: Optional[int] = None,
    contract_before: Optional[ContractStateBefore] = None,
) -> int:
    """JEDNA data końca w obu modelach — kontrakt i jego zamówienia klienta.

    ``Contract.end_date`` i ``ClientOrder.end_date`` to osobne kolumny
    skanowane przez dwa niezależne demony (``contract_alerts`` /
    ``dl_portal_expiry_scanner``) — bez jawnego syncu zakończony kontrakt
    zostawia otwarte zamówienia dryfujące bezterminowo, a skaner wygasania
    dalej alarmuje o czymś, co się skończyło. Reguły:

      * zamówienie startujące PO dacie końca → ``cancelled`` (nigdy nie ruszy),
      * pozostałe otwarte (draft/active/paused): ``end_date = when``;
        ``completed`` dopiero gdy data nadeszła — przyszłą datę materializuje
        dzienny skaner (lustrzana semantyka P0.7 kontraktu),
      * ``B2BGeneratedContract`` celowo NIETKNIĘTY (zamknięcie dokumentu
        prawnego to odrębna, ręczna operacja).

    Wyniesione z ``/terminate`` do funkcji, bo ma TRZECH wołających: dyspozycję
    wypowiedzenia, ustawienie statusu „Zakończony" wprost z rejestru umów oraz
    zmianę samej daty końca umowy (``update_contract``, reguła 09.2026).
    Druga ścieżka miała tę regułę pominiętą, więc kończyła kontrakt i
    zostawiała jego zamówienia otwarte — objaw widoczny dopiero jako alert DL
    o zamówieniu nieistniejącej już współpracy.

    Zwraca liczbę dotkniętych zamówień — ``/terminate`` zapisuje ją w audycie.

    ``contract_before`` — stan kontraktu sprzed zakończenia (migawka 0368 dla
    „Cofnij zakończenie"); wołający czyta go, zanim cokolwiek zmieni.
    """
    result = await apply_contract_order_offboarding(
        db,
        contract_id=contract_id,
        effective_date=when,
        actor_id=actor_id,
        contract_before=contract_before,
    )
    return result.affected_orders


async def _apply_contract_status_change(
    db: AsyncSession,
    contract: Contract,
    target: ContractStatus,
    *,
    actor_id: Optional[int],
    allow_direct_end: bool = False,
) -> None:
    """Jedyne wejście dla zapisu ``status`` z rejestru umów — POST i PATCH.

    ``ended`` na ISTNIEJĄCEJ umowie odmawia 409 ``termination_required``
    (ticket 09.2026): każde zakończenie przechodzi przez okno „Zakończ
    współpracę” (``/terminate``), bo tylko ono zapisuje powód, datę końca
    projektu i rozwiązanie umowy B2B, a status liczy z daty. Lista rozwijana
    kończyła kontrakt #674 bez żadnego z nich. ``allow_direct_end`` ma
    wyłącznie POST — wpis umowy, która skończyła się przed założeniem rekordu.

    Rejestr umów ma listę rozwijaną ze statusem i ta lista MA działać — ticket
    jest słuszny. Czym innym jest jednak „zapisz wybraną wartość do kolumny",
    a czym innym „wykonaj przejście stanu". Surowy
    ``setattr(contract, "status", ...)`` omija ``contract_lifecycle`` w
    całości i daje cztery skutki, z których każdy jest cichy:

      * ``ALLOWED_TRANSITIONS[void] == frozenset()`` — ``void`` jest TERMINALNY
        (soft-delete zachowujący dokumenty i hashe podpisów), a surowy zapis
        wskrzeszał go do MRR, liczników konsultantów i alertów DL;
      * ``active`` bez ``validate_ready_for_activation`` — umowa wchodzi do
        liczenia pieniędzy z pustymi polami, na których to liczenie stoi;
      * ``ended`` bez koherencji ``end_date`` i bez syncu ``ClientOrder`` —
        operacyjnie najgorsze, bo zamówienia klienta zostają otwarte, a skaner
        wygasania alarmuje o zakończonej współpracy.

    Dlatego pole nie jest odbierane, tylko przepuszczane przez maszynę stanów.
    Każda gałąź deleguje do funkcji, która JUŻ ma swój audyt i swoje bramki;
    ``assert_transition`` odpowiada za krawędzie, których żadna z nich nie
    obsługuje.

    Świadomie NIE ustawiamy tu ``terminated_at``/``termination_reason``:
    „Zakończony" w rejestrze znaczy „ta umowa się skończyła", a nie „wypowiadam
    ją przed czasem". Wypowiedzenie ma własny endpoint (``/terminate``), który
    wymaga powodu i dopisuje aneks ``early_termination``. Dopisanie tu daty
    wypowiedzenia bez powodu twierdziłoby coś, czego nikt nie zadeklarował.
    """
    if target == contract.status:
        return

    if target == ContractStatus.ended and not allow_direct_end:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": (
                    "Kontrakt kończy się oknem „Zakończ współpracę” — podaj "
                    "powód i datę zakończenia projektu."
                ),
                "reason": "termination_required",
            },
        )

    if target == ContractStatus.active:
        if contract.status in (ContractStatus.ended, ContractStatus.ending):
            # Powrót zakończonej/kończącej się umowy to REAKTYWACJA, nie
            # świeża aktywacja: dowód podpisu już istnieje z chwili, w której
            # umowę wykonano pierwszy raz. `reopen_contract` ma tę regułę i
            # zapisuje `contract_reopened` z `from_status`/`to_status`.
            await reopen_contract(
                db,
                contract,
                actor_id=actor_id,
                supersede_termination_snapshot=False,
            )
        else:
            # Aktywność jest stanem operacyjnym rejestru, niezależnym od
            # dostępności i weryfikowalności zewnętrznego podpisu. Jedyna
            # wspólna bramka to komplet danych potrzebnych raportowaniu.
            await lifecycle_activate_contract(db, contract, actor_id=actor_id)
        return

    if target == ContractStatus.draft:
        await revert_contract(
            db,
            contract,
            actor_id=actor_id,
            reason="Zmiana statusu w rejestrze umów",
        )
        return

    if target == ContractStatus.void:
        # Rejestr tej wartości nie oferuje, ale kontrakt HTTP nie jest listą
        # rozwijaną: gdyby dotarła, ma trafić w audytowany soft-delete, a nie
        # w surowy zapis kolumny.
        await void_contract(
            db,
            contract,
            actor_id=actor_id,
            reason="Zmiana statusu w rejestrze umów",
        )
        return

    if target == ContractStatus.ending:
        # „Kończący się" to `active` z bliskim końcem, a nie odrębna gałąź
        # cyklu życia. Status siedzi w `REVENUE_BEARING_STATUSES`, więc wpisany
        # wprost omija DOKŁADNIE tę samą bramkę co wpisany `active`: komplet
        # pól, na których stoi liczenie pieniędzy.
        # Maszyna stanów nie zna krawędzi `draft → ending` i to nie jest jej
        # luka — umowa najpierw zaczyna obowiązywać, a dopiero potem się
        # kończy. Dlatego szkic przechodzi przez `active` pełnym trybem, a
        # potem domykamy krawędź `active → ending`, którą maszyna zna.
        #
        if contract.status not in (ContractStatus.active, ContractStatus.ending):
            await _apply_contract_status_change(
                db,
                contract,
                ContractStatus.active,
                actor_id=actor_id,
            )
        # Dopiero TERAZ, po pełnej bramce aktywacji: umowa BEZTERMINOWA nie
        # może być „Kończąca się" — nie ma czego kończyć. Ta sama reguła stoi
        # w `_status_after_end_date_change` („An indefinite contract can't be
        # 'ending' either"), więc bez tej odmowy zapis wyglądałby na udany
        # i sam się kasował przy najbliższym przeliczeniu.
        #
        # Kolejność jest nośna: ładunek, któremu brakuje i daty, i stawek, ma
        # najpierw dostać PEŁNĄ listę braków. Odwrotna kolejność mówiłaby
        # o dacie, a po jej wpisaniu odsyłała po następną odmowę.
        # Świadomie TYLKO dla `ending` — `active` bez daty końca jest
        # w body-leasingu stanem docelowym, nie brakiem danych.
        if contract.end_date is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "message": (
                        "Status „Kończący się” wymaga daty zakończenia — "
                        "umowa bezterminowa się nie kończy. Wpisz datę albo "
                        "wybierz status „Aktywny”."
                    ),
                    "reason": "ending_requires_end_date",
                },
            )
        assert_transition(contract.status, ContractStatus.ending)
        contract.status = ContractStatus.ending
        return

    assert_transition(contract.status, target)

    if target == ContractStatus.ended:
        state_before = ContractStateBefore.of(contract)
        today = business_today()
        # Bez tego `_status_after_end_date_change` (niżej w handlerze oraz w
        # dziennym cronie) natychmiast cofnąłby `ended` na `active`, bo umowa
        # bezterminowa albo z datą w przyszłości „jeszcze się nie skończyła".
        # Zapis wyglądałby na udany i sam się kasował.
        if contract.end_date is None or contract.end_date > today:
            contract.end_date = today
        # Gdy kontrakt ma już historyczną datę końca, to ona jest faktem
        # biznesowym i granicą zamówień. Użycie zawsze `today` wydłużało okres
        # zamówienia po spóźnionym ręcznym oznaczeniu kontraktu jako zakończony.
        assert contract.end_date is not None
        await _sync_client_orders_to_contract_end(
            db,
            contract.id,
            contract.end_date,
            actor_id=actor_id,
            contract_before=state_before,
        )

    contract.status = target


def _agreement_termination(
    payload: Optional[AgreementTerminationPayload],
) -> Optional[AgreementTermination]:
    if payload is None:
        return None
    return AgreementTermination(
        mode=payload.mode,
        party=payload.party,
        signed_on=payload.signed_on,
        last_day=payload.last_day,
    )


async def _apply_termination_to_contract(
    db: AsyncSession,
    contract: Contract,
    *,
    termination_reason: ContractTerminationReason,
    when: date,
    termination_lessons: Optional[str] = None,
    overwrite_lessons: bool = True,
    actor_id: Optional[int],
    activity_action: str = "terminated",
    agreement_termination: Optional[AgreementTermination] = None,
) -> None:
    """Zakończenie współpracy na JEDNYM kontrakcie — wspólne dla obu dyspozycji.

    Wołają to ``POST /{id}/terminate`` (okno „Zakończ współpracę") oraz
    ``POST /bulk-mark-ended`` (masowe „Oznacz zakończone" w rejestrze umów).
    Obie akcje znaczą to samo zdarzenie biznesowe — osoba kończy współpracę —
    więc muszą zapisywać ten sam komplet: powód, datę, koherentny ``end_date``,
    status wyliczony z daty, offboarding zamówień klienta, aneks
    ``early_termination`` przy skróceniu i wpis audytowy.

    Do 09.2026 bulk szedł przez ``_apply_contract_status_change(..., ended)``,
    które ŚWIADOMIE nie dotyka ``terminated_at``/``termination_reason`` (patrz
    jego docstring: „Zakończony" w rejestrze to nie to samo co wypowiedzenie).
    Dla listy rozwijanej statusu ta reguła zostaje; dla przycisku „Oznacz
    zakończone" była błędem — zakończone zbiorczo umowy nie miały powodu
    w analityce odejść ani karty „Zakończenie współpracy" na szczegółach.

    Dwie kopie tej sekwencji rozjechałyby się przy pierwszej poprawce, dlatego
    jest jedna. Helper mieszka w tym module, a nie w ``app/services``, bo stoi
    na ``_status_after_termination`` i ``_sync_client_orders_to_contract_end``
    — serwis importujący router zamknąłby cykl importów.

    ``overwrite_lessons=False`` (bulk) zostawia zapisane wcześniej wnioski TAC:
    dyspozycja zbiorcza o nie nie pyta, więc nie ma czym ich zastąpić, a ciche
    wyzerowanie skasowałoby notatkę umowie zakończonej kiedyś pojedynczo,
    wznowionej i zakończonej ponownie z listy.
    """
    previous_end_date = contract.end_date
    state_before = ContractStateBefore.of(contract)
    # Odmowa PRZED jakimkolwiek zapisem (także zamówień i ścieżki powtórzenia):
    # unieważniona umowa nie może wrócić przez „Zakończ współpracę".
    effective_end = (
        when
        if contract.end_date is None or contract.end_date > when
        else contract.end_date
    )
    new_status = _status_after_termination(
        contract.status, effective_end, business_today()
    )

    # Idempotentny replay (double-submit / retry): identyczna dyspozycja nie
    # dokłada drugiej Activity ani aneksu — dotąd każdy resubmit dopisywał
    # kolejny wpis 'terminated' (audyt-higiena z weryfikacji Fazy A/B).
    if (
        contract.terminated_at == when
        and contract.termination_reason == termination_reason
        and contract.end_date is not None
        and contract.end_date <= when
        and contract_agreement_termination(contract) == agreement_termination
    ):
        # Retry pozostaje audytowo idempotentny, ale naprawia ewentualny brak
        # sprawy/alertu MD po przerwanym wcześniejszym wdrożeniu. Serwis ma
        # unikalność per (order, effective_date), więc nie dubluje historii.
        await _sync_client_orders_to_contract_end(
            db,
            contract.id,
            when,
            actor_id=actor_id,
        )
        # To samo dla Generatora: synchronizacja jest idempotentna po migawce.
        await sync_generator_after_contract_ended(db, contract, actor_id=actor_id)
        return

    contract.terminated_at = when
    contract.termination_reason = termination_reason
    if overwrite_lessons:
        contract.termination_lessons = termination_lessons
    elif termination_lessons:
        # Wspólne okno zbiorcze: wpisane wnioski obowiązują całą dyspozycję,
        # puste pole nie kasuje notatki zapisanej wcześniej.
        contract.termination_lessons = termination_lessons
    # Okno jest źródłem prawdy dla TEGO zakończenia: odznaczone „Rozwiązanie
    # umowy" czyści dane rozwiązania zapisane wcześniej (ticket, pkt 2.4).
    set_contract_agreement_termination(contract, agreement_termination)
    # Keep end_date coherent — never let it lag the termination date.
    if contract.end_date is None or contract.end_date > when:
        contract.end_date = when
    # P0.7: a future-dated termination must NOT flip the contract to `ended`
    # today. It stays active/ending until the effective end date; the daily
    # status job materializes `ended` on/after that date. Derived from the
    # (already coherent) end_date, not from raw ContractStatus.ended — and
    # validated against the CURRENT status (see `_status_after_termination`).
    contract.status = new_status

    synced_orders = await _sync_client_orders_to_contract_end(
        db,
        contract.id,
        when,
        actor_id=actor_id,
        contract_before=state_before,
    )

    # Audit amendment if the contract was cut short.
    early = previous_end_date is not None and when < previous_end_date
    if early:
        db.add(
            ContractAmendment(
                contract_id=contract.id,
                amendment_type=ContractAmendmentType.early_termination,
                old_values={
                    "end_date": previous_end_date.isoformat(),
                    "status": "active",
                },
                new_values={
                    "end_date": when.isoformat(),
                    "status": contract.status.value,
                },
                effective_date=when,
                reason=(
                    f"{termination_reason.value}: {termination_lessons}"
                    if termination_lessons
                    else termination_reason.value
                ),
                created_by=actor_id,
            )
        )

    db.add(
        Activity(
            entity_type="contract",
            entity_id=contract.id,
            action=activity_action,
            user_id=actor_id,
            details={
                "termination_reason": termination_reason.value,
                "terminated_at": when.isoformat(),
                "early": early,
                "synced_orders": synced_orders,
                "status": contract.status.value,
                **(
                    {
                        "agreement_termination": {
                            "mode": agreement_termination.mode,
                            "party": agreement_termination.party,
                            "signed_on": agreement_termination.signed_on.isoformat(),
                            "last_day": agreement_termination.last_day.isoformat(),
                        }
                    }
                    if agreement_termination is not None
                    else {}
                ),
            },
        )
    )
    # Zamówienia skrócone do daty zakończenia → okres zamówienia w kontrakcie.
    # Bez automatycznej aktywacji: zakończenie szkicu nie może go aktywować
    # (audyt 24.09, S8).
    await resync_contract_safely(db, contract, actor_id=actor_id, auto_activate=False)
    # Data zakończenia projektu z przeszłości = „Zakończony” od razu, więc
    # Generator przestawia umowę teraz; przyszła data — w nocy, dzień po niej.
    await sync_generator_after_contract_ended(db, contract, actor_id=actor_id)


def _normalize_contract_currency(value: object, field: str) -> str:
    """Canonical three-letter currency code used by contract write endpoints."""

    normalized = str(value or "").strip().upper()
    if len(normalized) != 3 or not normalized.isascii() or not normalized.isalpha():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "invalid_contract_currency",
                "field": field,
                "message": "Waluta musi być trzyliterowym kodem (np. PLN, EUR).",
            },
        )
    return normalized


def _raise_currency_conflict(fields: list[str]) -> None:
    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail={
            "code": "contract_currency_conflict",
            "fields": fields,
            "message": (
                "Legacy currency jest aliasem waluty stawki klienta i musi być "
                "zgodne z rate_client_currency."
            ),
        },
    )


def _prepare_create_rate_currencies(payload: dict, supplied_fields: set[str]) -> None:
    """Resolve legacy/new create payload into two real columns + client alias."""

    legacy = _normalize_contract_currency(payload.pop("currency", "PLN"), "currency")
    raw_client = payload.pop("rate_client_currency", None)
    raw_candidate = payload.pop("rate_candidate_currency", None)
    client = (
        _normalize_contract_currency(raw_client, "rate_client_currency")
        if "rate_client_currency" in supplied_fields
        else legacy
    )
    candidate = (
        _normalize_contract_currency(raw_candidate, "rate_candidate_currency")
        if "rate_candidate_currency" in supplied_fields
        else legacy
    )
    if "currency" in supplied_fields:
        conflicts = []
        if "rate_client_currency" in supplied_fields and client != legacy:
            conflicts.append("rate_client_currency")
        if conflicts:
            _raise_currency_conflict(conflicts)
    payload["rate_client_currency"] = client
    payload["rate_candidate_currency"] = candidate
    # Compatibility alias always follows the revenue/client side.
    payload["currency"] = client


def _prepare_update_rate_currencies(
    contract: Contract,
    updates: dict,
    supplied_fields: set[str],
) -> None:
    """Apply PATCH precedence without coupling independently supplied fields."""

    legacy_sent = "currency" in supplied_fields
    client_sent = "rate_client_currency" in supplied_fields
    candidate_sent = "rate_candidate_currency" in supplied_fields
    if not (legacy_sent or client_sent or candidate_sent):
        return

    legacy = (
        _normalize_contract_currency(updates.get("currency"), "currency")
        if legacy_sent
        else None
    )
    client = (
        _normalize_contract_currency(
            updates.get("rate_client_currency"), "rate_client_currency"
        )
        if client_sent
        else None
    )
    candidate = (
        _normalize_contract_currency(
            updates.get("rate_candidate_currency"), "rate_candidate_currency"
        )
        if candidate_sent
        else None
    )

    if legacy_sent:
        conflicts = []
        if client_sent and client != legacy:
            conflicts.append("rate_client_currency")
        if conflicts:
            _raise_currency_conflict(conflicts)
        updates["currency"] = legacy
        updates["rate_client_currency"] = legacy
        if candidate_sent:
            updates["rate_candidate_currency"] = candidate
        elif not client_sent:
            if legacy != contract.resolved_rate_client_currency:
                # A real legacy-only currency change retains the historical
                # shared-currency intent. An unchanged value can also come
                # from a stale browser tab that still round-trips ``currency``
                # on every edit; it must not erase an explicit mixed cost leg.
                updates["rate_candidate_currency"] = legacy
        return

    updates.pop("currency", None)
    if client_sent:
        updates["rate_client_currency"] = client
        # Legacy readers see the revenue/client currency.
        updates["currency"] = client
    if candidate_sent:
        updates["rate_candidate_currency"] = candidate


_DRAFT_ORDER_RATE_INHERITANCE_INPUTS = frozenset(
    {
        "rate_candidate",
        "rate_client",
        "candidate_rate_schedule",
        "currency",
        "rate_client_currency",
        "rate_candidate_currency",
        "rate_unit",
        "billing_hours_per_month",
    }
)


def _same_rate(left: object, right: object) -> bool:
    """Równość kwot niezależna od typu (Decimal z bazy vs float z JSON-a)."""
    if left is None or right is None:
        return left is None and right is None
    return Decimal(str(left)).quantize(Decimal("0.001")) == Decimal(
        str(right)
    ).quantize(Decimal("0.001"))


def _schedule_signature(steps: object) -> list[tuple]:
    """Treść harmonogramu do porównania: (stawka, od, do) w kolejności wpisu."""
    out: list[tuple] = []
    for step in steps or []:
        get = step.get if isinstance(step, dict) else step.__getattribute__
        rate = get("rate")
        out.append(
            (
                None if rate is None else Decimal(str(rate)).quantize(Decimal("0.001")),
                get("effective_from"),
                get("effective_to"),
            )
        )
    return out


def _rebuild_rate_schedule(
    model: type,
    existing: object,
    sent: object,
    *,
    actor_id: int,
) -> list:
    """Nowa lista kroków harmonogramu z PATCH-a — z pamięcią niezmienionych.

    Formularz zastępuje harmonogram w całości. Do 24.09 (audyt, W2) każdy
    zapis gubił notatki kroków („Stawka początkowa", powód aneksu) i autora:
    wszystkie kroki dostawały ``note`` z żądania (formularz go nie wysyłał)
    i ``created_by`` = zapisujący. Krok identyczny z zapisanym (stawka, od,
    do) zachowuje teraz swoją notatkę i autora, chyba że żądanie niesie
    własną notatkę. Duplikaty dat są legalne (resolver: wygrywa późniejszy
    wpis), więc dopasowanie zużywa kroki po kolei, a kolejność zostaje.
    """
    pool = [(_schedule_signature([step])[0], step) for step in (existing or [])]
    rebuilt = []
    for step in sent or []:
        signature = _schedule_signature([step])[0]
        match = next((i for i, (sig, _) in enumerate(pool) if sig == signature), None)
        previous = pool.pop(match)[1] if match is not None else None
        note = step.get("note")
        rebuilt.append(
            model(
                rate=step["rate"],
                effective_from=step["effective_from"],
                effective_to=step.get("effective_to"),
                note=(note if note is not None or previous is None else previous.note),
                created_by=(
                    previous.created_by
                    if previous is not None and previous.created_by is not None
                    else actor_id
                ),
            )
        )
    return rebuilt


def _switch_unit_for_patch(
    contract: Contract,
    updates: dict,
    target: RateUnit,
    *,
    previous_rate_client: object,
    today: date,
    schedule_input: object,
    framework_input: object,
) -> tuple[bool, bool]:
    """Zmiana jednostki w PATCH przelicza kwoty kontraktu (audyt 24.09, W1).

    Do 24.09 pętla ``setattr`` przestawiała samą etykietę: 150 zł/h stawało
    się „150 zł/mc", a synchronizacja przeliczała potem koszt do zamówień
    przez nową jednostkę (150 / 168 ≈ 0,89 zł/h). Teraz ``_switch_contract_unit``
    przelicza obie stawki, stawkę ramową, widełki i wszystkie harmonogramy.

    Formularz odsyła przy każdym zapisie wszystkie kwoty — także nieruszone,
    wciąż w STAREJ jednostce. Kwota równa tej, którą formularz pokazał (stawka
    efektywna na dziś), jest więc „bez zmian" i zostaje przeliczona; kwota
    inna to nowa wartość wpisana już w nowej jednostce. Tak samo harmonogram:
    identyczny z zapisanym zostaje przeliczony, zmieniony — zastępuje go.
    Zwraca, czy przysłane harmonogramy (kandydata, ramowy) nadal trzeba
    zastosować — ``False`` = przysłany był identyczny z zapisanym.
    """
    before = {
        "rate_candidate": contract.effective_candidate_rate(today),
        "rate_client": previous_rate_client,
        "framework_rate": contract.effective_framework_rate(today),
        "target_rate_min": contract.target_rate_min,
        "target_rate_max": contract.target_rate_max,
    }
    candidate_steps = sorted(
        _schedule_signature(contract.candidate_rate_schedule), key=repr
    )
    framework_steps = sorted(
        _schedule_signature(contract.framework_rate_schedule), key=repr
    )
    billing_hours = updates.get("billing_hours_per_month")
    _switch_contract_unit(
        contract,
        target,
        billing_hours=(
            int(billing_hours)
            if billing_hours is not None and target == RateUnit.hourly
            else None
        ),
    )
    for key, old in before.items():
        if key in updates and _same_rate(old, updates[key]):
            updates.pop(key)

    def _differs(sent: object, old_steps: list[tuple]) -> bool:
        return sorted(_schedule_signature(sent), key=repr) != old_steps

    return (
        schedule_input is None or _differs(schedule_input, candidate_steps),
        framework_input is None or _differs(framework_input, framework_steps),
    )


# Pola PATCH-a kontraktu, po których kontrakt i zamówienia tej osoby muszą się
# ponownie zgodzić (stawka kosztowa → zamówienia; status/daty/jednostka →
# okres i stawka przychodowa z zamówień). Edycja PM-a czy notatek nie rusza
# pieniędzy i nie powinna ich przeliczać.
_ORDER_SYNC_INPUTS = frozenset(
    {
        "rate_candidate",
        "rate_client",
        "candidate_rate_schedule",
        "currency",
        "rate_client_currency",
        "rate_candidate_currency",
        "rate_unit",
        "billing_hours_per_month",
        "start_date",
        "end_date",
        "status",
    }
)


async def _inherit_rates_into_unpriced_order_drafts(
    db: AsyncSession, contract: Contract
) -> int:
    """Initialize drafts created before the Contract had financial terms.

    Flow B can be created operationally by a Delivery Lead without rates.  Its
    non-null ORM defaults (monthly/168) must not masquerade as a manual order
    choice when an admin later completes the Contract.  We only touch
    standalone drafts whose two own rates are still empty; any priced order is
    already an independent snapshot and remains untouched.
    """

    if contract.rate_candidate is None or contract.rate_client is None:
        return 0
    result = await db.scalars(
        select(ClientOrder)
        .where(
            ClientOrder.contract_id == contract.id,
            ClientOrder.order_group_id.is_(None),
            ClientOrder.status == ClientOrderStatus.draft,
            ClientOrder.rate_candidate.is_(None),
            ClientOrder.rate_client.is_(None),
        )
        .order_by(ClientOrder.id.asc())
        .with_for_update()
    )
    drafts = list(result.all())
    inherited = inherited_order_rate_fields(contract)
    from app.services.order_engagement_separation import (
        AUTO_DRAFT_TITLE_PLACEHOLDER,
    )

    for order in drafts:
        for field, value in inherited.items():
            # Zaślepka „(bez numeru)” (hook zatrudnienia, klient MD/kosztowy)
            # nie jest zamówieniem, tylko zaproszeniem do wpisania numeru.
            # Stawka przychodowa skopiowana z kontraktu robiła z niej źródło
            # przychodu i okresu dla synchronizacji kontrakt ↔ zamówienia
            # („uzupełnione zamówienie” = start + dodatnia stawka przychodowa;
            # audyt 24.09, S3). Stawka kosztowa i jednostka mogą zostać.
            if (
                field == "rate_client"
                and (order.title or "").strip() == AUTO_DRAFT_TITLE_PLACEHOLDER
            ):
                continue
            setattr(order, field, value)
    return len(drafts)


def _normalize_candidate_contact_updates(updates: dict) -> None:
    """Sprowadź kontakt konsultanta do postaci zapisywalnej — w miejscu.

    Pusty string i same białe znaki stają się ``NULL``, więc „wyczyściłem pole"
    znaczy „wróć do profilu kandydata", a nie „zablokuj profil pustką". E-mail
    idzie małymi literami (jak `dedup_service._normalize_email`), telefon
    wyłącznie przycięty — prefiks i format zostają takie, jak je wpisano.

    Za długa wartość jest ODRZUCANA, nie przycinana: przycięty numer telefonu
    wygląda na poprawny i nie da się go odróżnić od literówki.
    """

    if "candidate_email" in updates:
        value = normalize_email(updates["candidate_email"])
        if email_too_long(value):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "code": "candidate_email_too_long",
                    "message": "E-mail kandydata może mieć najwyżej 255 znaków.",
                },
            )
        updates["candidate_email"] = value
    if "candidate_phone" in updates:
        value = normalize_phone(updates["candidate_phone"])
        if phone_too_long(value):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "code": "candidate_phone_too_long",
                    "message": "Telefon kandydata może mieć najwyżej 30 znaków.",
                },
            )
        updates["candidate_phone"] = value


def _to_detail(contract: Contract) -> ContractDetailResponse:
    """Serialize a Contract (with eager-loaded relations) to the detail schema."""
    contact = resolve_candidate_contact(contract)
    data = {
        "id": contract.id,
        "candidate_id": contract.candidate_id,
        "client_id": contract.client_id,
        "job_id": contract.job_id,
        "start_date": contract.start_date,
        "end_date": contract.end_date,
        "client_order_start_date": contract.client_order_start_date,
        "client_order_end_date": contract.client_order_end_date,
        "rate_candidate": contract.rate_candidate,
        "rate_client": contract.rate_client,
        "candidate_rate_schedule": _schedule_entries(contract),
        "client_rate_schedule": _client_schedule_entries(contract),
        "framework_rate_schedule": _framework_schedule_entries(contract),
        "framework_rate": contract.framework_rate,
        "target_rate_min": contract.target_rate_min,
        "target_rate_max": contract.target_rate_max,
        "currency": contract.resolved_rate_client_currency,
        "rate_client_currency": contract.resolved_rate_client_currency,
        "rate_candidate_currency": contract.resolved_rate_candidate_currency,
        "rate_unit": contract.rate_unit,
        "billing_hours_per_month": contract.billing_hours_per_month,
        "margin": contract.margin,
        "contract_type": contract.contract_type,
        "status": contract.status,
        "documents": contract.documents,
        # Kontakt do konsultanta: zapisane nadpisanie + wartość po fallbacku do
        # profilu + źródło. Czyta `contract.candidate`, które ta ścieżka ma
        # eager-loadowane (GET, PATCH); resolver nie dotyka innych relacji.
        "candidate_email": contract.candidate_email,
        "candidate_phone": contract.candidate_phone,
        "candidate_email_effective": contact.email,
        "candidate_phone_effective": contact.phone,
        "candidate_email_source": contact.email_source,
        "candidate_phone_source": contact.phone_source,
        "client_pm_name": contract.client_pm_name,
        "client_pm_email": contract.client_pm_email,
        "line_manager": contract.line_manager,
        "work_mode": contract.work_mode,
        "office_location": contract.office_location,
        "team_name": contract.team_name,
        "project_name": contract.project_name,
        "handover_notes": contract.handover_notes,
        "termination_reason": contract.termination_reason,
        "termination_lessons": contract.termination_lessons,
        "terminated_at": contract.terminated_at,
        "returned_from_contract_id": contract.returned_from_contract_id,
        "agreement_termination_mode": contract.agreement_termination_mode,
        "agreement_termination_party": contract.agreement_termination_party,
        "agreement_termination_signed_on": contract.agreement_termination_signed_on,
        "agreement_last_day": contract.agreement_last_day,
        "notice_period_months": contract.notice_period_months,
        "project_code": contract.project_code,
        "prolongation_status": contract.prolongation_status,
        "engagement_model": contract.engagement_model,
        "hours_pool_total": contract.hours_pool_total,
        "hours_pool_consumed": contract.hours_pool_consumed,
        "hours_pool_remaining": contract.hours_pool_remaining,
        "hours_pool_usage_pct": contract.hours_pool_usage_pct,
        "order_consumption": contract.order_consumption,
        "order_consumption_unit": contract.order_consumption_unit,
        "monthly_rate_candidate": contract.monthly_rate_candidate,
        "monthly_rate_client": contract.monthly_rate_client,
        "monthly_margin": contract.monthly_margin,
        "created_at": contract.created_at,
        "updated_at": contract.updated_at,
        "candidate_name": (
            f"{contract.candidate.name} {contract.candidate.lastname}"
            if contract.candidate
            else None
        ),
        "client_name": client_display_name(contract.client)
        if contract.client
        else None,
        "job_title": contract.job.title if contract.job else None,
    }
    # Derive current candidate + client rates / margin from the schedules.
    data.update(_effective_rate_fields(contract, business_today()))
    return ContractDetailResponse(**data)


def _apply_contract_list_filters(
    query,
    *,
    q: Optional[str],
    status: Optional[list[ContractStatus]],
    client_id: Optional[int],
    candidate_id: Optional[int],
    contract_type: Optional[list[str]],
    start_from: Optional[date],
    start_to: Optional[date],
    end_from: Optional[date],
    end_to: Optional[date],
    rate_client_min: Optional[int],
    rate_client_max: Optional[int],
    margin_min: Optional[int],
    expiring_in_days: Optional[int],
    period_from: Optional[date] = None,
    period_to: Optional[date] = None,
    subcategory: Optional[list[str]] = None,
    order_end_from: Optional[date] = None,
    order_end_to: Optional[date] = None,
):
    """Apply the shared contract list/export filters to ``query`` and return it.

    Single source of truth for the WHERE clauses so ``list_contracts`` and
    ``export_contracts`` never drift. ILIKE is case-insensitive and Unicode-aware,
    so "grądzki" matches "Grądzki"; names are stored NFC, so the query is
    normalised to NFC before matching (decomposed input would otherwise match
    nothing). Job is outer-joined (job_id is nullable) so contracts without a job
    still match on candidate/client — these relationships are many-to-one, so the
    joins never multiply rows (no DISTINCT needed). Multi-selects are OR-combined.
    """
    if q and q.strip():
        # Bez wrażliwości na polskie znaki: „gradzki" znajduje „Grądzki"
        # (UAT M08-B01). `polish_folded_ilike` normalizuje frazę do NFC.
        term = q.strip()
        query = (
            query.join(Contract.candidate)
            .join(Contract.client)
            .outerjoin(Contract.job)
            .where(
                or_(
                    polish_folded_ilike(Candidate.name, term),
                    polish_folded_ilike(Candidate.lastname, term),
                    polish_folded_ilike(
                        func.concat(Candidate.name, " ", Candidate.lastname), term
                    ),
                    polish_folded_ilike(client_display_name_expression(), term),
                    # Preserve the legacy/source name as a search alias when a
                    # full NEXUS display name is configured.
                    polish_folded_ilike(Client.name, term),
                    polish_folded_ilike(Job.title, term),
                )
            )
        )
    if status:
        query = query.where(Contract.status.in_(status))
    else:
        # Voided (soft-deleted) contracts are hidden from the default roster;
        # ask for them explicitly (?status=void) to see them.
        query = query.where(Contract.status != ContractStatus.void)
    if client_id:
        query = query.where(Contract.client_id == client_id)
    if candidate_id:
        query = query.where(Contract.candidate_id == candidate_id)
    if contract_type:
        query = query.where(Contract.contract_type.in_(contract_type))
    if start_from:
        query = query.where(Contract.start_date >= start_from)
    if start_to:
        query = query.where(Contract.start_date <= start_to)
    if end_from:
        query = query.where(Contract.end_date >= end_from)
    if end_to:
        query = query.where(Contract.end_date <= end_to)
    # „Okres" — nakładający się zakres (overlap): kontrakt trafia na listę, jeśli
    # jego okres obowiązywania [start_date, end_date] PRZECINA się z wybranym
    # [period_from, period_to] (a nie tylko po dacie startu lub tylko końca).
    # Otwarty koniec (end_date IS NULL = „bezterminowo") zawsze sięga w prawo;
    # brak startu (start_date IS NULL) zawsze sięga w lewo. Dwie niezależne
    # klauzule (AND) dają iloczyn = część wspólną przedziałów.
    if period_from is not None:
        query = query.where(
            or_(Contract.end_date.is_(None), Contract.end_date >= period_from)
        )
    if period_to is not None:
        query = query.where(
            or_(Contract.start_date.is_(None), Contract.start_date <= period_to)
        )
    # Koniec zamówienia u klienta = `client_order_end_date` (okres najnowszego
    # uzupełnionego zamówienia, prowadzony synchronizacją kontrakt ↔ zamówienia).
    # Zamówienie bezterminowe albo jego brak (NULL) nie ma daty, która mogłaby
    # zmieścić się w zakresie — przy aktywnym filtrze wypada z listy.
    if order_end_from is not None:
        query = query.where(Contract.client_order_end_date >= order_end_from)
    if order_end_to is not None:
        query = query.where(Contract.client_order_end_date <= order_end_to)
    if subcategory:
        # Podkategoria kompetencyjna kontraktu = `subcategory` powiązanej oferty
        # (Job leży pod jedną CC i niesie free-text podkategorię). Filtrujemy
        # przez podzapytanie po job_id, a NIE przez JOIN — helper bywa już
        # (outer)joinowany z Job w bloku `q`, więc drugi JOIN by się zderzał.
        # Kontrakty bez oferty (job_id NULL) naturalnie wypadają przy aktywnym
        # filtrze podkategorii.
        query = query.where(
            Contract.job_id.in_(select(Job.id).where(Job.subcategory.in_(subcategory)))
        )
    if rate_client_min is not None:
        query = query.where(Contract.rate_client >= rate_client_min)
    if rate_client_max is not None:
        query = query.where(Contract.rate_client <= rate_client_max)
    if margin_min is not None:
        query = query.where(Contract.margin >= margin_min)
    if expiring_in_days is not None:
        today = business_today()
        cutoff = today + timedelta(days=expiring_in_days)
        query = query.where(
            Contract.end_date.isnot(None),
            Contract.end_date <= cutoff,
            Contract.end_date >= today,
        )
    return query


# Sortowanie listy kontraktów (klik w nagłówek kolumny). Klucze są lustrem
# `CONTRACT_SORT_KEYS` we froncie (`lib/contracts-list-navigation.ts`).
ContractSortKey = Literal[
    "candidate",
    "client",
    "start_date",
    "order_end_date",
    "rate_candidate",
    "rate_client",
    "margin",
    "contract_type",
    "status",
]
# Kwoty: sortowanie po nich zdradzałoby ukryte stawki roli bez finansów
# (kolejność jako wyrocznia — ta sama klasa co F-13 przy filtrach kwot).
_FINANCE_SORT_KEYS = frozenset({"rate_candidate", "rate_client", "margin"})

# Status sortujemy po polskiej etykiecie widocznej w UI, nie po kolejności enuma.
_STATUS_SORT_LABEL = {
    ContractStatus.void: "Anulowany",
    ContractStatus.active: "Aktywny",
    ContractStatus.ready_for_signature: "Do podpisu",
    ContractStatus.ending: "Kończący się",
    ContractStatus.draft: "Szkic",
    ContractStatus.ended: "Zakończony",
}


def _effective_rate_sql(schedule_model, fallback_column, on: date):
    """Stawka obowiązująca dnia ``on`` — SQL-owe lustro ``_resolve_scheduled_rate``.

    Ostatni krok z ``effective_from <= on`` (remis: późniejsze ``id``), a gdy
    wszystkie są przyszłe — najwcześniejszy; bez harmonogramu kolumna legacy.
    Sortowanie po kolumnie cache (``contracts.rate_*``) rozjeżdżało się z
    wyświetlaną stawką: na produkcji 4–6 z 469 wierszy stało nie po kolei.
    """

    def step(*where, order):
        return (
            select(schedule_model.rate)
            .where(schedule_model.contract_id == Contract.id, *where)
            .order_by(*order)
            .limit(1)
            .correlate(Contract)
            .scalar_subquery()
        )

    past = step(
        schedule_model.effective_from <= on,
        order=(schedule_model.effective_from.desc(), schedule_model.id.desc()),
    )
    upcoming = step(
        order=(schedule_model.effective_from.asc(), schedule_model.id.desc())
    )
    return func.coalesce(past, upcoming, fallback_column)


def _resolved_currency_sql(column):
    """``Contract.resolved_rate_*_currency`` w SQL (fallback na ``currency``, PLN)."""
    return func.coalesce(
        func.nullif(func.upper(func.btrim(column)), ""),
        func.nullif(func.upper(func.btrim(Contract.currency)), ""),
        "PLN",
    )


def _contract_sort_expression(sort_by: str, on: date):
    """Wyrażenie SQL dla klucza sortowania listy.

    Nazwisko i klient idą skorelowanym podzapytaniem, nie JOIN-em — filtry
    (`q`) już joinują Candidate/Client, a drugi JOIN tej samej tabeli by się
    zderzył. Teksty foldujemy z polskich znaków i zmniejszamy litery: produkcja
    (musl) nie ma kolacji, więc bez tego „Łukasz" lądowałby za „Zenon".
    """
    if sort_by == "candidate":
        return (
            select(
                func.lower(
                    polish_folded(func.concat(Candidate.name, " ", Candidate.lastname))
                )
            )
            .where(Candidate.id == Contract.candidate_id)
            .correlate(Contract)
            .scalar_subquery()
        )
    if sort_by == "client":
        return (
            select(func.lower(polish_folded(client_display_name_expression())))
            .where(Client.id == Contract.client_id)
            .correlate(Contract)
            .scalar_subquery()
        )
    if sort_by == "start_date":
        return Contract.start_date
    if sort_by == "order_end_date":
        return Contract.client_order_end_date
    if sort_by == "rate_candidate":
        return _effective_rate_sql(ContractCandidateRate, Contract.rate_candidate, on)
    if sort_by == "rate_client":
        return _effective_rate_sql(ContractClientRate, Contract.rate_client, on)
    if sort_by == "margin":
        # Jak w `effective_rate_fields`: marża tylko przy jednej walucie obu
        # stawek — inaczej puste (i na końcu listy), jak w kolumnie.
        return case(
            (
                _resolved_currency_sql(Contract.rate_client_currency)
                == _resolved_currency_sql(Contract.rate_candidate_currency),
                _effective_rate_sql(ContractClientRate, Contract.rate_client, on)
                - _effective_rate_sql(
                    ContractCandidateRate, Contract.rate_candidate, on
                ),
            ),
            else_=None,
        )
    if sort_by == "contract_type":
        return func.lower(cast(Contract.contract_type, String))
    if sort_by == "status":
        return case(
            *[
                (Contract.status == value, label)
                for value, label in _STATUS_SORT_LABEL.items()
            ],
            else_="~",
        )
    raise ValueError(f"unknown contract sort key: {sort_by}")


def _contract_member_sort_value(c: Contract, sort_by: str, on: date):
    """Ten sam klucz w Pythonie — kolejność umów WEWNĄTRZ grupy osoby."""
    if sort_by == "candidate":
        return (
            fold_polish_query(f"{c.candidate.name} {c.candidate.lastname}").lower()
            if c.candidate
            else None
        )
    if sort_by == "client":
        return (
            fold_polish_query(client_display_name(c.client)).lower()
            if c.client
            else None
        )
    if sort_by == "start_date":
        return c.start_date
    if sort_by == "order_end_date":
        return c.client_order_end_date
    if sort_by in _FINANCE_SORT_KEYS:
        # Ta sama wartość, którą pokazuje wiersz (harmonogram na dziś).
        return _effective_rate_fields(c, on)[sort_by]
    if sort_by == "contract_type":
        return (
            str(getattr(c.contract_type, "value", c.contract_type) or "").lower()
            or None
        )
    if sort_by == "status":
        return _STATUS_SORT_LABEL.get(c.status)
    return None


def _sort_members(
    members: list[Contract], sort_by: str, sort_dir: str, on: date
) -> None:
    """Sortuje umowy grupy w miejscu: wartości puste zawsze na końcu."""
    present = [
        m for m in members if _contract_member_sort_value(m, sort_by, on) is not None
    ]
    missing = [
        m for m in members if _contract_member_sort_value(m, sort_by, on) is None
    ]
    present.sort(key=lambda m: -m.id)
    present.sort(
        key=lambda m: _contract_member_sort_value(m, sort_by, on),
        reverse=sort_dir == "desc",
    )
    missing.sort(key=lambda m: -m.id)
    members[:] = present + missing


async def _latest_order_end_dates(
    db: AsyncSession, contract_ids: list[int]
) -> dict[int, Optional[date]]:
    """Current ``ClientOrder.end_date`` per contract, in one grouped query.

    Powers the "Zamówienie do" column on the list + export (one Contract has N
    orders over time). Only an active order whose period includes the business
    date is current. If more than one such order overlaps for a contract, fail
    closed and omit that contract rather than choosing an arbitrary end date.
    Avoids N+1.
    """
    from app.models.client_order import ClientOrder, ClientOrderStatus

    if not contract_ids:
        return {}
    today = business_today()
    rows = await db.execute(
        select(ClientOrder.contract_id, func.max(ClientOrder.end_date))
        .where(
            ClientOrder.contract_id.in_(contract_ids),
            ClientOrder.status == ClientOrderStatus.active,
            ClientOrder.start_date <= today,
            or_(ClientOrder.end_date.is_(None), ClientOrder.end_date >= today),
        )
        .group_by(ClientOrder.contract_id)
        .having(func.count(ClientOrder.id) == 1)
    )
    return {row[0]: row[1] for row in rows.all()}


# P0.12: pola kwotowe kontraktu widzą tylko role z VIEW_FINANCE
# (Admin/Finance). TAC i Delivery Lead zachowują
# operacyjny widok listy/detalu, ale bez stawek, marży, harmonogramów oraz
# parametrów interpretacji kwoty.
_CONTRACT_FINANCE_SCALARS = (
    "rate_candidate",
    "rate_client",
    "framework_rate",
    "target_rate_min",
    "target_rate_max",
    "margin",
    "monthly_rate_candidate",
    "monthly_rate_client",
    "monthly_margin",
    "eur_pln_rate",
    "currency",
    "rate_client_currency",
    "rate_candidate_currency",
    "rate_unit",
    "billing_hours_per_month",
)
_CONTRACT_FINANCE_LISTS = (
    "candidate_rate_schedule",
    "client_rate_schedule",
    "framework_rate_schedule",
)

# Fields that can change a stored amount or its monetary interpretation. A
# non-finance caller may still create/edit the operational part of a contract,
# but an explicitly supplied key from this set is rejected before any write.
_CONTRACT_FINANCE_WRITE_FIELDS = frozenset(
    {
        "rate_candidate",
        "rate_client",
        "candidate_rate_schedule",
        "client_rate_schedule",
        "framework_rate_schedule",
        "framework_rate",
        "target_rate_min",
        "target_rate_max",
        "margin",
        "currency",
        "rate_client_currency",
        "rate_candidate_currency",
        "rate_unit",
        "billing_hours_per_month",
        "new_rate_candidate",
        "new_rate_client",
        "new_rate_unit",
        "new_billing_hours_per_month",
        "rate_change",
    }
)


def _assert_contract_finance_write_allowed(
    current_user: User,
    supplied_fields,
) -> None:
    """Reject hidden finance writes instead of merely redacting the response."""

    forbidden = sorted(
        set(supplied_fields).intersection(_CONTRACT_FINANCE_WRITE_FIELDS)
    )
    # Kwoty kontraktu zmienia admin albo osoba z MANAGE_FINANCE (Finanse,
    # decyzja Artura 22.09.2026). Delivery Lead, TCM, TAC i reszta — nie.
    if forbidden and not can_manage_finance_amounts(current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "finance_fields_forbidden",
                "fields": forbidden,
            },
        )


def _redact_contract_finance(
    item,
    allowed_client_ids: frozenset[int] | None = None,
):
    """Redact finance globally or outside a DL's assigned-client exception."""
    redact_primary = (
        allowed_client_ids is None or item.client_id not in allowed_client_ids
    )
    if redact_primary:
        for field in _CONTRACT_FINANCE_SCALARS:
            if hasattr(item, field):
                setattr(item, field, None)
        for field in _CONTRACT_FINANCE_LISTS:
            if hasattr(item, field):
                setattr(item, field, [])
    # Zgrupowany wiersz (group_by_candidate) niesie stawki per klient w
    # `group_members` — redakcja musi objąć też członków, inaczej rola bez
    # VIEW_FINANCE odczytałaby ukryte kwoty z rozbicia per klient.
    for member in getattr(item, "group_members", None) or []:
        if allowed_client_ids is None or member.client_id not in allowed_client_ids:
            member.rate_candidate = None
            member.rate_client = None
            member.margin = None
            member.rate_unit = None
            member.currency = None
            member.rate_client_currency = None
            member.rate_candidate_currency = None
    return item


# Kolejność członków w zgrupowanym wierszu i rodzeństwa w szczegółach: żywe
# umowy przed papierowymi, w obrębie statusu najnowsza pierwsza. Dzięki temu
# chip/oznaczenie pierwszego klienta wskazuje bieżące zatrudnienie.
_GROUP_STATUS_RANK = {
    ContractStatus.active: 0,
    ContractStatus.ending: 1,
    ContractStatus.ready_for_signature: 2,
    ContractStatus.draft: 3,
    ContractStatus.ended: 4,
    ContractStatus.void: 5,
}


def _group_member_from_contract(
    c: Contract, latest_order_dates: dict[int, date], today: date
) -> ContractGroupMember:
    """Jeden wpis rozbicia per klient — stawki z harmonogramów (jak wiersz listy)."""
    eff = _effective_rate_fields(c, today)
    return ContractGroupMember(
        id=c.id,
        client_id=c.client_id,
        client_name=client_display_name(c.client) if c.client else None,
        status=c.status,
        contract_type=c.contract_type,
        start_date=c.start_date,
        end_date=c.end_date,
        latest_order_end_date=latest_order_dates.get(c.id),
        client_order_start_date=c.client_order_start_date,
        client_order_end_date=c.client_order_end_date,
        job_title=c.job.title if c.job else None,
        rate_candidate=eff["rate_candidate"],
        rate_client=eff["rate_client"],
        margin=eff["margin"],
        rate_unit=c.rate_unit,
        currency=eff["currency"],
        rate_client_currency=eff["rate_client_currency"],
        rate_candidate_currency=eff["rate_candidate_currency"],
    )


def _contract_list_item(
    c: Contract, latest_order_dates: dict[int, date], today: date
) -> ContractResponse:
    """Jeden wiersz listy — wspólny dla trybu płaskiego i zgrupowanego.

    Wymaga eager-loadu candidate/client/job + trzech harmonogramów stawek.
    `group_members` jest wykluczone z iteracji po polach schematu: to pole
    czysto odpowiedziowe (ORM go nie ma), a `getattr(..., None)` podłożyłby
    None pod pole typu list i wywrócił walidację Pydantica.
    """
    return ContractResponse.model_validate(
        {
            **{
                k: getattr(c, k, None)
                for k in ContractResponse.model_fields.keys()
                if k
                not in (
                    "candidate_name",
                    "client_name",
                    "job_title",
                    "latest_order_end_date",
                    "group_members",
                )
            },
            "candidate_name": (
                f"{c.candidate.name} {c.candidate.lastname}".strip()
                if c.candidate
                else None
            ),
            "client_name": client_display_name(c.client) if c.client else None,
            "job_title": c.job.title if c.job else None,
            "latest_order_end_date": latest_order_dates.get(c.id),
            "candidate_rate_schedule": _schedule_entries(c),
            "client_rate_schedule": _client_schedule_entries(c),
            "framework_rate_schedule": _framework_schedule_entries(c),
            # Current candidate + client rates / margin derived from schedules.
            **_effective_rate_fields(c, today),
        }
    )


async def _ensure_delivery_lead_contract_visible(
    contract: Contract,
    current_user: User,
    db: AsyncSession,
) -> frozenset[int] | None:
    delivery_lead_client_ids = await resolve_delivery_lead_client_ids(current_user, db)
    assert_delivery_lead_client_visible(
        contract.client_id,
        delivery_lead_client_ids,
    )
    return delivery_lead_client_ids


async def _assert_contract_document_client_access(
    contract: Contract,
    current_user: User,
    db: AsyncSession,
) -> None:
    """Keep opaque legal/rate-bearing contract content assignment-bound.

    Structured contract data is safe to expose organization-wide after its
    financial fields are redacted. Draft HTML and uploaded files cannot be
    redacted reliably, so a plain Delivery Lead still needs ownership of the
    concrete client. Admin and the Finance reader retain their existing global
    access.
    """

    if current_user.has_role(UserRole.admin):
        return
    if current_user.has_role(UserRole.finance) and has_financial_access(current_user):
        return
    if current_user.has_role(UserRole.delivery_lead):
        assigned_client_ids = await resolve_delivery_lead_assigned_client_ids(
            current_user, db
        )
        if (
            assigned_client_ids is not None
            and contract.client_id in assigned_client_ids
        ):
            return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Dokument umowy wymaga przypisania Delivery Leada do klienta",
    )


async def _can_read_contract_finance(
    contract: Contract,
    current_user: User,
    db: AsyncSession,
) -> bool:
    """Apply the narrow Delivery Lead finance exception to one contract."""

    return can_read_client_finance(
        current_user,
        client_id=contract.client_id,
        delivery_lead_finance_client_ids=(
            await resolve_delivery_lead_finance_client_ids(current_user, db)
        ),
    )


@router.get("", response_model=ContractList)
async def list_contracts(
    current_user: ContractReadUser,
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    q: Optional[str] = Query(
        None,
        pattern=r"^[^\x00]*$",
        description=(
            "Free-text search — case-insensitive substring match across "
            "candidate name + lastname, client name and job title."
        ),
    ),
    status: Optional[list[ContractStatus]] = Query(
        None,
        description=(
            "Filter by `status` — one or more values. Repeat the param for "
            "multi-select (e.g. `?status=active&status=ending`). OR-combined."
        ),
    ),
    client_id: Optional[int] = None,
    candidate_id: Optional[int] = None,
    contract_type: Optional[list[str]] = Query(
        None,
        description=(
            "Filter by `contract_type` (engagement model: body_leasing / "
            "fixed_price / t_and_m). Repeat the param for multi-select. OR-combined."
        ),
    ),
    start_from: Optional[date] = Query(None),
    start_to: Optional[date] = Query(None),
    end_from: Optional[date] = Query(None),
    end_to: Optional[date] = Query(None),
    period_from: Optional[date] = Query(
        None,
        description=(
            "Okres (overlap) — dolna granica nakładającego się zakresu. Kontrakt "
            "trafia na listę, gdy jego okres obowiązywania przecina się z "
            "[period_from, period_to], nie tylko po dacie startu/końca."
        ),
    ),
    period_to: Optional[date] = Query(
        None, description="Okres (overlap) — górna granica nakładającego się zakresu."
    ),
    subcategory: Optional[list[str]] = Query(
        None,
        description=(
            "Filtr po podkategorii kompetencyjnej powiązanej rekrutacji "
            "(`Job.subcategory`, leżącej pod jej competence category). Powtarzalny "
            "dla multi-select, OR-łączony. Kontrakty bez rekrutacji są wykluczane."
        ),
    ),
    rate_client_min: Optional[int] = Query(None, ge=0),
    rate_client_max: Optional[int] = Query(None, ge=0),
    margin_min: Optional[int] = Query(None),
    expiring_in_days: Optional[int] = Query(None, ge=0, le=365),
    order_end_from: Optional[date] = Query(
        None,
        description=(
            "Koniec zamówienia u klienta (`client_order_end_date`) — dolna granica. "
            "Zamówienia bezterminowe i kontrakty bez zamówienia wypadają."
        ),
    ),
    order_end_to: Optional[date] = Query(
        None, description="Koniec zamówienia u klienta — górna granica."
    ),
    sort_by: Optional[ContractSortKey] = Query(
        None,
        description=(
            "Kolumna sortowania. Brak = najnowsze kontrakty najpierw. Puste "
            "wartości zawsze na końcu. Stawki i marża są ignorowane dla ról "
            "bez VIEW_FINANCE (kolejność zdradzałaby ukryte kwoty)."
        ),
    ),
    sort_dir: Literal["asc", "desc"] = Query("asc"),
    group_by_candidate: bool = Query(
        False,
        description=(
            "Konsolidacja kontraktorów wieloklientowych: jeden wiersz na OSOBĘ "
            "(candidate_id), a wszystkie jej umowy spełniające filtry lądują w "
            "`group_members`. `total` i stronicowanie liczą wtedy GRUPY, nie "
            "umowy. Umowy odpięte od usuniętych kandydatów zostają osobnymi "
            "wierszami. Widoki filtrowane po kandydacie/kliencie (historia, "
            "rejestr klienta) używają trybu płaskiego."
        ),
    ),
):
    """List contracts with advanced filters (Phase 9 C5)."""
    allowed_client_ids = await resolve_delivery_lead_client_ids(current_user, db)
    finance_client_ids = (
        await resolve_delivery_lead_finance_client_ids(current_user, db) or frozenset()
    )
    global_finance = user_has_capability(current_user, AnalyticsCapability.VIEW_FINANCE)
    has_finance_filter = any(
        value is not None for value in (rate_client_min, rate_client_max, margin_min)
    )
    restrict_finance_filter_to_assigned = (
        not global_finance
        and current_user.has_role(UserRole.delivery_lead)
        and bool(finance_client_ids)
        and has_finance_filter
    )
    if not global_finance and not restrict_finance_filter_to_assigned:
        # F-13: the amount fields are redacted from the response below. The
        # rate/margin FILTERS must be ignored too — otherwise a non-finance
        # caller can binary-search a hidden rate/margin by watching which rows
        # survive the filter (an oracle). Drop them before building the query.
        rate_client_min = rate_client_max = margin_min = None
    if not global_finance and sort_by in _FINANCE_SORT_KEYS:
        # Ta sama wyrocznia co przy filtrach kwot: kolejność wierszy po ukrytej
        # stawce pozwala ją odtworzyć. Rola bez finansów dostaje kolejność domyślną.
        sort_by = None

    filter_kwargs = dict(
        q=q,
        status=status,
        client_id=client_id,
        candidate_id=candidate_id,
        contract_type=contract_type,
        start_from=start_from,
        start_to=start_to,
        end_from=end_from,
        end_to=end_to,
        period_from=period_from,
        period_to=period_to,
        subcategory=subcategory,
        rate_client_min=rate_client_min,
        rate_client_max=rate_client_max,
        margin_min=margin_min,
        expiring_in_days=expiring_in_days,
        order_end_from=order_end_from,
        order_end_to=order_end_to,
    )
    sort_expr = (
        _contract_sort_expression(sort_by, business_today()) if sort_by else None
    )

    def _scoped_filtered(base_query):
        """Scope DL + komplet filtrów — jedna reguła dla obu trybów listy."""
        scoped = apply_delivery_lead_client_scope(
            base_query, Contract.client_id, allowed_client_ids
        )
        if restrict_finance_filter_to_assigned:
            scoped = scoped.where(Contract.client_id.in_(sorted(finance_client_ids)))
        return _apply_contract_list_filters(scoped, **filter_kwargs)

    load_options = (
        selectinload(Contract.candidate),
        selectinload(Contract.client),
        selectinload(Contract.job),
        selectinload(Contract.candidate_rate_schedule),
        selectinload(Contract.client_rate_schedule),
        selectinload(Contract.framework_rate_schedule),
    )
    _today = business_today()

    # Headline metadata is independent from row grouping/pagination.  Build it
    # from the exact same scoped+filtered contract set, then apply the shared
    # business identity key after the filter.  ``total`` below deliberately
    # remains the number of candidate-id groups used by pagination.
    filtered_contracts = _scoped_filtered(
        select(
            Contract.id.label("contract_id"),
            Contract.candidate_id.label("candidate_id"),
            Contract.status.label("status"),
            Contract.start_date.label("start_date"),
        ).select_from(Contract)
    ).subquery()
    identity_key = contractor_identity_sql_expression(
        Candidate.name,
        Candidate.lastname,
        Candidate.email,
        Candidate.id,
    )
    totals_row = (
        await db.execute(
            select(
                func.count(distinct(identity_key))
                .filter(Candidate.id.is_not(None))
                .label("contractors_total"),
                func.count(filtered_contracts.c.contract_id).label("contracts_total"),
                # Status „Aktywny” niesie też umowy, które dopiero się zaczną
                # (audyt 24.09.2026, U5) — nagłówek mówi, ile ich jest.
                func.count(filtered_contracts.c.contract_id)
                .filter(
                    filtered_contracts.c.status.in_(
                        (ContractStatus.active, ContractStatus.ending)
                    ),
                    filtered_contracts.c.start_date > _today,
                )
                .label("future_start_total"),
            )
            .select_from(filtered_contracts)
            .outerjoin(Candidate, Candidate.id == filtered_contracts.c.candidate_id)
        )
    ).one()
    contractors_total = int(totals_row.contractors_total or 0)
    contracts_total = int(totals_row.contracts_total or 0)
    future_start_total = int(totals_row.future_start_total or 0)

    if group_by_candidate:
        # Jeden wiersz na osobę. Grupowanie i stronicowanie odbywają się PO
        # STRONIE SERWERA — grupowanie strony wyników w FE rozdzielałoby osobę
        # między strony (jej umowy powstały w różnym czasie, więc przy sortowaniu
        # po id lądują na różnych stronach). Klucz: candidate_id; umowy odpięte
        # od usuniętych kandydatów (candidate_id NULL) nie mają czego grupować,
        # więc każda zostaje własnym wierszem pod ujemnym kluczem -id (ujemne
        # wartości nie kolidują z dodatnimi id osób).
        group_key = func.coalesce(Contract.candidate_id, -Contract.id)
        key_query = _scoped_filtered(
            select(
                group_key.label("group_key"),
                func.max(Contract.id).label("newest_id"),
            ).select_from(Contract)
        ).group_by(group_key)
        total = (
            await db.execute(select(func.count()).select_from(key_query.subquery()))
        ).scalar()
        # Kolejność grup = najnowsza umowa najpierw (lustro trybu płaskiego);
        # max(id) jest unikalne między grupami, więc porządek jest deterministyczny.
        if sort_expr is not None:
            # Grupa = osoba z N umowami: rosnąco decyduje jej najmniejsza
            # wartość, malejąco największa — tak, jak czyta się kolumnę.
            aggregate = (
                func.min(sort_expr) if sort_dir == "asc" else func.max(sort_expr)
            )
            ordered = aggregate.asc() if sort_dir == "asc" else aggregate.desc()
            group_order = (ordered.nulls_last(), func.max(Contract.id).desc())
        else:
            group_order = (func.max(Contract.id).desc(),)
        key_rows = await db.execute(
            key_query.order_by(*group_order)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        page_keys = [row.group_key for row in key_rows.all()]
        contracts: list[Contract] = []
        if page_keys:
            rows_query = (
                _scoped_filtered(select(Contract).options(*load_options))
                .where(group_key.in_(page_keys))
                .order_by(Contract.id.desc())
            )
            contracts = list((await db.execute(rows_query)).scalars().all())
        latest_order_dates = await _latest_order_end_dates(
            db, [c.id for c in contracts]
        )
        grouped: dict[int, list[Contract]] = {}
        for c in contracts:
            key = c.candidate_id if c.candidate_id is not None else -c.id
            grouped.setdefault(key, []).append(c)
        items = []
        for key in page_keys:
            members = grouped.get(key)
            if not members:
                continue
            members.sort(key=lambda m: (_GROUP_STATUS_RANK.get(m.status, 9), -m.id))
            primary = members[0]
            if sort_by:
                # Wiersz główny (link osoby) zostaje przy umowie najżywszej;
                # kolejność wierszy klientów idzie za sortowaną kolumną.
                _sort_members(members, sort_by, sort_dir, _today)
            item = _contract_list_item(primary, latest_order_dates, _today)
            item.group_members = [
                _group_member_from_contract(m, latest_order_dates, _today)
                for m in members
            ]
            items.append(item)
    else:
        query = _scoped_filtered(select(Contract).options(*load_options))
        total = contracts_total
        # Deterministyczna kolejność PRZED offset/limit — bez niej stronicowanie
        # gubi i dubluje umowy. Postgres bez ORDER BY zwraca wiersze w kolejności
        # skanu, a UPDATE tworzy nową wersję krotki i przesuwa wiersz na koniec:
        # czytelnik, który pobrał stronę 1 przed cudzym zapisem, a stronę 2 po nim,
        # NIE zobaczy jednej umowy na żadnej stronie, a inną zobaczy dwa razy.
        # Odtworzone na żywej bazie: po semantycznie pustym `UPDATE contracts SET
        # project_name = project_name WHERE id = 73` z okna czytelnika wypadła
        # umowa 375, a 73 pokazała się dwukrotnie.
        #
        # Po policzeniu `total`, wzorem `/api/jobs` — sortowanie nie ma po co
        # trafiać do podzapytania COUNT. `id` jest unikalne, więc wystarcza samo
        # za tie-breaker; lista nie ma parametru sortowania, a domyślną kolejnością
        # jest najnowsze najpierw.
        if sort_expr is not None:
            ordered = sort_expr.asc() if sort_dir == "asc" else sort_expr.desc()
            query = query.order_by(ordered.nulls_last(), Contract.id.desc())
        else:
            query = query.order_by(Contract.id.desc())
        result = await db.execute(query.offset((page - 1) * page_size).limit(page_size))
        contracts = list(result.scalars().all())
        # Latest order end_date per Contract for the "Zamówienie do" column.
        latest_order_dates = await _latest_order_end_dates(
            db, [c.id for c in contracts]
        )
        items = [_contract_list_item(c, latest_order_dates, _today) for c in contracts]

    if not global_finance:
        for item in items:
            _redact_contract_finance(item, finance_client_ids)
    return ContractList(
        items=items,
        total=total,
        contractors_total=contractors_total,
        contracts_total=contracts_total,
        future_start_total=future_start_total,
        page=page,
        page_size=page_size,
    )


# ── Export (CSV / XLSX) ───────────────────────────────────────────────────────
# Business-facing labels for the enum columns — the export goes to delivery /
# finance, so we render Polish labels instead of the raw enum values.
_CONTRACT_TYPE_LABELS = {
    "b2b": "B2B",
    "uop": "Umowa o pracę",
    "uzlecenie": "Umowa zlecenie",
}
_CONTRACT_STATUS_LABELS = {
    "draft": "Szkic",
    "active": "Aktywny",
    "ending": "Kończący się",
    "ended": "Zakończony",
    # Audyt 24.09 (S11): bez tych dwóch eksport pokazywał surowe `void`
    # i `ready_for_signature`. Lustro `frontend/src/lib/status-labels.ts`.
    "void": "Anulowany",
    "ready_for_signature": "Do podpisu",
}
_RATE_UNIT_LABELS = {
    "hourly": "godzinowa",
    "daily": "dzienna",
    "monthly": "miesięczna",
}
_WORK_MODE_LABELS = {
    "remote": "zdalnie",
    "hybrid": "hybrydowo",
    "onsite": "stacjonarnie",
}
_PROLONGATION_LABELS = {
    "unknown": "nieznany",
    "yes": "tak",
    "no": "nie",
    "negotiate": "negocjacje",
}

_CONTRACT_EXPORT_COLUMNS = [
    "ID",
    "Kandydat",
    # Kontakt jak na karcie kontraktu: nadpisanie z umowy, potem profil
    # kandydata, potem pusta komórka (resolve_for_contract).
    "E-mail",
    "Telefon",
    "Klient",
    "Stanowisko / Oferta",
    "Typ",
    "Status",
    "Data rozpoczęcia",
    "Data zakończenia",
    "Koniec zamówienia u klienta",
    "Najnowsze zamówienie do",
    "Stawka kandydata",
    "Waluta stawki kandydata",
    "Stawka klienta",
    "Waluta stawki klienta",
    "Marża",
    "Jednostka stawki",
    "Stawka mies. kandydata",
    "Stawka mies. klienta",
    "Marża mies.",
    "Stawka ramowa (MSA)",
    "Numer projektu/zamówienia",
    "Nazwa projektu",
    "PM klienta",
    "Line manager",
    "Tryb pracy",
    "Status przedłużenia",
    "Data utworzenia",
]


def _enum_label(value, labels: dict) -> str:
    """Polish label for an enum value; falls back to the raw value, "" for None."""
    if value is None:
        return ""
    raw = value.value if hasattr(value, "value") else str(value)
    return labels.get(raw, raw)


def _num_cell(value) -> object:
    """Numeric cell: ``float`` so Excel treats it as a number (sortable/summable),
    "" for None. ``float`` also renders cleanly in CSV. Rates are ``Decimal`` in
    the DB (up to 3 dp) — float64 represents those exactly for display."""
    if value is None:
        return ""
    return float(value)


def _date_cell(value) -> str:
    return value.isoformat() if value else ""


def _contract_export_row(
    c: Contract, latest_order_end: Optional[date], today: date
) -> list:
    """One export row. Rates/margin come from the effective-dated schedules
    (today's step), matching the list + detail views — not the raw columns."""
    eff = _effective_rate_fields(c, today)
    contact = resolve_candidate_contact(c)
    return [
        c.id,
        f"{c.candidate.name} {c.candidate.lastname}".strip() if c.candidate else "",
        contact.email or "",
        contact.phone or "",
        client_display_name(c.client) if c.client else "",
        c.job.title if c.job else "",
        _enum_label(c.contract_type, _CONTRACT_TYPE_LABELS),
        _enum_label(c.status, _CONTRACT_STATUS_LABELS),
        _date_cell(c.start_date),
        _date_cell(c.end_date),
        _date_cell(c.client_order_end_date),
        _date_cell(latest_order_end),
        _num_cell(eff["rate_candidate"]),
        eff["rate_candidate_currency"],
        _num_cell(eff["rate_client"]),
        eff["rate_client_currency"],
        _num_cell(eff["margin"]),
        _enum_label(c.rate_unit, _RATE_UNIT_LABELS),
        _num_cell(eff["monthly_rate_candidate"]),
        _num_cell(eff["monthly_rate_client"]),
        _num_cell(eff["monthly_margin"]),
        _num_cell(eff["framework_rate"]),
        c.project_code or "",
        c.project_name or "",
        c.client_pm_name or "",
        c.line_manager or "",
        _enum_label(c.work_mode, _WORK_MODE_LABELS),
        _enum_label(c.prolongation_status, _PROLONGATION_LABELS),
        _date_cell(c.created_at),
    ]


@router.get("/export")
async def export_contracts(
    current_user: FinanceReadUser,
    db: AsyncSession = Depends(get_db),
    format: str = Query("xlsx", pattern="^(csv|xlsx)$"),
    q: Optional[str] = Query(None),
    status: Optional[list[ContractStatus]] = Query(None),
    client_id: Optional[int] = None,
    candidate_id: Optional[int] = None,
    contract_type: Optional[list[str]] = Query(None),
    start_from: Optional[date] = Query(None),
    start_to: Optional[date] = Query(None),
    end_from: Optional[date] = Query(None),
    end_to: Optional[date] = Query(None),
    period_from: Optional[date] = Query(None),
    period_to: Optional[date] = Query(None),
    subcategory: Optional[list[str]] = Query(None),
    rate_client_min: Optional[int] = Query(None, ge=0),
    rate_client_max: Optional[int] = Query(None, ge=0),
    margin_min: Optional[int] = Query(None),
    expiring_in_days: Optional[int] = Query(None, ge=0, le=365),
    order_end_from: Optional[date] = Query(None),
    order_end_to: Optional[date] = Query(None),
    limit: int = Query(10000, ge=1, le=50000),
):
    """Export contracts to CSV or Excel — client, rates, order dates and more.

    Honours every filter the list endpoint accepts (so "export what I see" holds)
    but ignores pagination — all matching rows up to ``limit``. Defaults to XLSX.
    """
    # Eksport zawiera dane kandydata razem ze stawkami i marżą. Finance ma
    # jawny organization-wide business read; zapis i lifecycle kontraktu nadal
    # pozostają poza tą zależnością.
    query = select(Contract).options(
        selectinload(Contract.candidate),
        selectinload(Contract.client),
        selectinload(Contract.job),
        selectinload(Contract.candidate_rate_schedule),
        selectinload(Contract.client_rate_schedule),
        selectinload(Contract.framework_rate_schedule),
    )
    query = _apply_contract_list_filters(
        query,
        q=q,
        status=status,
        client_id=client_id,
        candidate_id=candidate_id,
        contract_type=contract_type,
        start_from=start_from,
        start_to=start_to,
        end_from=end_from,
        end_to=end_to,
        period_from=period_from,
        period_to=period_to,
        subcategory=subcategory,
        rate_client_min=rate_client_min,
        rate_client_max=rate_client_max,
        margin_min=margin_min,
        expiring_in_days=expiring_in_days,
        order_end_from=order_end_from,
        order_end_to=order_end_to,
    )
    query = query.order_by(Contract.id).limit(limit)
    result = await db.execute(query)
    contracts = list(result.scalars().all())
    latest_order_dates = await _latest_order_end_dates(db, [c.id for c in contracts])

    today = business_today()
    rows = [
        _contract_export_row(c, latest_order_dates.get(c.id), today) for c in contracts
    ]
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

    if format == "xlsx":
        from openpyxl import Workbook
        from openpyxl.styles import Font

        wb = Workbook()
        ws = wb.active
        ws.title = "Kontrakty"
        ws.append(_CONTRACT_EXPORT_COLUMNS)
        for cell in ws[1]:
            cell.font = Font(bold=True)
        ws.freeze_panes = "A2"  # keep the header row visible while scrolling
        for row in rows:
            ws.append(row)

        buf = BytesIO()
        wb.save(buf)
        buf.seek(0)
        filename = f"kontrakty_{ts}.xlsx"
        return StreamingResponse(
            buf,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    # CSV (default charset UTF-8). Prepend a BOM so Excel on Windows renders the
    # Polish diacritics correctly instead of mojibake.
    import csv
    from io import StringIO

    buf = StringIO()
    writer = csv.writer(buf, quoting=csv.QUOTE_MINIMAL)
    writer.writerow(_CONTRACT_EXPORT_COLUMNS)
    for row in rows:
        writer.writerow(row)
    filename = f"kontrakty_{ts}.csv"
    return StreamingResponse(
        iter(["\ufeff" + buf.getvalue()]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# \u2500\u2500 Per-klient rejestr \u2014 eksport XLSX \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
# Odr\u0119bny od finansowego /export: kolumny widocznej tabeli rejestru klienta
# (ClientContractRegister) + \u201ePodkategoria" (Job.subcategory powi\u0105zanej oferty)
# na ko\u0144cu jako jedyna kolumna wykraczaj\u0105ca poza ekran \u2014 na \u017cyczenie do analizy.
# BEZ stawek/mar\u017cy, wi\u0119c dost\u0119pny dla ca\u0142ego audytorium bezpiecznego
# rejestru, nie tylko Admina. Zawsze zaw\u0119\u017cony do jednego klienta ("brak
# klienta = brak sensu eksportu"). \u201ePodkategoria" dopisana po \u201eStatus" (koniec
# wiersza), \u017ceby zachowa\u0107 kolejno\u015b\u0107 7 kolumn widocznej tabeli.
_REGISTER_EXPORT_COLUMNS = [
    "Nr projektu",
    "Projekt",
    "Konsultant",
    "Model",
    "Okres / Pula godzin",
    "Prolongata",
    "Status",
    "Podkategoria",
]
# Etykiety lustrzane wobec frontendu (lib/contract-register.ts) \u2014 eksport czyta
# si\u0119 jak tabela na ekranie: te same etykiety, daty w formacie PL i liczby.
# Puste warto\u015bci tekstowe id\u0105 jako pusta kom\u00f3rka (nie UI-owy \u201e\u2014") \u2014 to naturalna
# reprezentacja braku w arkuszu do dalszej analizy.
_ENGAGEMENT_MODEL_LABELS = {
    "time_based": "Czasowy",
    "hours_pool": "Pula godzin",
}
_REGISTER_PROLONGATION_LABELS = {
    "unknown": "Nieznany",
    "yes": "Tak",
    "no": "Nie",
    "negotiate": "Negocjacje",
}


def _pl_date(d: Optional[date]) -> str:
    """Data w formacie polskim `d.mm.rrrr` \u2014 lustro frontendowego ``formatDate``
    (`Intl.DateTimeFormat('pl-PL')`: dzie\u0144 bez zera wiod\u0105cego, miesi\u0105c z zerem),
    np. 2026-01-01 \u2192 \u201e1.01.2026". Pusty string dla braku daty."""
    return f"{d.day}.{d.month:02d}.{d.year}" if d else ""


def _register_period_cell(c: Contract) -> str:
    """Kolumna \u201eOkres / Pula godzin" jako jedna kom\u00f3rka tekstowa \u2014 lustro
    ``PeriodCell`` z frontendu (te same liczby i daty co na ekranie). Dla
    ``hours_pool`` \u201ezu\u017cyte / total h (pct%)": procent zaokr\u0105glany half-up jak
    JS ``Math.round`` i ZAWSZE pokazywany (tak\u017ce 0% dla pustej/zerowej puli, jak
    na ekranie). Dla ``time_based`` okres \u201estart \u2192 koniec" w formacie PL (brak
    startu = \u201e\u2014", otwarty koniec = \u201ebezterminowo")."""
    if c.engagement_model == EngagementModel.hours_pool:
        total = c.hours_pool_total or 0
        consumed = c.hours_pool_consumed or 0
        # Ekran (PeriodCell) traktuje brakuj\u0105cy pct jako 0 i zawsze go renderuje;
        # `int(pct + 0.5)` = half-up (pct \u2265 0), lustrzane wobec JS Math.round.
        pct = c.hours_pool_usage_pct or 0
        return f"{consumed} / {total} h ({int(pct + 0.5)}%)"
    start = _pl_date(c.start_date) or "\u2014"
    end = _pl_date(c.end_date) if c.end_date else "bezterminowo"
    return f"{start} \u2192 {end}"


def _register_export_row(c: Contract) -> list:
    """Jeden wiersz eksportu rejestru \u2014 kolumny widocznej tabeli
    ``ClientContractRegister`` + \u201ePodkategoria" (`Job.subcategory`). Puste
    tekstowo = pusta kom\u00f3rka; placeholdery #id/\u201e\u2014" jak w UI zachowane. Wymaga
    eager-loadu ``Contract.job`` (endpoint dok\u0142ada ``selectinload``)."""
    consultant = (
        f"{c.candidate.name} {c.candidate.lastname}".strip()
        if c.candidate
        else f"#{c.candidate_id}"
    )
    subcategory = c.job.subcategory if (c.job and c.job.subcategory) else ""
    return [
        c.project_code or f"#{c.id}",
        c.project_name or "",
        consultant,
        _enum_label(c.engagement_model, _ENGAGEMENT_MODEL_LABELS),
        _register_period_cell(c),
        _enum_label(c.prolongation_status, _REGISTER_PROLONGATION_LABELS),
        _enum_label(c.status, _CONTRACT_STATUS_LABELS),
        subcategory,
    ]


@router.get("/register/export")
async def export_client_register(
    current_user: ContractReadUser,
    db: AsyncSession = Depends(get_db),
    client_id: int = Query(
        ...,
        description=(
            "Klient, kt\u00f3rego rejestr eksportujemy \u2014 WYMAGANY. Eksport jest zawsze "
            "zaw\u0119\u017cony do jednego klienta (bez klienta eksport nie ma sensu)."
        ),
    ),
    q: Optional[str] = Query(None),
    status: Optional[list[ContractStatus]] = Query(None),
    period_from: Optional[date] = Query(None),
    period_to: Optional[date] = Query(None),
    subcategory: Optional[list[str]] = Query(None),
    limit: int = Query(10000, ge=1, le=50000),
):
    """Eksport per-klient rejestru kontrakt\u00f3w do XLSX (kolumny widocznej tabeli
    + \u201ePodkategoria" = Job.subcategory oferty).

    Honoruje te same filtry co lista rejestru (``q``, ``status``, \u201eOkres" overlap,
    podkategoria oferty), wi\u0119c \u201eeksportuj to, co widz\u0119" jest zawsze prawdziwe;
    pomija paginacj\u0119 (wszystkie pasuj\u0105ce wiersze do ``limit``). Bez stawek/mar\u017cy \u2192
    dost\u0119pny dla bezpiecznych czytelnik\u00f3w Delivery, nie tylko Admina. Delivery
    Lead widzi wy\u0142\u0105cznie swoich klient\u00f3w (scope jak na li\u015bcie).
    """
    query = select(Contract).options(
        selectinload(Contract.candidate),
        selectinload(Contract.job),
    )
    query = apply_delivery_lead_client_scope(
        query,
        Contract.client_id,
        await resolve_delivery_lead_client_ids(current_user, db),
    )
    query = _apply_contract_list_filters(
        query,
        q=q,
        status=status,
        client_id=client_id,
        candidate_id=None,
        contract_type=None,
        start_from=None,
        start_to=None,
        end_from=None,
        end_to=None,
        period_from=period_from,
        period_to=period_to,
        subcategory=subcategory,
        rate_client_min=None,
        rate_client_max=None,
        margin_min=None,
        expiring_in_days=None,
    )
    query = query.order_by(Contract.id).limit(limit)
    result = await db.execute(query)
    contracts = list(result.scalars().all())
    rows = [_register_export_row(c) for c in contracts]
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

    from openpyxl import Workbook
    from openpyxl.styles import Font

    wb = Workbook()
    ws = wb.active
    ws.title = "Rejestr kontrakt\u00f3w"
    ws.append(_REGISTER_EXPORT_COLUMNS)
    for cell in ws[1]:
        cell.font = Font(bold=True)
    ws.freeze_panes = "A2"  # nag\u0142\u00f3wek widoczny przy przewijaniu
    for row in rows:
        ws.append(row)

    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    filename = f"rejestr-kontraktow_{ts}.xlsx"
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/order-sync-report")
async def contract_order_sync_report(
    current_user: AdminUser,
    db: AsyncSession = Depends(get_db),
):
    """Jednorazowe zestawienie zgodności zamówienie ↔ kontrakt (XLSX, 09.2026).

    Arkusz „Przed wdrożeniem" to migawka zapisana przez jednorazową korektę
    PRZED jakąkolwiek synchronizacją — niezgodności sprzed wdrożenia, których
    codzienny przebieg kosztowy już by nie pokazał. „Poprawione szkice" to
    paragon korekty (stan przed/po), „Stan bieżący" liczy się przy pobraniu.
    Nie ma przycisku w interfejsie: raport jest jednorazowy, a pełne stawki
    wszystkich klientów widzi tylko administrator.
    """
    from app.models.app_setting import AppSetting
    from app.services.contract_order_sync import REPAIR_MARKER
    from app.services.contract_order_sync_repair import (
        build_reconciliation_rows,
        build_reconciliation_workbook,
        repair_contract_names,
    )

    receipt = await db.get(AppSetting, REPAIR_MARKER)
    if receipt is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Jednorazowa korekta kontraktów jeszcze się nie wykonała — "
                "migawka stanu sprzed wdrożenia nie istnieje."
            ),
        )
    value = receipt.value or {}
    repaired = value.get("repaired") or []
    content = build_reconciliation_workbook(
        snapshot=value.get("snapshot") or [],
        repaired=repaired,
        repair_names=await repair_contract_names(
            db, [item["contract_id"] for item in repaired]
        ),
        live=await build_reconciliation_rows(db),
        summary=value,
    )
    filename = (
        f"zgodnosc-zamowienie-kontrakt_{value.get('business_day', 'raport')}.xlsx"
    )
    return StreamingResponse(
        BytesIO(content),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/candidate-contact-report")
async def contract_candidate_contact_report(
    current_user: AdminUser,
    db: AsyncSession = Depends(get_db),
):
    """Braki kontaktu do konsultanta po jednorazowej korekcie 0316 (XLSX).

    „Brak" liczy ta sama reguła, co karta kontraktu: wiersz trafia do arkusza
    dopiero wtedy, gdy ANI umowa, ANI profil kandydata nie mają e-maila lub
    telefonu. Zapytanie o samą pustą kolumnę wysyłałoby zespół do przepisywania
    danych, które i tak widać na ekranie.

    Bez przycisku w interfejsie — jak ``order-sync-report``: raport jest
    jednorazowy, a lista nazwisk konsultantów wszystkich klientów to widok
    administratora.
    """
    from app.models.app_setting import AppSetting
    from app.services.contract_candidate_contact_backfill import REPAIR_MARKER
    from app.services.contract_candidate_contact_report import (
        build_gap_workbook,
        gap_row,
    )

    receipt = await db.get(AppSetting, REPAIR_MARKER)
    if receipt is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Jednorazowa korekta kontaktu jeszcze się nie wykonała — "
                "lista braków byłaby liczona przed przepisaniem danych "
                "z generatora."
            ),
        )

    # `void` poza raportem: unieważnionej umowy nikt nie uzupełnia.
    contracts = (
        (
            await db.execute(
                select(Contract)
                .where(Contract.status != ContractStatus.void)
                .options(
                    selectinload(Contract.candidate),
                    selectinload(Contract.client),
                    selectinload(Contract.job),
                )
                .order_by(Contract.id)
            )
        )
        .scalars()
        .all()
    )
    rows: list[list[Any]] = []
    for contract in contracts:
        contact = resolve_candidate_contact(contract)
        missing_email = contact.email is None
        missing_phone = contact.phone is None
        if not (missing_email or missing_phone):
            continue
        candidate = contract.candidate
        rows.append(
            gap_row(
                contract_id=contract.id,
                candidate_name=(
                    f"{candidate.name} {candidate.lastname}" if candidate else None
                ),
                client_name=(
                    client_display_name(contract.client) if contract.client else None
                ),
                job_title=contract.job.title if contract.job else None,
                status=getattr(contract.status, "value", str(contract.status)),
                contract_type=getattr(
                    contract.contract_type, "value", str(contract.contract_type)
                ),
                start_date=contract.start_date,
                end_date=contract.end_date,
                missing_email=missing_email,
                missing_phone=missing_phone,
            )
        )

    content = await run_in_threadpool(
        build_gap_workbook, receipt=receipt.value or {}, rows=rows
    )
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    filename = f"braki-kontaktu-konsultantow_{ts}.xlsx"
    return StreamingResponse(
        BytesIO(content),
        media_type=(
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        ),
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/register/subcategories", response_model=RegisterSubcategoriesResponse)
async def list_client_register_subcategories(
    current_user: ContractReadUser,
    db: AsyncSession = Depends(get_db),
    client_id: int = Query(
        ..., description="Klient, którego podkategorie rekrutacji zwracamy — WYMAGANY."
    ),
) -> RegisterSubcategoriesResponse:
    """Odrębne podkategorie (`Job.subcategory`) ofert powiązanych z kontraktami
    danego klienta — zasila multiselect filtra podkategorii w rejestrze. Zwraca
    wyłącznie wartości faktycznie występujące u klienta (dropdown pokazuje tylko
    to, co da się odfiltrować). Voidy pominięte; scope Delivery Lead jak na liście.
    """
    query = (
        select(Job.subcategory)
        .join(Contract, Contract.job_id == Job.id)
        .where(
            Contract.client_id == client_id,
            Contract.status != ContractStatus.void,
            Job.subcategory.isnot(None),
            func.length(func.trim(Job.subcategory)) > 0,
        )
        .distinct()
    )
    query = apply_delivery_lead_client_scope(
        query,
        Contract.client_id,
        await resolve_delivery_lead_client_ids(current_user, db),
    )
    rows = await db.execute(query)
    # SQL `.distinct()` + WHERE (not-null, trimmed length > 0) już gwarantują
    # unikalność i niepustość — zostaje tylko stabilne sortowanie case-insensitive.
    values = sorted((v for (v,) in rows.all()), key=lambda s: s.casefold())
    return RegisterSubcategoriesResponse(subcategories=values)


# Duplikat = ta sama osoba u tego samego klienta w ŻYWYM stanie. Po `ended` /
# `void` wolno założyć nową umowę z tym samym klientem (powrót po przerwie).
_DUPLICATE_GUARD_STATUSES = (
    ContractStatus.draft,
    ContractStatus.ready_for_signature,
    ContractStatus.active,
    ContractStatus.ending,
)


async def _lock_candidate_identity(
    db: AsyncSession, candidate_id: int
) -> Optional[Candidate]:
    """Lock every Candidate row that the duplicate guard treats as one person.

    Candidate imports can leave two records with the same e-mail. Locking only
    the submitted id would let concurrent requests for those two records both
    pass the e-mail-based duplicate check. The initial read discovers the
    normalized identity; the second query acquires all matching row locks in a
    stable id order, so every create for that identity is serialized.
    """

    snapshot = await db.get(Candidate, candidate_id)
    if snapshot is None:
        return None
    email_norm = (snapshot.email or "").strip().lower()
    identity_clauses = [Candidate.id == candidate_id]
    if email_norm:
        identity_clauses.append(
            func.lower(func.btrim(Candidate.email, " \t\r\n")) == email_norm
        )
    locked = list(
        (
            await db.scalars(
                select(Candidate)
                .where(or_(*identity_clauses))
                .order_by(Candidate.id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        ).all()
    )
    return next((row for row in locked if row.id == candidate_id), None)


async def _assert_no_duplicate_contract(
    db: AsyncSession, *, candidate: Candidate, client: Client
) -> None:
    """Blokada duplikatu kontraktora: ta sama OSOBA + ten sam klient.

    Tożsamość osoby rozstrzyga ADRES E-MAIL (case/whitespace-insensitive), nie
    imię i nazwisko — nazwisko myli w obie strony: dwie różne osoby o tym samym
    nazwisku to nie duplikat, a literówka w nazwisku nie może duplikatu ukryć.
    Kandydat bez e-maila jest porównywany wyłącznie po własnym `candidate_id`.

    Umowa u INNEGO klienta duplikatem nie jest — to wieloklientowy feature
    („+ Dodaj kolejny projekt"): jedna osoba legalnie pracuje u N klientów.
    """
    email_norm = (candidate.email or "").strip().lower()
    identity_clauses = [Contract.candidate_id == candidate.id]
    if email_norm:
        # btrim z jawną listą znaków: goły `trim()` w Postgresie tnie WYŁĄCZNIE
        # spacje, a Pythonowy `.strip()` obok tnie też \t\n\r — e-mail
        # z importu zakończony nową linią umykałby porównaniu.
        identity_clauses.append(
            func.lower(func.btrim(Candidate.email, " \t\r\n")) == email_norm
        )
    existing_id = await db.scalar(
        select(Contract.id)
        .join(Candidate, Candidate.id == Contract.candidate_id)
        .where(
            Contract.client_id == client.id,
            Contract.status.in_(_DUPLICATE_GUARD_STATUSES),
            or_(*identity_clauses),
        )
        .limit(1)
    )
    if existing_id is None:
        return
    email_part = f" (e-mail: {candidate.email.strip()})" if email_norm else ""
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "code": "duplicate_contractor",
            "message": (
                f"Kontrakt dla tego kontraktora u klienta "
                f"„{client_display_name(client)}” już istnieje{email_part}."
            ),
            "existing_contract_id": existing_id,
        },
    )


async def _create_manual_project_order_draft(
    db: AsyncSession,
    *,
    contract: Contract,
    candidate: Candidate,
    source_contract_id: int,
    actor_id: int,
) -> ClientOrder:
    """Atomically add the fill-in draft required by „Dodaj kolejny projekt”."""

    candidate_name_parts = [
        part
        for part in (candidate.name, candidate.lastname)
        if part and part.strip() and part.strip() != "?"
    ]
    candidate_name = " ".join(part.strip() for part in candidate_name_parts)
    if not candidate_name:
        candidate_name = f"kandydata id={candidate.id}"
    suggested_type = await suggested_order_type(db, contract.client_id)
    order = ClientOrder(
        client_id=contract.client_id,
        contract_id=contract.id,
        job_id=contract.job_id,
        # Placeholder is intentionally rejected by order activation, so even a
        # fully priced active contract leaves this order in the Draft section
        # until Delivery fills in the real client order number.
        title="(bez numeru)",
        order_type=suggested_type.value,
        status=ClientOrderStatus.draft,
        filled_at=None,
        start_date=contract.start_date,
        end_date=contract.end_date,
        **inherited_order_rate_fields(contract),
        created_by_user_id=actor_id,
        notes=(
            "Auto-utworzone przy dodaniu kolejnego projektu dla "
            f"{candidate_name}. Uzupełnij numer, dane zamówienia i dokument PDF."
        ),
    )
    db.add(order)
    await db.flush()
    db.add(
        Activity(
            entity_type="client_order",
            entity_id=order.id,
            action="auto_drafted_from_manual_project",
            user_id=actor_id,
            details={
                "contract_id": contract.id,
                "candidate_id": candidate.id,
                "client_id": contract.client_id,
                "job_id": contract.job_id,
                "source_contract_id": source_contract_id,
            },
        )
    )
    return order


@router.post("", response_model=ContractResponse, status_code=status.HTTP_201_CREATED)
async def create_contract(
    data: ContractCreate,
    current_user: DeliveryLeadPlus,
    db: AsyncSession = Depends(get_db),
):
    _assert_contract_finance_write_allowed(current_user, data.model_fields_set)
    assert_delivery_lead_client_visible(
        data.client_id,
        await resolve_delivery_lead_client_ids(current_user, db),
    )
    # Jawne 404 po polsku zamiast FK IntegrityError → 500 przy nieistniejącym
    # id; przy okazji wiersze są potrzebne do komunikatu blokady duplikatu.
    # Serialize contract creation for the complete e-mail identity, including
    # duplicate Candidate records left by imports. Otherwise two fast requests
    # can both pass the read-before-write guard and create duplicate projects.
    candidate = await _lock_candidate_identity(db, data.candidate_id)
    if candidate is None:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "candidate_not_found",
                "message": "Wybrany kandydat nie istnieje.",
            },
        )
    client = await db.get(Client, data.client_id)
    if client is None:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "client_not_found",
                "message": "Wybrany klient nie istnieje.",
            },
        )
    if data.job_id is not None:
        job = await db.get(Job, data.job_id)
        if job is None:
            raise HTTPException(
                status_code=404,
                detail={
                    "code": "job_not_found",
                    "message": "Wybrana rekrutacja nie istnieje.",
                },
            )
        if job.client_id != client.id:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "code": "job_client_mismatch",
                    "message": "Wybrana rekrutacja należy do innego klienta.",
                },
            )
    if data.source_contract_id is not None:
        source_contract = await db.get(Contract, data.source_contract_id)
        if source_contract is None or source_contract.status == ContractStatus.void:
            raise HTTPException(
                status_code=404,
                detail={
                    "code": "source_contract_not_found",
                    "message": "Kontrakt źródłowy kolejnego projektu nie istnieje.",
                },
            )
        await _ensure_delivery_lead_contract_visible(source_contract, current_user, db)
        if source_contract.candidate_id != candidate.id:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "code": "source_contract_candidate_mismatch",
                    "message": "Kontrakt źródłowy należy do innego kandydata.",
                },
            )
        if source_contract.client_id == client.id:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "code": "source_contract_client_mismatch",
                    "message": "Kolejny projekt musi dotyczyć innego klienta.",
                },
            )
        if data.status not in (ContractStatus.draft, ContractStatus.active):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "code": "add_project_status_invalid",
                    "message": ("Kolejny projekt można dodać jako Szkic albo Aktywny."),
                },
            )
    await _assert_no_duplicate_contract(db, candidate=candidate, client=client)
    # Nowa umowa B2B rodzi się bezterminowa; datę niesie tylko wpis umowy już
    # zakończonej (rejestr importowanej historii).
    if not end_date_allowed(
        contract_type=data.contract_type,
        status=data.status,
        end_date=data.end_date,
        manually_terminated=False,
    ):
        _reject_b2b_end_date()
    payload = data.model_dump()
    # Kontrakt RODZI SIĘ szkicem i dopiero potem PRZECHODZI do wybranego stanu.
    # To nie jest odebranie rejestrowi listy rozwijanej — wybór operatora jest
    # honorowany — tylko odmowa wpisania statusu wprost do kolumny.
    # `Contract(**payload)` zapisałby go z pominięciem `contract_lifecycle`,
    # więc POST z `{"status": "active"}` zakładałby umowę od razu w przychodzie:
    # bez `validate_ready_for_activation` (pola, na których stoi liczenie
    # pieniędzy), bez sprawdzenia rozpoczętego podpisu i bez wiersza audytu
    # mówiącego, jak ten wiersz stał się aktywny. Samo przejście wykonujemy po
    # `flush()` — wiersz musi mieć `id`, patrz niżej.
    requested_status = payload.pop("status", None)
    source_contract_id = payload.pop("source_contract_id", None)
    schedule_input = payload.pop("candidate_rate_schedule", None) or []
    framework_schedule_input = payload.pop("framework_rate_schedule", None) or []
    _prepare_create_rate_currencies(payload, set(data.model_fields_set))
    contract = Contract(**payload)
    if schedule_input:
        # Schedule drives the candidate rate over time; persist each step.
        contract.candidate_rate_schedule = [
            ContractCandidateRate(
                rate=step["rate"],
                effective_from=step["effective_from"],
                effective_to=step.get("effective_to"),
                note=step.get("note"),
                created_by=current_user.id,
            )
            for step in schedule_input
        ]
    if framework_schedule_input:
        # Schedule drives the framework rate over time; persist each step.
        contract.framework_rate_schedule = [
            ContractFrameworkRate(
                rate=step["rate"],
                effective_from=step["effective_from"],
                effective_to=step.get("effective_to"),
                note=step.get("note"),
                created_by=current_user.id,
            )
            for step in framework_schedule_input
        ]
    # Stawki w Kontraktach są godzinowe (14.09.2026): kontrakt podany w MD
    # przeliczamy w całości (stawki, harmonogramy, stawka ramowa, widełki ÷ 8,
    # 168 h/mc) PRZED zapisem — nowy obiekt ma wszystkie kwoty w jednej
    # jednostce, a kolekcje harmonogramów nie wymagają doczytania.
    apply_contract_hourly_policy(contract)
    db.add(contract)
    await db.flush()
    if schedule_input:
        # Keep the cached column consistent with the schedule (current step).
        contract.rate_candidate = contract.effective_candidate_rate(business_today())
    if framework_schedule_input:
        # Keep the cached framework_rate consistent with the current step.
        contract.framework_rate = contract.effective_framework_rate(business_today())
    # Wybrany w rejestrze status ustawiamy DOPIERO TERAZ, tą samą funkcją co
    # PATCH — jedna reguła, jedno miejsce. Kolejność jest nośna w obie strony:
    # wiersz ma już `id` (audyt cyklu życia i wyszukanie podpisów go
    # potrzebują), a `rate_candidate`/`framework_rate` są już wyprowadzone
    # z harmonogramów, więc `validate_ready_for_activation` ocenia kontrakt,
    # który naprawdę powstał, a nie surowy ładunek żądania.
    #
    # Skutek dla operatora: „Aktywny" wybrany dla umowy bez daty rozpoczęcia,
    # stawek albo trybu pracy kończy się teraz 409 z listą brakujących pól, a nie
    # cichym szkicem podanym jako sukces ani aktywną umową z pustymi polami
    # w MRR. Odmowa jest wykonalna — wystarczy uzupełnić pola albo wybrać
    # „Szkic"; `get_db` wycofuje wtedy całą transakcję, więc nie zostaje
    # połowiczny wiersz.
    if requested_status is not None:
        await _apply_contract_status_change(
            db,
            contract,
            ContractStatus(requested_status),
            actor_id=current_user.id,
            allow_direct_end=True,
        )
    draft_order: Optional[ClientOrder] = None
    if source_contract_id is not None and not is_cost_order_client(contract.client_id):
        draft_order = await _create_manual_project_order_draft(
            db,
            contract=contract,
            candidate=candidate,
            source_contract_id=source_contract_id,
            actor_id=current_user.id,
        )
        # audyt 22.09 r2 (FIN-CHG-2): szkic następnego projektu zamyka brak
        # od razu, z chwilą założenia — nie przy nocnym przebiegu.
        from app.services.order_gaps import refresh_order_gaps_safely

        await db.flush()
        await refresh_order_gaps_safely(
            db, contract_ids=[contract.id], actor_id=current_user.id
        )
    db.add(
        Activity(
            entity_type="contract",
            entity_id=contract.id,
            action="created",
            user_id=current_user.id,
        )
    )
    await db.flush()
    # Re-load with relations so the response carries the schedule + derived rate.
    result = await db.execute(
        select(Contract)
        .where(Contract.id == contract.id)
        .options(
            selectinload(Contract.candidate),
            selectinload(Contract.client),
            selectinload(Contract.job),
            selectinload(Contract.candidate_rate_schedule),
            selectinload(Contract.client_rate_schedule),
            selectinload(Contract.framework_rate_schedule),
        )
    )
    detail = _to_detail(result.scalar_one())
    detail.draft_order_id = draft_order.id if draft_order is not None else None
    # Operacyjny create bez pól finansowych nie grantuje ich odczytu. Wyjątkiem
    # pozostaje DL u przypisanego klienta; globalnej capability nadal nie ma.
    if not await _can_read_contract_finance(contract, current_user, db):
        _redact_contract_finance(detail)
    return detail


@router.post("/alerts/run", status_code=status.HTTP_200_OK)
async def run_alerts_now(current_user: AdminUser):
    """Admin trigger for the contract-alerts cycle — useful for smoke tests."""
    stats = await run_contract_alerts_cycle()
    return stats


# ── Bulk operations (Phase 9 C3) ─────────────────────────────────────────────


def _add_months_keeping_month_end(day: date, months: int) -> date:
    """Data + N miesięcy; koniec miesiąca zostaje końcem miesiąca.

    Do 24.09 (audyt, S7) dzień był przycinany do 28 dla KAŻDEGO miesiąca:
    30.06 + 3 miesiące dawało 28.09 i skracało umowę o dwa dni. Teraz dzień
    przycina się do długości miesiąca docelowego (31.01 + 1 = 28/29.02),
    a ostatni dzień miesiąca przechodzi na ostatni dzień miesiąca docelowego
    (30.06 + 1 = 31.07).
    """
    total = day.month - 1 + months
    year, month = day.year + total // 12, total % 12 + 1
    last_day = calendar.monthrange(year, month)[1]
    if day.day == calendar.monthrange(day.year, day.month)[1]:
        return date(year, month, last_day)
    return date(year, month, min(day.day, last_day))


@router.post("/bulk-extend", status_code=status.HTTP_200_OK)
async def bulk_extend_contracts(
    current_user: DeliveryLeadPlus,
    db: AsyncSession = Depends(get_db),
    contract_ids: list[int] = Query(..., alias="ids"),
    months: int = Query(..., ge=1, le=24, description="Extension in months"),
):
    """Extend each selected contract's end_date by N months.

    If end_date is NULL, the contract is skipped. Returns per-id outcome.
    """
    if not contract_ids:
        raise HTTPException(status_code=422, detail="No contract ids provided")
    # FOR UPDATE w stałej kolejności (jak `/bulk-mark-ended`): `reopen_contract`
    # ocenia status z pamięci, a równoległy `void` nie może zostać nadpisany (F03).
    result = await db.execute(
        select(Contract)
        .where(Contract.id.in_(contract_ids))
        .order_by(Contract.id.asc())
        .with_for_update()
    )
    contracts = list(result.scalars().all())
    for contract in contracts:
        await _ensure_delivery_lead_contract_visible(contract, current_user, db)
    extended_ids: list[int] = []
    skipped: list[int] = []
    skipped_void: list[int] = []
    for c in contracts:
        # Anulowanej umowy nie przedłużamy: `reopen_contract` odmówiłby 409
        # i wywrócił całą paczkę (audyt 24.09, S7).
        if c.status == ContractStatus.void:
            skipped.append(c.id)
            skipped_void.append(c.id)
            continue
        # Umowa B2B bez zakończenia nie ma czego przedłużać — jest bezterminowa
        # (`b2b_contract_end_date`). Przedłużyć można wyłącznie datę umowy
        # zakończonej ręcznie, czyli przesunąć jej zakończenie.
        if c.end_date is None or (
            is_b2b(c.contract_type) and not await is_manually_terminated(db, c)
        ):
            skipped.append(c.id)
            continue
        new_end = _add_months_keeping_month_end(c.end_date, months)
        c.end_date = new_end
        # Client order is renewed together with the contract — keep its end date
        # in sync (only when the contract already tracks one). Mirrors the
        # extension-amendment path.
        c.client_order_end_date = _synced_client_order_end(
            c.client_order_end_date, new_end
        )
        # Zakończony/kończący się kontrakt wraca na `active`. Przez warstwę
        # cyklu życia, a nie przypisaniem wprost: inaczej przejście najściślej
        # powiązane z przychodem (konsultant wracający do pracy, bo współpracę
        # przedłużono) jako JEDYNE nie zostawia wiersza `Activity` z
        # `from_status`/`to_status`, więc nie da się go odtworzyć ze śladu
        # audytowego. Funkcja sama pilnuje `assert_transition`.
        await reopen_contract(db, c, actor_id=current_user.id)
        extended_ids.append(c.id)
    # Historia tylko przy umowach NAPRAWDĘ przedłużonych — wpis przy pominiętej
    # (albo nieistniejącej) twierdził coś, co się nie wydarzyło.
    for cid in extended_ids:
        db.add(
            Activity(
                entity_type="contract",
                entity_id=cid,
                action=f"bulk_extended_{months}m",
                user_id=current_user.id,
            )
        )
    # Przedłużenie przesuwa „koniec zamówienia u klienta" razem z umową
    # (`_synced_client_order_end`); okres zamówienia prowadzi jednak
    # synchronizacja z zamówień, więc przywracamy go z ich prawdy. Bez
    # automatycznej aktywacji: przedłużenie nie jest decyzją o aktywacji
    # szkicu (audyt 24.09, S8).
    for c in contracts:
        if c.id in extended_ids:
            await resync_contract_safely(
                db, c, actor_id=current_user.id, auto_activate=False
            )
    await db.commit()
    return {
        "requested": len(contract_ids),
        "extended": len(extended_ids),
        "skipped_no_end_date": skipped,
        "skipped_void": skipped_void,
    }


@router.post("/bulk-mark-ended", status_code=status.HTTP_200_OK)
async def bulk_mark_ended(
    data: ContractBulkTerminateRequest,
    current_user: DeliveryLeadPlus,
    db: AsyncSession = Depends(get_db),
    contract_ids: list[int] = Query(..., alias="ids"),
):
    """Zakończ współpracę na każdej zaznaczonej umowie — powód i data z ciała.

    To nie jest „ustaw status na zakończony": przycisk „Oznacz zakończone"
    w rejestrze znaczy faktyczny koniec projektu, więc zapisuje dokładnie to
    samo co okno „Zakończ współpracę" na pojedynczej umowie — przez ten sam
    helper (``_apply_termination_to_contract``). Do 09.2026 szło to przez
    ``_apply_contract_status_change``, które powodu i daty nie zapisuje, więc
    zakończona zbiorczo umowa nie miała ich ani w analityce odejść, ani na
    karcie „Zakończenie współpracy".

    Operacja jest ATOMOWA: jedna umowa, której maszyna stanów nie pozwala
    zakończyć (``void`` jest terminalny), odrzuca całą partię 409-ką i nic nie
    zostaje zapisane. Cicha zmiana części zaznaczenia byłaby gorsza — nikt nie
    wie wtedy, których wierszy dyspozycja nie objęła.
    """
    if not contract_ids:
        raise HTTPException(status_code=422, detail="No contract ids provided")
    # Rodzic Contract przed dziećmi ClientOrder — ten sam porządek co cron.
    # Bez blokady rodzica bulk mógł trzymać order i czekać na Contract dopiero
    # przy flushu, podczas gdy cron trzymał Contract i czekał na ten order.
    result = await db.execute(
        select(Contract)
        .where(Contract.id.in_(contract_ids))
        .order_by(Contract.id.asc())
        .with_for_update()
    )
    contracts = list(result.scalars().all())
    for contract in contracts:
        await _ensure_delivery_lead_contract_visible(contract, current_user, db)
    changed = 0
    # Każde zakończenie blokuje powiązane zamówienia. Dwa nakładające się bulki
    # muszą brać kontrakty (a przez nie ordery) w tej samej kolejności,
    # niezależnie od kolejności ``ids`` i planu zapytania.
    for c in sorted(contracts, key=lambda contract: contract.id):
        # `overwrite_lessons=False`: dyspozycja zbiorcza nie pyta o wnioski TAC,
        # więc nie ma czym ich zastąpić — a ciche wyzerowanie skasowałoby
        # notatkę umowie zakończonej kiedyś pojedynczo i wznowionej.
        # Wpis audytowy zostaje `bulk_marked_ended` (etykieta istnieje w logu
        # admina i na osi czasu kontraktu), ale niesie już powód i datę.
        await _apply_termination_to_contract(
            db,
            c,
            termination_reason=data.termination_reason,
            when=data.terminated_at,
            termination_lessons=(data.termination_lessons or "").strip() or None,
            overwrite_lessons=False,
            actor_id=current_user.id,
            activity_action="bulk_marked_ended",
            agreement_termination=_agreement_termination(data.agreement_termination),
        )
        changed += 1
    await db.commit()
    return {"requested": len(contract_ids), "changed": changed}


@router.get("/expiring", response_model=List[ContractResponse])
async def expiring_contracts(
    current_user: ContractReadUser,
    db: AsyncSession = Depends(get_db),
    days: int = Query(EXPIRY_WARNING_DAYS, ge=1, le=90),
):
    """Return contracts expiring within N days.

    Counts both `active` and `ending` contracts: the daily `_promote_statuses`
    cron flips an active contract to `ending` once it crosses the 30-day mark,
    so filtering on `active` alone silently drops every already-promoted
    contract (the banner would read 0 while dozens are genuinely expiring).
    This matches the active+ending set the Slack expiry summary already uses.
    """
    cutoff = business_today() + timedelta(days=days)
    expiring_query = (
        select(Contract)
        .where(
            Contract.end_date <= cutoff,
            Contract.end_date >= business_today(),
            Contract.status.in_([ContractStatus.active, ContractStatus.ending]),
        )
        # Eager-load the schedule: it's a serialized field on ContractResponse,
        # so from_attributes would otherwise trigger an async lazy-load error.
        .options(
            selectinload(Contract.candidate_rate_schedule),
            selectinload(Contract.client_rate_schedule),
            selectinload(Contract.framework_rate_schedule),
        )
    )
    allowed_client_ids = await resolve_delivery_lead_client_ids(current_user, db)
    expiring_query = apply_delivery_lead_client_scope(
        expiring_query,
        Contract.client_id,
        allowed_client_ids,
    )
    result = await db.execute(expiring_query)
    today = business_today()
    items = [
        ContractResponse.model_validate(
            {
                **{
                    k: getattr(c, k, None)
                    for k in ContractResponse.model_fields.keys()
                    # Pole odpowiedziowe bez odpowiednika na ORM — `getattr`
                    # podłożyłby None pod pole typu list (błąd walidacji).
                    if k != "group_members"
                },
                "candidate_rate_schedule": _schedule_entries(c),
                "client_rate_schedule": _client_schedule_entries(c),
                "framework_rate_schedule": _framework_schedule_entries(c),
                **_effective_rate_fields(c, today),
            }
        )
        for c in result.scalars().all()
    ]
    # Banner is operational and all-client. TCM sees dates without rates; DL
    # sees rates only for rows in its still-assigned finance portfolio.
    global_finance = user_has_capability(current_user, AnalyticsCapability.VIEW_FINANCE)
    finance_client_ids = (
        await resolve_delivery_lead_finance_client_ids(current_user, db) or frozenset()
    )
    if not global_finance:
        for item in items:
            _redact_contract_finance(item, finance_client_ids)
    return items


@router.get("/{contract_id}", response_model=ContractDetailResponse)
async def get_contract(
    contract_id: int, current_user: ContractReadUser, db: AsyncSession = Depends(get_db)
):
    """Return contract with denormalized candidate/client/job names."""
    result = await db.execute(
        select(Contract)
        .where(Contract.id == contract_id)
        .options(
            selectinload(Contract.candidate),
            selectinload(Contract.client),
            selectinload(Contract.job),
            selectinload(Contract.candidate_rate_schedule),
            selectinload(Contract.client_rate_schedule),
            selectinload(Contract.framework_rate_schedule),
        )
    )
    contract = result.scalar_one_or_none()
    if not contract:
        raise HTTPException(status_code=404, detail="Contract not found")
    await _ensure_delivery_lead_contract_visible(contract, current_user, db)
    detail = _to_detail(contract)
    detail.related_contracts = await _related_contracts_for(db, contract, current_user)
    await _fill_termination_recovery(db, contract, detail)
    can_view_finance = can_read_client_finance(
        current_user,
        client_id=contract.client_id,
        delivery_lead_finance_client_ids=(
            await resolve_delivery_lead_finance_client_ids(current_user, db)
        ),
    )
    contract_currencies = {
        contract.resolved_rate_client_currency,
        contract.resolved_rate_candidate_currency,
    }
    if can_view_finance and "EUR" in contract_currencies:
        from app.services.fx_service import get_rate_snapshot_to_pln

        snapshot = await get_rate_snapshot_to_pln(db, "EUR", business_today())
        if snapshot is not None and snapshot.source.upper() == "NBP":
            detail.eur_pln_rate = ContractEurPlnRate(
                rate=float(snapshot.rate_to_pln),
                effective_date=snapshot.effective_date,
                source=snapshot.source,
                table="A",
            )
    if not can_view_finance:
        _redact_contract_finance(detail)
    return detail


async def _related_contracts_for(
    db: AsyncSession, contract: Contract, current_user: User
) -> list[ContractSiblingRef]:
    """Pozostałe kontrakty tej samej osoby — zasilają zakładki per klient.

    Bez `void` (anulowane nie są zakładką do przeglądania) i w operacyjnym
    scope Delivery Leada, który obejmuje wszystkich klientów. Referencje nie
    niosą kwot; pełny detal redaguje je niezależnie per klient. Kolejność:
    żywe przed papierowymi, w obrębie statusu najnowsza pierwsza.
    """
    if contract.candidate_id is None:
        return []
    siblings_query = (
        select(Contract, client_display_name_expression().label("client_name"))
        .join(Client, Client.id == Contract.client_id)
        .where(
            Contract.candidate_id == contract.candidate_id,
            Contract.id != contract.id,
            Contract.status != ContractStatus.void,
        )
    )
    siblings_query = apply_delivery_lead_client_scope(
        siblings_query,
        Contract.client_id,
        await resolve_delivery_lead_client_ids(current_user, db),
    )
    rows = (await db.execute(siblings_query)).all()
    refs = [
        ContractSiblingRef(
            id=sib.id,
            client_id=sib.client_id,
            client_name=client_name,
            status=sib.status,
            contract_type=sib.contract_type,
            start_date=sib.start_date,
            end_date=sib.end_date,
        )
        for sib, client_name in rows
    ]
    refs.sort(key=lambda r: (_GROUP_STATUS_RANK.get(r.status, 9), -r.id))
    return refs


@router.get("/{contract_id}/activities", response_model=List[ContractActivityEntry])
async def contract_activities(
    contract_id: int,
    current_user: ContractReadUser,
    db: AsyncSession = Depends(get_db),
    limit: int = Query(50, ge=1, le=200),
):
    """Return activity log entries for a contract, newest first."""
    contract = await db.scalar(select(Contract).where(Contract.id == contract_id))
    if contract is None:
        raise HTTPException(status_code=404, detail="Contract not found")
    await _ensure_delivery_lead_contract_visible(contract, current_user, db)

    # An ``updated`` row can carry rates. DL sees them only for an assigned
    # client; TCM and other non-finance readers receive the redacted feed.
    finance_ok = can_read_client_finance(
        current_user,
        client_id=contract.client_id,
        delivery_lead_finance_client_ids=(
            await resolve_delivery_lead_finance_client_ids(current_user, db)
        ),
    )

    result = await db.execute(
        select(Activity, User.email)
        .outerjoin(User, Activity.user_id == User.id)
        .where(Activity.entity_type == "contract", Activity.entity_id == contract_id)
        .order_by(Activity.created_at.desc())
        .limit(limit)
    )
    entries: list[ContractActivityEntry] = []
    for activity, user_email in result.all():
        details = redact_feed_activity(
            activity.action, activity.details, finance_ok=finance_ok
        )
        if details is None:
            continue
        entries.append(
            ContractActivityEntry(
                id=activity.id,
                action=activity.action,
                details=details,
                user_id=activity.user_id,
                user_name=user_email,
                created_at=activity.created_at,
            )
        )
    entries.extend(await _order_line_technical_entries(db, contract_id, limit))
    entries.sort(key=lambda entry: entry.created_at, reverse=True)
    return entries[:limit]


async def _order_line_technical_entries(
    db: AsyncSession, contract_id: int, limit: int
) -> list[ContractActivityEntry]:
    """Techniczne zmiany pól linii zamówień tego kontraktu (ticket 7, 09.2026).

    Historia zamówienia pokazuje wyłącznie zdarzenia biznesowe — waluty,
    jednostka stawki czy dzielnik godzin trafiają TU, z polskimi nazwami pól.
    Źródłem jest dziennik zamówienia (jeden zapis, dwa widoki), więc także
    wpisy sprzed tej zmiany są widoczne. ``id`` ujemne = wpis spoza tabeli
    ``activities`` (klucz listy, nie odsyłacz).
    """
    from app.models.client_order_group import ClientOrderGroup, ClientOrderGroupEvent
    from app.services.multi_consultant_orders import EVENT_MANUAL_EDIT
    from app.services.order_history import RawEvent, technical_changes

    rows = await db.execute(
        select(ClientOrderGroupEvent, ClientOrderGroup.order_number, User.email)
        .join(ClientOrder, ClientOrder.id == ClientOrderGroupEvent.order_id)
        .join(ClientOrderGroup, ClientOrderGroup.id == ClientOrderGroupEvent.group_id)
        .outerjoin(User, User.id == ClientOrderGroupEvent.created_by_user_id)
        .where(
            ClientOrder.contract_id == contract_id,
            ClientOrderGroupEvent.event_type == EVENT_MANUAL_EDIT,
        )
        .order_by(ClientOrderGroupEvent.created_at.desc())
        .limit(limit * 4)
    )
    out: list[ContractActivityEntry] = []
    for event, order_number, user_email in rows.all():
        changes = technical_changes(
            RawEvent(
                id=event.id,
                event_type=event.event_type,
                description=event.description,
                order_id=event.order_id,
                payload=event.payload,
                created_at=event.created_at,
                author_id=event.created_by_user_id,
                author_name=user_email,
            )
        )
        if not changes:
            continue
        details: dict = {
            "order_number": order_number,
            "fields": [change.label for change in changes],
        }
        described = [
            f"{change.label}: {change.before or '—'} → {change.after or '—'}"
            for change in changes
            if change.before is not None or change.after is not None
        ]
        if described:
            details["changes"] = described
        out.append(
            ContractActivityEntry(
                id=-event.id,
                action="order_line_fields_changed",
                details=details,
                user_id=event.created_by_user_id,
                user_name=user_email,
                created_at=event.created_at,
            )
        )
        if len(out) >= limit:
            break
    return out


@router.get(
    "/{contract_id}/rate-history", response_model=List[ContractRateHistoryEntry]
)
async def contract_rate_history(
    contract_id: int,
    current_user: ContractReadUser,
    db: AsyncSession = Depends(get_db),
):
    """Return rate history for this contract's candidate+client combination."""
    contract_result = await db.execute(
        select(Contract).where(Contract.id == contract_id)
    )
    contract = contract_result.scalar_one_or_none()
    if not contract:
        raise HTTPException(status_code=404, detail="Contract not found")
    await _ensure_delivery_lead_contract_visible(contract, current_user, db)

    history_query = select(RateHistory).where(
        RateHistory.candidate_id == contract.candidate_id
    )
    history_query = history_query.where(
        (RateHistory.client_id == contract.client_id)
        | (RateHistory.client_id.is_(None))
    )
    history_query = history_query.order_by(RateHistory.start_date.desc())

    finance_ok = can_read_client_finance(
        current_user,
        client_id=contract.client_id,
        delivery_lead_finance_client_ids=(
            await resolve_delivery_lead_finance_client_ids(current_user, db)
        ),
    )

    result = await db.execute(history_query)
    return [
        ContractRateHistoryEntry(
            id=r.id,
            rate=(r.rate if finance_ok else None),
            currency=(r.currency if finance_ok else None),
            contract_type=r.contract_type.value
            if hasattr(r.contract_type, "value")
            else str(r.contract_type),
            start_date=r.start_date,
            end_date=r.end_date,
            notes=r.notes,
            created_at=r.created_at,
        )
        for r in result.scalars().all()
    ]


# PATCH kontraktu: admin / Delivery Lead albo Finanse z MANAGE_FINANCE — te
# ostatnie wyłącznie dla pól kwot (22.09.2026).
_CONTRACT_PATCH_OPERATIONAL_ROLES = (UserRole.delivery_lead,)
ContractPatchUser = Annotated[
    User,
    Depends(require_roles_or_finance_manager(*_CONTRACT_PATCH_OPERATIONAL_ROLES)),
]


@router.patch("/{contract_id}", response_model=ContractDetailResponse)
async def update_contract(
    contract_id: int,
    data: ContractUpdate,
    current_user: ContractPatchUser,
    db: AsyncSession = Depends(get_db),
):
    assert_finance_manager_touches_only_amounts(
        current_user,
        data.model_fields_set,
        _CONTRACT_FINANCE_WRITE_FIELDS,
        operational_roles=_CONTRACT_PATCH_OPERATIONAL_ROLES,
    )
    _assert_contract_finance_write_allowed(current_user, data.model_fields_set)
    # FOR UPDATE na rodzicu — ta sama racja co w `update_contract_status`
    # (ocena statusu z pamięci obchodziła `void`), ten sam porządek blokad.
    # Znany dług (audyt 14.09): writery zamówień (`commit_order_write` →
    # `sync_pending_order_contracts`) blokują `client_orders` PRZED `contracts`,
    # czyli odwrotnie — kolizja kończy się `deadlock detected` po jednej stronie
    # (Postgres przerywa, nie psuje danych). Świadomie zaakceptowane; nie
    # ujednolicaj kolejności w jednym miejscu bez drugiego.
    result = await db.execute(
        select(Contract)
        .where(Contract.id == contract_id)
        .options(
            selectinload(Contract.candidate),
            selectinload(Contract.client),
            selectinload(Contract.job),
            selectinload(Contract.candidate_rate_schedule),
            selectinload(Contract.client_rate_schedule),
            selectinload(Contract.framework_rate_schedule),
        )
        .with_for_update()
    )
    contract = result.scalar_one_or_none()
    if not contract:
        raise HTTPException(status_code=404, detail="Contract not found")
    await _ensure_delivery_lead_contract_visible(contract, current_user, db)
    previous_end_date = contract.end_date
    previous_start_date = contract.start_date
    state_before = ContractStateBefore.of(contract)
    # Audyt 22.09 r2 (FIN-03): formularz pokazuje stawkę EFEKTYWNĄ z
    # harmonogramu (``GET /contracts/{id}`` → ``effective_rate_fields``), nie
    # kolumnę cache'u. Porównanie z kolumną robiło z „zmiany na wartość starej
    # kolumny” cichy no-op, a z nieruszonej stawki — fałszywą zmianę.
    previous_rate_client = contract.effective_client_rate(business_today())
    was_incomplete_draft = contract.status == ContractStatus.draft and bool(
        validate_ready_for_activation(contract)
    )
    updates = data.model_dump(exclude_unset=True)
    _normalize_candidate_contact_updates(updates)
    _prepare_update_rate_currencies(contract, updates, set(data.model_fields_set))
    # The candidate-rate schedule ("stawka progresywna") is a relationship, not a
    # scalar column — pull it out of the setattr loop and replace it explicitly.
    # Presence of the key (even as []) is the intent to REPLACE; absence leaves
    # the existing schedule untouched (partial PATCHes stay backward-compatible).
    schedule_sent = "candidate_rate_schedule" in updates
    schedule_input = updates.pop("candidate_rate_schedule", None)
    # The framework-rate schedule ("stawka z umowy ramowej") follows the same
    # replace-on-presence contract as the candidate schedule above.
    framework_sent = "framework_rate_schedule" in updates
    framework_input = updates.pop("framework_rate_schedule", None)
    # `status` NIE może przejść przez pętlę `setattr` niżej — surowy zapis
    # omija maszynę stanów (m.in. wskrzesza terminalny `void`) i zostawia
    # zakończony kontrakt z otwartymi zamówieniami klienta.
    # `_apply_contract_status_change` opisuje komplet skutków.
    status_sent = "status" in updates
    status_target = updates.pop("status", None)
    await _assert_b2b_end_date_update(contract, updates, status_target, db)
    requested_unit = (
        RateUnit(updates["rate_unit"]) if updates.get("rate_unit") is not None else None
    )
    current_unit = RateUnit(contract.rate_unit)
    # Dwa przejścia jednostki bez przeliczenia są odrzucane: NA MD (stawki
    # w Kontraktach są godzinowe) i Z MD na inną jednostkę kontraktu wciąż
    # w MD — samo przestawienie etykiety zostawiłoby kroki harmonogramu (nie
    # wysyłane w tym żądaniu) w MD, czytane odtąd jako zł/h (× 8 błędu).
    # Kontrakt w MD zapisany BEZ zmiany jednostki przelicza się niżej w całości.
    if (
        requested_unit is not None
        and requested_unit != current_unit
        and (RateUnit.daily in (requested_unit, current_unit))
    ):
        _reject_daily_contract_unit()
    # Godziny ↔ ryczałt miesięczny: przeliczenie kwot, nie sama etykieta (W1).
    if requested_unit is not None and requested_unit != current_unit:
        schedule_changed, framework_changed = _switch_unit_for_patch(
            contract,
            updates,
            requested_unit,
            previous_rate_client=previous_rate_client,
            today=business_today(),
            schedule_input=schedule_input if schedule_sent else None,
            framework_input=framework_input if framework_sent else None,
        )
        schedule_sent = schedule_sent and schedule_changed
        framework_sent = framework_sent and framework_changed
    for k, v in updates.items():
        setattr(contract, k, v)
    if schedule_sent:
        contract.candidate_rate_schedule = _rebuild_rate_schedule(
            ContractCandidateRate,
            contract.candidate_rate_schedule,
            schedule_input,
            actor_id=current_user.id,
        )
        # A non-empty schedule is authoritative for the cached rate; an empty
        # schedule clears history and defers to the plain `rate_candidate` field
        # (set above by the setattr loop when present in this same PATCH).
        if contract.candidate_rate_schedule:
            contract.rate_candidate = contract.effective_candidate_rate(
                business_today()
            )
    if framework_sent:
        contract.framework_rate_schedule = _rebuild_rate_schedule(
            ContractFrameworkRate,
            contract.framework_rate_schedule,
            framework_input,
            actor_id=current_user.id,
        )
        # A non-empty schedule drives the cached framework_rate; an empty schedule
        # clears history and defers to the plain `framework_rate` field (set by the
        # setattr loop when present in this same PATCH).
        if contract.framework_rate_schedule:
            contract.framework_rate = contract.effective_framework_rate(
                business_today()
            )
    # Kontrakt wciąż w MD (sprzed korekty 0309) — zapis przelicza CAŁY kontrakt
    # na zł/h. Wszystkie kwoty (także przysłane w tym żądaniu) są wtedy w MD.
    normalized_from_daily = apply_contract_hourly_policy(contract)
    if normalized_from_daily:
        updates["rate_unit"] = RateUnit.hourly
        updates["billing_hours_per_month"] = contract.billing_hours_per_month
        updates["orders_in_md"] = contract.orders_in_md

    draft_orders_inherited = 0
    if data.model_fields_set & _DRAFT_ORDER_RATE_INHERITANCE_INPUTS:
        draft_orders_inherited = await _inherit_rates_into_unpriced_order_drafts(
            db, contract
        )
    # Przejście stanu PO zapisaniu pozostałych pól ORAZ po wyprowadzeniu stawek
    # z harmonogramów, nie przed. Dotyczy to zarówno jawnego statusu, jak i
    # automatycznej aktywacji po domknięciu wymaganych danych. Kolejność jest
    # nośna w obie strony:
    # `activate_contract` sprawdza komplet pól, więc musi widzieć wartości
    # z TEGO żądania, a domknięcie umowy przypina `end_date` do dziś — pętla
    # `setattr` odtworzyłaby potem przysłaną datę i zostawiła `ended` z datą
    # w przyszłości, czyli status niezgodny z własną datą.
    #
    # Harmonogram MUSI być przed przejściem z tego samego powodu, dla którego
    # jest przed nim w POST (patrz `create_contract`): formularz rejestru
    # wysyła stawkę kandydata ALBO jako `rate_candidate`, ALBO — gdy jest
    # progresywna — wyłącznie jako `candidate_rate_schedule`. Przy starej
    # kolejności bramka oglądała jeszcze pustą kolumnę cache'u i odmawiała
    # aktywacji z „missing: rate_candidate", mimo że stawka przyszła w tym
    # samym żądaniu — a linijkę niżej ta sama kolumna była już wypełniana.
    auto_activated = False
    if status_sent and status_target is not None:
        status_before_change = contract.status
        await _apply_contract_status_change(
            db,
            contract,
            ContractStatus(status_target),
            actor_id=current_user.id,
        )
        # Umowa B2B przywrócona z „Zakończony"/„Kończący się" na „Aktywny"
        # wraca BEZTERMINOWA — ta sama reguła co wskrzeszenie zamówieniem
        # (`sync_contract_to_live_order`). Ze starą datą nocny cron kończyłby
        # ją ponownie następnej nocy. Datę jawnie zmienioną w tym samym
        # żądaniu zostawiamy (pilnuje jej `_assert_b2b_end_date_update`).
        if (
            is_b2b(contract.contract_type)
            and status_before_change in (ContractStatus.ended, ContractStatus.ending)
            and contract.status == ContractStatus.active
            and contract.end_date is not None
            and contract.end_date == previous_end_date
        ):
            contract.end_date = None
            updates["end_date"] = None
        # Audyt ma nieść WYNIK przejścia, nie żądaną wartość — przejście
        # potrafi wylądować gdzie indziej niż na wprost przysłanej wartości.
        updates["status"] = contract.status.value
    elif (
        not status_sent
        and was_incomplete_draft
        and data.model_fields_set & _AUTO_ACTIVATION_INPUTS
    ):
        auto_activated = await auto_activate_complete_draft(
            db,
            contract,
            actor_id=current_user.id,
            status_explicit=False,
        )
        if auto_activated:
            updates["status"] = contract.status.value
            # Do not emit the legacy ``contract_signed`` Teams event here.
            # Operational readiness is signature-independent, so automatic
            # completion must not announce a signature that may not exist.
    # Coherence guard: a PATCH that leaves the contract indefinite or with a
    # future end date makes a stored "Zakończony"/"Kończący się" stale. Reset to
    # active so editing only the end date to "bezterminowo" heals a contract
    # wrongly marked ended; the daily cron re-derives "ending" within 30 days.
    #
    # Pomijany, gdy PATCH NIÓSŁ status: to samoleczenie jest heurystyką
    # („nikt nie prosił, więc domyśl się z daty"), a jawny wybór operatora nie
    # jest heurystyką. Bez tego wyjątku wybranie „Zakończony" dla umowy
    # bezterminowej zostałoby natychmiast cofnięte na `active` w tym samym
    # żądaniu — zapis zwracałby 200 i nie robił nic.
    if not status_sent:
        coerced_status = _status_after_end_date_change(
            contract.status, contract.end_date, business_today()
        )
        if coerced_status != contract.status:
            contract.status = coerced_status
            updates["status"] = coerced_status.value  # reflect the outcome in audit
    # Reguła zakładki „Zakończeni" (09.2026): data końca umowy wpisana w module
    # Kontrakty jest zarazem datą końca ZAMÓWIENIA tej osoby. Otwarte
    # zamówienia dostają tę samą datę (zaczynające się później — anulowane),
    # a ``completed`` dopiero gdy dzień nadejdzie: do daty włącznie osoba jest
    # w „Aktywni", od następnego dnia przenosi ją nocny cron. Wyłącznie
    # SKRACANIE — zamówienie to PO klienta, przedłużenie umowy go nie wydłuża.
    # Zmiana statusu na „Zakończony" ma własny sync w
    # ``_apply_contract_status_change`` — bez wykluczenia liczba w audycie
    # podwajałaby się. Wyczyszczenie daty (bezterminowa) nie rusza zamówień.
    orders_synced_to_end = 0
    if (
        "end_date" in data.model_fields_set
        and contract.end_date is not None
        and contract.end_date != previous_end_date
        and not (status_sent and contract.status == ContractStatus.ended)
    ):
        orders_synced_to_end = await _sync_client_orders_to_contract_end(
            db,
            contract.id,
            contract.end_date,
            actor_id=current_user.id,
            contract_before=state_before,
        )
    # Ręczna stawka przychodowa w kontrakcie z harmonogramem — krok od dziś,
    # inaczej resolver (czytający harmonogram, nie kolumnę) by ją zignorował.
    # Tylko gdy wartość RÓŻNI SIĘ od tej, którą formularz pokazał (stawka
    # efektywna na dziś sprzed zapisu): formularz odsyła całą stawkę przy
    # każdej edycji, więc nieruszona stawka nie może dopisać kroku.
    if "rate_client" in data.model_fields_set and not _same_rate(
        previous_rate_client, data.rate_client
    ):
        apply_manual_client_rate(
            contract,
            (
                convert_order_rate(
                    data.rate_client,
                    RateUnit.daily,
                    RateUnit.hourly,
                    scale=CONTRACT_RATE_SCALE,
                )
                if normalized_from_daily
                else data.rate_client
            ),
            actor_id=current_user.id,
            today=business_today(),
        )
    # Synchronizacja z zamówieniami tej osoby: kontrakt jest źródłem stawki
    # kosztowej zamówień, a zamówienia — okresu zamówienia i stawki
    # przychodowej kontraktu. Jawnie wybrana w tym zapisie jednostka wygrywa
    # z jednostką zamówienia, a jawny status — z automatyczną aktywacją.
    order_sync = None
    if data.model_fields_set & _ORDER_SYNC_INPUTS or orders_synced_to_end:
        order_sync = await resync_contract_safely(
            db,
            contract,
            actor_id=current_user.id,
            auto_activate=not status_sent,
            follow_order_unit="rate_unit" not in data.model_fields_set,
            follow_order_currency=not (
                {"currency", "rate_client_currency"} & data.model_fields_set
            ),
            audit=False,
        )
        if order_sync is not None and order_sync.activated:
            updates["status"] = contract.status.value
    contract.margin = contract.calculate_margin()
    db.add(
        Activity(
            entity_type="contract",
            entity_id=contract_id,
            action="updated",
            user_id=current_user.id,
            details={
                **{
                    k: (v.isoformat() if hasattr(v, "isoformat") else v)
                    for k, v in updates.items()
                },
                **(
                    {"candidate_rate_schedule_steps": len(schedule_input or [])}
                    if schedule_sent
                    else {}
                ),
                **(
                    {"framework_rate_schedule_steps": len(framework_input or [])}
                    if framework_sent
                    else {}
                ),
                **({"auto_activated": True} if auto_activated else {}),
                **(
                    {"order_drafts_inherited_rates": draft_orders_inherited}
                    if draft_orders_inherited
                    else {}
                ),
                **(
                    {"orders_synced_to_end_date": orders_synced_to_end}
                    if orders_synced_to_end
                    else {}
                ),
                **(
                    {"order_sync": order_sync.as_details()}
                    if order_sync is not None and order_sync.changed
                    else {}
                ),
                # Formularz odsyła datę rozpoczęcia przy KAŻDYM zapisie, więc
                # sama nowa wartość nie mówi, czy ktoś ją zmienił. Poprzednia
                # pojawia się tylko przy realnej zmianie (zgłoszenie 21.09.2026).
                **(
                    {
                        "previous_start_date": (
                            previous_start_date.isoformat()
                            if previous_start_date
                            else None
                        )
                    }
                    if contract.start_date != previous_start_date
                    else {}
                ),
            },
        )
    )
    await db.flush()
    if schedule_sent or framework_sent or order_sync is not None:
        # Reload with relations so the response carries the replaced schedule
        # (+ ids/created_at) without risking an async lazy-load on the collection
        # we just reassigned. Mirrors create_contract's re-select.
        reloaded = await db.execute(
            select(Contract)
            .where(Contract.id == contract_id)
            .options(
                selectinload(Contract.candidate),
                selectinload(Contract.client),
                selectinload(Contract.job),
                selectinload(Contract.candidate_rate_schedule),
                selectinload(Contract.client_rate_schedule),
                selectinload(Contract.framework_rate_schedule),
            )
        )
        detail = _to_detail(reloaded.scalar_one())
    else:
        await db.refresh(contract)
        detail = _to_detail(contract)
    # Operacyjny PATCH bez pól finansowych pozostaje dostępny. Kwoty z
    # odpowiedzi widzi tylko globalna rola finansowa albo DL tego klienta.
    if not await _can_read_contract_finance(contract, current_user, db):
        _redact_contract_finance(detail)
    return detail


@router.patch("/{contract_id}/status", response_model=ContractDetailResponse)
async def update_contract_status(
    contract_id: int,
    data: ContractStatusUpdate,
    current_user: ContractStatusWriteUser,
    db: AsyncSession = Depends(get_db),
):
    """Change only the operational status; TCM cannot mutate other fields."""

    # FOR UPDATE na wierszu `contracts`: maszyna stanów (`assert_transition`,
    # `revert_contract`, `void_contract`) ocenia `contract.status` Z PAMIĘCI,
    # więc dwie równoległe sesje mogły obejść terminalny `void` — pierwsza
    # anulowała, druga na starym obiekcie „cofała do szkicu" i UPDATE po
    # commicie sąsiada przepychał `active → void → draft`. Po blokadzie druga
    # sesja czeka i widzi już `void` (409). `selectinload` idzie osobnymi
    # SELECT-ami, więc blokada dotyczy tylko rodzica — ten sam porządek co
    # cron i `/bulk-mark-ended` (kontrakt PRZED zamówieniami). `resync_contract`
    # bierze ten sam wiersz w tej samej transakcji (re-entrant), bez zakleszczenia.
    result = await db.execute(
        select(Contract)
        .where(Contract.id == contract_id)
        .options(
            selectinload(Contract.candidate),
            selectinload(Contract.client),
            selectinload(Contract.job),
            selectinload(Contract.candidate_rate_schedule),
            selectinload(Contract.client_rate_schedule),
            selectinload(Contract.framework_rate_schedule),
        )
        .with_for_update()
    )
    contract = result.scalar_one_or_none()
    if contract is None:
        raise HTTPException(status_code=404, detail="Contract not found")
    await _ensure_delivery_lead_contract_visible(contract, current_user, db)

    previous_status = contract.status
    await _apply_contract_status_change(
        db, contract, data.status, actor_id=current_user.id
    )
    # „Cofnij zakończenie” z listy statusu: umowa B2B wraca BEZTERMINOWA —
    # lustro PATCH-a kontraktu. Ze starą datą nocny cron zakończyłby ją
    # ponownie następnej nocy, a Generator znów przeniósłby umowę.
    if (
        is_b2b(contract.contract_type)
        and previous_status in (ContractStatus.ended, ContractStatus.ending)
        and contract.status == ContractStatus.active
        and contract.end_date is not None
    ):
        contract.end_date = None
    db.add(
        Activity(
            entity_type="contract",
            entity_id=contract_id,
            action="status_updated",
            user_id=current_user.id,
            details={
                "from_status": previous_status.value,
                "to_status": contract.status.value,
            },
        )
    )
    await db.flush()
    await db.refresh(contract)
    detail = _to_detail(contract)
    if not await _can_read_contract_finance(contract, current_user, db):
        _redact_contract_finance(detail)
    return detail


@router.post("/{contract_id}/activate", response_model=ContractDetailResponse)
async def activate_contract(
    contract_id: int,
    _: ContractActivateRequest,
    current_user: DeliveryLeadPlus,
    db: AsyncSession = Depends(get_db),
):
    """Explicitly flip a draft contract to ``active`` after validation.

    A PATCH that completes an ordinary draft now performs this transition
    automatically. This command remains available for explicit/manual clients
    and for ``ready_for_signature`` contracts. It returns 409 with the stable
    missing-fields list when the operational data is incomplete.
    """
    # FOR UPDATE: status oceniany niżej musi być tym po commicie ewentualnego
    # równoległego `void` (F03) — inaczej unieważniona umowa wraca na `active`.
    result = await db.execute(
        select(Contract)
        .where(Contract.id == contract_id)
        .options(
            selectinload(Contract.candidate),
            selectinload(Contract.client),
            selectinload(Contract.job),
            selectinload(Contract.candidate_rate_schedule),
            selectinload(Contract.client_rate_schedule),
            selectinload(Contract.framework_rate_schedule),
        )
        .with_for_update()
    )
    contract = result.scalar_one_or_none()
    if not contract:
        raise HTTPException(status_code=404, detail="Contract not found")
    await _ensure_delivery_lead_contract_visible(contract, current_user, db)

    if contract.status not in (
        ContractStatus.draft,
        ContractStatus.ready_for_signature,
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Contract is already {contract.status.value}, cannot activate",
        )

    # Single guarded path to `active`. Enforces operational field completeness,
    # independently of any agreement/signature state. Deliberately no
    # Notification row: the auto-draft hook in pipeline.py already fired a
    # `contract_activated` notification when the candidate moved to `hired`
    # (the per-day dedup index would collide). The lifecycle service writes the
    # audit Activity row.
    await lifecycle_activate_contract(db, contract, actor_id=current_user.id)

    # `flush` runs the before_update margin recompute; `refresh` eagerly reloads
    # the server `onupdate` columns (updated_at, margin) in async context so the
    # sync `_to_detail` serializer never triggers a lazy load. Serialize BEFORE
    # the commit so the response is built while the connection is live.
    await db.flush()
    await db.refresh(contract)
    detail = _to_detail(contract)
    if not await _can_read_contract_finance(contract, current_user, db):
        _redact_contract_finance(detail)

    # Bez powiadomienia Teams „contract_signed” (audyt 24.09, N6): aktywacja
    # jest stanem operacyjnym niezależnym od podpisu — ta sama reguła co
    # automatyczna aktywacja w PATCH, która świadomie go nie wysyła. Do tego
    # dnia `/activate` ogłaszał podpis, którego mogło nie być, i odpalał
    # zadanie bez trzymanej referencji (asyncio może je zebrać w połowie).
    return detail


# ── Editable draft (migracja 0058) ───────────────────────────────────────────


async def _load_contract_with_relations(
    db: AsyncSession,
    contract_id: int,
    current_user: User,
    *,
    for_update: bool = False,
) -> Contract:
    """Kontrakt z relacjami; ``for_update=True`` dla handlerów zmieniających status.

    Blokada wiersza jest potrzebna wszędzie, gdzie maszyna stanów ocenia
    ``contract.status``: bez niej równoległy ``void`` commitowany po naszym
    odczycie zostałby nadpisany (F03, audyt 14.09.2026).
    """
    stmt = (
        select(Contract)
        .where(Contract.id == contract_id)
        .options(
            selectinload(Contract.candidate),
            selectinload(Contract.client),
            selectinload(Contract.job),
            selectinload(Contract.candidate_rate_schedule),
            selectinload(Contract.client_rate_schedule),
            selectinload(Contract.framework_rate_schedule),
            selectinload(Contract.b2b_detail).selectinload(B2BContractDetail.role),
        )
    )
    if for_update:
        stmt = stmt.with_for_update()
    contract = await db.scalar(stmt)
    if not contract:
        raise HTTPException(status_code=404, detail="Contract not found")
    await _ensure_delivery_lead_contract_visible(contract, current_user, db)
    return contract


async def _list_templates_for_contract_type(
    db: AsyncSession, contract_type_value: str
) -> list[ContractTemplate]:
    res = await db.execute(
        select(ContractTemplate)
        .where(ContractTemplate.contract_type == contract_type_value)
        .order_by(ContractTemplate.is_default.desc(), ContractTemplate.name)
    )
    return list(res.scalars().all())


def _render_draft_body(template: ContractTemplate, contract: Contract) -> str:
    """Render Jinja template against contract context. Returns raw HTML body
    (no <html> wrap — that's added by the printable endpoint)."""
    try:
        return _jinja_env.from_string(template.content_jinja).render(
            **_contract_vars(contract)
        )
    except TemplateError as exc:
        raise HTTPException(status_code=422, detail=f"Template render error: {exc}")


# Draft/contract HTML is authored by DeliveryLeadPlus (non-admin) users and served
# same-origin for preview. An explicit restrictive CSP is the browser-side
# trust boundary against stored XSS (M5-P0.10): every script is blocked EXCEPT
# our own auto-print snippet, allowed by its SHA-256 hash. Inline styles +
# data: images are permitted so the legal-document formatting still renders.
# Set per-route so it holds even in DEBUG and independent of the incidental
# global default. An injected `<script>`/`onerror=` in the draft body has no
# matching hash → the browser refuses to run it.
# Stałe i otoczka żyją w `app.core.printable_html` — ten sam dokument otwiera
# front jako blob (bez nagłówków odpowiedzi), więc CSP jedzie też w <meta>.
_AUTOPRINT_JS = AUTOPRINT_JS
_AUTOPRINT_HASH = AUTOPRINT_HASH
_CONTRACT_PREVIEW_CSP = PRINTABLE_CSP

_CONTRACT_PRINT_STYLE = (
    "<style>"
    "body{font-family:'Helvetica',Arial,sans-serif;max-width:780px;"
    "margin:40px auto;line-height:1.55;color:#222;padding:0 20px;}"
    "h1,h2,h3{color:#111}"
    "table{border-collapse:collapse;width:100%;margin:1em 0}"
    "th,td{border:1px solid #ccc;padding:6px 10px;text-align:left}"
    "@media print{body{margin:0;padding:0}}"
    "</style>"
)


def _wrap_printable(body_html: str, contract_id: int, title: str) -> str:
    """Wrap raw body HTML with print-friendly stylesheet + auto-print script."""
    return printable_document(
        body_html,
        f"{title} — kontrakt #{contract_id}",
        head_extra=_CONTRACT_PRINT_STYLE,
    )


def _draft_response(
    contract: Contract,
    available_templates: list[ContractTemplate],
    updated_by_name: Optional[str],
    rendered_from_default: bool,
    *,
    content_html_override: Optional[str] = None,
    template_id_override: Optional[int] = None,
) -> ContractDraftResponse:
    return ContractDraftResponse(
        contract_id=contract.id,
        content_html=(
            content_html_override
            if content_html_override is not None
            else contract.draft_content_html
        ),
        template_id=(
            template_id_override
            if template_id_override is not None
            else contract.draft_template_id
        ),
        updated_at=contract.draft_updated_at,
        updated_by=contract.draft_updated_by,
        updated_by_name=updated_by_name,
        available_templates=[
            ContractTemplateBrief.model_validate(t) for t in available_templates
        ],
        rendered_from_default=rendered_from_default,
    )


@router.get("/{contract_id}/draft", response_model=ContractDraftResponse)
async def get_contract_draft(
    contract_id: int,
    current_user: ContractDocumentReadUser,
    db: AsyncSession = Depends(get_db),
):
    """Return draft state for a contract.

    First call (`draft_content_html IS NULL`) lazy-renders the default
    template for this `contract_type`. Existing write roles preserve the legacy
    persisted initialization; Finance receives the same rendered preview
    without mutating the contract or activity log. If no default exists, the
    response carries an empty body.
    """
    contract = await _load_contract_with_relations(db, contract_id, current_user)
    await _assert_contract_document_client_access(contract, current_user, db)
    contract_type_value = (
        contract.contract_type.value
        if hasattr(contract.contract_type, "value")
        else str(contract.contract_type)
    )
    available = await _list_templates_for_contract_type(db, contract_type_value)

    rendered_from_default = False
    preview_content_html: Optional[str] = None
    preview_template_id: Optional[int] = None
    if contract.draft_content_html is None:
        default = next((t for t in available if t.is_default), None)
        if default is not None:
            rendered_from_default = True
            rendered = _render_draft_body(default, contract)
            if current_user.has_role(UserRole.finance) and has_financial_access(
                current_user
            ):
                preview_content_html = rendered
                preview_template_id = default.id
            else:
                contract.draft_content_html = rendered
                contract.draft_template_id = default.id
                contract.draft_updated_at = datetime.now(timezone.utc)
                contract.draft_updated_by = current_user.id
                db.add(
                    Activity(
                        entity_type="contract",
                        entity_id=contract.id,
                        action="draft_initialized",
                        user_id=current_user.id,
                        details={
                            "template_id": default.id,
                            "template_name": default.name,
                        },
                    )
                )
                await db.flush()

    updated_by_name: Optional[str] = None
    if contract.draft_updated_by:
        updated_by_name = await db.scalar(
            select(User.email).where(User.id == contract.draft_updated_by)
        )

    return _draft_response(
        contract,
        available,
        updated_by_name,
        rendered_from_default,
        content_html_override=preview_content_html,
        template_id_override=preview_template_id,
    )


@router.patch("/{contract_id}/draft", response_model=ContractDraftResponse)
async def update_contract_draft(
    contract_id: int,
    payload: ContractDraftUpdate,
    current_user: DeliveryLeadPlus,
    db: AsyncSession = Depends(get_db),
):
    """Update the draft body. Two mutually exclusive modes:

    - `template_id` only → re-render that template (overwrites content).
    - `content_html` only → save edited body verbatim.
    """
    if payload.template_id is None and payload.content_html is None:
        raise HTTPException(
            status_code=422,
            detail="Provide either `template_id` (re-render) or `content_html` (save).",
        )
    if payload.template_id is not None and payload.content_html is not None:
        raise HTTPException(
            status_code=422,
            detail=(
                "Choose one: `template_id` re-renders and discards manual edits, "
                "`content_html` saves manual edits."
            ),
        )

    contract = await _load_contract_with_relations(db, contract_id, current_user)
    await _assert_contract_document_client_access(contract, current_user, db)

    if payload.template_id is not None:
        tpl = await db.scalar(
            select(ContractTemplate).where(ContractTemplate.id == payload.template_id)
        )
        if not tpl:
            raise HTTPException(status_code=404, detail="Template not found")
        contract.draft_content_html = _render_draft_body(tpl, contract)
        contract.draft_template_id = tpl.id
        action = "draft_template_changed"
        details = {"template_id": tpl.id, "template_name": tpl.name}
    else:
        contract.draft_content_html = payload.content_html
        action = "draft_edited"
        details = {"length": len(payload.content_html or "")}

    contract.draft_updated_at = datetime.now(timezone.utc)
    contract.draft_updated_by = current_user.id

    db.add(
        Activity(
            entity_type="contract",
            entity_id=contract.id,
            action=action,
            user_id=current_user.id,
            details=details,
        )
    )
    await db.flush()

    contract_type_value = (
        contract.contract_type.value
        if hasattr(contract.contract_type, "value")
        else str(contract.contract_type)
    )
    available = await _list_templates_for_contract_type(db, contract_type_value)
    updated_by_name = await db.scalar(
        select(User.email).where(User.id == current_user.id)
    )
    return _draft_response(contract, available, updated_by_name, False)


@router.get("/{contract_id}/draft/render-pdf", response_class=HTMLResponse)
async def render_draft_for_print(
    contract_id: int,
    current_user: ContractDocumentReadUser,
    db: AsyncSession = Depends(get_db),
):
    """Return the draft body wrapped in a printable HTML page.

    The browser opens this URL in a new tab; an embedded `window.print()`
    fires the OS print dialog where the user picks "Save as PDF". No
    server-side PDF dependency required.
    """
    contract = await _load_contract_with_relations(db, contract_id, current_user)
    await _assert_contract_document_client_access(contract, current_user, db)
    body = contract.draft_content_html
    if (
        not body
        and current_user.has_role(UserRole.finance)
        and has_financial_access(current_user)
    ):
        contract_type_value = (
            contract.contract_type.value
            if hasattr(contract.contract_type, "value")
            else str(contract.contract_type)
        )
        available = await _list_templates_for_contract_type(db, contract_type_value)
        default = next(
            (template for template in available if template.is_default), None
        )
        if default is not None:
            body = _render_draft_body(default, contract)
    if not body:
        raise HTTPException(
            status_code=404,
            detail="Draft is empty — open the editor and pick a template first.",
        )
    title = (
        contract.candidate
        and f"{contract.candidate.name} {contract.candidate.lastname}"
    ) or "Umowa"
    return HTMLResponse(
        content=_wrap_printable(body, contract.id, title),
        headers={"Content-Security-Policy": _CONTRACT_PREVIEW_CSP},
    )


@router.post(
    "/{contract_id}/draft/finalize",
    response_model=ContractDraftFinalizeResponse,
)
async def finalize_contract_draft(
    contract_id: int,
    current_user: DeliveryLeadPlus,
    db: AsyncSession = Depends(get_db),
):
    """Snapshot the draft as a `ContractDocument(doc_type=contract)` and move
    the contract from `draft` to `ready_for_signature`.

    An unsigned finalized draft is NOT active — finalizing produces the immutable
    snapshot that is then sent for a qualified signature, and the contract stops
    at `ready_for_signature`. Reaching `active` still requires the guarded
    `/activate` path (which enforces signed evidence). Reuses the same
    field-validation rule as `/activate` so the UI can show a consistent
    missing-field list. No `contract_signed` side effect fires here — the
    contract is not signed yet.
    """
    contract = await _load_contract_with_relations(
        db, contract_id, current_user, for_update=True
    )
    await _assert_contract_document_client_access(contract, current_user, db)

    if contract.status != ContractStatus.draft:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Contract is already {contract.status.value}, cannot finalize draft",
        )

    if not contract.draft_content_html:
        raise HTTPException(
            status_code=422,
            detail="Draft is empty — generate or paste content before finalizing.",
        )

    # Validate required fields BEFORE writing the snapshot to storage, so a
    # 409 never leaves an orphan file behind.
    missing = validate_ready_for_activation(contract)
    if missing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"message": "Missing required fields", "missing": missing},
        )

    # Persist the rendered draft as an immutable HTML snapshot.
    candidate_label = (
        f"{contract.candidate.name}_{contract.candidate.lastname}"
        if contract.candidate
        else f"contract_{contract.id}"
    )
    filename = (
        f"umowa_{candidate_label}_{contract.start_date.isoformat()}.html"
    ).replace(" ", "_")
    snapshot_html = _wrap_printable(
        contract.draft_content_html, contract.id, "Umowa (snapshot draftu)"
    )
    blob = snapshot_html.encode("utf-8")
    relative_path, size = storage_service.save_contract_document(
        contract_id=contract.id,
        upload_filename=filename,
        source=BytesIO(blob),
    )

    doc = ContractDocument(
        contract_id=contract.id,
        filename=filename,
        file_path=relative_path,
        content_type="text/html",
        size_bytes=size,
        doc_type=ContractDocumentType.contract,
        uploaded_by=current_user.id,
    )
    db.add(doc)
    db.add(
        Activity(
            entity_type="contract",
            entity_id=contract.id,
            action="draft_finalized",
            user_id=current_user.id,
            details={"snapshot_filename": filename},
        )
    )

    # Guarded transition to `ready_for_signature` (NOT `active`): the snapshot is
    # unsigned. No `contract_signed` side effect — the contract is not signed.
    await move_to_ready_for_signature(db, contract, actor_id=current_user.id)

    await db.flush()
    await db.refresh(doc)

    return ContractDraftFinalizeResponse(
        contract_id=contract.id,
        status=contract.status,
        document_id=doc.id,
        document_filename=doc.filename,
    )


@router.post("/{contract_id}/reopen", response_model=ContractDetailResponse)
async def reopen_contract_endpoint(
    contract_id: int,
    data: ContractReopenRequest,
    current_user: DeliveryLeadPlus,
    db: AsyncSession = Depends(get_db),
):
    """Audited revert to `draft` — the guarded replacement for free status writes.

    Legitimate uses: a mistakenly activated/finalized/ended contract that needs
    to go back to editing. Terminal metadata is cleared. Illegal transitions
    (e.g. reopening a `void`) return 409.
    """
    # FOR UPDATE: bez blokady cofnięcie czyta `active` sprzed commitu
    # równoległego `void` i przepycha `active → void → draft` (F03).
    result = await db.execute(
        select(Contract)
        .where(Contract.id == contract_id)
        .options(
            selectinload(Contract.candidate),
            selectinload(Contract.client),
            selectinload(Contract.job),
            selectinload(Contract.candidate_rate_schedule),
            selectinload(Contract.client_rate_schedule),
            selectinload(Contract.framework_rate_schedule),
        )
        .with_for_update()
    )
    contract = result.scalar_one_or_none()
    if not contract:
        raise HTTPException(status_code=404, detail="Contract not found")
    await _ensure_delivery_lead_contract_visible(contract, current_user, db)

    await revert_contract(db, contract, actor_id=current_user.id, reason=data.reason)
    await db.flush()
    await db.refresh(contract)
    detail = _to_detail(contract)
    if not await _can_read_contract_finance(contract, current_user, db):
        _redact_contract_finance(detail)
    return detail


@router.post("/{contract_id}/void", response_model=ContractDetailResponse)
async def void_contract_endpoint(
    contract_id: int,
    data: ContractVoidRequest,
    current_user: DeliveryLeadPlus,
    db: AsyncSession = Depends(get_db),
):
    """Soft-delete (annul) a contract, preserving documents + signature evidence.

    The safe alternative to a hard DELETE for executed/active contracts.
    """
    # FOR UPDATE na rodzicu — ta sama racja co w `update_contract_status`
    # (ocena statusu z pamięci obchodziła `void`), ten sam porządek blokad.
    result = await db.execute(
        select(Contract)
        .where(Contract.id == contract_id)
        .options(
            selectinload(Contract.candidate),
            selectinload(Contract.client),
            selectinload(Contract.job),
            selectinload(Contract.candidate_rate_schedule),
            selectinload(Contract.client_rate_schedule),
            selectinload(Contract.framework_rate_schedule),
        )
        .with_for_update()
    )
    contract = result.scalar_one_or_none()
    if not contract:
        raise HTTPException(status_code=404, detail="Contract not found")
    await _ensure_delivery_lead_contract_visible(contract, current_user, db)

    await void_contract(db, contract, actor_id=current_user.id, reason=data.reason)
    await db.flush()
    await db.refresh(contract)
    detail = _to_detail(contract)
    if not await _can_read_contract_finance(contract, current_user, db):
        _redact_contract_finance(detail)
    return detail


@router.delete("/{contract_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_contract(
    contract_id: int, current_user: DeliveryLeadPlus, db: AsyncSession = Depends(get_db)
):
    """Trwale usuń kontrakt z modułu Kontrakty — i TYLKO ten rekord.

    Kandydat zostaje w module Kandydaci (FK działa w drugą stronę), a
    wygenerowane umowy B2B zostają w „Wygenerowane umowy" — niepodpisane
    (oraz podpisane, których ``client_id`` jawnie wskazuje INNEGO klienta niż
    kasowany kontrakt, czyli link po rozjeździe) są odpinane (``contract_id``
    → NULL, stan „umowa bez projektu") zamiast blokować operację FK-iem
    RESTRICT. Pod-zasoby kontraktu (dokumenty,
    aneksy, harmonogramy, onboarding, sprzęt, faktury, zamówienia) idą FK
    CASCADE — to dane TEGO kontraktu, a przypadek użycia to wiersz dodany
    błędnie albo zdublowany. Notatki i rozmowy zostają odpięte (FK SET NULL).

    Odmowa wyłącznie przy PODPISANYCH dowodach (podpis kwalifikowany albo
    umowa B2B potwierdzona obustronnie) — patrz ``hard_delete_blocker``.
    Ukończony podpis kwalifikowany pozostaje bezwzględną blokadą, bo jego FK
    skasowałby dowód. Podpisaną wygenerowaną B2B może wyjątkowo usunąć Admin
    przez drugi, jawnie potwierdzany endpoint; zwykły DELETE nigdy tego nie
    obchodzi.
    """
    async with audited_deletion(
        db,
        actor=current_user,
        event_type="contract.delete",
        entity_type="contract",
        entity_id=contract_id,
    ) as audit:
        result = await db.execute(select(Contract).where(Contract.id == contract_id))
        contract = result.scalar_one_or_none()
        if not contract:
            raise HTTPException(status_code=404, detail="Contract not found")
        await _describe_contract_for_audit(db, contract, audit)
        await _ensure_delivery_lead_contract_visible(contract, current_user, db)

        await hard_delete_contract(db, contract, actor_id=current_user.id)


async def _describe_contract_for_audit(
    db: AsyncSession, contract: Contract, audit: DeletionAudit
) -> None:
    """Etykieta kontraktu do Historii zdarzeń — czytana PRZED usunięciem.

    Bez imienia i nazwiska kontraktora: wpis przeżywa usunięcie kandydata
    (art. 17 RODO), a numer kontraktu i klient wystarczają, żeby wiedzieć,
    czego dotyczył.
    """

    audit.describe(
        label=f"Kontrakt #{contract.id}",
        client_id=contract.client_id,
        status=getattr(contract.status, "value", contract.status),
    )


@router.post(
    "/{contract_id}/force-delete-signed",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def force_delete_signed_contract(
    contract_id: int,
    data: ContractSignedDeleteRequest,
    current_user: AdminUser,
    db: AsyncSession = Depends(get_db),
):
    """Admin-only break-glass delete for a contract protected by signed B2B.

    The shared service re-locks the contract and all signature/agreement rows,
    re-evaluates the blocker, and validates the exact contractor full name or
    contract number (``563`` / ``#563``). The signed generated agreement is
    detached and remains in its register; completed qualified signatures are
    intentionally not overridable because deleting the contract would cascade
    away their proof.
    """
    async with audited_deletion(
        db,
        actor=current_user,
        event_type="contract.force_delete_signed",
        entity_type="contract",
        entity_id=contract_id,
    ) as audit:
        contract = await db.get(Contract, contract_id)
        if contract is None:
            raise HTTPException(status_code=404, detail="Contract not found")
        await _describe_contract_for_audit(db, contract, audit)

        await hard_delete_contract(
            db,
            contract,
            actor_id=current_user.id,
            force_signed_confirmation=data.confirmation,
        )


# ── Documents (Phase 9 A4) ────────────────────────────────────────────────────


async def _assert_contract(
    db: AsyncSession,
    contract_id: int,
    current_user: User,
) -> Contract:
    contract = await db.scalar(select(Contract).where(Contract.id == contract_id))
    if contract is None:
        raise HTTPException(status_code=404, detail="Contract not found")
    await _ensure_delivery_lead_contract_visible(contract, current_user, db)
    return contract


async def _document_to_response(
    db: AsyncSession, doc: ContractDocument
) -> ContractDocumentResponse:
    user_email: Optional[str] = None
    if doc.uploaded_by:
        user_email = await db.scalar(
            select(User.email).where(User.id == doc.uploaded_by)
        )
    return ContractDocumentResponse(
        id=doc.id,
        contract_id=doc.contract_id,
        filename=doc.filename,
        doc_type=doc.doc_type,
        content_type=doc.content_type,
        size_bytes=doc.size_bytes,
        expiry_date=doc.expiry_date,
        uploaded_by=doc.uploaded_by,
        uploaded_by_email=user_email,
        created_at=doc.created_at,
    )


@router.get(
    "/{contract_id}/documents",
    response_model=List[ContractDocumentResponse],
)
async def list_contract_documents(
    contract_id: int,
    current_user: ContractDocumentReadUser,
    db: AsyncSession = Depends(get_db),
):
    contract = await _assert_contract(db, contract_id, current_user)
    await _assert_contract_document_client_access(contract, current_user, db)
    result = await db.execute(
        select(ContractDocument)
        .where(ContractDocument.contract_id == contract_id)
        .order_by(ContractDocument.created_at.desc())
    )
    docs = list(result.scalars().all())
    return [await _document_to_response(db, d) for d in docs]


@router.post(
    "/{contract_id}/documents",
    response_model=ContractDocumentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_contract_document(
    contract_id: int,
    current_user: DeliveryLeadPlus,
    db: AsyncSession = Depends(get_db),
    file: UploadFile = File(...),
    doc_type: ContractDocumentType = Form(ContractDocumentType.other),
    expiry_date: Optional[date] = Form(None),
):
    contract = await _assert_contract(db, contract_id, current_user)
    await _assert_contract_document_client_access(contract, current_user, db)

    # Rudimentary size guard — FastAPI's UploadFile is a SpooledTemporaryFile,
    # so we only know the true size after reading. We read via storage_service
    # which returns the byte count and lets us reject oversized files.
    relative_path, size = storage_service.save_contract_document(
        contract_id=contract_id,
        upload_filename=file.filename or "file",
        source=file.file,
    )
    if size > MAX_UPLOAD_BYTES:
        storage_service.delete_contract_document(relative_path)
        raise HTTPException(
            status_code=413,
            detail=f"File exceeds {MAX_UPLOAD_BYTES // (1024 * 1024)} MB",
        )

    doc = ContractDocument(
        contract_id=contract_id,
        filename=file.filename or "file",
        file_path=relative_path,
        content_type=file.content_type,
        size_bytes=size,
        doc_type=doc_type,
        expiry_date=expiry_date,
        uploaded_by=current_user.id,
    )
    db.add(doc)
    db.add(
        Activity(
            entity_type="contract",
            entity_id=contract_id,
            action="document_uploaded",
            user_id=current_user.id,
            details={
                "filename": doc.filename,
                "doc_type": doc_type.value
                if hasattr(doc_type, "value")
                else str(doc_type),
                "size_bytes": size,
            },
        )
    )
    await db.flush()
    await db.refresh(doc)
    return await _document_to_response(db, doc)


@router.patch(
    "/{contract_id}/documents/{document_id}",
    response_model=ContractDocumentResponse,
)
async def update_contract_document(
    contract_id: int,
    document_id: int,
    data: ContractDocumentUpdate,
    current_user: DeliveryLeadPlus,
    db: AsyncSession = Depends(get_db),
):
    contract = await _assert_contract(db, contract_id, current_user)
    await _assert_contract_document_client_access(contract, current_user, db)
    result = await db.execute(
        select(ContractDocument).where(
            ContractDocument.id == document_id,
            ContractDocument.contract_id == contract_id,
        )
    )
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    updates = data.model_dump(exclude_unset=True)
    for k, v in updates.items():
        setattr(doc, k, v)
    await db.flush()
    await db.refresh(doc)
    return await _document_to_response(db, doc)


@router.get("/{contract_id}/documents/{document_id}/download")
async def download_contract_document(
    contract_id: int,
    document_id: int,
    current_user: ContractDocumentReadUser,
    db: AsyncSession = Depends(get_db),
):
    contract = await _assert_contract(db, contract_id, current_user)
    await _assert_contract_document_client_access(contract, current_user, db)
    result = await db.execute(
        select(ContractDocument).where(
            ContractDocument.id == document_id,
            ContractDocument.contract_id == contract_id,
        )
    )
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    try:
        abs_path = storage_service.get_contract_document_path(doc.file_path)
    except FileNotFoundError:
        raise HTTPException(status_code=410, detail="File no longer on storage")
    return FileResponse(
        path=str(abs_path),
        filename=doc.filename,
        media_type=doc.content_type or "application/octet-stream",
    )


@router.delete(
    "/{contract_id}/documents/{document_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_contract_document(
    contract_id: int,
    document_id: int,
    current_user: DeliveryLeadPlus,
    db: AsyncSession = Depends(get_db),
):
    contract = await _assert_contract(db, contract_id, current_user)
    await _assert_contract_document_client_access(contract, current_user, db)
    result = await db.execute(
        select(ContractDocument).where(
            ContractDocument.id == document_id,
            ContractDocument.contract_id == contract_id,
        )
    )
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    storage_service.delete_contract_document(doc.file_path)
    db.add(
        Activity(
            entity_type="contract",
            entity_id=contract_id,
            action="document_deleted",
            user_id=current_user.id,
            details={"filename": doc.filename},
        )
    )
    await db.delete(doc)


# ── Amendments (Phase 9 B3) ──────────────────────────────────────────────────


async def _amendment_to_response(
    db: AsyncSession,
    amendment: ContractAmendment,
    *,
    finance_ok: bool,
) -> ContractAmendmentResponse:
    user_email: Optional[str] = None
    if amendment.created_by:
        user_email = await db.scalar(
            select(User.email).where(User.id == amendment.created_by)
        )
    return ContractAmendmentResponse(
        id=amendment.id,
        contract_id=amendment.contract_id,
        amendment_type=amendment.amendment_type,
        old_values=(
            amendment.old_values
            if finance_ok
            else redact_financial_fields(amendment.old_values)
        ),
        new_values=(
            amendment.new_values
            if finance_ok
            else redact_financial_fields(amendment.new_values)
        ),
        effective_date=amendment.effective_date,
        reason=amendment.reason,
        document_id=amendment.document_id,
        created_by=amendment.created_by,
        created_by_email=user_email,
        created_at=amendment.created_at,
    )


@router.get(
    "/{contract_id}/amendments",
    response_model=List[ContractAmendmentResponse],
)
async def list_contract_amendments(
    contract_id: int,
    current_user: ContractReadUser,
    db: AsyncSession = Depends(get_db),
):
    contract = await _assert_contract(db, contract_id, current_user)
    result = await db.execute(
        select(ContractAmendment)
        .where(ContractAmendment.contract_id == contract_id)
        .order_by(ContractAmendment.created_at.desc())
    )
    amendments = list(result.scalars().all())
    finance_ok = await _can_read_contract_finance(contract, current_user, db)
    return [
        await _amendment_to_response(db, a, finance_ok=finance_ok) for a in amendments
    ]


@router.post(
    "/{contract_id}/amendments",
    response_model=ContractAmendmentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_contract_amendment(
    contract_id: int,
    data: ContractAmendmentCreate,
    current_user: DeliveryLeadPlus,
    db: AsyncSession = Depends(get_db),
):
    supplied_fields = set(data.model_fields_set)
    if data.amendment_type == ContractAmendmentType.rate_change:
        supplied_fields.add("rate_change")
    _assert_contract_finance_write_allowed(current_user, supplied_fields)

    # FOR UPDATE: aneks przedłużający i wcześniejsze zakończenie zmieniają
    # status — oceniany musi być ten po commicie równoległego `void` (F03).
    contract_res = await db.execute(
        select(Contract)
        .where(Contract.id == contract_id)
        .options(
            selectinload(Contract.candidate_rate_schedule),
            selectinload(Contract.client_rate_schedule),
            selectinload(Contract.framework_rate_schedule),
        )
        .with_for_update()
    )
    contract = contract_res.scalar_one_or_none()
    if not contract:
        raise HTTPException(status_code=404, detail="Contract not found")
    await _ensure_delivery_lead_contract_visible(contract, current_user, db)

    # Snapshot only the fields that might change, for audit.
    old_values: dict = {
        "end_date": contract.end_date.isoformat() if contract.end_date else None,
        "client_order_end_date": (
            contract.client_order_end_date.isoformat()
            if contract.client_order_end_date
            else None
        ),
        "rate_candidate": contract.rate_candidate,
        "rate_client": contract.rate_client,
        "rate_unit": contract.rate_unit.value
        if hasattr(contract.rate_unit, "value")
        else str(contract.rate_unit),
        "billing_hours_per_month": contract.billing_hours_per_month,
        "project_name": contract.project_name,
        "team_name": contract.team_name,
        "status": contract.status.value
        if hasattr(contract.status, "value")
        else str(contract.status),
    }
    new_values: dict = {}

    # Apply changes per amendment_type
    if data.amendment_type == ContractAmendmentType.extension:
        if data.new_end_date is None:
            raise HTTPException(
                status_code=422,
                detail="new_end_date is required for extension amendment",
            )
        # Aneks przedłużający dawał umowie B2B datę, której nikt nie
        # wypowiedział — dokładnie ten stan, który korekta 09.2026 czyści.
        # Zakończoną ręcznie umowę B2B wolno przedłużyć (przesunięcie końca).
        if is_b2b(contract.contract_type) and not await is_manually_terminated(
            db, contract
        ):
            _reject_b2b_end_date()
        contract.end_date = data.new_end_date
        # Keep "Koniec zamówienia u klienta" in step with the new contract end —
        # an extension renews the client's order alongside the contract. Only
        # touch it when the contract already tracks an order end (see helper).
        synced_order_end = _synced_client_order_end(
            contract.client_order_end_date, data.new_end_date
        )
        if synced_order_end != contract.client_order_end_date:
            contract.client_order_end_date = synced_order_end
            new_values["client_order_end_date"] = (
                synced_order_end.isoformat() if synced_order_end else None
            )
        # Powrót `ending`/`ended` → `active` po przedłużeniu — przez warstwę
        # cyklu życia (audyt `contract_reopened` + `assert_transition`), a nie
        # drugą ręczną kopią tej samej reguły. Patrz `reopen_contract`.
        await reopen_contract(db, contract, actor_id=current_user.id)
        new_values["end_date"] = data.new_end_date.isoformat()
        new_values["status"] = contract.status.value

    elif data.amendment_type == ContractAmendmentType.rate_change:
        # Jednostka i liczba godzin nie mają harmonogramu — zapis zmienia je
        # NATYCHMIAST. Aneks z datą przyszłą przeliczałby więc dzisiejsze
        # kwoty nową jednostką przed dniem jej wejścia w życie (audyt AN-03).
        if (
            data.new_rate_unit is not None
            or data.new_billing_hours_per_month is not None
        ) and data.effective_date > business_today():
            raise HTTPException(
                status_code=422,
                detail=(
                    "Zmianę jednostki lub liczby godzin wpisz w dniu jej wejścia "
                    "w życie — nie da się jej zaplanować z wyprzedzeniem."
                ),
            )
        # Zmiana jednostki PRZED nowymi krokami: istniejące kwoty i kroki są
        # w starej jednostce i przeliczają się (audyt 24.09, W1 — do tego dnia
        # aneks przestawiał samą etykietę i 150 zł/h stawało się 150 zł/mc),
        # a stawki z aneksu są już podane w nowej jednostce.
        if data.new_rate_unit is not None:
            if RateUnit(data.new_rate_unit) == RateUnit.daily:
                _reject_daily_contract_unit()
            if RateUnit(data.new_rate_unit) != RateUnit(contract.rate_unit):
                _switch_contract_unit(
                    contract,
                    RateUnit(data.new_rate_unit),
                    billing_hours=(
                        data.new_billing_hours_per_month
                        if RateUnit(data.new_rate_unit) == RateUnit.hourly
                        else None
                    ),
                )
            new_values["rate_unit"] = data.new_rate_unit
        # Krok bazowy harmonogramu potrzebuje daty. Kontrakt bez daty
        # rozpoczęcia dawał dotąd IntegrityError (500) po stronie kandydata
        # (audyt 24.09, N1), a po stronie klienta krok bazowy „od dziś"
        # przykrywał aneks wsteczny. Najwcześniejsza znana data wygrywa.
        baseline_from = contract.start_date or min(
            data.effective_date, business_today()
        )
        if data.new_rate_candidate is not None:
            # The candidate rate lives in the schedule. Seed a baseline step
            # (the contract's current rate from its start) the first time we
            # touch the schedule so the history stays complete for contracts
            # created before this feature; then append the new step.
            if (
                not contract.candidate_rate_schedule
                and contract.rate_candidate is not None
            ):
                contract.candidate_rate_schedule.append(
                    ContractCandidateRate(
                        rate=contract.rate_candidate,
                        effective_from=baseline_from,
                        note="Stawka początkowa",
                        created_by=current_user.id,
                    )
                )
            contract.candidate_rate_schedule.append(
                ContractCandidateRate(
                    rate=data.new_rate_candidate,
                    effective_from=data.effective_date,
                    note=data.reason,
                    created_by=current_user.id,
                )
            )
            new_values["rate_candidate"] = data.new_rate_candidate
        if data.new_rate_client is not None:
            # The client rate also lives in an effective-dated schedule (mirror
            # of the candidate rate). A future-dated change therefore keeps the
            # old client rate until its effective_date: the running order bills
            # at the old rate to its end, and the new rate applies only from the
            # new order. Seed a baseline step (current rate from the contract's
            # start) the first time we touch the schedule so history stays
            # complete; then append the new step.
            if not contract.client_rate_schedule and contract.rate_client is not None:
                contract.client_rate_schedule.append(
                    ContractClientRate(
                        rate=contract.rate_client,
                        effective_from=baseline_from,
                        note="Stawka początkowa",
                        created_by=current_user.id,
                    )
                )
            contract.client_rate_schedule.append(
                ContractClientRate(
                    rate=data.new_rate_client,
                    effective_from=data.effective_date,
                    note=data.reason,
                    created_by=current_user.id,
                )
            )
            new_values["rate_client"] = data.new_rate_client
        if data.new_billing_hours_per_month is not None:
            contract.billing_hours_per_month = data.new_billing_hours_per_month
            new_values["billing_hours_per_month"] = data.new_billing_hours_per_month
        if not new_values:
            raise HTTPException(
                status_code=422,
                detail="At least one rate field must change for rate_change amendment",
            )
        # Current rates derived from the (updated) schedules — a future-dated
        # step won't change today's rate until it takes effect. Keep the cached
        # columns consistent so direct reads + the margin event see today's rate.
        contract.rate_candidate = contract.effective_candidate_rate(business_today())
        contract.rate_client = contract.effective_client_rate(business_today())
        contract.margin = contract.calculate_margin()

    elif data.amendment_type == ContractAmendmentType.scope_change:
        if data.new_project_name is not None:
            contract.project_name = data.new_project_name
            new_values["project_name"] = data.new_project_name
        if data.new_team_name is not None:
            contract.team_name = data.new_team_name
            new_values["team_name"] = data.new_team_name
        if not new_values:
            raise HTTPException(
                status_code=422,
                detail="scope_change requires new_project_name or new_team_name",
            )

    elif data.amendment_type == ContractAmendmentType.early_termination:
        # Wcześniejsze zakończenie wyłącznie przez okno „Zakończ współpracę”
        # (``/terminate``) — ta sama reguła co zmiana statusu na „Zakończony”
        # (audyt 24.09, S5). Aneks przez API omijał powód, datę końca projektu,
        # rozwiązanie umowy B2B i migawkę do „Cofnij zakończenie”. Historyczne
        # aneksy tego typu zostają (czyta je ``is_manually_terminated``);
        # nowe dopisuje wyłącznie ``/terminate``.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": (
                    "Kontrakt kończy się oknem „Zakończ współpracę” — podaj "
                    "powód i datę zakończenia projektu."
                ),
                "reason": "termination_required",
            },
        )

    # Synchronizacja z zamówieniami: aneks stawki zmienia koszt w KONTRAKCIE
    # (zamówienia dostają go od daty aneksu; przyszła podwyżka wejdzie w swoim
    # dniu przez przebieg dobowy), a przedłużenie i wcześniejsze zakończenie
    # ruszają okres zamówienia. Jednostka z aneksu wygrywa z zamówieniem.
    # Bez automatycznej aktywacji szkicu — aneks nie jest decyzją o aktywacji
    # (audyt 24.09, S8); tę podejmuje PATCH albo `/activate`.
    if data.amendment_type != ContractAmendmentType.scope_change:
        await resync_contract_safely(
            db,
            contract,
            actor_id=current_user.id,
            auto_activate=False,
            follow_order_unit=not (
                data.amendment_type == ContractAmendmentType.rate_change
                and data.new_rate_unit is not None
            ),
        )

    amendment = ContractAmendment(
        contract_id=contract_id,
        amendment_type=data.amendment_type,
        old_values=old_values,
        new_values=new_values,
        effective_date=data.effective_date,
        reason=data.reason,
        document_id=data.document_id,
        created_by=current_user.id,
    )
    db.add(amendment)
    db.add(
        Activity(
            entity_type="contract",
            entity_id=contract_id,
            action=f"amendment_{data.amendment_type.value}",
            user_id=current_user.id,
            details={
                "old": old_values,
                "new": new_values,
                "effective_date": data.effective_date.isoformat(),
            },
        )
    )
    await db.flush()
    await db.refresh(amendment)
    return await _amendment_to_response(
        db,
        amendment,
        finance_ok=await _can_read_contract_finance(contract, current_user, db),
    )


# ── Onboarding checklist (Phase 9 B6) ────────────────────────────────────────


@router.get(
    "/{contract_id}/onboarding",
    response_model=List[OnboardingItemResponse],
)
async def list_onboarding_items(
    contract_id: int,
    current_user: ContractReadUser,
    db: AsyncSession = Depends(get_db),
):
    await _assert_contract(db, contract_id, current_user)
    res = await db.execute(
        select(ContractOnboardingItem)
        .where(ContractOnboardingItem.contract_id == contract_id)
        .order_by(ContractOnboardingItem.order, ContractOnboardingItem.id)
    )
    return list(res.scalars().all())


@router.post(
    "/{contract_id}/onboarding",
    response_model=OnboardingItemResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_onboarding_item(
    contract_id: int,
    data: OnboardingItemCreate,
    current_user: DeliveryLeadPlus,
    db: AsyncSession = Depends(get_db),
):
    await _assert_contract(db, contract_id, current_user)
    item = ContractOnboardingItem(contract_id=contract_id, **data.model_dump())
    db.add(item)
    await db.flush()
    await db.refresh(item)
    return item


# Domyślna lista onboardingowa. Mieszka po stronie serwera, bo front wysyłał ją
# kiedyś jako OSIEM osobnych POST-ów bez blokady: podwójne kliknięcie albo dwie
# karty dawały zdublowaną listę (audyt FE-04).
DEFAULT_ONBOARDING_ITEMS: tuple[str, ...] = (
    "BHP — szkolenie",
    "Podpisana umowa",
    "Sprzęt (laptop)",
    "Dostępy do VPN klienta",
    "Konto w Slacku klienta",
    "Onboarding u PM klienta",
    "Email firmowy",
    "Dostęp do repozytorium",
)


@router.post(
    "/{contract_id}/onboarding/seed",
    response_model=List[OnboardingItemResponse],
)
async def seed_onboarding_items(
    contract_id: int,
    current_user: DeliveryLeadPlus,
    db: AsyncSession = Depends(get_db),
):
    """Załóż domyślną listę onboardingową — atomowo i idempotentnie.

    Blokada ``FOR UPDATE`` na wierszu kontraktu serializuje równoległe
    wywołania: drugie widzi pozycje założone przez pierwsze i zwraca je
    zamiast dopisywać drugi komplet. Lista niepusta = nic nie jest dodawane.
    """
    await _assert_contract(db, contract_id, current_user)
    await db.execute(
        select(Contract.id).where(Contract.id == contract_id).with_for_update()
    )
    existing_query = (
        select(ContractOnboardingItem)
        .where(ContractOnboardingItem.contract_id == contract_id)
        .order_by(ContractOnboardingItem.order, ContractOnboardingItem.id)
    )
    existing = list((await db.execute(existing_query)).scalars().all())
    if existing:
        return existing
    db.add_all(
        ContractOnboardingItem(contract_id=contract_id, label=label, order=idx)
        for idx, label in enumerate(DEFAULT_ONBOARDING_ITEMS)
    )
    await db.flush()
    return list((await db.execute(existing_query)).scalars().all())


@router.patch(
    "/{contract_id}/onboarding/{item_id}",
    response_model=OnboardingItemResponse,
)
async def update_onboarding_item(
    contract_id: int,
    item_id: int,
    data: OnboardingItemUpdate,
    current_user: DeliveryLeadPlus,
    db: AsyncSession = Depends(get_db),
):
    await _assert_contract(db, contract_id, current_user)
    item = await db.scalar(
        select(ContractOnboardingItem).where(
            ContractOnboardingItem.id == item_id,
            ContractOnboardingItem.contract_id == contract_id,
        )
    )
    if not item:
        raise HTTPException(status_code=404, detail="Onboarding item not found")
    for k, v in data.model_dump(exclude_unset=True).items():
        setattr(item, k, v)
    await db.flush()
    await db.refresh(item)
    return item


@router.delete(
    "/{contract_id}/onboarding/{item_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_onboarding_item(
    contract_id: int,
    item_id: int,
    current_user: DeliveryLeadPlus,
    db: AsyncSession = Depends(get_db),
):
    await _assert_contract(db, contract_id, current_user)
    item = await db.scalar(
        select(ContractOnboardingItem).where(
            ContractOnboardingItem.id == item_id,
            ContractOnboardingItem.contract_id == contract_id,
        )
    )
    if not item:
        raise HTTPException(status_code=404, detail="Onboarding item not found")
    await db.delete(item)


# ── Equipment (Kontrakty expansion: ewidencja sprzętu) ──────────────────────


@router.get(
    "/{contract_id}/equipment",
    response_model=List[ContractEquipmentResponse],
)
async def list_contract_equipment(
    contract_id: int,
    current_user: ContractReadUser,
    db: AsyncSession = Depends(get_db),
):
    await _assert_contract(db, contract_id, current_user)
    result = await db.execute(
        select(ContractEquipment)
        .where(ContractEquipment.contract_id == contract_id)
        .order_by(ContractEquipment.created_at.desc())
    )
    return list(result.scalars().all())


@router.post(
    "/{contract_id}/equipment",
    response_model=ContractEquipmentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_contract_equipment(
    contract_id: int,
    data: ContractEquipmentCreate,
    current_user: DeliveryLeadPlus,
    db: AsyncSession = Depends(get_db),
):
    contract_res = await db.execute(select(Contract).where(Contract.id == contract_id))
    contract = contract_res.scalar_one_or_none()
    if not contract:
        raise HTTPException(status_code=404, detail="Contract not found")
    await _ensure_delivery_lead_contract_visible(contract, current_user, db)

    payload = data.model_dump()
    # If the caller didn't supply a return_due_date, default to the contract's
    # end_date so the alert task picks it up automatically.
    if payload.get("return_due_date") is None and contract.end_date is not None:
        payload["return_due_date"] = contract.end_date

    item = ContractEquipment(contract_id=contract_id, **payload)
    db.add(item)
    db.add(
        Activity(
            entity_type="contract",
            entity_id=contract_id,
            action="equipment_added",
            user_id=current_user.id,
            details={
                "item_type": item.item_type.value
                if hasattr(item.item_type, "value")
                else str(item.item_type),
                "serial_number": item.serial_number,
                "owner": item.owner.value
                if hasattr(item.owner, "value")
                else str(item.owner),
            },
        )
    )
    await db.flush()
    await db.refresh(item)
    return item


@router.patch(
    "/{contract_id}/equipment/{equipment_id}",
    response_model=ContractEquipmentResponse,
)
async def update_contract_equipment(
    contract_id: int,
    equipment_id: int,
    data: ContractEquipmentUpdate,
    current_user: DeliveryLeadPlus,
    db: AsyncSession = Depends(get_db),
):
    await _assert_contract(db, contract_id, current_user)
    item = await db.scalar(
        select(ContractEquipment).where(
            ContractEquipment.id == equipment_id,
            ContractEquipment.contract_id == contract_id,
        )
    )
    if not item:
        raise HTTPException(status_code=404, detail="Equipment item not found")
    updates = data.model_dump(exclude_unset=True)
    for k, v in updates.items():
        setattr(item, k, v)
    # Guard: returned_date requires return_status=returned (mark as returned).
    if (
        item.returned_date is not None
        and item.return_status != EquipmentReturnStatus.returned
    ):
        item.return_status = EquipmentReturnStatus.returned
    db.add(
        Activity(
            entity_type="contract",
            entity_id=contract_id,
            action="equipment_updated",
            user_id=current_user.id,
            details={
                k: (v.isoformat() if hasattr(v, "isoformat") else v)
                for k, v in updates.items()
            },
        )
    )
    await db.flush()
    await db.refresh(item)
    return item


@router.delete(
    "/{contract_id}/equipment/{equipment_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_contract_equipment(
    contract_id: int,
    equipment_id: int,
    current_user: DeliveryLeadPlus,
    db: AsyncSession = Depends(get_db),
):
    await _assert_contract(db, contract_id, current_user)
    item = await db.scalar(
        select(ContractEquipment).where(
            ContractEquipment.id == equipment_id,
            ContractEquipment.contract_id == contract_id,
        )
    )
    if not item:
        raise HTTPException(status_code=404, detail="Equipment item not found")
    db.add(
        Activity(
            entity_type="contract",
            entity_id=contract_id,
            action="equipment_removed",
            user_id=current_user.id,
            details={"equipment_id": equipment_id},
        )
    )
    await db.delete(item)


# ── Termination (dedicated endpoint with structured reason) ──────────────────


@router.post(
    "/{contract_id}/terminate",
    response_model=ContractDetailResponse,
)
async def terminate_contract(
    contract_id: int,
    data: ContractTerminateRequest,
    # Te same role co lista statusu (`PATCH /{id}/status`): od 09.2026
    # „Zakończony” z listy otwiera to okno, więc TCM — który mógł zakończyć
    # kontrakt listą — musi móc je zapisać (decyzja 10.09: TCM w całej org.).
    current_user: ContractStatusWriteUser,
    db: AsyncSession = Depends(get_db),
):
    """Mark the contract as ended with a structured reason and optional lessons.

    If the effective date is earlier than the current end_date, an
    `early_termination` amendment is also recorded for audit.
    """
    # FOR UPDATE: zakończenie ocenia bieżący status (F03).
    result = await db.execute(
        select(Contract)
        .where(Contract.id == contract_id)
        .options(
            selectinload(Contract.candidate),
            selectinload(Contract.client),
            selectinload(Contract.job),
            selectinload(Contract.candidate_rate_schedule),
            selectinload(Contract.client_rate_schedule),
            selectinload(Contract.framework_rate_schedule),
        )
        .with_for_update()
    )
    contract = result.scalar_one_or_none()
    if not contract:
        raise HTTPException(status_code=404, detail="Contract not found")
    await _ensure_delivery_lead_contract_visible(contract, current_user, db)

    # Puste pole = „dzisiaj" — kontrakt tego endpointu sprzed wydzielenia
    # helpera; masowe zakończenie ma datę WYMAGANĄ (jedna wartość na N umów).
    when = data.terminated_at or business_today()
    await _apply_termination_to_contract(
        db,
        contract,
        termination_reason=data.termination_reason,
        when=when,
        termination_lessons=data.termination_lessons,
        actor_id=current_user.id,
        agreement_termination=_agreement_termination(data.agreement_termination),
    )
    await db.flush()
    await db.refresh(contract)
    detail = _to_detail(contract)
    if not await _can_read_contract_finance(contract, current_user, db):
        _redact_contract_finance(detail)
    return detail


# ── Cofnięcie zakończenia i powrót po przerwie (0368) ────────────────────────


async def _fill_termination_recovery(
    db: AsyncSession, contract: Contract, detail: ContractDetailResponse
) -> None:
    detail.can_reverse_termination = await reversal_available(db, contract)
    successor = await existing_return(db, contract.id)
    detail.return_contract_id = successor.id if successor is not None else None
    detail.can_return_after_break = (
        contract.status == ContractStatus.ended and successor is None
    )
    reversal = await latest_reversal(db, contract.id)
    if reversal is not None:
        detail.termination_reversed_at = reversal.reversed_at
        if reversal.reversed_by_user_id is not None:
            author = await db.get(User, reversal.reversed_by_user_id)
            if author is not None:
                detail.termination_reversed_by_name = author.name or author.email


async def _lock_contract_for_recovery(db: AsyncSession, contract_id: int) -> Contract:
    contract = await db.scalar(
        select(Contract)
        .where(Contract.id == contract_id)
        .options(
            selectinload(Contract.candidate),
            selectinload(Contract.client),
            selectinload(Contract.job),
            selectinload(Contract.candidate_rate_schedule),
            selectinload(Contract.client_rate_schedule),
            selectinload(Contract.framework_rate_schedule),
        )
        .with_for_update()
    )
    if contract is None:
        raise HTTPException(status_code=404, detail="Contract not found")
    return contract


@router.get(
    "/{contract_id}/termination-reversal",
    response_model=ContractTerminationReversalPlanRead,
)
async def preview_termination_reversal(
    contract_id: int,
    current_user: ContractTerminationRecoveryUser,
    db: AsyncSession = Depends(get_db),
):
    """Okno potwierdzenia „Cofnij zakończenie": co wróci i co blokuje akcję.

    Tylko odczyt — ten sam plan liczy potem wykonanie (pod blokadą).
    """
    contract = await db.scalar(select(Contract).where(Contract.id == contract_id))
    if contract is None:
        raise HTTPException(status_code=404, detail="Contract not found")
    try:
        plan = await build_reversal_plan(db, contract)
    except ReversalUnavailable as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "nothing_to_reverse", "message": str(exc)},
        ) from exc
    return ContractTerminationReversalPlanRead(**plan.as_json())


@router.post(
    "/{contract_id}/termination-reversal",
    response_model=ContractTerminationReversalPlanRead,
)
async def reverse_termination(
    contract_id: int,
    current_user: ContractTerminationRecoveryUser,
    db: AsyncSession = Depends(get_db),
):
    """„Cofnij zakończenie" — kontrakt zakończono przez pomyłkę.

    Kontrakt i każde zamówienie ruszone przez zakończenie wracają do stanu
    sprzed niego; decyzja o puli MD podjęta po zakończeniu blokuje akcję (409
    z listą: które zamówienie, jaka decyzja). Bez limitu czasu.
    """
    contract = await _lock_contract_for_recovery(db, contract_id)
    try:
        plan = await execute_reversal(db, contract, actor_id=current_user.id)
    except ReversalUnavailable as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "nothing_to_reverse", "message": str(exc)},
        ) from exc
    except ReversalBlocked as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "termination_reversal_blocked",
                "message": " ".join(b["message"] for b in exc.plan.blockers),
                "blockers": exc.plan.blockers,
            },
        ) from exc
    result = plan.as_json()
    await commit_order_write(db, actor_id=current_user.id)
    return ContractTerminationReversalPlanRead(**result, executed=True)


@router.post(
    "/{contract_id}/return-after-break",
    response_model=ContractReturnAfterBreakResponse,
    status_code=status.HTTP_201_CREATED,
)
async def return_after_break(
    contract_id: int,
    data: ContractReturnAfterBreakRequest,
    current_user: ContractTerminationRecoveryUser,
    db: AsyncSession = Depends(get_db),
):
    """„Powrót po przerwie" — nowy kontrakt (szkic) powiązany z poprzednim.

    Poprzedni kontrakt zostaje zakończony bez zmian; na jego zamówieniach
    konsultant dostaje nowe przypisanie w statusie Szkic.
    """
    contract = await _lock_contract_for_recovery(db, contract_id)
    result = await create_return_after_break(
        db, contract, start_date=data.start_date, actor_id=current_user.id
    )
    await commit_order_write(db, actor_id=current_user.id)
    return ContractReturnAfterBreakResponse(
        contract_id=result.contract.id,
        returned_from_contract_id=contract.id,
        orders=result.orders,
    )


# ── Notes + Calls timeline per contract ──────────────────────────────────────


@router.get(
    "/{contract_id}/notes",
    response_model=List[ContractTimelineItem],
)
async def contract_timeline(
    contract_id: int,
    current_user: ContractReadUser,
    db: AsyncSession = Depends(get_db),
    limit: int = Query(100, ge=1, le=500),
):
    """Chronological merge of notes + calls attached to this contract."""
    await _assert_contract(db, contract_id, current_user)

    notes_res = await db.execute(
        select(Note, User.email)
        .outerjoin(User, Note.author_id == User.id)
        .where(Note.contract_id == contract_id)
        .order_by(Note.created_at.desc())
        .limit(limit)
    )
    calls_res = await db.execute(
        select(Call, User.email)
        .outerjoin(User, Call.user_id == User.id)
        .where(Call.contract_id == contract_id)
        .order_by(Call.created_at.desc())
        .limit(limit)
    )

    items: list[ContractTimelineItem] = []

    for note, author_email in notes_res.all():
        items.append(
            ContractTimelineItem(
                id=note.id,
                kind="note",
                at=note.created_at,
                content=note.content,
                sub_type=note.note_type.value
                if hasattr(note.note_type, "value")
                else str(note.note_type),
                author_id=note.author_id,
                author_name=author_email,
            )
        )

    for call, author_email in calls_res.all():
        items.append(
            ContractTimelineItem(
                id=call.id,
                kind="call",
                at=call.created_at,
                summary=call.summary,
                content=call.transcript,
                sub_type=call.direction.value
                if hasattr(call.direction, "value")
                else str(call.direction),
                status=call.status.value
                if hasattr(call.status, "value")
                else str(call.status),
                author_id=call.user_id,
                author_name=author_email,
                duration_seconds=call.duration_seconds,
            )
        )

    items.sort(key=lambda i: i.at, reverse=True)
    return items[:limit]


# ── Benchmark comparison (rate vs internal avg vs market) ────────────────────


def _monthly_equivalent(
    rate: object, unit: RateUnit, hours: Optional[int]
) -> Optional[float]:
    """Kwota miesięczna do porównania w benchmarku — w złotych z groszami.

    Do 24.09 (audyt, S1) funkcja obiecywała ``int``, a stawki kontraktu są
    ``Numeric(16, 6)``: 125,19375 zł/h × 168 dawało ułamek, schemat odpowiedzi
    (``Optional[int]``) odrzucał go i karta kończyła się 500.
    """
    if rate is None:
        return None
    amount = Decimal(str(rate))
    if unit == RateUnit.daily:
        amount = amount * MD_PER_MONTH
    elif unit == RateUnit.hourly:
        amount = amount * (hours or HOURS_PER_MONTH)
    return float(amount.quantize(Decimal("0.01")))


async def _resolve_role_for_contract(
    db: AsyncSession, contract: Contract
) -> Optional[str]:
    """Best-effort role extraction: job.title → candidate.competence_category."""
    if contract.job_id:
        title = await db.scalar(select(Job.title).where(Job.id == contract.job_id))
        if title:
            return title
    cc = await db.scalar(
        select(Candidate.competence_category).where(
            Candidate.id == contract.candidate_id
        )
    )
    return cc


@router.get(
    "/{contract_id}/benchmark",
    response_model=ContractBenchmarkComparison,
)
async def contract_benchmark(
    contract_id: int,
    current_user: FinanceReadUser,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Contract)
        .where(Contract.id == contract_id)
        .options(
            selectinload(Contract.candidate),
            selectinload(Contract.client_rate_schedule),
        )
    )
    contract = result.scalar_one_or_none()
    if not contract:
        raise HTTPException(status_code=404, detail="Contract not found")

    today = business_today()
    role = await _resolve_role_for_contract(db, contract)
    # Stawka z harmonogramu na dziś, nie kolumna cache'u (aneks z datą, która
    # już nadeszła, zostawiał w kolumnie starą kwotę).
    contract_rate_monthly = _monthly_equivalent(
        contract.effective_client_rate(today),
        contract.rate_unit,
        contract.billing_hours_per_month,
    )

    # Internal average: other running contracts for the same role — „Kończący
    # się” też pracuje (audyt 24.09, S1).
    internal_avg_monthly: Optional[float] = None
    internal_median_monthly: Optional[float] = None
    internal_sample_size = 0
    if role:
        peer_q = (
            select(Contract, Job.title, Candidate.competence_category)
            .join(Candidate, Candidate.id == Contract.candidate_id)
            .outerjoin(Job, Job.id == Contract.job_id)
            .options(selectinload(Contract.client_rate_schedule))
            .where(
                Contract.id != contract_id,
                Contract.status.in_((ContractStatus.active, ContractStatus.ending)),
                func.upper(
                    func.coalesce(
                        Contract.rate_client_currency,
                        Contract.currency,
                        "PLN",
                    )
                )
                == contract.resolved_rate_client_currency,
                or_(Job.title == role, Candidate.competence_category == role),
            )
        )
        rows = (await db.execute(peer_q)).all()
        monthly_values: list[float] = []
        for peer, _, _ in rows:
            peer_monthly = _monthly_equivalent(
                peer.effective_client_rate(today),
                peer.rate_unit,
                peer.billing_hours_per_month,
            )
            if peer_monthly is not None:
                monthly_values.append(peer_monthly)
        if monthly_values:
            internal_sample_size = len(monthly_values)
            internal_avg_monthly = round(sum(monthly_values) / internal_sample_size, 2)
            sorted_v = sorted(monthly_values)
            mid = internal_sample_size // 2
            internal_median_monthly = (
                sorted_v[mid]
                if internal_sample_size % 2 == 1
                else round((sorted_v[mid - 1] + sorted_v[mid]) / 2, 2)
            )

    # Market benchmark: pick the most recent entry for the role in same currency.
    market_row = None
    if role:
        market_q = (
            select(RateBenchmark)
            .where(
                RateBenchmark.role.ilike(role),
                RateBenchmark.currency == contract.resolved_rate_client_currency,
            )
            .order_by(RateBenchmark.source_date.desc())
            .limit(1)
        )
        market_row = (await db.execute(market_q)).scalar_one_or_none()

    market_min_monthly: Optional[float] = None
    market_median_monthly: Optional[float] = None
    market_max_monthly: Optional[float] = None
    market_source = None
    market_source_date = None
    if market_row is not None:
        market_min_monthly = _monthly_equivalent(
            market_row.market_min,
            market_row.rate_unit,
            contract.billing_hours_per_month,
        )
        market_median_monthly = _monthly_equivalent(
            market_row.market_median,
            market_row.rate_unit,
            contract.billing_hours_per_month,
        )
        market_max_monthly = _monthly_equivalent(
            market_row.market_max,
            market_row.rate_unit,
            contract.billing_hours_per_month,
        )
        market_source = market_row.source
        market_source_date = market_row.source_date

    return ContractBenchmarkComparison(
        contract_rate_monthly=contract_rate_monthly,
        internal_avg_monthly=internal_avg_monthly,
        internal_median_monthly=internal_median_monthly,
        internal_sample_size=internal_sample_size,
        market_min=market_min_monthly,
        market_median=market_median_monthly,
        market_max=market_max_monthly,
        market_source=market_source,
        market_source_date=market_source_date,
        role_used=role,
        currency=contract.resolved_rate_client_currency,
    )
