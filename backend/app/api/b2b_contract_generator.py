"""Generator Umów B2B — katalog ról (CRUD) + generowanie umowy + eksport DOCX.

Reużywa istniejący system draftów: po `POST /generate` powstaje `Contract`
(typ b2b, status draft) z wyrenderowanym `draft_content_html`, więc działają
istniejące endpointy draftu (edycja Tiptap, render-pdf) oraz Autenti. DOCX jest
jedynym genuinnie nowym wyjściem (eksport na oryginalnym szablonie prawnym).
"""

from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.concurrency import run_in_threadpool
from jinja2 import TemplateError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.contract_templates import _jinja_env
from app.api.contracts import _load_contract_with_relations, _render_draft_body
from app.api.deps import AdminUser, CurrentUser
from app.core.database import get_db
from app.models.activity import Activity
from app.models.b2b_contract_detail import B2BContractDetail
from app.models.b2b_contract_role import B2BContractRole
from app.models.b2b_generated_contract import B2BGeneratedContract
from app.models.contract import (
    Contract,
    ContractStatus,
    ContractType,
    RateUnit,
)
from app.models.contract_candidate_rate import ContractCandidateRate
from app.models.contract_template import ContractTemplate
from app.models.job import Job
from app.models.user import User, UserRole
from app.schemas.b2b_contract_generator import (
    B2BCompanyLookupResponse,
    B2BContractDetailResponse,
    B2BGenerateRequest,
    B2BGenerateResponse,
    B2BGeneratedContractItem,
    B2BGeneratedContractUpdate,
    B2BNextNumberResponse,
    B2BRenderHtmlResponse,
    B2BRenderRequest,
    B2BRoleCreate,
    B2BRoleResponse,
    B2BRoleUpdate,
    B2BUopCheckRequest,
    B2BUopCheckResponse,
)
from app.services.b2b_contract_generator.clause_overrides import (
    apply_ops_html,
    overrides_for_client,
)
from app.services.b2b_contract_generator.docx_renderer import (
    normalize_language,
    render_contract_docx,
    render_from_context,
)
from app.services.b2b_contract_generator.registry_lookup import lookup_company
from app.services.b2b_contract_generator.render_context import build_render_context
from app.services.b2b_contract_generator.uop_check import (
    CVGeneratorAIError,
    check_employment_hallmarks,
)

router = APIRouter()

_DOCX_MEDIA = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def _ascii_filename(name: str) -> str:
    """Transliteruj na ASCII i oczyść do bezpiecznej nazwy pliku."""
    norm = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    safe = "".join(c if c.isalnum() or c in "._-" else "_" for c in norm)
    return safe.strip("._") or "umowa"


# ── Katalog ról ──────────────────────────────────────────────────────────────


@router.get("/roles", response_model=list[B2BRoleResponse])
async def list_roles(
    current_user: CurrentUser,
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
    await db.commit()
    await db.refresh(role)
    return role


@router.get("/roles/{role_id}", response_model=B2BRoleResponse)
async def get_role(
    role_id: int,
    current_user: CurrentUser,
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
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
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
        )
        if not contract:
            raise HTTPException(status_code=404, detail="Umowa nie znaleziona")
        if contract.contract_type != ContractType.b2b:
            raise HTTPException(status_code=409, detail="To nie jest umowa B2B")
    else:
        # client_id można wyprowadzić z wybranej rekrutacji (job → klient).
        client_id = payload.client_id
        if not client_id and payload.job_id:
            job = await db.get(Job, payload.job_id)
            client_id = job.client_id if job else None
        if not payload.candidate_id or not client_id:
            raise HTTPException(
                status_code=422,
                detail="Wymagany candidate_id oraz client_id lub job_id z klientem",
            )
        contract = Contract(
            candidate_id=payload.candidate_id,
            client_id=client_id,
            job_id=payload.job_id,
            contract_type=ContractType.b2b,
            status=ContractStatus.draft,
            start_date=payload.start_date,
            rate_unit=RateUnit.hourly,
            currency=payload.currency,
        )
        db.add(contract)
        await db.flush()

    # 2. Pola finansowe/daty na Contract.
    contract.start_date = payload.start_date
    contract.rate_candidate = payload.rate_candidate
    contract.currency = payload.currency
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
    contract = await _load_contract_with_relations(db, contract.id)
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
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    contract = await _load_contract_with_relations(db, contract_id)
    d = contract.b2b_detail
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
        rate_candidate=contract.rate_candidate,
        currency=contract.currency,
        rate_in_words=d.rate_in_words if d else None,
        scope_items_override=d.role_scope_override if d else None,
    )


