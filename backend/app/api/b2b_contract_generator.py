"""Generator Umów B2B — katalog ról (CRUD) + generowanie umowy + eksport DOCX.

Reużywa istniejący system draftów: po `POST /generate` powstaje `Contract`
(typ b2b, status draft) z wyrenderowanym `draft_content_html`, więc działają
istniejące endpointy draftu (edycja Tiptap, render-pdf) oraz Autenti. DOCX jest
jedynym genuinnie nowym wyjściem (eksport na oryginalnym szablonie prawnym).
"""

from __future__ import annotations

import logging
import re
import unicodedata
from datetime import date, datetime, timezone
from typing import get_args

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.concurrency import run_in_threadpool
from jinja2 import TemplateError
from sqlalchemy import Select, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute, selectinload

from app.api.contract_access import (
    B2B_GENERATOR_UNCONDITIONAL_ROLES,
    B2BGeneratorAccess,
    apply_contract_legal_client_scope,
    assert_b2b_generator_action_access,
    assert_contract_legal_client_access,
)
from app.api.contract_templates import _jinja_env
from app.api.contracts import _load_contract_with_relations, _render_draft_body
from app.analytics.capabilities import AnalyticsCapability, user_has_capability
from app.api.deps import AdminUser
from app.api.recruitment_access import ensure_job_membership
from app.api.section_access import SOURCING_SECTION_DEPENDENCIES
from app.core.database import get_db
from app.models.activity import Activity
from app.models.b2b_contract_detail import B2BContractDetail
from app.models.b2b_contract_role import B2BContractRole
from app.models.b2b_generated_contract import B2BGeneratedContract
from app.models.b2b_generated_contract_status_event import (
    B2BGeneratedContractStatusEvent,
)
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.client_order import ClientOrder
from app.models.contract import (
    Contract,
    ContractStatus,
    ContractType,
    RateUnit,
)
from app.models.contract_candidate_rate import ContractCandidateRate
from app.models.contract_template import ContractTemplate
from app.models.job import Job
from app.models.note import Note, NoteType
from app.models.job_collaborator import JobCollaborator
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.models.user import User, UserRole
from app.services.action_permissions import (
    ActionAccess,
    ProductAction,
    action_access_for_user,
)
from app.services.access_scope import resolve_delivery_lead_assigned_client_ids
from app.services.critical_events import audited_deletion
from app.schemas.b2b_contract_generator import (
    B2B_CLOSING_STATUSES,
    B2BClosureReason,
    B2BCompanyLookupResponse,
    B2BContractDetailResponse,
    B2BContractStatus,
    B2BGenerateRequest,
    B2BGenerateResponse,
    B2BConfirmFullySignedRequest,
    B2BConfirmFullySignedResponse,
    B2BGeneratedContractItem,
    B2BGeneratedContractUpdate,
    B2BNextNumberResponse,
    B2BStatusEventItem,
    B2BRenderHtmlResponse,
    B2BRenderRequest,
    B2BRoleCreate,
    B2BRoleResponse,
    B2BRoleUpdate,
    B2BUopCheckRequest,
    B2BUopCheckResponse,
)
from app.services.order_engagement_separation import has_open_group_line
from app.services.polish_ilike import polish_folded_ilike
from app.services.contract_lifecycle import (
    SIGNED_AGREEMENT_ACTIVATION,
    activate_without_revenue_gate,
)
from app.services.contract_order_sync import resync_contract_safely
from app.services.hired_order_status import notify_finance_hired_without_order
from app.services.pipeline_realtime import broadcast_pipeline_changed
from app.services.b2b_contract_automation import (
    ORDER_SKIPPED_COST_CLIENT,
    ORDER_SKIPPED_OPEN_GROUP_LINE,
    ensure_b2b_employment_draft,
    fill_candidate_contact,
    should_auto_create_order,
)
from app.services.b2b_contract_generator.clause_overrides import (
    ClauseOverrideError,
    apply_ops_html_counted,
    ops_fingerprint,
    overrides_for_key,
    resolve_override,
)
from app.services.b2b_contract_generator.docx_renderer import (
    RESOLVE_BY_CLIENT_NAME,
    normalize_language,
    render_contract_docx,
    render_from_context,
)
from app.services.b2b_contract_generator.entity_type import (
    partner_display_lines,
    resolve_partner_entity_type,
)
from app.services.b2b_contract_generator.registry_lookup import lookup_company
from app.services.b2b_contract_generator.render_context import build_render_context
from app.services.b2b_contract_generator.uop_check import (
    CVGeneratorAIError,
    check_employment_hallmarks,
)
from app.services.client_identity import (
    client_display_name,
    client_display_name_expression,
)

logger = logging.getLogger(__name__)

router = APIRouter(dependencies=SOURCING_SECTION_DEPENDENCIES)

_DOCX_MEDIA = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

# Klucz snapshotu rejestru klauzul w `render_payload`. Podkreślnik z przodu, bo
# to metadane wydania dokumentu, a nie pole formularza — `B2BRenderRequest`
# ignoruje nieznane klucze, więc odtworzenie payloadu go po prostu pomija.
_CLAUSE_SNAPSHOT_FIELD = "_clause_override"

# Wiersz z rejestru Excela działu (0359) — treść prowadzi dział w pliku, więc
# NEXUS jej nie poprawia, nie usuwa i nie potwierdza podpisu (ponowny import
# cofnąłby każdą taką zmianę). Zmiana statusu handlowego jest dozwolona.
_EXCEL_ROW_READ_ONLY = (
    "Umowa z rejestru Excel działu — treść, podpis i usunięcie zmienia się "
    "w pliku Excel i kolejnym imporcie."
)


def _reject_excel_row(row: B2BGeneratedContract) -> None:
    if row.source == "excel":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=_EXCEL_ROW_READ_ONLY
        )


def _is_view_only_generator_user(user: User) -> bool:
    """Whether rate-bearing document content must stay redacted."""

    return (
        action_access_for_user(user, ProductAction.b2b_contract_generator)
        < ActionAccess.generate
    )


def _require_contract_generation(user: User) -> None:
    assert_b2b_generator_action_access(user, ActionAccess.generate)


def _require_generated_contract_management(user: User) -> None:
    assert_b2b_generator_action_access(user, ActionAccess.manage)


def _clause_snapshot(key: str | None, ops: list, *, source: str = "generate") -> dict:
    """Snapshot rozstrzygnięcia rejestru zapisywany przy WYDANIU dokumentu.

    Bez niego ponowne pobranie rozstrzyga rejestr od nowa i wydaje inną umowę
    niż podpisana — dwa commity w pięć tygodni po cichu zmieniły treść już
    dostarczonych dokumentów (§4 BNP zniknął z umów Cardif, §10 z zakazem
    konkurencji doszedł umowom e-Zdrowia), a wiersz rejestru nie niósł nic,
    po czym dałoby się je wylistować."""
    return {
        "key": key,
        # Odcisk TREŚCI: sam klucz przypina wpis, nie brzmienie klauzul.
        "fingerprint": ops_fingerprint(ops),
        "ops": len(ops),
        "resolved_at": datetime.now(timezone.utc).isoformat(),
        # Skąd wzięło się to rozstrzygnięcie: wydanie dokumentu czy późniejsza
        # korekta nazwy Klienta. Bez tego nie da się odróżnić umowy wydanej
        # z danym zestawem klauzul od takiej, której zestaw zmieniono po fakcie.
        "source": source,
    }


async def _render_docx_or_500(
    context: dict, lang: str, clause_override_key: str | None
) -> bytes:
    """Render DOCX; niekompletny zestaw klauzul → 500 zamiast wydanego pliku."""
    try:
        return await run_in_threadpool(
            lambda: render_from_context(
                context, language=lang, clause_override_key=clause_override_key
            )
        )
    except ClauseOverrideError as exc:
        raise HTTPException(status_code=500, detail=str(exc))


def _pinned_clause_key(row: B2BGeneratedContract, lang: str) -> str | None:
    """Klucz rejestru do ponownego wydania dokumentu z wiersza logu.

    Brak snapshotu (wiersze sprzed tej zmiany) → rozstrzygnięcie po nazwie, czyli
    zachowanie dotychczasowe; nic lepszego dla nich nie istnieje, ale zostaje po
    tym ślad w logu. Rozjazd odcisku = klauzule pod tym samym kluczem zmieniły
    brzmienie po wydaniu umowy — ostrzegamy zamiast odmawiać, bo odmowa
    zablokowałaby pobranie każdej historycznej umowy po pierwszej edycji
    rejestru przez prawnika."""
    snap = (row.render_payload or {}).get(_CLAUSE_SNAPSHOT_FIELD)
    if not isinstance(snap, dict):
        logger.info(
            "b2b_clause_snapshot_missing generated_id=%s number=%s",
            row.id,
            row.contract_number,
        )
        return RESOLVE_BY_CLIENT_NAME
    key = snap.get("key")
    current = ops_fingerprint(overrides_for_key(key, lang))
    if snap.get("fingerprint") and snap["fingerprint"] != current:
        logger.warning(
            "b2b_clause_registry_drift generated_id=%s number=%s key=%s "
            "snapshot=%s current=%s",
            row.id,
            row.contract_number,
            key,
            snap["fingerprint"],
            current,
        )
    return key


def _ascii_filename(name: str) -> str:
    """Transliteruj na ASCII i oczyść do bezpiecznej nazwy pliku."""
    norm = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    safe = "".join(c if c.isalnum() or c in "._-" else "_" for c in norm)
    return safe.strip("._") or "umowa"


def _contract_docx_filename(contract_number: str | None) -> str:
    """Publiczna nazwa pobieranego DOCX: ``Umowa B2B 1472-2026.docx``."""
    number = re.sub(r"\s*/\s*", "-", (contract_number or "").strip())
    label = _ascii_filename(number) if number else ""
    return f"Umowa B2B {label}.docx" if label else "Umowa B2B.docx"


def _docx_response(
    data: bytes,
    contract_number: str | None,
    *,
    generated_id: int | None = None,
) -> Response:
    """Zwróć DOCX z nazwą widoczną dla frontendu także przez CORS.

    ``X-Generated-Contract-Id`` niesie id wiersza rejestru — formularz po
    pobraniu wie, KTÓRY wpis opisuje, i poprawka idzie do niego zamiast
    zakładać drugi wiersz z nowym numerem."""
    filename = _contract_docx_filename(contract_number)
    headers = {
        "Content-Disposition": f'attachment; filename="{filename}"',
        "Access-Control-Expose-Headers": (
            "Content-Disposition, X-Contract-Number, X-Generated-Contract-Id"
        ),
    }
    if contract_number:
        headers["X-Contract-Number"] = contract_number
    if generated_id is not None:
        headers["X-Generated-Contract-Id"] = str(generated_id)
    return Response(content=data, media_type=_DOCX_MEDIA, headers=headers)


# Etykiety PL statusów i powodów. Front ma własne — te NIE są ich duplikatem
# w sensie, który zwykle jest błędem: służą do zbudowania TREŚCI NOTATKI, która
# ląduje w bazie jako trwały tekst w module Kontrakty, i do komunikatów błędów.
# Notatka jest artefaktem, nie widokiem — musi być czytelna bez frontendu.
_STATUS_LABEL_PL = {
    "active": "Aktywna",
    "in_progress": "W trakcie",
    "cancelled": "Anulowana",
    "suspended": "Zawieszona",
    "closed": "Zakończona",
}

# Komunikat o ręcznym wyborze „W trakcie". Do 0328 żył w walidatorze
# `B2BGeneratedContractUpdate`, który odrzucał ten status bezwarunkowo. Od 0328
# jest legalny DOKŁADNIE z „Anulowanej", a tego DTO nie potrafi sprawdzić (nie
# zna bieżącego stanu wiersza) — więc reguła zeszła do handlera, a komunikat dla
# przypadku niedozwolonego został bajt w bajt taki sam.
_IN_PROGRESS_IS_AUTOMATIC = (
    "Status „W trakcie” ustawia system automatycznie przy "
    "generowaniu umowy — nie można go wybrać ręcznie. Umowa "
    "staje się „Aktywna” po potwierdzeniu podpisu."
)

# Powód, dla którego anulowana umowa nie może zostać oznaczona jako podpisana.
# Jedno źródło dla `blocked_reason` w serializerze (chowa przycisk) i dla 409
# z `confirm-fully-signed` (egzekwuje) — ukrycie przycisku nie jest kontrolą.
_CANCELLED_BLOCKS_SIGNATURE = (
    "Umowa jest anulowana. Przywróć status „W trakcie”, aby potwierdzić podpis."
)

_CLOSURE_REASON_LABEL_PL = {
    "no_client_budget": "Brak budżetu u klienta",
    "contractor_found_other_project": "Kontraktor znalazł inny projekt",
    "contractor_health_reasons": "Względy zdrowotne kontraktora",
    "contractor_underperformance": (
        "Kontraktor nie wywiązywał się z obowiązków projektowych"
    ),
    "project_completed": "Zakończenie projektu",
    "internalization": "Internalizacja",
    "other": "Inny",
    # Katalog sprzed 0226 — do odczytu wierszy historycznych.
    "resignation_before_signing": "Rezygnacja przed podpisaniem umowy",
    "termination": "Wypowiedzenie",
    "mutual_agreement": "Porozumienie o rozwiązaniu umowy",
}


def _closure_reason_text(reason: str | None, reason_other: str | None) -> str:
    """Czytelny powód: własny tekst dla „Inny", inaczej etykieta z katalogu."""
    if reason == "other":
        return (reason_other or "").strip() or "Inny"
    if reason:
        return _CLOSURE_REASON_LABEL_PL.get(reason, reason)
    return "nie podano"


def _previous_project_note(
    prev_date: date | None,
    prev_reason: str | None,
    prev_reason_other: str | None,
) -> str:
    """Treść notatki dopisywanej do kontraktu przy powrocie z zawieszenia.

    Szablon z Ticketu 6. ``prev_date`` bywa ``None`` tylko dla wierszy, które
    trafiły w stan zawieszenia z pominięciem API (safety-net, ręczny UPDATE) —
    „nie podano" jest wtedy uczciwsze niż podstawienie dzisiejszej daty.
    """
    when = prev_date.isoformat() if prev_date else "nie podano"
    return (
        "Poprzedni projekt zakończony: "
        f"{when}, powód: {_closure_reason_text(prev_reason, prev_reason_other)}"
    )


async def _reactivation_contract_id(
    db: AsyncSession, *, current_contract_id: int, job: Job
) -> int | None:
    """Kontrakt NOWEGO projektu, na który ma wskazać reaktywowana umowa.

    Projekt to OSOBNY wiersz ``Contract``, więc powrót z zawieszenia na inny
    projekt musi przepiąć `contract_id` razem z `job_id`/`client_id`. Bez tego
    link zostawał na kontrakcie poprzedniego projektu i psuł ochronę
    w OBIE strony: stary projekt nie dawał się usunąć (chroniony podpisem,
    który go już nie dotyczy), a nowy nie był chroniony wcale.

    Osobę bierzemy z kontraktu aktualnie podpiętego — jest zawsze obecny
    (reaktywacja bez niego kończy się 409) i to właśnie jego link przepinamy,
    więc szukamy „innego kontraktu TEJ SAMEJ osoby". ``candidate_id`` bywa
    ``NULL`` (SET NULL po usunięciu kandydata) — wtedy nie ma po czym szukać.

    Kolejność: kontrakt wskazujący WPROST wybraną rekrutację, a dopiero potem
    kontrakt u jej klienta bez przypisanego projektu (``Contract.job_id`` jest
    na produkcji pusty niemal wszędzie, więc to jest ścieżka realna). Kontrakt
    związany z INNĄ rekrutacją jest świadomie pomijany — przepięcie na cudzy
    projekt tylko przesunęłoby ten sam defekt.

    ``None`` znaczy „nie ma na co przepiąć" i zostawia link bez zmian.
    **Nie tworzymy** tu kontraktu: ``ensure_b2b_employment_draft`` zakłada go
    z pominięciem ``_assert_no_duplicate_contract``, więc reaktywacja mogłaby
    po cichu zrobić drugi wiersz u tego samego klienta.
    """
    candidate_id = await db.scalar(
        select(Contract.candidate_id).where(Contract.id == current_contract_id)
    )
    if candidate_id is None:
        return None

    live_contract = (
        Contract.candidate_id == candidate_id,
        Contract.status != ContractStatus.void,
    )
    by_job = await db.scalar(
        select(Contract.id)
        .where(*live_contract, Contract.job_id == job.id)
        .order_by(Contract.id.desc())
        .limit(1)
    )
    if by_job is not None:
        return by_job
    return await db.scalar(
        select(Contract.id)
        .where(
            *live_contract,
            Contract.client_id == job.client_id,
            Contract.job_id.is_(None),
        )
        .order_by(Contract.id.desc())
        .limit(1)
    )


