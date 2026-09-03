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
    assert_contract_legal_client_access,
)
from app.api.contract_templates import _jinja_env
from app.api.contracts import _load_contract_with_relations, _render_draft_body
from app.api.deps import AdminUser, TacPlus
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
from app.models.recruitment_pipeline import CandidateStage
from app.models.user import User, UserRole
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
from app.services.b2b_contract_automation import (
    ORDER_SKIPPED_COST_CLIENT,
    ORDER_SKIPPED_OPEN_GROUP_LINE,
    ensure_b2b_employment_draft,
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


_TCM_ELEVATED_CONTRACT_ROLES = (
    UserRole.admin,
    UserRole.head_of_recruitment,
    UserRole.delivery_lead,
    UserRole.tac,
    UserRole.finance,
)


def _is_read_only_tcm(user: User) -> bool:
    """Return whether TCM is the caller's only contract-operating persona.

    Unlike Delivery order surfaces, this sourcing-side generator already
    grants HoR and TAC their own contract-operating persona. A TCM+HoR/TAC
    hybrid therefore uses that established persona; a plain TCM stays
    finance-redacted and read-only.
    """

    return user.has_role(UserRole.talent_community_manager) and not user.has_any_role(
        *_TCM_ELEVATED_CONTRACT_ROLES
    )


def _deny_tcm_contract_content(user: User) -> None:
    """Block opaque rate-bearing content while keeping safe metadata visible."""

    if _is_read_only_tcm(user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "finance_fields_forbidden",
                "fields": ["rate_candidate", "currency", "contract_document"],
            },
        )


def _deny_tcm_generated_contract_write(user: User) -> None:
    """Keep the TCM generated-contract register read-only."""

    if _is_read_only_tcm(user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "section_access_denied", "section": "delivery"},
        )


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


def _docx_response(data: bytes, contract_number: str | None) -> Response:
    """Zwróć DOCX z nazwą widoczną dla frontendu także przez CORS."""
    filename = _contract_docx_filename(contract_number)
    headers = {
        "Content-Disposition": f'attachment; filename="{filename}"',
        "Access-Control-Expose-Headers": "Content-Disposition, X-Contract-Number",
    }
    if contract_number:
        headers["X-Contract-Number"] = contract_number
    return Response(content=data, media_type=_DOCX_MEDIA, headers=headers)


# Etykiety PL statusów i powodów. Front ma własne — te NIE są ich duplikatem
# w sensie, który zwykle jest błędem: służą do zbudowania TREŚCI NOTATKI, która
# ląduje w bazie jako trwały tekst w module Kontrakty, i do komunikatów błędów.
# Notatka jest artefaktem, nie widokiem — musi być czytelna bez frontendu.
_STATUS_LABEL_PL = {
    "active": "Aktywna",
    "in_progress": "W trakcie",
    "suspended": "Zawieszona",
    "closed": "Zakończona",
}

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


def _has_signature_role(user: User) -> bool:
    return user.has_any_role(
        UserRole.admin,
        UserRole.delivery_lead,
        UserRole.tac,
    )


def _generator_unscoped(user: User) -> bool:
    """Roles that operate the generator without the client-team scope.

    Every role is a full-access generator persona except Delivery Lead
    (product decision, 20.08 — the generator is open to every role, see
    ``require_b2b_generator_access``). TAC was the original full-access
    persona (business decision): it may draft, render, list and download
    every B2B contract regardless of any ``ClientTacAssignment`` graph.
    Admin/Head of Recruitment were already unrestricted through the
    underlying resolvers. Finance/recruiter/sourcer/the legacy `user` role
    join them here for the same structural reason TAC needed this: none of
    them have any row in ``ClientTacAssignment``/
    ``DeliveryLeadClientAssignment`` to be scoped by, so leaving them off this
    list would mean they pass ``require_b2b_generator_access`` and then hit a
    permanently empty list/403 on every entity — auth without access, not a
    real access decision. Delivery Lead is deliberately excluded — it keeps
    the per-client assignment scope, unchanged by the 20.08 decision.

    Reuses ``B2B_GENERATOR_UNCONDITIONAL_ROLES`` from ``contract_access``
    instead of its own copy of the role tuple (auto-review on #1216 flagged
    the two-tuple duplication as a sync hazard: a role added to the entry
    gate but not here would silently pass auth into a permanently empty
    list). One tuple, two call sites — the entry gate and this scope check
    can no longer drift apart.
    """

    return user.has_any_role(*B2B_GENERATOR_UNCONDITIONAL_ROLES)