@router.get("/contracts/{contract_id}/docx")
async def download_docx(
    contract_id: int,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    language: str | None = Query(None),
):
    contract = await _load_contract_with_relations(db, contract_id)
    detail_lang = contract.b2b_detail.language if contract.b2b_detail else "pl"
    lang = normalize_language(language or detail_lang)
    data = await run_in_threadpool(render_contract_docx, contract, language=lang)

    cand = contract.candidate
    label = f"{cand.name}_{cand.lastname}" if cand else f"contract_{contract.id}"
    filename = _ascii_filename(f"Umowa_B2B_{label}_{lang}") + ".docx"
    return Response(
        content=data,
        media_type=_DOCX_MEDIA,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ── Numeracja umów (auto, uwzględnia wcześniej wygenerowane) ──────────────────

# Numer umowy w formacie „<liczba>/<rok>" (np. „1434/2026"). Prefiks liczbowy
# jest faktycznym numerem porządkowym — kolumna `seq` to tylko licznik wierszy.
_NUMBER_RE = re.compile(r"^\s*(\d+)\s*/\s*(\d{4})\s*$")


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
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """Sugerowany kolejny WOLNY numer umowy `<seq>/<rok>` (edytowalny w UI)."""
    year = datetime.now(timezone.utc).year
    seq = await _next_seq(db, year)
    return B2BNextNumberResponse(contract_number=f"{seq}/{year}", year=year, seq=seq)


# ── Auto-uzupełnianie danych firmy z rejestru (NIP / KRS) ────────────────────


@router.get("/company-lookup", response_model=B2BCompanyLookupResponse)
async def company_lookup(
    current_user: CurrentUser,
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
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    fmt: str = Query("docx", alias="format", pattern="^(docx|html)$"),
):
    """Generuje umowę wprost z pól formularza (tryb ręczny / standalone).

    `format=html` → podgląd (nie loguje numeru). `format=docx` → przypisuje
    numer, loguje wygenerowanie i zwraca plik DOCX.
    """
    lang = normalize_language(payload.language)
    role = await db.get(B2BContractRole, payload.role_id) if payload.role_id else None
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
        ops = overrides_for_client(payload.client_name, lang)
        if ops:
            html = apply_ops_html(html, ops)
        return B2BRenderHtmlResponse(html=html, contract_number=payload.contract_number)

    # format == docx → numer + log + plik
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
            # Zapis surowych pól → ponowne pobranie DOCX z listy (re-render).
            render_payload=payload.model_dump(mode="json"),
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

    data = await run_in_threadpool(render_from_context, context, language=lang)
    label = _ascii_filename(payload.partner_name or number)
    filename = _ascii_filename(f"Umowa_B2B_{label}_{lang}") + ".docx"
    return Response(
        content=data,
        media_type=_DOCX_MEDIA,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-Contract-Number": number,
            "Access-Control-Expose-Headers": "X-Contract-Number",
        },
    )


@router.get("/generated", response_model=list[B2BGeneratedContractItem])
async def list_generated_contracts(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    limit: int = Query(50, ge=1, le=200),
):
    """Ostatnio wygenerowane umowy (numer, partner, klient, data) — do zakładki
    „Wygenerowane umowy", by potwierdzić poprawność numeru.

    ``can_delete`` mówi UI, czy bieżący użytkownik może usunąć dany wpis (autor
    wpisu lub admin)."""
    is_admin = current_user.has_role(UserRole.admin)
    rows = (
        await db.execute(
            select(B2BGeneratedContract, User.name)
            .outerjoin(User, User.id == B2BGeneratedContract.created_by)
            .order_by(B2BGeneratedContract.created_at.desc())
            .limit(limit)
        )
    ).all()
    return [
        B2BGeneratedContractItem(
            id=r.id,
            contract_number=r.contract_number,
            partner_name=r.partner_name,
            client_name=r.client_name,
            language=r.language,
            signing_date=r.signing_date,
            created_at=r.created_at.isoformat() if r.created_at else None,
            created_by_name=creator_name,
            can_delete=is_admin or r.created_by == current_user.id,
            can_edit=is_admin or r.created_by == current_user.id,
            can_download=r.render_payload is not None,
        )
        for r, creator_name in rows
    ]