def _has_signature_permission(user: User) -> bool:
    return (
        action_access_for_user(user, ProductAction.b2b_signature_confirmation)
        >= ActionAccess.manage
    )


def _require_signature_confirmation(user: User) -> None:
    assert_b2b_generator_action_access(user, ActionAccess.view)
    if not _has_signature_permission(user):
        raise HTTPException(
            status_code=403,
            detail={
                "code": "action_access_denied",
                "action": ProductAction.b2b_signature_confirmation.value,
                "required": "manage",
            },
        )


async def _assert_signature_client_access(
    db: AsyncSession, user: User, client_id: int | None
) -> None:
    # Preserve existing legal scope for DL/TAC. The separately granted command
    # lets operational users confirm signatures without granting document edits.
    if user.has_any_role(UserRole.delivery_lead, UserRole.tac):
        await assert_contract_legal_client_access(db, user, client_id, write=True)


def _generator_unscoped(user: User) -> bool:
    """Roles that operate the generator without the client-team scope.

    Every role is a client-unscoped generator persona except Delivery Lead
    (product decision, 20.08 — the generator is open to every role, see
    ``require_b2b_generator_access``). TAC was the original full-access
    persona (business decision): it may draft, render, list and download
    every B2B contract regardless of any ``ClientTacAssignment`` graph.
    Admin/Head of Recruitment were already unrestricted through the
    underlying resolvers. Finance/recruiter/sourcer
    join them here for the same structural reason TAC needed this: none of
    them have any row in ``ClientTacAssignment``/
    ``DeliveryLeadClientAssignment`` to be scoped by, so leaving them off this
    list would mean they pass ``require_b2b_generator_access`` and then hit a
    permanently empty list/403 on every entity — auth without access, not a
    real access decision. Delivery Lead is deliberately excluded so clientless
    entities stay fail-closed. It can browse every concrete client, while rate
    content and document mutations still require ownership assignment.

    „Bez zakresu" dotyczy rejestru, nie stawek: od 22.09.2026 stawki cudzych
    umów widzą tylko admin i Finanse (``_RateVisibility``).

    Reuses ``B2B_GENERATOR_UNCONDITIONAL_ROLES`` from ``contract_access``
    instead of its own copy of the role tuple (auto-review on #1216 flagged
    the two-tuple duplication as a sync hazard: a role added to the entry
    gate but not here would silently pass auth into a permanently empty
    list). One tuple, two call sites — the entry gate and this scope check
    can no longer drift apart.
    """

    return user.has_any_role(*B2B_GENERATOR_UNCONDITIONAL_ROLES)


def _sees_every_generator_rate(user: User) -> bool:
    """Wszystkie stawki umów B2B: admin i Finanse (``VIEW_FINANCE``)."""

    return user.has_role(UserRole.admin) or user_has_capability(
        user, AnalyticsCapability.VIEW_FINANCE
    )


async def _jobs_run_by(db: AsyncSession, user: User, job_ids: set[int]) -> set[int]:
    """Rekrutacje z ``job_ids``, które ``user`` prowadzi albo współprowadzi.

    Prowadzi = rekruter, TAC albo Delivery Lead rekrutacji; współprowadzi =
    aktywny współpracownik. Jedno zapytanie na listę, żeby rejestr umów nie
    robił N+1 przy liczeniu, czyje stawki wolno pokazać.
    """

    if not job_ids:
        return set()
    owned = {
        int(job_id)
        for job_id in (
            await db.scalars(
                select(Job.id).where(
                    Job.id.in_(job_ids),
                    or_(
                        Job.recruiter_id == user.id,
                        Job.tac_id == user.id,
                        Job.delivery_lead_id == user.id,
                    ),
                )
            )
        ).all()
    }
    owned.update(
        int(job_id)
        for job_id in (
            await db.scalars(
                select(JobCollaborator.job_id).where(
                    JobCollaborator.job_id.in_(job_ids),
                    JobCollaborator.user_id == user.id,
                    JobCollaborator.removed_from_auto_cc.is_(False),
                )
            )
        ).all()
    )
    return owned


class _RateVisibility:
    """Kto widzi stawki w dokumentach Generatora B2B (decyzja Artura 22.09.2026).

    Wszystkie stawki: admin i Finanse. Delivery Lead: klienci ze swojego
    portfela. Każda inna rola (rekruter, sourcer, TCM, TAC, HoR): wyłącznie
    umowy, które sama wygenerowała, i umowy z rekrutacji, które prowadzi.
    Wejście do generatora zostaje otwarte dla wszystkich (decyzja 20.08) —
    to reguła dla STAWEK, nie dla rejestru.
    """

    def __init__(
        self,
        user: User,
        *,
        every: bool,
        assigned_client_ids: frozenset[int] | None,
        run_job_ids: set[int],
    ) -> None:
        self._user = user
        self._every = every
        self._assigned = assigned_client_ids
        self._run_job_ids = run_job_ids

    def visible(
        self,
        *,
        client_id: int | None,
        created_by: int | None,
        job_id: int | None,
    ) -> bool:
        if self._every:
            return True
        if created_by is not None and created_by == self._user.id:
            return True
        if job_id is not None and job_id in self._run_job_ids:
            return True
        return (
            self._assigned is not None
            and client_id is not None
            and client_id in self._assigned
        )


async def _rate_visibility(
    db: AsyncSession, user: User, job_ids: set[int]
) -> _RateVisibility:
    every = _sees_every_generator_rate(user)
    assigned = (
        await resolve_delivery_lead_assigned_client_ids(user, db)
        if not every and user.has_role(UserRole.delivery_lead)
        else None
    )
    run_job_ids = set() if every else await _jobs_run_by(db, user, job_ids)
    return _RateVisibility(
        user, every=every, assigned_client_ids=assigned, run_job_ids=run_job_ids
    )


async def _generator_rate_content_visible(
    db: AsyncSession,
    user: User,
    client_id: int | None,
    *,
    created_by: int | None = None,
    job_id: int | None = None,
) -> bool:
    """Czy ``user`` widzi stawki jednego dokumentu (patrz ``_RateVisibility``)."""

    visibility = await _rate_visibility(
        db, user, {job_id} if job_id is not None else set()
    )
    return visibility.visible(client_id=client_id, created_by=created_by, job_id=job_id)


async def _contract_author_id(
    db: AsyncSession, user: User, contract: Contract
) -> int | None:
    """``user.id``, gdy to ``user`` wygenerował umowę kontraktu, inaczej ``None``.

    ``Contract`` nie ma kolumny autora — autorstwo niesie wpis ``b2b_generated``
    w dzienniku (``POST /generate``) albo wiersz rejestru z tym kontraktem.
    """

    activity = await db.scalar(
        select(Activity.id)
        .where(
            Activity.entity_type == "contract",
            Activity.entity_id == contract.id,
            Activity.action == "b2b_generated",
            Activity.user_id == user.id,
        )
        .limit(1)
    )
    if activity is not None:
        return user.id
    generated = await db.scalar(
        select(B2BGeneratedContract.id)
        .where(
            B2BGeneratedContract.contract_id == contract.id,
            B2BGeneratedContract.created_by == user.id,
        )
        .limit(1)
    )
    return user.id if generated is not None else None


_RATE_CONTENT_DENIED = (
    "Stawki tej umowy widzą admin, Finanse, Delivery Lead klienta, autor umowy "
    "i zespół rekrutacji, z której powstała."
)


async def _require_generator_rate_content(
    db: AsyncSession,
    user: User,
    client_id: int | None,
    *,
    created_by: int | None,
    job_id: int | None,
) -> None:
    """DOCX niesie stawkę w treści — cudzej umowy nie wydajemy wcale."""

    if not await _generator_rate_content_visible(
        db, user, client_id, created_by=created_by, job_id=job_id
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=_RATE_CONTENT_DENIED
        )


async def _assert_generator_client_access(
    db: AsyncSession,
    user: User,
    client_id: int | None,
    *,
    write: bool = False,
) -> None:
    """Client-entity authorization for the generator, bypassed for unscoped roles.

    Full-access personas (see :func:`_generator_unscoped`) skip the client-team
    check entirely; everyone else falls through to the shared client-aware
    guard. Delivery Lead reads all concrete clients and writes only assigned
    ones.
    """

    if _generator_unscoped(user):
        return
    await assert_contract_legal_client_access(db, user, client_id, write=write)


async def _scope_generator_query(
    statement: Select,
    client_column: InstrumentedAttribute,
    db: AsyncSession,
    user: User,
) -> Select:
    """Scope the generated-contracts list to every concrete client for DL.

    A full-access TAC must see every generated contract — including ones it just
    drafted for a client it is not assigned to — so the client-team scope is not
    applied. Delivery Lead receives all current client ids, while clientless
    rows remain restricted to unscoped personas.
    """

    if _generator_unscoped(user):
        return statement
    return await apply_contract_legal_client_scope(statement, client_column, db, user)


async def _require_signature_job_scope(db: AsyncSession, user: User, job: Job) -> None:
    if not user.has_role(UserRole.talent_community_manager):
        await ensure_job_membership(db, user, job.id)


async def _load_legal_scoped_job(
    db: AsyncSession,
    user: User,
    job_id: int,
    *,
    write: bool,
    strict_client_scope: bool = False,
) -> Job:
    """Load a Job and authorize its client before touching candidate/legal PII.

    ``strict_client_scope`` selects which authorization applies. The default
    (``False``) uses the generator's TAC-unscoped check, so drafting/rendering
    is reachable for a full-access TAC. The audited ``confirm-fully-signed``
    automation passes ``True`` to keep DL/TAC bound to their explicit client
    assignment — that one-way employment automation must stay contained.
    """

    job = await db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Rekrutacja nie istnieje")
    if strict_client_scope:
        await assert_contract_legal_client_access(
            db,
            user,
            job.client_id,
            write=write,
        )
    else:
        await _assert_generator_client_access(
            db,
            user,
            job.client_id,
            write=write,
        )
    return job


async def _validate_candidate_job_link(
    db: AsyncSession,
    *,
    candidate_id: int,
    job_id: int,
) -> tuple[Candidate, Job]:
    candidate = await db.get(Candidate, candidate_id)
    if candidate is None:
        raise HTTPException(status_code=404, detail="Kandydat nie istnieje")
    job = await db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Rekrutacja nie istnieje")
    has_pipeline = await db.scalar(
        select(CandidateStage.id)
        .where(
            CandidateStage.candidate_id == candidate.id,
            CandidateStage.job_id == job.id,
        )
        .limit(1)
    )
    if has_pipeline is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Kandydat nie uczestniczy w wybranej rekrutacji. "
                "Nie utworzono powiązania ani kontraktora."
            ),
        )
    return candidate, job


async def _serialize_generated_contracts(
    db: AsyncSession,
    rows: list[B2BGeneratedContract],
    current_user: User,
) -> list[B2BGeneratedContractItem]:
    """One serializer for list, PATCH and signature command responses."""

    user_ids = {
        uid
        for row in rows
        for uid in (row.created_by, row.signed_by_user_id, row.recruiter_user_id)
        if uid is not None
    }
    candidate_ids = {row.candidate_id for row in rows if row.candidate_id is not None}
    job_ids = {row.job_id for row in rows if row.job_id is not None}
    client_ids = {row.client_id for row in rows if row.client_id is not None}

    users: dict[int, str] = {}
    if user_ids:
        result = await db.execute(
            select(User.id, User.name).where(User.id.in_(user_ids))
        )
        users = {uid: name for uid, name in result.all()}

    candidates: dict[int, str] = {}
    if candidate_ids:
        result = await db.execute(
            select(Candidate.id, Candidate.name, Candidate.lastname).where(
                Candidate.id.in_(candidate_ids)
            )
        )
        candidates = {
            cid: f"{name} {lastname}".strip() for cid, name, lastname in result.all()
        }

    jobs: dict[int, Job] = {}
    if job_ids:
        result = await db.execute(select(Job).where(Job.id.in_(job_ids)))
        jobs = {job.id: job for job in result.scalars().all()}

    clients: dict[int, str] = {}
    if client_ids:
        result = await db.execute(
            select(
                Client.id,
                client_display_name_expression().label("client_name"),
            ).where(Client.id.in_(client_ids))
        )
        clients = {cid: name for cid, name in result.all()}

    scoped_job_ids: set[int] = set()
    if _has_signature_permission(current_user):
        if current_user.has_any_role(
            UserRole.admin,
            UserRole.head_of_recruitment,
            UserRole.talent_community_manager,
        ):
            scoped_job_ids = set(job_ids)
        else:
            scoped_job_ids = {
                job.id
                for job in jobs.values()
                if current_user.id
                in {
                    job.recruiter_id,
                    job.delivery_lead_id,
                    job.tac_id,
                }
            }
            if job_ids:
                result = await db.execute(
                    select(JobCollaborator.job_id).where(
                        JobCollaborator.job_id.in_(job_ids),
                        JobCollaborator.user_id == current_user.id,
                        JobCollaborator.removed_from_auto_cc.is_(False),
                    )
                )
                scoped_job_ids.update(job_id for (job_id,) in result.all())

    # Stan powiązanego kontraktu: rejestr nie wie, że kontrakt się skończył
    # albo został usunięty (audyt 23.09.2026 — trzy umowy „Aktywne” przy
    # zakończonych kontraktach). Wiersz pokazuje ostrzeżenie, status zmienia
    # człowiek.
    contract_ids = {row.contract_id for row in rows if row.contract_id is not None}
    linked_contracts: dict[int, tuple[str, date | None]] = {}
    if contract_ids:
        result = await db.execute(
            select(Contract.id, Contract.status, Contract.end_date).where(
                Contract.id.in_(contract_ids)
            )
        )
        linked_contracts = {
            cid: (getattr(cstatus, "value", cstatus), end_date)
            for cid, cstatus, end_date in result.all()
        }

    rate_visibility = await _rate_visibility(db, current_user, set(job_ids))
    is_admin = current_user.has_role(UserRole.admin)
    generator_access = action_access_for_user(
        current_user, ProductAction.b2b_contract_generator
    )
    can_generate_documents = generator_access >= ActionAccess.generate
    can_manage_documents = generator_access >= ActionAccess.manage
    delivery_scoped = current_user.has_role(
        UserRole.delivery_lead
    ) and not _generator_unscoped(current_user)
    assigned_client_ids = (
        await resolve_delivery_lead_assigned_client_ids(current_user, db)
        if delivery_scoped
        else None
    )
    signature_client_access: dict[int | None, bool] = {}
    if _has_signature_permission(current_user):
        for client_id in {row.client_id for row in rows}:
            try:
                await _assert_signature_client_access(db, current_user, client_id)
                signature_client_access[client_id] = True
            except HTTPException as exc:
                if exc.status_code != 403:
                    raise
                signature_client_access[client_id] = False
    items: list[B2BGeneratedContractItem] = []
    for row in rows:
        is_signed = row.signature_status == "signed_both"
        can_write_client = not delivery_scoped or (
            assigned_client_ids is not None and row.client_id in assigned_client_ids
        )
        can_manage = (
            can_manage_documents
            and can_write_client
            and not is_signed
            and (is_admin or row.created_by == current_user.id)
        )
        is_cancelled = row.contract_status == "cancelled"
        from_excel = row.source == "excel"
        if from_excel:
            # Wiersz z rejestru Excela: treść i usunięcie należą do pliku
            # działu (ponowny import by je cofnął). Status handlowy — tak.
            can_manage = False
        can_confirm = (
            generator_access >= ActionAccess.view
            and (
                row.client_id is None
                or signature_client_access.get(row.client_id, False)
            )
            and _has_signature_permission(current_user)
            and not is_signed
            and not is_cancelled
        )
        blocked_reason: str | None = None
        if from_excel and not is_signed:
            blocked_reason = _EXCEL_ROW_READ_ONLY
            can_confirm = False
        elif is_signed:
            blocked_reason = "Umowa została już oznaczona jako podpisana obustronnie."
        # PRZED gałęziami uprawnień: anulowanie jest najbardziej konkretnym
        # powodem i niesie następny krok („przywróć W trakcie”), a komunikat
        # o brakującym uprawnieniu wysyłałby użytkownika do administratora po
        # coś, co i tak nie odblokuje tego wiersza.
        elif is_cancelled:
            blocked_reason = _CANCELLED_BLOCKS_SIGNATURE
        elif generator_access < ActionAccess.view:
            blocked_reason = (
                "Oznaczenie podpisu wymaga dostępu do rejestru Generatora Umów B2B."
            )
            can_confirm = False
        elif not can_write_client:
            blocked_reason = (
                "Oznaczenie podpisu wymaga przypisania Delivery Leada do klienta."
            )
            can_confirm = False
        elif not _has_signature_permission(current_user):
            blocked_reason = "Brak uprawnienia „Oznaczanie podpisu umowy B2B”. Administrator może je nadać w Ustawienia → Uprawnienia."
            can_confirm = False
        elif row.client_id is not None and not signature_client_access.get(
            row.client_id, False
        ):
            blocked_reason = "Brak uprawnień do potwierdzania podpisu dla tego klienta. Sprawdź przypisanie klienta i dostęp do Delivery."
            can_confirm = False
        elif row.job_id is not None and row.job_id not in scoped_job_ids:
            blocked_reason = "Brak przypisania do powiązanej rekrutacji."
            can_confirm = False

        linked_status, linked_end = linked_contracts.get(row.contract_id, (None, None))
        job = jobs.get(row.job_id) if row.job_id is not None else None
        # Kolumna „Partner": nazwa firmy z rejestru, a dla spółki dodatkowo
        # druga linia z osobą. Rozstrzygane TUTAJ, nie na frontendzie — reguła
        # („niejednoznaczne → spółka" + kasowanie duplikacji przez podciąg) musi
        # dać ten sam wynik w tabeli, w dialogu podpisu i w odpowiedzi PATCH-a,
        # a wszystkie trzy przechodzą przez ten serializer.
        partner_display, partner_secondary = partner_display_lines(
            legal_name=row.partner_legal_name,
            person_name=row.partner_name,
            entity_type=resolve_partner_entity_type(
                stored=row.partner_entity_type,
                legal_name=row.partner_legal_name,
            ),
        )
        items.append(
            B2BGeneratedContractItem(
                # Zmiana statusu handlowego celowo NIE wygasa po podpisaniu:
                # wypowiedzenie i porozumienie o rozwiązaniu dotyczą właśnie
                # umów podpisanych.
                #
                # Status handlowy wymaga poziomu `manage`; zakres wierszy nadal
                # ogranicza `_scope_generator_query`. Korekta TREŚCI dokumentu
                # (`can_edit`) pozostaje dodatkowo przy autorze albo adminie.
                can_change_status=can_manage_documents and can_write_client,
                contract_status=row.contract_status,
                closure_reason=row.closure_reason,
                closure_reason_other=row.closure_reason_other,
                closure_date=row.closure_date,
                id=row.id,
                contract_number=row.contract_number,
                partner_name=row.partner_name,
                partner_display_name=partner_display,
                partner_secondary_line=partner_secondary,
                partner_nip=row.partner_nip,
                start_date=row.start_date,
                client_name=row.client_name,
                language=row.language,
                signing_date=row.signing_date,
                created_at=row.created_at.isoformat() if row.created_at else None,
                created_by_name=users.get(row.created_by),
                can_delete=can_manage,
                can_edit=can_manage,
                # DOCX niesie stawkę — pobranie tylko przy widocznych stawkach.
                can_download=(
                    row.render_payload is not None
                    and can_generate_documents
                    and can_write_client
                    and rate_visibility.visible(
                        client_id=row.client_id,
                        created_by=row.created_by,
                        job_id=row.job_id,
                    )
                ),
                signature_status=row.signature_status,
                signature_source=row.signature_source,
                candidate_id=row.candidate_id,
                job_id=row.job_id,
                client_id=row.client_id,
                contract_id=row.contract_id,
                linked_contract_status=linked_status,
                linked_contract_end_date=linked_end,
                candidate_name=candidates.get(row.candidate_id),
                job_title=job.title if job else None,
                canonical_client_name=clients.get(row.client_id),
                signed_at=row.signed_at.isoformat() if row.signed_at else None,
                signed_by_name=users.get(row.signed_by_user_id),
                can_confirm_signed=can_confirm,
                blocked_reason=blocked_reason,
                source=row.source or "generator",
                raw_contract_number=row.raw_contract_number,
                position=row.position,
                contract_kind=row.contract_kind,
                start_date_mode=row.start_date_mode,
                recruiter_name=users.get(row.recruiter_user_id),
                legacy_flags=list((row.legacy_data or {}).get("flags") or []),
                needs_business_data_annex=bool(row.needs_business_data_annex),
                business_data_annex_done_at=row.business_data_annex_done_at,
                excel_missing_since=(
                    row.excel_missing_since.isoformat()
                    if row.excel_missing_since
                    else None
                ),
            )
        )
    return items