async def _assert_generator_client_access(
    db: AsyncSession,
    user: User,
    client_id: int | None,
    *,
    write: bool = False,
) -> None:
    """Client-entity authorization for the generator, bypassed for TAC.

    Full-access personas (see :func:`_generator_unscoped`) skip the client-team
    check entirely; everyone else falls through to the shared, relationship-aware
    :func:`assert_contract_legal_client_access` so Delivery Lead stays scoped.
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
    """Scope the generated-contracts list, unrestricted for TAC.

    A full-access TAC must see every generated contract — including ones it just
    drafted for a client it is not assigned to — so the client-team scope is not
    applied. Delivery Lead keeps its assignment-bounded view.
    """

    if _generator_unscoped(user):
        return statement
    return await apply_contract_legal_client_scope(statement, client_column, db, user)


async def _require_signature_job_scope(db: AsyncSession, user: User, job: Job) -> None:
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
        for uid in (row.created_by, row.signed_by_user_id)
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
    if _has_signature_role(current_user):
        if current_user.has_role(UserRole.admin):
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

    is_admin = current_user.has_role(UserRole.admin)
    is_read_only_tcm = _is_read_only_tcm(current_user)
    items: list[B2BGeneratedContractItem] = []
    for row in rows:
        is_signed = row.signature_status == "signed_both"
        can_manage = not is_signed and (is_admin or row.created_by == current_user.id)
        can_confirm = _has_signature_role(current_user) and not is_signed
        blocked_reason: str | None = None
        if is_signed:
            blocked_reason = "Umowa została już oznaczona jako podpisana obustronnie."
        elif not _has_signature_role(current_user):
            blocked_reason = (
                "Oznaczenie podpisu wymaga roli administratora, Delivery Lead lub TAC."
            )
            can_confirm = False
        elif row.job_id is not None and row.job_id not in scoped_job_ids:
            blocked_reason = "Brak przypisania do powiązanej rekrutacji."
            can_confirm = False

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
                # `True` bezwarunkowo, bo autoryzacja zaszła WYŻEJ: do tej listy
                # dociera wyłącznie `B2BGeneratorAccess` (admin / head of
                # recruitment / TAC / delivery lead z niepustym grafem klientów),
                # a `_scope_generator_query` zawęża ją do klientów, których
                # użytkownik prowadzi. Wcześniejsza reguła „autor albo admin"
                # była za wąska dla operacji, o którą tu chodzi: kontraktora na
                # nowy projekt kieruje delivery, nie osoba, która kiedyś
                # wygenerowała dokument — przy tamtej regule przycisk „Zmień
                # status" byłby niewidoczny dla większości zespołu, a zakładka
                # „Umowy bez projektu" nie miałaby jak działać. Korekta TREŚCI
                # dokumentu (`can_edit`) zostaje przy wąskiej bramce.
                can_change_status=not is_read_only_tcm,
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
                can_delete=can_manage and not is_read_only_tcm,
                can_edit=can_manage and not is_read_only_tcm,
                can_download=(row.render_payload is not None and not is_read_only_tcm),
                signature_status=row.signature_status,
                signature_source=row.signature_source,
                candidate_id=row.candidate_id,
                job_id=row.job_id,
                client_id=row.client_id,
                contract_id=row.contract_id,
                candidate_name=candidates.get(row.candidate_id),
                job_title=job.title if job else None,
                canonical_client_name=clients.get(row.client_id),
                signed_at=row.signed_at.isoformat() if row.signed_at else None,
                signed_by_name=users.get(row.signed_by_user_id),
                can_confirm_signed=can_confirm,
                blocked_reason=blocked_reason,
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
    # TCM may browse the operational register, but generating a document writes
    # ``rate_candidate`` and embeds it in an opaque DOCX. An additional
    # contract-operating role still contributes its normal permission.
    _deny_tcm_contract_content(current_user)
    role = await db.get(B2BContractRole, payload.role_id)
    if not role:
        raise HTTPException(status_code=404, detail="Rola nie znaleziona")
    lang = normalize_language(payload.language)
    tpl = await _b2b_template_for(db, lang)

    # 1. Utwórz lub wczytaj draft Contract (typ b2b).
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
    redact_finance = _is_read_only_tcm(current_user)
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
    _deny_tcm_contract_content(current_user)
    contract = await _load_contract_with_relations(db, contract_id, current_user)
    await _assert_generator_client_access(
        db,
        current_user,
        contract.client_id,
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


async def _next_seq(db: AsyncSession, year: int) -> int:
    """Następny numer porządkowy = max(liczbowy prefiks `contract_number`) + 1.

    Liczone z REALNYCH numerów (string „1434/2026"), NIE z kolumny `seq` (zwykły
    licznik wierszy) — dzięki temu sugestia respektuje ręcznie wpisane numery
    (kontynuacja zewnętrznej numeracji, np. 1433→1434→1435) zamiast cofać się do
    „8/2026". Duplikaty nie zawyżają wyniku (max po wartości, nie po liczbie wierszy)."""
    rows = await db.execute(
        select(B2BGeneratedContract.contract_number).where(
            B2BGeneratedContract.year == year
        )
    )
    max_seq = 0
    for (number,) in rows.all():
        parsed = _parse_seq(number, year)
        if parsed is not None and parsed > max_seq:
            max_seq = parsed
    return max_seq + 1