@router.get("/generated/{generated_id}/docx")
async def download_generated_contract(
    generated_id: int,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """Pobierz ponownie DOCX wygenerowanej umowy — odtworzony z zapisanego payloadu.

    Render jest deterministyczny z zapisanych pól formularza, więc dokument jest
    treściowo tożsamy z pierwotnie pobranym (numer umowy bierzemy z wiersza logu,
    nie z payloadu). Wiersze sprzed wdrożenia tej funkcji nie mają payloadu → 422
    z prośbą o ponowne wygenerowanie."""
    row = await db.get(B2BGeneratedContract, generated_id)
    if not row:
        raise HTTPException(status_code=404, detail="Wpis nie został znaleziony")
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

    data = await run_in_threadpool(render_from_context, context, language=lang)
    label = _ascii_filename(row.partner_name or row.contract_number)
    filename = _ascii_filename(f"Umowa_B2B_{label}_{lang}") + ".docx"
    return Response(
        content=data,
        media_type=_DOCX_MEDIA,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.patch("/generated/{generated_id}", response_model=B2BGeneratedContractItem)
async def update_generated_contract(
    generated_id: int,
    payload: B2BGeneratedContractUpdate,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """Popraw wpis na liście „Wygenerowane umowy" — obecnie tylko nazwę Klienta.

    Aktualizuje zarówno kolumnę ``client_name`` (widoczną na liście), jak i
    ``render_payload['client_name']`` — dzięki temu ponowne pobranie DOCX ma już
    poprawioną nazwę, a per-klienta klauzule (§/załączniki) dobiorą się pod nią.
    Edytować może wyłącznie autor wpisu lub administrator (jak przy usuwaniu)."""
    row = await db.get(B2BGeneratedContract, generated_id)
    if not row:
        raise HTTPException(status_code=404, detail="Wpis nie został znaleziony")
    is_admin = current_user.has_role(UserRole.admin)
    if not is_admin and row.created_by != current_user.id:
        raise HTTPException(
            status_code=403,
            detail="Możesz edytować tylko umowy, które samodzielnie wygenerowałeś.",
        )

    old_client = row.client_name
    new_client = (payload.client_name or "").strip() or None
    row.client_name = new_client
    # Zsynchronizuj zapisany payload → ponowny render DOCX i klauzule per-klient
    # użyją już poprawionej nazwy. Reassign (nie mutacja in-place), by SQLAlchemy
    # wykrył zmianę kolumny JSON.
    if row.render_payload is not None:
        row.render_payload = {**row.render_payload, "client_name": new_client}

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
            },
        )
    )
    await db.commit()
    await db.refresh(row)

    creator_name = None
    if row.created_by is not None:
        creator_name = await db.scalar(
            select(User.name).where(User.id == row.created_by)
        )
    can_manage = is_admin or row.created_by == current_user.id
    return B2BGeneratedContractItem(
        id=row.id,
        contract_number=row.contract_number,
        partner_name=row.partner_name,
        client_name=row.client_name,
        language=row.language,
        signing_date=row.signing_date,
        created_at=row.created_at.isoformat() if row.created_at else None,
        created_by_name=creator_name,
        can_delete=can_manage,
        can_edit=can_manage,
        can_download=row.render_payload is not None,
    )


@router.delete("/generated/{generated_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_generated_contract(
    generated_id: int,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """Usuń wpis z listy „Wygenerowane umowy".

    Może to zrobić wyłącznie autor wpisu (osoba, która wygenerowała umowę) lub
    administrator. Usunięcie nie zwalnia numeru wstecz — sugestia kolejnego numeru
    liczona jest jako ``max(numer)+1``, więc skasowanie najnowszego wpisu pozwala
    ponownie użyć jego numeru (świadome — to log/audyt, nie rejestr nadań)."""
    row = await db.get(B2BGeneratedContract, generated_id)
    if not row:
        raise HTTPException(status_code=404, detail="Wpis nie został znaleziony")
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
    current_user: CurrentUser,
):
    """AI-sprawdzenie opisu/zakresu pod kątem znamion umowy o pracę (art. 22 §1 KP).

    Zwraca wykryte ryzykowne sformułowania + bezpieczniejszą redakcję. Wymaga
    skonfigurowanego ``ANTHROPIC_API_KEY`` (inaczej 503)."""
    text = (payload.text or "").strip()
    if not text:
        return B2BUopCheckResponse(ok=True, issues=[], rewritten="", summary="")
    try:
        result = await run_in_threadpool(
            check_employment_hallmarks, text, payload.language
        )
    except CVGeneratorAIError as exc:
        raise HTTPException(
            status_code=503,
            detail="Sprawdzanie AI jest niedostępne (brak konfiguracji ANTHROPIC_API_KEY).",
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=502,
            detail="AI zwróciło nieprawidłową odpowiedź — spróbuj ponownie.",
        ) from exc
    return B2BUopCheckResponse(**result)