async def _serialize_generated_contract(
    db: AsyncSession,
    row: B2BGeneratedContract,
    current_user: User,
) -> B2BGeneratedContractItem:
    return (await _serialize_generated_contracts(db, [row], current_user))[0]


# ── Katalog ról ──────────────────────────────────────────────────────────────


@router.get("/roles", response_model=list[B2BRoleResponse])
async def list_roles(
    current_user: B2BGeneratorAccess,
    db: AsyncSession = Depends(get_db),
    include_inactive: bool = Query(False),
):
    """Lista ról (pogrupowanie wg `category_key` robi frontend)."""
    query = select(B2BContractRole)
    if not include_inactive:
        query = query.where(B2BContractRole.is_active.is_(True))
    query = query.order_by(B2BContractRole.display_order, B2BContractRole.name_pl)
    res = await db.execute(query)
    return list(res.scalars().all())


@router.post(
    "/roles", response_model=B2BRoleResponse, status_code=status.HTTP_201_CREATED
)
async def create_role(
    data: B2BRoleCreate,
    current_user: AdminUser,
    db: AsyncSession = Depends(get_db),
):
    dup = await db.scalar(
        select(B2BContractRole.id).where(B2BContractRole.slug == data.slug)
    )
    if dup:
        raise HTTPException(status_code=409, detail="Rola o tym slug już istnieje")
    from app.data.b2b_roles import CATEGORY_LABELS

    if data.category_key not in CATEGORY_LABELS:
        raise HTTPException(
            status_code=422,
            detail=f"Nieznana kategoria: {data.category_key}",
        )
    cat_pl, cat_en = CATEGORY_LABELS[data.category_key]
    role = B2BContractRole(
        category_key=data.category_key,
        category_label_pl=cat_pl,
        category_label_en=cat_en,
        slug=data.slug,
        name_pl=data.name_pl,
        name_en=data.name_en,
        area_label_pl=data.area_label_pl,
        area_label_en=data.area_label_en,
        scope_pl=data.scope_pl,
        scope_en=data.scope_en,
        display_order=data.display_order,
    )
    db.add(role)
    # The slug check above is racy; the UNIQUE constraint on
    # b2b_contract_roles.slug is the real guard. Give the loser of a concurrent
    # create the same 409 as the read path, not a 500.
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=409, detail="Rola o tym slug już istnieje"
        ) from None
    await db.refresh(role)
    return role


@router.get("/roles/{role_id}", response_model=B2BRoleResponse)
async def get_role(
    role_id: int,
    current_user: B2BGeneratorAccess,
    db: AsyncSession = Depends(get_db),
):
    role = await db.get(B2BContractRole, role_id)
    if not role:
        raise HTTPException(status_code=404, detail="Rola nie znaleziona")
    return role


@router.patch("/roles/{role_id}", response_model=B2BRoleResponse)
async def update_role(
    role_id: int,
    data: B2BRoleUpdate,
    current_user: AdminUser,
    db: AsyncSession = Depends(get_db),
):
    role = await db.get(B2BContractRole, role_id)
    if not role:
        raise HTTPException(status_code=404, detail="Rola nie znaleziona")
    updates = data.model_dump(exclude_unset=True)
    if "category_key" in updates:
        from app.data.b2b_roles import CATEGORY_LABELS

        if updates["category_key"] not in CATEGORY_LABELS:
            raise HTTPException(status_code=422, detail="Nieznana kategoria")
        role.category_label_pl, role.category_label_en = CATEGORY_LABELS[
            updates["category_key"]
        ]
    for k, v in updates.items():
        setattr(role, k, v)
    await db.commit()
    await db.refresh(role)
    return role


@router.delete("/roles/{role_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_role(
    role_id: int,
    current_user: AdminUser,
    db: AsyncSession = Depends(get_db),
):
    role = await db.get(B2BContractRole, role_id)
    if not role:
        raise HTTPException(status_code=404, detail="Rola nie znaleziona")
    # FK b2b_contract_details.b2b_role_id = ON DELETE SET NULL → bezpieczne.
    await db.delete(role)
    await db.commit()


# ── Generowanie umowy ────────────────────────────────────────────────────────


async def _b2b_template_for(db: AsyncSession, lang: str) -> ContractTemplate:
    tpl = await db.scalar(
        select(ContractTemplate).where(
            ContractTemplate.contract_type == "b2b",
            ContractTemplate.language == lang,
        )
    )
    if not tpl:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Brak szablonu umowy B2B ({lang}). "
                "Seed nie został uruchomiony — zrestartuj aplikację."
            ),
        )
    return tpl


@router.post("/generate", response_model=B2BGenerateResponse)
async def generate(
    payload: B2BGenerateRequest,
    current_user: B2BGeneratorAccess,
    db: AsyncSession = Depends(get_db),
):
    # Register view is intentionally separate from rate-bearing generation.
    # The latter writes ``rate_candidate`` and embeds it in an opaque DOCX.
    _require_contract_generation(current_user)
    role = await db.get(B2BContractRole, payload.role_id)
    if not role:
        raise HTTPException(status_code=404, detail="Rola nie znaleziona")
    lang = normalize_language(payload.language)
    tpl = await _b2b_template_for(db, lang)

    # 1. Utwórz lub wczytaj draft Contract (typ b2b).
    # Kontrakt, który istniał PRZED tym wywołaniem, jest cudzą pracą — jego
    # stawkę wolno nadpisać tylko komuś, kto ją widzi (audyt 23.09.2026:
    # rekruter spoza zespołu zmieniał stawkę szkicu Delivery z 150 na 1).
    pre_existing_contract = payload.contract_id is not None
    if payload.contract_id is not None:
        # selectinload harmonogramu: replace relacji niżej musi znać stan
        # bieżący (delete-orphan) — lazy-load w async wywala MissingGreenlet.
        contract = await db.scalar(
            select(Contract)
            .where(Contract.id == payload.contract_id)
            .options(selectinload(Contract.candidate_rate_schedule))
            .with_for_update()
        )
        if not contract:
            raise HTTPException(status_code=404, detail="Umowa nie znaleziona")
        await _assert_generator_client_access(
            db,
            current_user,
            contract.client_id,
            write=True,
        )
        if contract.contract_type != ContractType.b2b:
            raise HTTPException(status_code=409, detail="To nie jest umowa B2B")
        if contract.status != ContractStatus.draft:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "message": (
                        f"Kontrakt #{contract.id} ma status "
                        f"'{contract.status.value}' i nie może być edytowany "
                        "przez generator."
                    ),
                    "contract_ids": [contract.id],
                },
            )
        signed_generated_id = await db.scalar(
            select(B2BGeneratedContract.id)
            .where(
                B2BGeneratedContract.contract_id == contract.id,
                B2BGeneratedContract.signature_status == "signed_both",
            )
            .limit(1)
        )
        if signed_generated_id is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "message": (
                        "Kontrakt jest już powiązany z audytowanym "
                        "potwierdzeniem podpisanej umowy i nie może być "
                        "ponownie zmieniony przez generator."
                    ),
                    "contract_ids": [contract.id],
                },
            )
        if (
            (
                payload.candidate_id is not None
                and payload.candidate_id != contract.candidate_id
            )
            or (payload.job_id is not None and payload.job_id != contract.job_id)
            or (
                payload.client_id is not None
                and payload.client_id != contract.client_id
            )
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "message": (
                        "candidate_id, job_id lub client_id nie odpowiadają "
                        "istniejącemu draftowi."
                    ),
                    "contract_ids": [contract.id],
                },
            )
        if contract.job_id is not None:
            _, existing_job = await _validate_candidate_job_link(
                db,
                candidate_id=contract.candidate_id,
                job_id=contract.job_id,
            )
            if existing_job.client_id != contract.client_id:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail={
                        "message": (
                            "Klient kontraktu nie odpowiada klientowi rekrutacji."
                        ),
                        "contract_ids": [contract.id],
                    },
                )
    else:
        # client_id można wyprowadzić z wybranej rekrutacji (job → klient).
        client_id = payload.client_id
        job: Job | None = None
        if payload.job_id:
            job = await _load_legal_scoped_job(
                db,
                current_user,
                payload.job_id,
                write=True,
            )
        if job is not None and payload.candidate_id:
            _, job = await _validate_candidate_job_link(
                db,
                candidate_id=payload.candidate_id,
                job_id=job.id,
            )
            if client_id is not None and client_id != job.client_id:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="client_id nie odpowiada klientowi wybranej rekrutacji",
                )
            client_id = job.client_id
        elif job is not None:
            client_id = job.client_id
        if not payload.candidate_id or not client_id:
            raise HTTPException(
                status_code=422,
                detail="Wymagany candidate_id oraz client_id lub job_id z klientem",
            )
        await _assert_generator_client_access(
            db,
            current_user,
            client_id,
            write=True,
        )
        if job is not None:
            ensured = await ensure_b2b_employment_draft(
                db,
                candidate_id=payload.candidate_id,
                job=job,
                actor_id=current_user.id,
                payload=payload,
                contract_number=payload.contract_number,
                signing_date=payload.signing_date,
                language=lang,
                allowed_statuses=(ContractStatus.draft,),
                # A draft is the generator's editable workspace. Identity,
                # client and lifecycle are still guarded by the shared
                # service, but form fields below intentionally replace its
                # current terms.
                validate_terms=False,
                reject_signed_generated_link=True,
            )
            contract = ensured.contract
            pre_existing_contract = not ensured.created_contract
        else:
            # Legacy ad-hoc path without a recruitment cannot be safely
            # deduplicated. New UI flows always send job_id.
            contract = Contract(
                candidate_id=payload.candidate_id,
                client_id=client_id,
                job_id=None,
                contract_type=ContractType.b2b,
                status=ContractStatus.draft,
                start_date=payload.start_date,
                rate_unit=RateUnit.hourly,
                currency=payload.currency,
                rate_client_currency=payload.currency,
                rate_candidate_currency=payload.currency,
            )
            db.add(contract)
            await db.flush()

    if pre_existing_contract:
        await _require_generator_rate_content(
            db,
            current_user,
            contract.client_id,
            created_by=await _contract_author_id(db, current_user, contract),
            job_id=contract.job_id,
        )

    # 2. Pola finansowe/daty na Contract.
    contract.start_date = payload.start_date
    contract.rate_candidate = payload.rate_candidate
    contract.rate_candidate_currency = payload.currency
    contract.rate_unit = RateUnit.hourly
    # Stawka progresywna → harmonogram `candidate_rate_schedule`. Formularz
    # generatora wysyła zawsze PEŁNY stan, więc replace bezwarunkowy: brak
    # `rate_stages` czyści harmonogram z poprzedniej generacji (inaczej stary
    # rozkład dalej sterowałby zdaniem o stawce w umowie). Reassignment =
    # replace (delete-orphan). Etap startowy bez „Obowiązuje od" dziedziczy
    # datę rozpoczęcia usług.
    contract.candidate_rate_schedule = [
        ContractCandidateRate(
            rate=s.rate,
            effective_from=s.effective_from or payload.start_date,
            effective_to=s.effective_to,
            created_by=current_user.id,
        )
        for s in (payload.rate_stages or [])
    ]
    if contract.candidate_rate_schedule:
        # Cache spójny z harmonogramem — etap obowiązujący dziś (wzorzec z
        # PATCH /api/contracts).
        contract.rate_candidate = contract.effective_candidate_rate(date.today())

    # 3. Upsert B2BContractDetail.
    detail = await db.scalar(
        select(B2BContractDetail).where(B2BContractDetail.contract_id == contract.id)
    )
    if detail is None:
        detail = B2BContractDetail(contract_id=contract.id)
        db.add(detail)
    detail.contract_number = payload.contract_number
    detail.signing_date = payload.signing_date
    detail.project_city = payload.project_city
    detail.project_description = payload.project_description
    detail.correspondence_address = payload.correspondence_address
    detail.rate_in_words = payload.rate_in_words
    detail.language = lang
    detail.b2b_role_id = role.id
    detail.role_scope_override = payload.scope_items_override
    await db.flush()

    # 4. Render draftu HTML z szablonu B2B (eager-load relacji incl. b2b_detail).
    contract = await _load_contract_with_relations(db, contract.id, current_user)
    contract.draft_content_html = await run_in_threadpool(
        _render_draft_body, tpl, contract
    )
    contract.draft_template_id = tpl.id
    contract.draft_updated_at = datetime.now(timezone.utc)
    contract.draft_updated_by = current_user.id

    db.add(
        Activity(
            entity_type="contract",
            entity_id=contract.id,
            action="b2b_generated",
            user_id=current_user.id,
            details={"role": role.slug, "language": lang},
        )
    )
    await db.commit()
    return B2BGenerateResponse(
        contract_id=contract.id, draft_template_id=tpl.id, language=lang
    )