@router.get("/next-number", response_model=B2BNextNumberResponse)
async def next_number(
    current_user: B2BGeneratorAccess,
    db: AsyncSession = Depends(get_db),
):
    """Sugerowany kolejny WOLNY numer umowy `<seq>/<rok>` (edytowalny w UI)."""
    year = datetime.now(timezone.utc).year
    seq = await _next_seq(db, year)
    return B2BNextNumberResponse(contract_number=f"{seq}/{year}", year=year, seq=seq)


# ── Auto-uzupełnianie danych firmy z rejestru (NIP / KRS) ────────────────────


@router.get("/company-lookup", response_model=B2BCompanyLookupResponse)
async def company_lookup(
    current_user: B2BGeneratorAccess,
    nip: str | None = Query(None),
    krs: str | None = Query(None),
):
    """Dane firmy z rejestru: Biała Lista MF po NIP (JDG + spółki) lub KRS."""
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
    _deny_tcm_contract_content(current_user)
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
    suggested_seq = await _next_seq(db, default_year)
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

    db.add(
        B2BGeneratedContract(
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
    )
    try:
        await db.commit()
    except IntegrityError:
        # Race: dwa równoległe rendery z tym samym numerem przeszły SELECT-check;
        # constraint UNIQUE(year, seq) ubija drugi INSERT (migracja 0128).
        await db.rollback()
        fresh = await _next_seq(db, row_year)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Numer umowy „{number}” został właśnie użyty przez kogoś innego "
                f"— wybierz inny. Następny wolny: {fresh}/{row_year}."
            ),
        )
    context["b2b"]["contract_number"] = number

    data = await _render_docx_or_500(context, lang, override_key)
    return _docx_response(data, number)


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
    start_from: date | None = Query(
        None, description="Data rozpoczęcia usług OD (włącznie)."
    ),
    start_to: date | None = Query(
        None, description="Data rozpoczęcia usług DO (włącznie)."
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
        pattern = _like_needle(needle)
        # OUTER JOIN, bo większość wierszy nie ma dowiązanego kandydata —
        # INNER wyciąłby je z wyników wyszukiwania po numerze umowy.
        query = query.outerjoin(
            Candidate, Candidate.id == B2BGeneratedContract.candidate_id
        )
        clauses = [
            B2BGeneratedContract.contract_number.ilike(pattern, escape="\\"),
            B2BGeneratedContract.partner_name.ilike(pattern, escape="\\"),
            # Kolumna „Partner" pokazuje NAZWĘ FIRMY, więc bez tego warunku
            # wyszukiwarka nie znajduje tego, co użytkownik widzi na liście.
            B2BGeneratedContract.partner_legal_name.ilike(pattern, escape="\\"),
            B2BGeneratedContract.client_name.ilike(pattern, escape="\\"),
            Candidate.name.ilike(pattern, escape="\\"),
            Candidate.lastname.ilike(pattern, escape="\\"),
            # Pełne „Imię Nazwisko" wpisane jednym ciągiem — pojedyncze
            # kolumny wyżej same tego nie dopasują.
            func.concat(Candidate.name, " ", Candidate.lastname).ilike(
                pattern, escape="\\"
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

    # Koniunkcja z `q` i `contract_status` wychodzi sama: każdy filtr dokłada
    # własne `.where(...)`, a SQLAlchemy łączy je AND-em. Wiersze bez
    # `start_date` (historyczne, bez payloadu) WYPADAJĄ z zakresu — nieznana
    # data rozpoczęcia nie mieści się w żadnym przedziale.
    if start_from is not None:
        query = query.where(B2BGeneratedContract.start_date >= start_from)
    if start_to is not None:
        query = query.where(B2BGeneratedContract.start_date <= start_to)

    rows = list(
        (
            await db.execute(
                query.order_by(B2BGeneratedContract.created_at.desc()).limit(limit)
            )
        )
        .scalars()
        .all()
    )
    return await _serialize_generated_contracts(db, rows, current_user)


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
    _deny_tcm_contract_content(current_user)
    row = await db.get(B2BGeneratedContract, generated_id)
    if not row:
        raise HTTPException(status_code=404, detail="Wpis nie został znaleziony")
    await _assert_generator_client_access(
        db,
        current_user,
        row.client_id,
    )
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


@router.post(
    "/generated/{generated_id}/confirm-fully-signed",
    response_model=B2BConfirmFullySignedResponse,
)
async def confirm_generated_contract_fully_signed(
    generated_id: int,
    payload: B2BConfirmFullySignedRequest,
    current_user: TacPlus,
    db: AsyncSession = Depends(get_db),
):
    """One-way, audited manual confirmation with atomic employment automation."""

    try:
        row = await db.scalar(
            select(B2BGeneratedContract)
            .where(B2BGeneratedContract.id == generated_id)
            .with_for_update()
        )
        if row is None:
            raise HTTPException(status_code=404, detail="Wpis nie został znaleziony")
        # confirm-fully-signed is the audited, one-way employment automation —
        # it stays strictly client-scoped for DL/TAC even though the rest of the
        # generator is unscoped for a full-access TAC.
        if row.client_id is not None:
            await assert_contract_legal_client_access(
                db,
                current_user,
                row.client_id,
                write=True,
            )
        elif payload.job_id is None:
            await assert_contract_legal_client_access(
                db,
                current_user,
                None,
                write=True,
            )
        if payload.job_id is not None:
            await _load_legal_scoped_job(
                db,
                current_user,
                payload.job_id,
                write=True,
                strict_client_scope=True,
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
                },
            )
        )
        # Build the public projection before committing so even a serializer
        # failure rolls back the entire handoff instead of returning a 500
        # after employment was already persisted.
        await db.flush()
        item = await _serialize_generated_contract(db, row, current_user)
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
            message = (
                "Utworzono szkic kontraktora i zamówienia oraz oznaczono "
                "kandydata jako zatrudnionego."
                if result.order is not None
                else (
                    "Utworzono szkic kontraktora i oznaczono kandydata jako "
                    "zatrudnionego."
                )
            )
        else:
            message = (
                "Kontraktor już istniał — umowę powiązano bez tworzenia "
                "duplikatu, a zatrudnienie zsynchronizowano."
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
    _deny_tcm_generated_contract_write(current_user)
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
        # trafia do dziennika (niżej), więc ślad zostaje. Ta ścieżka NIE ma
        # dziś powierzchni w UI: zakładka „Zakończone umowy" jest read-only,
        # a dialog statusu nie oferuje „Aktywnej" dla wiersza zawieszonego.
        reactivating = new_status == "active" and old_status == "suspended"

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
    administrator. Usunięcie nie zwalnia numeru wstecz — sugestia kolejnego numeru
    liczona jest jako ``max(numer)+1``, więc skasowanie najnowszego wpisu pozwala
    ponownie użyć jego numeru (świadome — to log/audyt, nie rejestr nadań)."""
    _deny_tcm_generated_contract_write(current_user)
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
    if row.signature_status == "signed_both":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Podpisana umowa jest częścią historii zatrudnienia i nie może "
                "być usunięta."
            ),
        )
    if not current_user.has_role(UserRole.admin) and row.created_by != current_user.id:
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