@router.get("/contracts/{contract_id}/detail", response_model=B2BContractDetailResponse)
async def get_detail(
    contract_id: int,
    current_user: B2BGeneratorAccess,
    db: AsyncSession = Depends(get_db),
):
    contract = await _load_contract_with_relations(db, contract_id, current_user)
    await _assert_generator_client_access(
        db,
        current_user,
        contract.client_id,
    )
    d = contract.b2b_detail
    redact_finance = _is_view_only_generator_user(
        current_user
    ) or not await _generator_rate_content_visible(
        db,
        current_user,
        contract.client_id,
        created_by=await _contract_author_id(db, current_user, contract),
        job_id=contract.job_id,
    )
    return B2BContractDetailResponse(
        contract_id=contract.id,
        candidate_id=contract.candidate_id,
        client_id=contract.client_id,
        job_id=contract.job_id,
        role_id=d.b2b_role_id if d else None,
        language=(d.language if d else "pl"),
        contract_number=d.contract_number if d else None,
        signing_date=d.signing_date if d else None,
        start_date=contract.start_date,
        project_city=d.project_city if d else None,
        project_description=d.project_description if d else None,
        correspondence_address=d.correspondence_address if d else None,
        rate_candidate=None if redact_finance else contract.rate_candidate,
        currency=None if redact_finance else contract.resolved_rate_candidate_currency,
        rate_in_words=None if redact_finance else (d.rate_in_words if d else None),
        scope_items_override=d.role_scope_override if d else None,
    )


@router.get("/contracts/{contract_id}/docx")
async def download_docx(
    contract_id: int,
    current_user: B2BGeneratorAccess,
    db: AsyncSession = Depends(get_db),
    language: str | None = Query(None),
):
    _require_contract_generation(current_user)
    contract = await _load_contract_with_relations(db, contract_id, current_user)
    await _assert_generator_client_access(
        db,
        current_user,
        contract.client_id,
        write=True,
    )
    await _require_generator_rate_content(
        db,
        current_user,
        contract.client_id,
        created_by=await _contract_author_id(db, current_user, contract),
        job_id=contract.job_id,
    )
    detail_lang = contract.b2b_detail.language if contract.b2b_detail else "pl"
    lang = normalize_language(language or detail_lang)
    data = await run_in_threadpool(render_contract_docx, contract, language=lang)

    number = contract.b2b_detail.contract_number if contract.b2b_detail else None
    return _docx_response(data, number)


# ── Numeracja umów (auto, uwzględnia wcześniej wygenerowane) ──────────────────

# Numer umowy w formacie „<liczba>/<rok>" (np. „1434/2026"). Prefiks liczbowy
# jest faktycznym numerem porządkowym — kolumna `seq` to tylko licznik wierszy.
_NUMBER_RE = re.compile(r"^\s*(\d+)\s*/\s*(\d{4})\s*$")


def _nip_digits(raw: str | None) -> str | None:
    """NIP kanonicznie do samych cyfr (kolumna `b2b_generated_contracts.nip`).

    Surowe formatowanie („123-456-32-18", „PL 1234563218") zostaje
    w `render_payload`, więc dokument renderuje się bez zmian. Kolumna jest
    kanoniczna, bo inaczej wyszukiwanie po NIP zależałoby od tego, jak
    użytkownik wpisał kreski: „1234563218" nie znalazłoby „123-456-32-18".
    """
    digits = re.sub(r"\D", "", raw or "")
    return digits[:32] or None


def _parse_seq(contract_number: str | None, year: int | None = None) -> int | None:
    """Wyłuskaj numer porządkowy z `contract_number` („1434/2026" → 1434).

    Gdy podano `year`, dopasuj tylko numery z tego roku (inaczej zwróć None)."""
    if not contract_number:
        return None
    m = _NUMBER_RE.match(contract_number)
    if not m:
        return None
    if year is not None and int(m.group(2)) != year:
        return None
    return int(m.group(1))


def _validate_contract_number(number: str, suggested: str) -> tuple[int, int, str]:
    """Zwaliduj format „liczba/rok” i zwróć `(seq, rok, postać kanoniczna)`.

    Postać kanoniczna (`"1434/2026"`, bez spacji) jest jedyną zapisywaną do DB —
    inaczej „1434 / 2026” ominąłby string-owy check unikalności."""
    m = _NUMBER_RE.match(number)
    if not m:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Numer umowy musi być w formacie „liczba/rok”, np. {suggested}.",
        )
    seq, year = int(m.group(1)), int(m.group(2))
    return seq, year, f"{seq}/{year}"


async def _next_seq(db: AsyncSession) -> int:
    """Następny numer porządkowy = max(liczbowy prefiks `contract_number`) + 1.

    Liczone z REALNYCH numerów (string „1434/2026"), NIE z kolumny `seq` (zwykły
    licznik wierszy) — dzięki temu sugestia respektuje ręcznie wpisane numery
    (kontynuacja zewnętrznej numeracji, np. 1433→1434→1435) zamiast cofać się do
    „8/2026". Duplikaty nie zawyżają wyniku (max po wartości, nie po liczbie wierszy)."""
    # Numeracja jest CIĄGŁA między latami — zmienia się tylko rok („1302/2026”
    # był pierwszym numerem 2026 w rejestrze Excel działu). Liczone po
    # wszystkich latach; z filtrem po roku 1 stycznia sugestią byłoby „1/2027”.
    rows = await db.execute(
        select(
            B2BGeneratedContract.contract_number,
            B2BGeneratedContract.raw_contract_number,
        )
    )
    max_seq = 0
    for record in rows.all():
        number = record[0]
        raw_number = record[1] if len(record) > 1 else None
        parsed = _parse_seq(number)
        # Wiersz z Excela bez daty podpisania ma numer bez roku („1517”) —
        # numeracja działu jest wspólna i ciągła, więc też się liczy.
        if parsed is None and raw_number and raw_number.strip().isdigit():
            parsed = int(raw_number.strip())
        if parsed is not None and parsed > max_seq:
            max_seq = parsed
    # Numery USUNIĘTYCH wpisów są POMIJANE, nie wliczane do maksimum (audyt
    # 23.09.2026): usunięty DOCX mógł już wyjść do Partnera, a `max+1` z samych
    # żywych wierszy oddawało jego numer następnej osobie (1518 i 1522/2026
    # wydane dwa razy). Maksimum liczone z nich zawyżyłoby numerację na zawsze
    # po jednej usuniętej literówce („15190/2026” zamiast „1519/2026”).
    deleted = {
        parsed
        for number in await _deleted_contract_numbers(db)
        if (parsed := _parse_seq(number)) is not None
    }
    candidate = max_seq + 1
    while candidate in deleted:
        candidate += 1
    return candidate


async def _deleted_contract_numbers(db: AsyncSession) -> list[str]:
    """Numery umów, których wpis usunięto z rejestru (dziennik `activities`).

    Wiersz rejestru znika przy DELETE, ale wpis `deleted` w dzienniku zostaje —
    to on pamięta, że numer został wydany. Bez osobnej tabeli nagrobków."""
    rows = await db.execute(
        select(Activity.details["contract_number"].astext).where(
            Activity.entity_type == "b2b_generated_contract",
            Activity.action == "deleted",
        )
    )
    numbers: list[str] = []
    for (number,) in rows.all():
        if not number:
            continue
        # Postać kanoniczna („1518/2026”): stary wpis „1518 / 2026” musi
        # blokować ten sam numer, a nie osobny napis.
        m = _NUMBER_RE.match(number)
        numbers.append(f"{int(m.group(1))}/{int(m.group(2))}" if m else number)
    return numbers


@router.get("/next-number", response_model=B2BNextNumberResponse)
async def next_number(
    current_user: B2BGeneratorAccess,
    db: AsyncSession = Depends(get_db),
):
    """Sugerowany kolejny WOLNY numer umowy `<seq>/<rok>` (edytowalny w UI)."""
    year = datetime.now(timezone.utc).year
    seq = await _next_seq(db)
    return B2BNextNumberResponse(contract_number=f"{seq}/{year}", year=year, seq=seq)


# ── Auto-uzupełnianie danych firmy z rejestru (NIP / KRS) ────────────────────


@router.get("/company-lookup", response_model=B2BCompanyLookupResponse)
async def company_lookup(
    current_user: B2BGeneratorAccess,
    nip: str | None = Query(None),
    krs: str | None = Query(None),
):
    """Dane firmy z rejestru: Biała Lista MF po NIP (JDG + spółki) lub KRS."""
    _require_contract_generation(current_user)
    data = await lookup_company(nip=nip, krs=krs)
    if not data:
        raise HTTPException(
            status_code=404,
            detail="Nie znaleziono firmy w rejestrze (sprawdź NIP / KRS).",
        )
    return data


# ── Standalone render (DOCX / HTML) — bez rekordu Contract ───────────────────


@router.post("/render")
async def render_standalone(
    payload: B2BRenderRequest,
    current_user: B2BGeneratorAccess,
    db: AsyncSession = Depends(get_db),
    fmt: str = Query("docx", alias="format", pattern="^(docx|html)$"),
):
    """Generuje umowę wprost z pól formularza (tryb ręczny / standalone).

    `format=html` → podgląd (nie loguje numeru). `format=docx` → przypisuje
    numer, loguje wygenerowanie i zwraca plik DOCX.
    """
    _require_contract_generation(current_user)
    lang = normalize_language(payload.language)
    role = await db.get(B2BContractRole, payload.role_id) if payload.role_id else None
    linked_job: Job | None = None
    if payload.candidate_id is not None and payload.job_id is not None:
        linked_job = await _load_legal_scoped_job(
            db,
            current_user,
            payload.job_id,
            write=True,
        )
        _, linked_job = await _validate_candidate_job_link(
            db,
            candidate_id=payload.candidate_id,
            job_id=linked_job.id,
        )
    await _assert_generator_client_access(
        db,
        current_user,
        linked_job.client_id if linked_job else None,
        write=True,
    )
    context = build_render_context(payload, role)

    if fmt == "html":
        tpl = await _b2b_template_for(db, lang)
        try:
            html = await run_in_threadpool(
                lambda: _jinja_env.from_string(tpl.content_jinja).render(**context)
            )
        except TemplateError as exc:
            raise HTTPException(status_code=422, detail=f"Render error: {exc}")
        # Per-klient modyfikacje umowy (§ 10, § 4 BNP, Załączniki CA/BIK…).
        key, ops = resolve_override(payload.client_name, lang)
        if ops:
            html, applied = apply_ops_html_counted(html, ops)
            if applied != len(ops):
                # Podgląd, z którego znikła klauzula, jest gorszy niż brak
                # podglądu: rekruter akceptuje go jako obraz umowy, którą za
                # chwilę wyda. logger.error → Sentry.
                logger.error(
                    "b2b_clause_override_incomplete surface=html lang=%s key=%s "
                    "applied=%d expected=%d",
                    lang,
                    key,
                    applied,
                    len(ops),
                )
                raise HTTPException(
                    status_code=500,
                    detail=(
                        "Nie udało się wstawić wszystkich klauzul Klienta do "
                        "podglądu umowy — szablon rozjechał się z rejestrem "
                        "klauzul. Zgłoś to zanim wygenerujesz dokument."
                    ),
                )
        return B2BRenderHtmlResponse(html=html, contract_number=payload.contract_number)

    # format == docx → numer + log + plik
    # Rozstrzygamy rejestr klauzul RAZ, PRZED zapisem wiersza: ta sama wartość
    # trafia do snapshotu i do renderu, więc log rejestru nie może opisywać
    # innego dokumentu niż wydany.
    override_key, override_ops = resolve_override(payload.client_name, lang)
    default_year = (
        payload.signing_date.year
        if payload.signing_date
        else datetime.now(timezone.utc).year
    )
    suggested_seq = await _next_seq(db)
    suggested = f"{suggested_seq}/{default_year}"
    raw_number = (payload.contract_number or "").strip() or suggested

    # Format „liczba/rok" (np. 1435/2026) — wymagany; zapis tylko kanoniczny.
    row_seq, row_year, number = _validate_contract_number(raw_number, suggested)

    # Unikalność: ten sam numer umowy nie może być użyty dwa razy.
    clash = await db.scalar(
        select(B2BGeneratedContract.id).where(
            B2BGeneratedContract.contract_number == number
        )
    )
    if clash:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Numer umowy „{number}” jest już użyty — wybierz inny. "
                f"Następny wolny: {suggested}."
            ),
        )
    # Numeracja działu jest ciągła między latami, a wiersz z Excela bywa bez
    # roku („1517” bez daty podpisania) — ten sam numer porządkowy z Excela
    # w DOWOLNYM roku jest już wydany.
    excel_clash = await db.scalar(
        select(B2BGeneratedContract.id)
        .where(
            B2BGeneratedContract.source == "excel",
            or_(
                B2BGeneratedContract.seq == row_seq,
                func.trim(B2BGeneratedContract.raw_contract_number) == str(row_seq),
                B2BGeneratedContract.contract_number.like(f"{row_seq}/%"),
            ),
        )
        .limit(1)
    )
    if excel_clash:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Numer porządkowy {row_seq} jest już w rejestrze z Excela działu "
                f"— wybierz inny. Następny wolny: {suggested}."
            ),
        )
    if number in set(await _deleted_contract_numbers(db)):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Numer umowy „{number}” był już wydany (wpis usunięto z "
                f"rejestru, ale dokument mógł trafić do Partnera) — wybierz "
                f"inny. Następny wolny: {suggested}."
            ),
        )

    # Render PRZED zapisem wiersza (audyt 23.09.2026): dotąd numer był
    # commitowany, a dopiero potem powstawał plik — rozjazd rejestru klauzul
    # z szablonem dawał 500 i wiersz „W trakcie” bez dokumentu, który trzeba
    # było usuwać, żeby odzyskać numer. Render nie potrzebuje bazy.
    context["b2b"]["contract_number"] = number
    data = await _render_docx_or_500(context, lang, override_key)

    created = B2BGeneratedContract(
        year=row_year,
        seq=row_seq,
        contract_number=number,
        partner_name=payload.partner_name,
        client_name=payload.client_name,
        language=lang,
        signing_date=payload.signing_date,
        created_by=current_user.id,
        candidate_id=payload.candidate_id,
        job_id=payload.job_id,
        client_id=linked_job.client_id if linked_job else None,
        # Wygenerowanie dokumentu to początek biegu umowy, nie jej
        # obowiązywanie. „Aktywna" znaczy „podpisana obustronnie" i ustawia
        # ją WYŁĄCZNIE confirm-fully-signed; default kolumny („active")
        # kłamałby o każdej nowej umowie.
        contract_status="in_progress",
        # Snapshot danych rejestrowych na potrzeby listy — odnormalizowane
        # z payloadu, bo lista pokazuje je jako kolumny i filtruje po
        # `start_date` po stronie SQL-a.
        partner_legal_name=payload.partner_legal_name,
        partner_nip=_nip_digits(payload.partner_nip),
        start_date=payload.start_date,
        # Rozstrzygnięcie zapada TERAZ, nie przy każdym odczycie: ticket
        # wymaga snapshotu „nieprzeliczanego później", a forma prawna
        # Partnera po podpisaniu umowy przestaje być bieżącą informacją.
        partner_entity_type=resolve_partner_entity_type(
            stored=payload.partner_entity_type,
            legal_name=payload.partner_legal_name,
        ),
        # Zapis surowych pól → ponowne pobranie DOCX z listy (re-render).
        # Plus snapshot rejestru klauzul — bez niego re-render rozstrzyga
        # rejestr od nowa i wydaje inną umowę niż podpisana.
        render_payload={
            **payload.model_dump(mode="json"),
            _CLAUSE_SNAPSHOT_FIELD: _clause_snapshot(override_key, override_ops),
        },
    )
    db.add(created)
    try:
        await db.commit()
    except IntegrityError as exc:
        # Race: dwa równoległe rendery z tym samym numerem przeszły SELECT-check;
        # constraint UNIQUE(year, seq) ubija drugi INSERT (migracja 0128).
        await db.rollback()
        if "uq_b2b_generated_contracts_year_seq" not in str(exc.orig):
            # Inny więz (np. FK do usuniętej w międzyczasie rekrutacji) NIE jest
            # „numerem zajętym przez kogoś innego” — dotąd dostawał ten komunikat.
            logger.error("b2b_render_integrity_error number=%s: %s", number, exc.orig)
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "Nie udało się zapisać umowy — powiązany kandydat, rekrutacja "
                    "albo klient zmienił się w trakcie. Odśwież formularz i spróbuj "
                    "ponownie."
                ),
            ) from exc
        fresh = await _next_seq(db)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Numer umowy „{number}” został właśnie użyty przez kogoś innego "
                f"— wybierz inny. Następny wolny: {fresh}/{row_year}."
            ),
        )
    await _stamp_candidate_contact_on_contract(db, payload)
    return _docx_response(data, number, generated_id=created.id)


async def _stamp_candidate_contact_on_contract(
    db: AsyncSession, payload: "B2BRenderRequest"
) -> None:
    """Przepisz kontakt z „Danych Partnera" na JEDNOZNACZNĄ umowę tej pary.

    Ticket wymaga, żeby e-mail i telefon wpisane przy generowaniu były „danymi
    powiązanymi z kontraktem" — a nie dopiero po podpisie.
    ``b2b_generated_contracts.contract_id`` ustawia się wyłącznie
    w ``confirm-fully-signed``, więc tutaj jedynym wiązaniem jest para
    (kandydat, rekrutacja).

    Trzy świadome zawężenia:

    * **dokładnie jedna** nie-``void`` umowa tej pary — zero trafień albo więcej
      niż jedno kończy się pominięciem, bo wpisanie kontaktu w zgadniętą umowę
      jest gorsze niż jego brak (fallback do profilu i tak działa);
    * **fill-only** — ręczna poprawka Delivery wygrywa z dokumentem;
    * **fail-soft** — to poboczny efekt pobrania DOCX. Awaria tutaj nie może
      zabrać użytkownikowi wygenerowanego dokumentu, za który już zapłacił
      czasem; zostaje log i fallback do profilu.
    """

    if payload.candidate_id is None or payload.job_id is None:
        return
    if not (payload.partner_email or payload.partner_phone):
        return
    try:
        rows = (
            (
                await db.execute(
                    select(Contract)
                    .where(
                        Contract.candidate_id == payload.candidate_id,
                        Contract.job_id == payload.job_id,
                        Contract.status != ContractStatus.void,
                    )
                    .limit(2)
                )
            )
            .scalars()
            .all()
        )
        if len(rows) != 1:
            return
        if fill_candidate_contact(rows[0], payload):
            await db.commit()
    except Exception:  # noqa: BLE001 — treść błędu może nieść dane umowy
        await db.rollback()
        logger.warning(
            "b2b render: candidate contact stamp skipped (%s)",
            "unexpected_error",
        )


def _like_needle(raw: str) -> str:
    """Zamień frazę użytkownika na bezpieczny wzorzec ILIKE.

    Escapujemy `%`, `_` i `\\`, żeby wpisanie ich w wyszukiwarce szukało tych
    znaków, a nie działało jak wildcard (`%` bez escapu zwracał całą listę)."""
    escaped = raw.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


@router.get("/generated", response_model=list[B2BGeneratedContractItem])
async def list_generated_contracts(
    current_user: B2BGeneratorAccess,
    db: AsyncSession = Depends(get_db),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(
        0,
        ge=0,
        description=(
            "Stronicowanie „Pokaż więcej” — okno po `created_at DESC`. Bez "
            "niego rejestr cicho kończył się na `limit` najnowszych wierszach."
        ),
    ),
    q: str | None = Query(
        None,
        max_length=120,
        description=(
            "Szukaj po numerze umowy, nazwie firmy Partnera, NIP, nazwie "
            "Klienta lub imieniu i nazwisku Partnera/powiązanego kandydata."
        ),
    ),
    contract_status: list[str] | None = Query(
        None,
        description=(
            "Filtr statusu handlowego umowy. Parametr powtarzalny — zakładka "
            "„Umowy aktywne i w trakcie podpisu” przesyła dwie wartości."
        ),
    ),
    closure_reason: str | None = Query(
        None,
        description="Filtr powodu zakończenia projektu (zakładki bez projektu / zakończone).",
    ),
    job_id: int | None = Query(
        None,
        gt=0,
        description=(
            "Umowy powiązane z jedną rekrutacją — krok 08 „Umowa” na ekranie "
            "rekrutacji. Bez tego filtra karta zamknięcia czytałaby tylko "
            "najnowsze `limit` wierszy REJESTRU i gubiła umowę starszą niż "
            "widoczna strona."
        ),
    ),
    start_from: date | None = Query(
        None, description="Data rozpoczęcia usług OD (włącznie)."
    ),
    start_to: date | None = Query(
        None, description="Data rozpoczęcia usług DO (włącznie)."
    ),
    source: str | None = Query(
        None,
        pattern="^(generator|excel)$",
        description="Tylko umowy wydane w NEXUSIE (`generator`) albo z Excela działu.",
    ),
    business_data_annex_pending: bool = Query(
        False,
        description=(
            "Tylko umowy czekające na aneks „uzupełnienie danych firmy” "
            "(podpisane przed założeniem działalności)."
        ),
    ),
):
    """Ostatnio wygenerowane umowy (numer, partner, klient, data) — do zakładki
    „Wygenerowane umowy", by potwierdzić poprawność numeru.

    ``q`` filtruje po stronie serwera (nie po `limit` pobranych wierszy), więc
    znajduje też umowy starsze niż widoczna strona listy.

    ``can_delete`` mówi UI, czy bieżący użytkownik może usunąć dany wpis (autor
    wpisu lub admin)."""
    # Odwrócony zakres zwróciłby pustą listę, którą użytkownik czyta jako „nie
    # ma takich umów", a nie „pomyliłeś daty". Cicha zamiana granic byłaby
    # jeszcze gorsza: filtr działałby inaczej, niż napisano w URL-u. FastAPI nie
    # waliduje między parametrami, więc musi to być jawny guard w ciele.
    if start_from is not None and start_to is not None and start_from > start_to:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="„Data rozpoczęcia od” nie może być późniejsza niż „do”.",
        )

    # Walidacja w ciele, a nie regexem w `Query(pattern=…)`: parametr jest teraz
    # powtarzalny, a `pattern` na `list[str]` FastAPI stosuje do CAŁEJ listy,
    # więc regex albo przepuszczałby wszystko, albo nic. Nieznana wartość musi
    # dać 422 z nazwą pomyłki — ciche zignorowanie filtra zwróciłoby PEŁNĄ listę
    # umów pod nagłówkiem zakładki, która obiecuje wąski podzbiór.
    statuses = [s for s in (contract_status or []) if s]
    unknown = sorted(set(statuses) - set(get_args(B2BContractStatus)))
    if unknown:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Nieznany status umowy: {', '.join(unknown)}.",
        )
    if closure_reason is not None and closure_reason not in get_args(B2BClosureReason):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Nieznany powód zakończenia: {closure_reason}.",
        )

    query = await _scope_generator_query(
        select(B2BGeneratedContract),
        B2BGeneratedContract.client_id,
        db,
        current_user,
    )

    needle = (q or "").strip()
    if needle:
        # OUTER JOIN, bo większość wierszy nie ma dowiązanego kandydata —
        # INNER wyciąłby je z wyników wyszukiwania po numerze umowy.
        query = query.outerjoin(
            Candidate, Candidate.id == B2BGeneratedContract.candidate_id
        )
        # Pola tekstowe bez wrażliwości na polskie znaki (UAT M08-B01);
        # `polish_folded_ilike` escapuje `%`, `_` i `\\` jak `_like_needle`.
        clauses = [
            polish_folded_ilike(B2BGeneratedContract.contract_number, needle),
            polish_folded_ilike(B2BGeneratedContract.partner_name, needle),
            # Kolumna „Partner" pokazuje NAZWĘ FIRMY, więc bez tego warunku
            # wyszukiwarka nie znajduje tego, co użytkownik widzi na liście.
            polish_folded_ilike(B2BGeneratedContract.partner_legal_name, needle),
            polish_folded_ilike(B2BGeneratedContract.client_name, needle),
            polish_folded_ilike(Candidate.name, needle),
            polish_folded_ilike(Candidate.lastname, needle),
            # Pełne „Imię Nazwisko" wpisane jednym ciągiem — pojedyncze
            # kolumny wyżej same tego nie dopasują.
            polish_folded_ilike(
                func.concat(Candidate.name, " ", Candidate.lastname), needle
            ),
        ]
        # NIP dochodzi tylko dla fraz wyglądających jak NIP. Próg 5 cyfr, bo
        # `q="1"` dopasowałoby połowę rejestru. Kolumna trzyma same cyfry
        # (kanonicznie, patrz `_nip_digits`), więc needle też normalizujemy —
        # inaczej „123-456-32-18" nie znalazłoby zapisanego „1234563218".
        nip_needle = re.sub(r"\D", "", needle)
        if len(nip_needle) >= 5:
            clauses.append(
                B2BGeneratedContract.partner_nip.ilike(
                    _like_needle(nip_needle), escape="\\"
                )
            )
        query = query.where(or_(*clauses))

    if statuses:
        query = query.where(B2BGeneratedContract.contract_status.in_(statuses))
    if closure_reason:
        query = query.where(B2BGeneratedContract.closure_reason == closure_reason)
    if job_id is not None:
        query = query.where(B2BGeneratedContract.job_id == job_id)
    if source is not None:
        query = query.where(B2BGeneratedContract.source == source)
    if business_data_annex_pending:
        query = query.where(
            B2BGeneratedContract.needs_business_data_annex.is_(True),
            B2BGeneratedContract.business_data_annex_done_at.is_(None),
        )

    # Koniunkcja z `q` i `contract_status` wychodzi sama: każdy filtr dokłada
    # własne `.where(...)`, a SQLAlchemy łączy je AND-em. Wiersze bez
    # `start_date` (historyczne, bez payloadu) WYPADAJĄ z zakresu — nieznana
    # data rozpoczęcia nie mieści się w żadnym przedziale.
    if start_from is not None:
        query = query.where(B2BGeneratedContract.start_date >= start_from)
    if start_to is not None:
        query = query.where(B2BGeneratedContract.start_date <= start_to)

    # Okno wierszy zostaje „najnowsze `limit`" (po `created_at`), żeby świeżo
    # wygenerowana umowa — także z ręcznie wpisanym NISKIM numerem — nigdy nie
    # wypadła poza widoczną stronę. Gdyby oknem był sam numer, `ORDER BY year,
    # seq ASC LIMIT` zwracałby najNIŻSZE numery (najstarsze umowy) i chował te
    # dopiero co utworzone — dokładnie odwrotnie do potrzeby.
    rows = list(
        (
            await db.execute(
                query.order_by(
                    B2BGeneratedContract.created_at.desc(),
                    B2BGeneratedContract.id.desc(),
                )
                .offset(offset)
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    # WYŚWIETLAMY malejąco po numerze umowy, żeby najnowszy numer był na górze
    # tabeli. Sortujemy po LICZBOWYCH kolumnach (year, seq) — nie po stringu
    # „1500/2026", który leksykalnie stawia „999/2026" przed „1000/2026".
    # UNIQUE(year, seq) czyni z tej pary porządek całkowity, więc kolejność jest
    # deterministyczna także przy numerach wpisanych ręcznie.
    # Wiersz z Excela bez numeru kanonicznego (`seq`/`year` NULL) ląduje na
    # końcu strony, po numerowanych.
    rows.sort(key=lambda r: (r.year or 0, r.seq or 0, r.id), reverse=True)
    return await _serialize_generated_contracts(db, rows, current_user)


# ── Eksport rejestru w układzie Excela działu ────────────────────────────────

#: Nagłówki kolumn A–N arkusza „Umowy B2B” działu — w tej kolejności, żeby
#: wiersze dało się wkleić do pliku prowadzonego równolegle (decyzja 23.09.2026).
REGISTER_EXPORT_HEADERS: tuple[str, ...] = (
    "NAZWISKO, PÓŹNIEJ IMIE",
    "Numer umowy",
    "Klient",
    "Stanowisko",
    "Rodzaj umowy",
    "Data podpisania",
    "Data startu pracy",
    "Data zakończenia umowy",
    "Okres lojalności",
    "Rekruter",
    "czy wysłano informację o rozliczeniach",
    "mail powitalny",
    "UWAGI",
    "ZMIANY W UMOWIE",
)
_KIND_LABELS = {
    "b2b": "B2B",
    "mandate": "zlecenie",
    "work": "dzieło",
    "employment": "UoP",
}
_START_MODE_PREFIX = {
    "not_later": "nie później niż ",
    "not_earlier": "nie wcześniej niż ",
}
_XLSX_MEDIA = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _register_export_sort_key(row: B2BGeneratedContract) -> tuple[int, int, int]:
    raw = (row.raw_contract_number or "").strip()
    number = row.seq if row.seq is not None else (int(raw) if raw.isdigit() else None)
    if number is None:
        number = _parse_seq(row.contract_number) or 10**9
    return (number, row.year or 0, row.id)


def _surname_first(person: str | None) -> str | None:
    parts = (person or "").split()
    if len(parts) < 2:
        return person
    return " ".join(parts[-1:] + parts[:-1])


def _build_register_xlsx(
    rows: list[B2BGeneratedContract],
    *,
    role_names: dict[int, str],
    user_names: dict[int, str],
    job_recruiters: dict[int, int],
    include_free_text: bool = True,
) -> bytes:
    from io import BytesIO

    from openpyxl import Workbook

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Umowy B2B"
    sheet.append(list(REGISTER_EXPORT_HEADERS))
    for row in rows:
        excel = (
            ((row.legacy_data or {}).get("excel") or {})
            if row.source == "excel"
            else {}
        )
        payload = row.render_payload or {}
        if row.source == "excel":
            number: object = row.seq if row.seq is not None else row.raw_contract_number
            if isinstance(number, str) and number.strip().isdigit():
                number = int(number.strip())
            name = excel.get("name") or _surname_first(row.partner_name)
            position = row.position
            kind = _KIND_LABELS.get(row.contract_kind or "", excel.get("kind"))
            recruiter = user_names.get(row.recruiter_user_id) or excel.get("recruiter")
        else:
            number = _parse_seq(row.contract_number) or row.contract_number
            name = _surname_first(row.partner_name)
            role_id = payload.get("role_id")
            position = role_names.get(role_id) if isinstance(role_id, int) else None
            kind = "B2B"
            recruiter_id = job_recruiters.get(row.job_id) if row.job_id else None
            recruiter = user_names.get(recruiter_id) if recruiter_id else None
        if row.start_date and row.start_date_mode in _START_MODE_PREFIX:
            start: object = _START_MODE_PREFIX[
                row.start_date_mode
            ] + row.start_date.strftime("%d.%m.%Y")
        else:
            start = row.start_date or excel.get("start")
        end_date = excel.get("end_date")
        end: object = (
            date.fromisoformat(end_date)
            if end_date
            else excel.get("end") or "czas nieokreślony"
        )
        signing: object = row.signing_date
        if signing is None:
            signing = excel.get("signing") or (
                "umowa nie doszła do skutku"
                if row.contract_status == "cancelled"
                else None
            )
        sheet.append(
            [
                name,
                number,
                row.client_name,
                position,
                kind,
                signing,
                start,
                end,
                excel.get("loyalty"),
                recruiter,
                # Wolny tekst działu bywa o stawkach („zmiana stawki od…”) —
                # tylko dla ról, które widzą wszystkie stawki (admin, Finanse).
                excel.get("settlement_info") if include_free_text else None,
                excel.get("welcome_mail"),
                excel.get("notes") if include_free_text else None,
                excel.get("changes") if include_free_text else None,
            ]
        )
    for cells in sheet.iter_rows(min_row=2):
        for cell in cells:
            if isinstance(cell.value, date):
                cell.number_format = "DD.MM.YYYY"
            elif cell.data_type == "f":
                # openpyxl zamienia napis zaczynający się od „=” w formułę —
                # tekst z pliku działu ma zostać tekstem (formula injection).
                cell.data_type = "s"
    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


@router.get("/generated/export.xlsx")
async def export_generated_contracts_xlsx(
    current_user: B2BGeneratorAccess,
    db: AsyncSession = Depends(get_db),
):
    """Cały rejestr (NEXUS + Excel) w układzie kolumn A–N arkusza działu,
    posortowany po numerze — do wklejenia umów wydanych w NEXUSIE do Excela.
    Stawek NIE eksportujemy (plik wychodzi poza NEXUS)."""
    query = await _scope_generator_query(
        select(B2BGeneratedContract),
        B2BGeneratedContract.client_id,
        db,
        current_user,
    )
    rows = list((await db.execute(query)).scalars().all())
    rows.sort(key=_register_export_sort_key)
    role_ids = {
        payload.get("role_id")
        for row in rows
        if isinstance(payload := row.render_payload or {}, dict)
        and isinstance(payload.get("role_id"), int)
    }
    role_names: dict[int, str] = {}
    if role_ids:
        result = await db.execute(
            select(B2BContractRole.id, B2BContractRole.name_pl).where(
                B2BContractRole.id.in_(role_ids)
            )
        )
        role_names = {rid: name for rid, name in result.all()}
    job_ids = {row.job_id for row in rows if row.job_id is not None}
    job_recruiters: dict[int, int] = {}
    if job_ids:
        result = await db.execute(
            select(Job.id, Job.recruiter_id).where(Job.id.in_(job_ids))
        )
        job_recruiters = {jid: rid for jid, rid in result.all() if rid is not None}
    user_ids = {row.recruiter_user_id for row in rows if row.recruiter_user_id} | set(
        job_recruiters.values()
    )
    user_names: dict[int, str] = {}
    if user_ids:
        result = await db.execute(
            select(User.id, User.name).where(User.id.in_(user_ids))
        )
        user_names = {uid: name for uid, name in result.all()}
    data = await run_in_threadpool(
        _build_register_xlsx,
        rows,
        role_names=role_names,
        user_names=user_names,
        job_recruiters=job_recruiters,
        include_free_text=current_user.has_role(UserRole.admin)
        or current_user.has_role(UserRole.finance),
    )
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return Response(
        content=data,
        media_type=_XLSX_MEDIA,
        headers={
            "Content-Disposition": f'attachment; filename="rejestr-umow-b2b-{stamp}.xlsx"'
        },
    )


@router.get(
    "/generated/{generated_id}/status-history",
    response_model=list[B2BStatusEventItem],
)
async def generated_contract_status_history(
    generated_id: int,
    current_user: B2BGeneratorAccess,
    db: AsyncSession = Depends(get_db),
):
    """Dziennik zmian statusu jednej umowy — dialog „Historia statusów".

    To JEDYNE miejsce, w którym da się odczytać datę i powód zakończenia
    projektu po tym, jak umowa wróciła z zawieszenia do gry: powrót na „Aktywna"
    czyści `closure_*` na wierszu (wymusza to
    `ck_b2b_generated_contracts_closure_coherence`).

    Rosnąco po `created_at`: historia czyta się od początku, a nie od końca.
    """
    row = await db.get(B2BGeneratedContract, generated_id)
    if not row:
        raise HTTPException(status_code=404, detail="Wpis nie został znaleziony")
    await _assert_generator_client_access(db, current_user, row.client_id)

    events = list(
        (
            await db.execute(
                select(B2BGeneratedContractStatusEvent)
                .where(
                    B2BGeneratedContractStatusEvent.generated_contract_id
                    == generated_id
                )
                .order_by(
                    B2BGeneratedContractStatusEvent.created_at.asc(),
                    B2BGeneratedContractStatusEvent.id.asc(),
                )
            )
        )
        .scalars()
        .all()
    )
    if not events:
        return []

    # Batch lookup jak w `_serialize_generated_contracts` — dziennik bywa długi
    # dla kontraktora krążącego między projektami, a N+1 na trzech tabelach
    # zrobiłby z dialogu historii najwolniejszy ekran w module.
    job_ids = {e.job_id for e in events if e.job_id}
    client_ids = {e.client_id for e in events if e.client_id}
    user_ids = {e.changed_by for e in events if e.changed_by}

    jobs: dict[int, str] = {}
    if job_ids:
        result = await db.execute(select(Job.id, Job.title).where(Job.id.in_(job_ids)))
        jobs = {jid: title for jid, title in result.all()}
    clients: dict[int, str] = {}
    if client_ids:
        result = await db.execute(
            select(
                Client.id,
                client_display_name_expression().label("client_name"),
            ).where(Client.id.in_(client_ids))
        )
        clients = {cid: name for cid, name in result.all()}
    users: dict[int, str] = {}
    if user_ids:
        result = await db.execute(
            select(User.id, User.name).where(User.id.in_(user_ids))
        )
        users = {uid: name for uid, name in result.all()}

    return [
        B2BStatusEventItem(
            id=e.id,
            from_status=e.from_status,
            to_status=e.to_status,
            effective_date=e.effective_date,
            reason=e.reason,
            reason_other=e.reason_other,
            job_id=e.job_id,
            job_title=jobs.get(e.job_id) if e.job_id else None,
            client_id=e.client_id,
            client_name=clients.get(e.client_id) if e.client_id else None,
            changed_by_name=users.get(e.changed_by) if e.changed_by else None,
            created_at=e.created_at.isoformat() if e.created_at else None,
        )
        for e in events
    ]


@router.get("/generated/{generated_id}/docx")
async def download_generated_contract(
    generated_id: int,
    current_user: B2BGeneratorAccess,
    db: AsyncSession = Depends(get_db),
):
    """Pobierz ponownie DOCX wygenerowanej umowy — odtworzony z zapisanego payloadu.

    Render bierze pola formularza z `render_payload` ORAZ przypięty tam snapshot
    rejestru klauzul, więc treść nie zmienia się przy kolejnych edycjach rejestru
    (numer umowy bierzemy z wiersza logu, nie z payloadu).

    UWAGA — to nie jest dowód tego, co strony podpisały. Wiersze wydane przed
    wprowadzeniem snapshotu (`_clause_override`) rozstrzygają rejestr po nazwie
    Klienta, czyli mogą wyjść z inną treścią niż wersja dostarczona; rozjazd
    treści klauzul pod tym samym kluczem też jest tylko logowany, nie blokowany.
    Autorytatywny jest podpisany dokument, nie ten plik. Wiersze bez payloadu →
    422 z prośbą o ponowne wygenerowanie."""
    _require_contract_generation(current_user)
    row = await db.get(B2BGeneratedContract, generated_id)
    if not row:
        raise HTTPException(status_code=404, detail="Wpis nie został znaleziony")
    await _assert_generator_client_access(
        db,
        current_user,
        row.client_id,
        write=True,
    )
    await _require_generator_rate_content(
        db,
        current_user,
        row.client_id,
        created_by=row.created_by,
        job_id=row.job_id,
    )
    _reject_excel_row(row)
    if not row.render_payload:
        raise HTTPException(
            status_code=422,
            detail=(
                "Ta umowa została wygenerowana zanim dodaliśmy zapis danych — "
                "nie można jej odtworzyć. Wygeneruj ją ponownie z formularza."
            ),
        )
    payload = B2BRenderRequest(**row.render_payload)
    lang = normalize_language(payload.language)
    role = await db.get(B2BContractRole, payload.role_id) if payload.role_id else None
    context = build_render_context(payload, role)
    context["b2b"]["contract_number"] = row.contract_number

    data = await _render_docx_or_500(context, lang, _pinned_clause_key(row, lang))
    return _docx_response(data, row.contract_number)


async def _load_row_for_correction(
    db: AsyncSession, current_user: User, generated_id: int
) -> B2BGeneratedContract:
    """Wiersz rejestru, który ``current_user`` może poprawić pod tym samym numerem.

    Jedna bramka dla odczytu danych formularza i dla ponownego renderu —
    rozjazd dałby przycisk „Popraw”, który kończy się 403 dopiero przy zapisie."""
    _require_contract_generation(current_user)
    _require_generated_contract_management(current_user)
    row = await db.scalar(
        select(B2BGeneratedContract)
        .where(B2BGeneratedContract.id == generated_id)
        .with_for_update()
    )
    if not row:
        raise HTTPException(status_code=404, detail="Wpis nie został znaleziony")
    await _assert_generator_client_access(db, current_user, row.client_id, write=True)
    _reject_excel_row(row)
    if not current_user.has_role(UserRole.admin) and row.created_by != current_user.id:
        raise HTTPException(
            status_code=403,
            detail="Poprawić umowę może tylko jej autor albo administrator.",
        )
    if row.signature_status == "signed_both" or row.contract_status != "in_progress":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Poprawić można tylko niepodpisaną umowę „W trakcie” — "
                "podpisany dokument jest zapisem tego, co strony podpisały."
            ),
        )
    return row


@router.get("/generated/{generated_id}/form")
async def generated_contract_form(
    generated_id: int,
    current_user: B2BGeneratorAccess,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Dane formularza zapisanej umowy — „Popraw” z wiersza rejestru.

    Bez tego poprawka pod tym samym numerem działała tylko w karcie, w której
    umowę pobrano; po odświeżeniu zostawało „Usuń”, a usunięcie trwale zużywa
    numer (audyt 23.09.2026). Snapshot rejestru klauzul zostaje po stronie
    serwera — ponowny render rozstrzyga go na nowo."""
    row = await _load_row_for_correction(db, current_user, generated_id)
    if not row.render_payload:
        raise HTTPException(
            status_code=422,
            detail=(
                "Ta umowa została wygenerowana zanim dodaliśmy zapis danych — "
                "nie da się jej wczytać do formularza."
            ),
        )
    form = {
        key: value
        for key, value in row.render_payload.items()
        if key != _CLAUSE_SNAPSHOT_FIELD
    }
    form["contract_number"] = row.contract_number
    return {"id": row.id, "contract_number": row.contract_number, "form": form}


@router.post("/generated/{generated_id}/rerender")
async def rerender_generated_contract(
    generated_id: int,
    payload: B2BRenderRequest,
    current_user: B2BGeneratorAccess,
    db: AsyncSession = Depends(get_db),
):
    """Popraw niepodpisaną umowę i pobierz ją ponownie — POD TYM SAMYM numerem.

    Do 23.09.2026 jedyną drogą poprawki literówki albo zmiany języka było
    „usuń i wygeneruj od nowa” (15 usunięć na ~104 generacje), a każde
    ponowne kliknięcie „Pobierz” zakładało drugi wiersz z kolejnym numerem.
    Poprawka nadpisuje ``render_payload`` i kolumny snapshotu tego samego
    wiersza. Kandydata i rekrutacji zmienić nie można — to już inna umowa.
    Bramka jak przy usuwaniu: autor albo admin, tylko umowa „W trakcie”."""
    row = await _load_row_for_correction(db, current_user, generated_id)
    if (payload.candidate_id, payload.job_id) != (row.candidate_id, row.job_id):
        raise HTTPException(
            status_code=422,
            detail=(
                "Zmiana kandydata albo rekrutacji to nowa umowa — wygeneruj ją "
                "z pustego formularza („Nowa umowa”)."
            ),
        )

    lang = normalize_language(payload.language)
    role = await db.get(B2BContractRole, payload.role_id) if payload.role_id else None
    context = build_render_context(payload, role)
    context["b2b"]["contract_number"] = row.contract_number
    override_key, override_ops = resolve_override(payload.client_name, lang)
    data = await _render_docx_or_500(context, lang, override_key)

    row.partner_name = payload.partner_name
    row.client_name = payload.client_name
    row.language = lang
    row.signing_date = payload.signing_date
    row.partner_legal_name = payload.partner_legal_name
    row.partner_nip = _nip_digits(payload.partner_nip)
    row.start_date = payload.start_date
    row.partner_entity_type = resolve_partner_entity_type(
        stored=payload.partner_entity_type,
        legal_name=payload.partner_legal_name,
    )
    row.render_payload = {
        **payload.model_dump(mode="json"),
        "contract_number": row.contract_number,
        _CLAUSE_SNAPSHOT_FIELD: _clause_snapshot(override_key, override_ops),
    }
    db.add(
        Activity(
            entity_type="b2b_generated_contract",
            entity_id=row.id,
            action="regenerated",
            user_id=current_user.id,
            details={
                "contract_number": row.contract_number,
                "language": lang,
                "clause_override": override_key,
            },
        )
    )
    await db.commit()
    await _stamp_candidate_contact_on_contract(db, payload)
    return _docx_response(data, row.contract_number, generated_id=row.id)


@router.post(
    "/generated/{generated_id}/confirm-fully-signed",
    response_model=B2BConfirmFullySignedResponse,
)
async def confirm_generated_contract_fully_signed(
    generated_id: int,
    payload: B2BConfirmFullySignedRequest,
    current_user: B2BGeneratorAccess,
    db: AsyncSession = Depends(get_db),
):
    """One-way, audited manual confirmation with atomic employment automation.

    Wiąże kontrakt, zapewnia zamówienie i przesuwa kandydata na „Zatrudniony"
    (Pipeline v4, decyzja Artura 23.09.2026 — cofa decyzję z 17.09.2026:
    podpisana umowa JEST zatrudnieniem, człowiek nie musi tego klikać drugi
    raz). Podpis jest dowodem zatrudnienia, więc przesuwa także kartę
    z zamkniętej historii (np. „Odrzucony" z importu Traffita) — jak przed
    17.09. Gdy para nie ma uzupełnionego zamówienia, Finanse dostają
    powiadomienie ``hired_order_missing``.
    """

    _require_signature_confirmation(current_user)
    try:
        row = await db.scalar(
            select(B2BGeneratedContract)
            .where(B2BGeneratedContract.id == generated_id)
            .with_for_update()
        )
        if row is None:
            raise HTTPException(status_code=404, detail="Wpis nie został znaleziony")
        _reject_excel_row(row)
        # confirm-fully-signed is the audited, one-way employment automation —
        # it stays strictly client-scoped for DL/TAC even though the rest of the
        # generator is unscoped for a full-access TAC.
        if row.client_id is not None:
            await _assert_signature_client_access(
                db,
                current_user,
                row.client_id,
            )
        elif payload.job_id is None:
            await _assert_signature_client_access(
                db,
                current_user,
                None,
            )
        if payload.job_id is not None:
            selected_job = await db.get(Job, payload.job_id)
            if selected_job is None:
                raise HTTPException(status_code=404, detail="Rekrutacja nie istnieje")
            await _assert_signature_client_access(
                db, current_user, selected_job.client_id
            )

        # Idempotent replay: do not recreate an order/stage after the original
        # workflow has completed (the order may legitimately be completed or
        # deleted later). Return the durable links that still exist.
        if row.signature_status == "signed_both":
            if (
                row.contract_id is None
                or row.candidate_id is None
                or row.job_id is None
                or row.client_id is None
            ):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=(
                        "Podpisany wpis ma niepełne powiązania. Wymaga naprawy "
                        "administracyjnej; automatyzacja nie zostanie powtórzona."
                    ),
                )
            signed_job = await db.get(Job, row.job_id)
            if signed_job is None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Powiązana rekrutacja już nie istnieje.",
                )
            await _require_signature_job_scope(db, current_user, signed_job)
            # Replay odpowiada tym samym, co pierwsze potwierdzenie: TYLKO
            # zamówieniem okresowym (linia grupy ma własny rejestr i własne
            # `job_id`, więc bez tego filtra replay zwracał jej id tam, gdzie
            # pierwsza odpowiedź niosła `null`) — a gdy go nie ma, powodem,
            # liczonym tak samo jak w serwisie.
            order_id = await db.scalar(
                select(ClientOrder.id)
                .where(
                    ClientOrder.contract_id == row.contract_id,
                    ClientOrder.job_id == row.job_id,
                    ClientOrder.order_group_id.is_(None),
                )
                .order_by(ClientOrder.created_at.desc(), ClientOrder.id.desc())
                .limit(1)
            )
            replay_skipped_reason: str | None = None
            if order_id is None:
                if await has_open_group_line(db, row.contract_id):
                    replay_skipped_reason = ORDER_SKIPPED_OPEN_GROUP_LINE
                elif not should_auto_create_order(signed_job.client_id):
                    replay_skipped_reason = ORDER_SKIPPED_COST_CLIENT
            item = await _serialize_generated_contract(db, row, current_user)
            await db.commit()
            return B2BConfirmFullySignedResponse(
                outcome="already_processed",
                contract_id=row.contract_id,
                order_id=order_id,
                order_skipped_reason=replay_skipped_reason,
                candidate_id=row.candidate_id,
                job_id=row.job_id,
                client_id=row.client_id,
                message=(
                    "Umowa była już oznaczona jako podpisana. "
                    "Nie utworzono żadnych dodatkowych rekordów."
                ),
                generated_contract=item,
            )

        # Anulowana umowa nie może zostać oznaczona jako podpisana. Serializer
        # chowa przycisk (`can_confirm_signed`), ale ukryty przycisk nie jest
        # kontrolą — endpoint do 0328 NIE patrzył na `contract_status` w ogóle.
        # Po idempotentnym replayu, żeby wiersz już podpisany (stan, którego ta
        # ścieżka nie potrafi wytworzyć, ale który mógłby powstać w danych)
        # nadal odpowiadał tym samym, co zawsze, zamiast nagle 409.
        if row.contract_status == "cancelled":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=_CANCELLED_BLOCKS_SIGNATURE,
            )

        if (
            row.candidate_id is not None
            and payload.candidate_id is not None
            and row.candidate_id != payload.candidate_id
        ) or (
            row.job_id is not None
            and payload.job_id is not None
            and row.job_id != payload.job_id
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "Wpis ma już inne powiązanie źródłowe. Nie można przepiąć "
                    "go podczas potwierdzania podpisu."
                ),
            )

        candidate_id = row.candidate_id or payload.candidate_id
        job_id = row.job_id or payload.job_id
        if candidate_id is None or job_id is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    "Historyczna umowa wymaga wskazania kandydata i konkretnej "
                    "rekrutacji przed potwierdzeniem podpisu."
                ),
            )

        _, job = await _validate_candidate_job_link(
            db,
            candidate_id=candidate_id,
            job_id=job_id,
        )
        await _require_signature_job_scope(db, current_user, job)
        await _assert_signature_client_access(db, current_user, job.client_id)
        if row.client_id is not None and row.client_id != job.client_id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "Klient zapisany przy umowie nie odpowiada klientowi "
                    "wybranej rekrutacji."
                ),
            )

        render_payload = (
            B2BRenderRequest(**row.render_payload) if row.render_payload else None
        )
        result = await ensure_b2b_employment_draft(
            db,
            candidate_id=candidate_id,
            job=job,
            actor_id=current_user.id,
            payload=render_payload,
            contract_number=row.contract_number,
            signing_date=row.signing_date,
            language=row.language,
            ensure_order=True,
            # Pipeline v4 (23.09.2026): podpis przesuwa kandydata na
            # „Zatrudniony". Gdy polityka Priority Work odmówi otwarcia procesu,
            # `_ensure_hired_stage` łapie PriorityWorkLocked i podpis przechodzi
            # bez ruchu karty — komunikat mówi to wprost.
            ensure_hired=True,
            audit_source_generated_id=row.id,
            keep_existing_terms=payload.keep_existing_contract_terms,
        )
        # Brak zamówienia jest stanem do obsłużenia WYŁĄCZNIE z powodem
        # podanym przez serwis: klient kosztowy (typ zamówienia wybiera
        # Delivery Lead) albo osoba już obsadzona na żywej linii zamówienia
        # MD/kosztowego (auto-szkic okresowy dublowałby współpracę na tym
        # samym kontrakcie — #1321). Do 09.2026 bramka pytała tylko o klienta
        # kosztowego, więc drugi powód kończył się 500 („Network Error") i
        # wycofaniem całego podpisu u BIK/BNP. Bez powodu to nadal awaria:
        # cichy „brak zamówienia" zostawiłby zatrudnienie bez rekordu, który
        # czytają skaner wygasania, MRR i sync terminacji.
        if result.order is None and result.order_skipped_reason is None:
            raise RuntimeError("employment automation returned no ClientOrder")

        # Podpisana obustronnie umowa = kontrakt AKTYWNY od razu (09.2026):
        # okres start umowy → bezterminowo, stawka kosztowa godzinowa z umowy.
        # Stawka przychodowa dojdzie z zamówienia klienta — dlatego aktywacja
        # omija bramkę kompletności, która wymaga obu stawek. Bez daty startu
        # (historyczny wpis bez payloadu) kontrakt zostaje szkicem: aktywny
        # kontrakt bez początku okresu wypadałby z każdego raportu okresowego.
        contract_activated = False
        if result.contract.start_date is not None:
            contract_activated = await activate_without_revenue_gate(
                db,
                result.contract,
                actor_id=current_user.id,
                source=SIGNED_AGREEMENT_ACTIVATION,
                extra={"generated_contract_id": row.id},
            )
        row.signature_status = "signed_both"
        row.signature_source = "manual_confirmation"
        # Podpis obustronny to JEDYNE przejście `in_progress` → `active`.
        # WARUNKOWO, nie bezwarunkowo: umowę wolno zamknąć powodem
        # `resignation_before_signing` PRZED podpisem, a bezwarunkowe „active"
        # na takim wierszu zostawiłoby wypełnione pola `closure_*` przy statusie
        # `active` → IntegrityError z ck_..._closure_coherence, w środku
        # atomowej automatyzacji zatrudnienia.
        if row.contract_status == "in_progress":
            row.contract_status = "active"
        row.candidate_id = candidate_id
        row.job_id = job.id
        row.client_id = job.client_id
        row.contract_id = result.contract.id
        row.signed_at = datetime.now(timezone.utc)
        row.signed_by_user_id = current_user.id
        await db.flush()
        from app.services.order_mail_signature import complete_signed_mail_drafts

        await complete_signed_mail_drafts(
            db, result.contract.id, actor_id=current_user.id
        )
        # Zamówienie tej osoby bywa uzupełnione PRZED podpisem (np. z maila
        # od klienta) — wtedy kontrakt od razu dostaje okres zamówienia
        # i stawkę przychodową, a zamówienia stawkę kosztową z umowy.
        await resync_contract_safely(db, result.contract, actor_id=current_user.id)
        if row.render_payload is not None:
            row.render_payload = {
                **row.render_payload,
                "candidate_id": candidate_id,
                "job_id": job.id,
            }
        db.add(
            Activity(
                entity_type="b2b_generated_contract",
                entity_id=row.id,
                action="fully_signed_confirmed",
                user_id=current_user.id,
                details={
                    "contract_number": row.contract_number,
                    "candidate_id": candidate_id,
                    "job_id": job.id,
                    "client_id": job.client_id,
                    "contract_id": result.contract.id,
                    "order_id": result.order.id if result.order else None,
                    "source": "manual_confirmation",
                    "outcome": (
                        "created" if result.created_contract else "linked_existing"
                    ),
                    # Różnice, które operator świadomie zaakceptował — bez tego
                    # wpisu audyt nie odróżnia „warunki zgodne" od „powiązano
                    # mimo różnic, kontrakt został jak był".
                    "acknowledged_conflicts": list(result.acknowledged_conflicts),
                    "order_skipped_reason": result.order_skipped_reason,
                    "contract_activated": contract_activated,
                },
            )
        )
        # Build the public projection before committing so even a serializer
        # failure rolls back the entire handoff instead of returning a 500
        # after employment was already persisted.
        await db.flush()
        item = await _serialize_generated_contract(db, row, current_user)
        # Stan etapu PO automatyzacji — komunikat mówi prawdę także wtedy, gdy
        # kandydat był już zatrudniony albo jego proces jest zamknięty.
        latest_stage = await db.scalar(
            select(CandidateStage.stage)
            .where(
                CandidateStage.candidate_id == candidate_id,
                CandidateStage.job_id == job.id,
            )
            .order_by(CandidateStage.moved_at.desc(), CandidateStage.id.desc())
            .limit(1)
        )
        is_hired = latest_stage == PipelineStage.hired
        # Identyfikatory przed commitem — powiadomienie Finansów idzie po nim.
        finance_notice = {
            "contract_id": result.contract.id,
            "candidate_id": candidate_id,
            "job_id": job.id,
            "client_id": job.client_id,
            "start_date": result.contract.start_date,
        }
        current_user_id = current_user.id
        await db.commit()
        # Live kanban: karta przeszła na „Zatrudniony" (best-effort).
        if result.created_hired_stage:
            await broadcast_pipeline_changed(db, job.id, current_user_id)
        # Finanse: nowy kontraktor bez uzupełnionego zamówienia. Osoba na
        # otwartej linii zamówienia MD/kosztowego ma już zamówienie grupowe.
        # Fail-soft: podpis jest już zapisany.
        if result.order_skipped_reason != ORDER_SKIPPED_OPEN_GROUP_LINE:
            if await notify_finance_hired_without_order(db, **finance_notice):
                await db.commit()
        outcome = "created" if result.created_contract else "linked_existing"
        # Zdanie bazowe wybierane RAZ, sufiks klienta kosztowego DOKLEJANY —
        # nie nadpisujący. Wcześniej gałąź „brak zamówienia" podmieniała cały
        # komunikat, więc u Polkomtela potwierdzenie mimo różnic mówiło
        # „powiązano bez duplikatu", co czyta się jak „warunki zgodne", choć
        # stawka w kontrakcie dalej była inna niż w podpisanym dokumencie.
        if result.acknowledged_conflicts:
            message = (
                "Kontraktor już istniał — umowę powiązano, a jego dotychczasowe "
                "warunki zostały bez zmian (różnice względem dokumentu: "
                + ", ".join(result.acknowledged_conflicts)
                + "). Sprawdź kontrakt i w razie potrzeby popraw go ręcznie."
            )
        elif result.created_contract:
            contract_label = (
                "aktywny kontrakt" if contract_activated else "szkic kontraktora"
            )
            message = (
                f"Utworzono {contract_label} i szkic zamówienia."
                if result.order is not None
                else f"Utworzono {contract_label}."
            )
        else:
            message = (
                "Kontraktor już istniał — umowę powiązano bez tworzenia duplikatu."
            )
            if contract_activated:
                message += " Kontrakt jest teraz aktywny."
        if result.created_hired_stage:
            message += " Kandydata przesunięto na etap „Zatrudniony”."
        elif is_hired:
            message += " Kandydat jest na etapie „Zatrudniony”."
        else:
            message += (
                " Etapu kandydata w pipeline nie zmieniono automatycznie (brak "
                "otwartego procesu w tej rekrutacji) — przesuń go ręcznie na "
                "„Zatrudniony”."
            )
        if result.order_skipped_reason == ORDER_SKIPPED_OPEN_GROUP_LINE:
            # Osoba już na linii MD/kosztowej — inny powód i inny następny
            # krok niż u klienta kosztowego: nic nie trzeba dodawać, co
            # najwyżej poprawić istniejącą linię w zamówieniu grupowym.
            # „Otwartej", nie „żywej": linia zaplanowanej grupy jest szkicem,
            # a i tak blokuje auto-szkic okresowy (`OPEN_ORDER_STATUSES`).
            message += (
                " Zamówienia nie utworzono automatycznie: konsultant jest już "
                "obsadzony na otwartej (także zaplanowanej) linii zamówienia "
                "MD/kosztowego u tego klienta, a zamówienie okresowe obok niej "
                "byłoby drugim zapisem tej samej współpracy. W razie potrzeby "
                "edytuj linię w zamówieniu grupowym."
            )
        elif result.order is None:
            # Wariant klienta kosztowego — komunikat MUSI powiedzieć, że brak
            # zamówienia jest decyzją, nie awarią, i wskazać następny krok.
            message += (
                " Zamówienia nie utworzono automatycznie: u tego klienta typ "
                "zamówienia (kosztowe albo MD) wybiera Delivery Lead, dodając "
                "je ręcznie w zakładce Zamówienia („Nowy kontraktor / "
                "zamówienie”)."
            )
        return B2BConfirmFullySignedResponse(
            outcome=outcome,
            contract_id=result.contract.id,
            order_id=result.order.id if result.order else None,
            candidate_id=candidate_id,
            job_id=job.id,
            client_id=job.client_id,
            message=message,
            generated_contract=item,
            acknowledged_conflicts=list(result.acknowledged_conflicts),
            order_skipped_reason=result.order_skipped_reason,
        )
    except HTTPException:
        await db.rollback()
        raise
    except Exception:
        await db.rollback()
        raise


@router.patch("/generated/{generated_id}", response_model=B2BGeneratedContractItem)
async def update_generated_contract(
    generated_id: int,
    payload: B2BGeneratedContractUpdate,
    current_user: B2BGeneratorAccess,
    db: AsyncSession = Depends(get_db),
):
    """Popraw wpis na liście „Wygenerowane umowy": nazwa Klienta i/lub status.

    ``client_name`` aktualizuje zarówno kolumnę (widoczną na liście), jak i
    ``render_payload['client_name']`` — dzięki temu ponowne pobranie DOCX ma już
    poprawioną nazwę, a per-klienta klauzule (§/załączniki) dobiorą się pod nią.
    Edytować może wyłącznie autor wpisu lub administrator (jak przy usuwaniu).

    Zmiana treści dokumentu jest zablokowana po podpisaniu, ale zmiana **statusu
    handlowego** — nie: wypowiedzenie i porozumienie o rozwiązaniu dotyczą z
    definicji umów już podpisanych. Zamknięcie nie usuwa wiersza.

    **Kto co może** (dwie różne bramki, celowo):
    - ``client_name`` — autor wpisu albo admin, jak przy usuwaniu. To korekta
      TREŚCI dokumentu (synchronizuje `render_payload`), więc trzyma wąską
      bramkę.
    - ``contract_status`` — każdy, kto widzi wiersz (`B2BGeneratorAccess` +
      client-scope z `_scope_generator_query`). Kontraktora na nowy projekt
      kieruje delivery, nie osoba, która kiedyś kliknęła „generuj"; przy wąskiej
      bramce przycisk byłby niewidoczny dla większości zespołu i cała zakładka
      „Umowy bez projektu" nie miałaby jak działać."""
    _require_generated_contract_management(current_user)
    row = await db.scalar(
        select(B2BGeneratedContract)
        .where(B2BGeneratedContract.id == generated_id)
        .with_for_update()
    )
    if not row:
        raise HTTPException(status_code=404, detail="Wpis nie został znaleziony")
    await _assert_generator_client_access(
        db,
        current_user,
        row.client_id,
        write=True,
    )

    fields = payload.model_fields_set
    wants_client_name = "client_name" in fields
    wants_status = "contract_status" in fields
    if not wants_client_name and not wants_status:
        raise HTTPException(
            status_code=422,
            detail="Nie przesłano żadnej zmiany.",
        )
    # Autoryzacja PRZED regułami biznesowymi: inaczej kody odpowiedzi
    # (409 „podpisana" / 422 „zły status wyjściowy") odpowiadałyby na pytania
    # o cudzy wiersz, zanim ustalimy, że pytający ma do niego prawo.
    is_admin = current_user.has_role(UserRole.admin)
    if wants_client_name and not is_admin and row.created_by != current_user.id:
        raise HTTPException(
            status_code=403,
            detail="Nazwę Klienta może poprawić tylko autor wpisu albo administrator.",
        )
    if wants_client_name and row.source == "excel":
        _reject_excel_row(row)
    if wants_client_name and row.signature_status == "signed_both":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Podpisana umowa jest częścią historii zatrudnienia i nie może "
                "być edytowana."
            ),
        )

    if wants_client_name:
        old_client = row.client_name
        new_client = (payload.client_name or "").strip() or None
        row.client_name = new_client
        # Zsynchronizuj zapisany payload → ponowny render DOCX użyje już
        # poprawionej nazwy. Reassign (nie mutacja in-place), by SQLAlchemy
        # wykrył zmianę kolumny JSON.
        #
        # Snapshot rejestru klauzul rozstrzygamy TU PONOWNIE — i tylko tu.
        # Poza tą ścieżką jest przypięty (znalezisko: ponowne pobranie zmieniało
        # treść już wydanych umów), ale korekta nazwy Klienta to jedyny moment,
        # w którym zmienia się to, co dokument MIAŁ mówić: literówka
        # („BNP Paribass") wyłączała §4 banku, a bez re-rozstrzygnięcia poprawka
        # nazwy naprawiłaby nagłówek i zostawiła umowę bez klauzul. Bezpieczne,
        # bo ta gałąź jest zablokowana 409 dla umów podpisanych obustronnie —
        # żaden podpisany dokument nie zmienia tędy treści.
        if row.render_payload is not None:
            patch_lang = normalize_language(row.render_payload.get("language"))
            patch_key, patch_ops = resolve_override(new_client, patch_lang)
            row.render_payload = {
                **row.render_payload,
                "client_name": new_client,
                _CLAUSE_SNAPSHOT_FIELD: _clause_snapshot(
                    patch_key, patch_ops, source="client_name_patch"
                ),
            }
        else:
            patch_key = None
        db.add(
            Activity(
                entity_type="b2b_generated_contract",
                entity_id=row.id,
                action="updated",
                user_id=current_user.id,
                details={
                    "contract_number": row.contract_number,
                    "field": "client_name",
                    "old": old_client,
                    "new": new_client,
                    # Ślad audytowy: który wpis rejestru klauzul obowiązuje po
                    # korekcie (``None`` = umowa bez modyfikacji per-klient).
                    "clause_override": patch_key,
                },
            )
        )

    if wants_status:
        old_status = row.contract_status
        new_status = payload.contract_status
        # ŚWIADOMA ASYMETRIA: projektu i notatki wymaga wyłącznie powrót
        # z ZAWIESZENIA, nie każde przejście na „Aktywna".
        #
        # `suspended → active` to ZDARZENIE BIZNESOWE — kontraktor wraca do
        # pracy, więc musi być powiedziane, do czyjego projektu, a informacja
        # o poprzednim projekcie musi trafić do Kontraktów, zanim `closure_*`
        # zostaną wyczyszczone.
        #
        # `closed → active` to KOREKTA POMYŁKI — ktoś zamknął nie tę umowę.
        # Wymuszanie projektu blokowałoby cofnięcie błędnego kliknięcia
        # i zmuszało do wpisania projektu, którego może nie być. Zdarzenie
        # trafia do dziennika (niżej), więc ślad zostaje. Od 23.09.2026
        # zakładka „Zakończone umowy" ma „Zmień status”; „Aktywna” dotyczy
        # wyłącznie umów podpisanych (guard niżej), a dialog nie oferuje jej
        # dla wiersza zawieszonego.
        reactivating = new_status == "active" and old_status == "suspended"

        # „Anulowana" opisuje umowę, która NIE DOSZŁA DO SKUTKU. Podpisana
        # obustronnie doszła — jej koniec to „Zakończona". 409, nie 422: dane
        # w żądaniu są poprawne, to stan wiersza wyklucza to przejście.
        if new_status == "cancelled" and row.signature_status == "signed_both":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "Ta umowa jest podpisana obustronnie, więc doszła do "
                    "skutku — „Anulowana” opisuje umowę, która nigdy nie "
                    "zaczęła obowiązywać. Zakończ ją statusem „Zakończona”."
                ),
            )

        # Jedyny ręczny wybór „W trakcie": powrót z „Anulowanej" (Partner jednak
        # wraca do podpisu). Każde inne źródło dostaje komunikat, który do 0328
        # padał w walidatorze DTO — bez zmian dla użytkownika.
        # Drugi legalny wybór: cofnięcie pomyłkowego zamknięcia NIEPODPISANEJ
        # umowy — „Aktywna” jest dla niej zablokowana (guard niżej), a bez tej
        # ścieżki wiersz utknąłby w „Zakończonych” (audyt 23.09.2026).
        reopening_unsigned = (
            old_status == "closed" and row.signature_status != "signed_both"
        )
        if (
            new_status == "in_progress"
            and old_status != "cancelled"
            and not reopening_unsigned
        ):
            raise HTTPException(status_code=422, detail=_IN_PROGRESS_IS_AUTOMATIC)

        # Z „Anulowanej" nie ma skrótu do „Aktywnej": ta umowa jest z definicji
        # niepodpisana (guard wyżej), a `active` ustawia WYŁĄCZNIE potwierdzenie
        # podpisu obustronnego. Droga wiedzie przez „W trakcie".
        if new_status == "active" and old_status == "cancelled":
            raise HTTPException(
                status_code=422,
                detail=(
                    "Anulowaną umowę przywróć najpierw na „W trakcie” — "
                    "„Aktywna” ustawia się po potwierdzeniu podpisu "
                    "obustronnego."
                ),
            )

        # „Aktywna" znaczy „podpisana obustronnie" — ręczne przejście z każdego
        # innego stanu dawało wiersz „Aktywny i Niepodpisany” bez kontraktu,
        # zamówienia i ruchu kandydata (audyt 23.09.2026). Powrót z zawieszenia
        # dotyczy umowy, która była już aktywna, więc jest podpisana.
        if (
            new_status == "active"
            and old_status not in ("active", "suspended")
            and row.signature_status != "signed_both"
        ):
            raise HTTPException(
                status_code=422,
                detail=(
                    "Umowa nie jest podpisana obustronnie — „Aktywna” ustawia "
                    "się przyciskiem „Oznacz jako podpisaną”."
                ),
            )

        # Zawiesić można WYŁĄCZNIE umowę już obowiązującą. Bez tego guardu
        # `in_progress → suspended` byłby ślepym zaułkiem: powrót na „Aktywna"
        # wymaga powiązanego kontraktu (409 niżej), a ten powstaje dopiero przy
        # potwierdzeniu podpisu — jedynym wyjściem zostawałoby zamknięcie umowy.
        if new_status == "suspended" and old_status != "active":
            raise HTTPException(
                status_code=422,
                detail=(
                    "Zawiesić można tylko umowę aktywną. Ta ma status "
                    f"„{_STATUS_LABEL_PL.get(old_status, old_status)}”."
                ),
            )

        job: Job | None = None
        if reactivating:
            if payload.job_id is None:
                raise HTTPException(
                    status_code=422,
                    detail="Wybierz projekt, do którego wraca kontraktor.",
                )
            # 409, nie 422: to nie jest błąd w przesłanych danych, tylko stan
            # świata, który trzeba najpierw zmienić gdzie indziej.
            if row.contract_id is None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=(
                        "Ta umowa nie ma powiązanego kontraktora, więc notatka "
                        "o poprzednim projekcie nie miałaby gdzie trafić. "
                        "Najpierw oznacz umowę jako podpisaną obustronnie."
                    ),
                )
            job = await db.get(Job, payload.job_id)
            if job is None:
                raise HTTPException(
                    status_code=422, detail="Wybrany projekt nie istnieje."
                )
            # Nowy projekt może należeć do INNEGO klienta niż dotychczasowy, więc
            # dostęp trzeba sprawdzić względem klienta docelowego. Bez tego
            # delivery lead przypiąłby kontraktora do klienta spoza swojego grafu.
            await _assert_generator_client_access(
                db, current_user, job.client_id, write=True
            )
        elif "job_id" in fields:
            raise HTTPException(
                status_code=422,
                detail=(
                    "Projekt można przypisać wyłącznie przy przywracaniu "
                    "zawieszonej umowy."
                ),
            )

        # Odczyt PRZED czyszczeniem — to jedyne miejsce, w którym data i powód
        # zakończenia poprzedniego projektu jeszcze istnieją.
        prev_reason = row.closure_reason
        prev_reason_other = row.closure_reason_other
        prev_date = row.closure_date

        row.contract_status = new_status
        if new_status in B2B_CLOSING_STATUSES:
            row.closure_reason = payload.closure_reason
            row.closure_reason_other = (
                (payload.closure_reason_other or "").strip() or None
                if payload.closure_reason == "other"
                else None
            )
            row.closure_date = payload.closure_date
        else:
            # Powrót na „Aktywna" czyści komplet pól zamknięcia — inaczej
            # zostawałby osierocony powód, którego CHECK i tak by nie przepuścił.
            # Historia nie ginie: leci do dziennika niżej.
            row.closure_reason = None
            row.closure_reason_other = None
            row.closure_date = None

        if job is not None:
            row.job_id = job.id
            row.client_id = job.client_id
            # Bez gałęzi `if job.client_id` — `Job.client_id` jest NOT NULL od
            # migracji 0120, więc taki guard byłby martwym kodem udającym
            # obsłużony przypadek.
            client = await db.get(Client, job.client_id)
            if client is not None:
                row.client_name = client_display_name(client)
            # `render_payload` NIE jest synchronizowany — w odróżnieniu od
            # korekty literówki w nazwie Klienta. Tam poprawiamy to, co miało
            # być w dokumencie; tutaj zmienia się fakt handlowy, a podpisany
            # DOCX jest zapisem tego, co strony podpisały, i nie wolno go
            # przepisać pod nowego klienta.

        db.add(
            B2BGeneratedContractStatusEvent(
                generated_contract_id=row.id,
                from_status=old_status,
                to_status=new_status,
                # Przy zamknięciu/zawieszeniu zapisujemy datę NOWEGO zdarzenia,
                # przy powrocie na „Aktywna" — datę zakończenia POPRZEDNIEGO
                # projektu, bo to ona właśnie znika z wiersza.
                effective_date=(
                    row.closure_date
                    if new_status in B2B_CLOSING_STATUSES
                    else prev_date
                ),
                reason=(
                    row.closure_reason
                    if new_status in B2B_CLOSING_STATUSES
                    else prev_reason
                ),
                reason_other=(
                    row.closure_reason_other
                    if new_status in B2B_CLOSING_STATUSES
                    else prev_reason_other
                ),
                job_id=job.id if job is not None else None,
                client_id=job.client_id if job is not None else None,
                changed_by=current_user.id,
            )
        )

        if reactivating:
            db.add(
                Note(
                    contract_id=row.contract_id,
                    content=_previous_project_note(
                        prev_date, prev_reason, prev_reason_other
                    ),
                    note_type=NoteType.general,
                    author_id=current_user.id,
                )
            )
            # Przepięcie DOPIERO PO notatce — i to jest kolejność wymuszona,
            # nie kosmetyka: notatka o poprzednim projekcie musi trafić do
            # kontraktu, którego dotyczy, czyli do STAREGO `contract_id`.
            assert job is not None  # 422 wyżej dla reaktywacji bez projektu
            assert row.contract_id is not None  # 409 wyżej dla braku kontraktu
            new_contract_id = await _reactivation_contract_id(
                db, current_contract_id=row.contract_id, job=job
            )
            if new_contract_id is not None:
                row.contract_id = new_contract_id

        db.add(
            Activity(
                entity_type="b2b_generated_contract",
                entity_id=row.id,
                action="status_changed",
                user_id=current_user.id,
                details={
                    "contract_number": row.contract_number,
                    "field": "contract_status",
                    "old": old_status,
                    "new": row.contract_status,
                    "closure_reason": row.closure_reason,
                    "closure_reason_other": row.closure_reason_other,
                    "closure_date": (
                        row.closure_date.isoformat() if row.closure_date else None
                    ),
                    "job_id": row.job_id if job is not None else None,
                    # Ślad przepięcia linku do Kontraktów. Bez niego zmiana FK
                    # przy reaktywacji jest niewidoczna — a to właśnie jej brak
                    # zostawił na produkcji umowę „Bank Pocztowy" wskazującą
                    # kontrakt zupełnie innego klienta.
                    "contract_id": row.contract_id,
                },
            )
        )

    await db.commit()
    await db.refresh(row)

    return await _serialize_generated_contract(db, row, current_user)


@router.delete("/generated/{generated_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_generated_contract(
    generated_id: int,
    current_user: B2BGeneratorAccess,
    db: AsyncSession = Depends(get_db),
):
    """Usuń wpis z listy „Wygenerowane umowy".

    Może to zrobić wyłącznie autor wpisu (osoba, która wygenerowała umowę) lub
    administrator. Usunięcie NIE zwalnia numeru: wpis `deleted` w dzienniku
    trzyma go poza pulą (`_deleted_contract_numbers`), bo usunięty dokument mógł
    już trafić do Partnera (audyt 23.09.2026)."""
    async with audited_deletion(
        db,
        actor=current_user,
        event_type="b2b_agreement.delete",
        entity_type="agreement",
        entity_id=generated_id,
    ) as audit:
        _require_generated_contract_management(current_user)
        row = await db.scalar(
            select(B2BGeneratedContract)
            .where(B2BGeneratedContract.id == generated_id)
            .with_for_update()
        )
        if not row:
            raise HTTPException(status_code=404, detail="Wpis nie został znaleziony")
        # Bez nazwy Partnera (to osoba — wpis przeżywa jej usunięcie).
        audit.describe(
            label=f"Umowa B2B {row.contract_number}",
            client_id=row.client_id,
            client_name=row.client_name,
            contract_number=row.contract_number,
            signature_status=row.signature_status,
        )
        await _assert_generator_client_access(
            db,
            current_user,
            row.client_id,
            write=True,
        )
        _reject_excel_row(row)
        if row.signature_status == "signed_both":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "Podpisana umowa jest częścią historii zatrudnienia i nie może "
                    "być usunięta."
                ),
            )
        if (
            not current_user.has_role(UserRole.admin)
            and row.created_by != current_user.id
        ):
            raise HTTPException(
                status_code=403,
                detail="Możesz usunąć tylko umowy, które samodzielnie wygenerowałeś.",
            )
        number, partner, rid = row.contract_number, row.partner_name, row.id
        await db.delete(row)
        db.add(
            Activity(
                entity_type="b2b_generated_contract",
                entity_id=rid,
                action="deleted",
                user_id=current_user.id,
                details={"contract_number": number, "partner_name": partner},
            )
        )
        await db.commit()


@router.post("/check-uop", response_model=B2BUopCheckResponse)
async def check_uop(
    payload: B2BUopCheckRequest,
    current_user: B2BGeneratorAccess,
    db: AsyncSession = Depends(get_db),
):
    """AI-sprawdzenie opisu/zakresu pod kątem znamion umowy o pracę (art. 22 §1 KP).

    Zwraca wykryte ryzykowne sformułowania + bezpieczniejszą redakcję. Wymaga
    skonfigurowanego ``ANTHROPIC_API_KEY`` (inaczej 503).

    Kwota: ``AIFeatureKey.uop_check``. Ta trasa stała CAŁKOWICIE poza systemem
    kwot — zmierzone na produkcji 02.09: wywołanie trwało 15,4 s, a licznik
    w Ustawieniach → AI nie drgnął. Główny wyłącznik też jej nie dotyczył, choć
    panel obiecywał, że gasi wszystko.

    Naliczamy RAZ, choć serwis robi do dwóch round-tripów (własna pętla
    ponowienia przy nieparsowalnym JSON-ie): jednostką jest decyzja
    użytkownika, nie liczba prób, którymi system się do niej dobiera.
    """
    from app.models.ai_feature import AIFeatureKey
    from app.services.ai_quota import AIQuotaExceeded, ai_feature

    _require_contract_generation(current_user)
    text = (payload.text or "").strip()
    if not text:
        return B2BUopCheckResponse(ok=True, issues=[], rewritten="", summary="")
    try:
        async with ai_feature(db, AIFeatureKey.uop_check, user_id=current_user.id):
            # Naliczenie commitujemy PRZED wyjściem do dostawcy — liczymy
            # decyzję o dopuszczeniu, nie sukces round-tripu. Bez tego 502
            # od modelu zwracałby wywołanie za darmo, mimo wydanych tokenów.
            await db.commit()
            result = await run_in_threadpool(
                check_employment_hallmarks, text, payload.language
            )
    except AIQuotaExceeded as exc:
        await db.rollback()
        raise HTTPException(
            status_code=503,
            detail={
                "feature": exc.feature.value,
                "reason": exc.reason,
                "used": exc.used,
                "limit": exc.limit,
            },
        ) from exc
    except CVGeneratorAIError as exc:
        raise HTTPException(
            status_code=503,
            detail="Sprawdzanie AI jest chwilowo niedostępne — spróbuj ponownie później.",
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=502,
            detail="AI zwróciło nieprawidłową odpowiedź — spróbuj ponownie.",
        ) from exc
    return B2BUopCheckResponse(**result)
