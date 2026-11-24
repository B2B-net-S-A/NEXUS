"""Pozycje kolejki Cpro dla bota: dane do formularza i to, czego brakuje.

Źródłem jest ta sama kolejka co okno „Do Cpro” (``board_tasks.load_snapshot``,
rodzaj ``cpro_to_send``), więc bot nie widzi niczego, czego nie widzi osoba
od Cpro, i nie bierze kart sprzed akceptacji Delivery Leada.

Brakujące Warunki (miasto, tryb pracy, narodowość, „pracował u klienta”,
dostępność) i brakujące CV bierzemy z najnowszej karty tej osoby w innej
rekrutacji tego samego klienta (decyzja Artura 17.11.2026, przypadek osoby
wrzucanej na kilka requestów Nordei bez screeningu). Pozycja mówi wtedy,
z której rekrutacji są dane.

Pozycja z brakami (``blockers``) nie idzie do bota; braki widać w kolejce,
a po uzupełnieniu w NEXUSIE następna pętla weźmie kartę sama.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Iterable, Mapping, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.candidate import Candidate
from app.models.candidate_stage_cv import CandidateStageCV
from app.models.cv_document_version import CvDocumentVersion
from app.models.job import Job
from app.models.recommendation_card import RecommendationCard
from app.models.recruitment_pipeline import CandidateStage
from app.models.user import User
from app.services import board_tasks as board
from app.services import dz_review
from app.services.action_permissions import ProductAction, has_permission
from app.services.cpro_bot import offer_text
from app.services.cpro_bot.accounts import (
    ACCOUNT_NAMES,
    IGOR_HINT,
    MARCIN_HINT,
    CproAccountName,
)
from app.services.cv_qc import _effective_sections
from app.services.effective_access import resolve_effective_access
from app.services.recommendation_card_rules import has_value, split_fields
from app.services.stage_client_rate import latest_client_rates

#: Pola Warunków, które bot czyta z karty pary, a bez nich — z innej karty
#: tej osoby u tego samego klienta.
CARD_KEYS: tuple[str, ...] = (
    "location",
    "work_mode",
    "nationality",
    "worked_at_client",
    "availability",
)

BLOCK_NOT_ACCEPTED = "Bez akceptacji Delivery Leada"
BLOCK_NO_RATE = "Brak stawki do Cpro"
BLOCK_RATE_UNIT = "Stawka nie w zł za godzinę — wrzuć ręcznie"
BLOCK_NO_REQUEST = "Rekrutacja nie ma numeru requestu Cpro"
BLOCK_NO_CV = "Brak zatwierdzonego CV firmowego"
BLOCK_QC = "QC CV ma błędy blokujące"
BLOCK_NO_WHY = "CV bez punktów „Why our candidate”"
BLOCK_NO_CITY = "Brak miasta kandydata w Warunkach"
BLOCK_NO_CITIZENSHIP = "Brak narodowości w Warunkach"
BLOCK_NO_CPRO_ACCOUNT = "Delivery Lead rekrutacji nie ma aktywnego konta Cpro bota"

# Tożsamość konta wybiera zapisany DL TEJ rekrutacji, nigdy osoba prowadząca
# kandydata, autor ruchu ani DL rekrutacji, z której pożyczamy CV/Warunki.
# Identyfikatory kont NEXUSA potwierdzone 18.11.2026; nazwy służą tylko
# poleceniu dla bota i wskazaniu wpisu Vault, nie dopasowaniu użytkownika.
CPRO_ACCOUNTS: dict[int, tuple[str, str]] = {
    14: ("Igor", IGOR_HINT),
    27: ("Marcin", MARCIN_HINT),
    # Jawne konto portalu, nie zmiana właściciela rekrutacji (24.11.2026).
    32: ("Dominik", MARCIN_HINT),
}


def cpro_account_name(account: dict) -> Optional[CproAccountName]:
    """Nazwa konta portalu ze snapshotu; nie utożsamiaj jej z prawdziwym DL."""
    lead_id = account.get("delivery_lead_id")
    expected = CPRO_ACCOUNTS.get(lead_id) if type(lead_id) is int else None
    if expected is None or account.get("vault_entry") != expected[1]:
        return None
    return ACCOUNT_NAMES.get(expected[1])


_REQUEST_NUMBER = re.compile(r"\b(\d{4,7})\b")


def request_number(client_reference: Optional[str]) -> Optional[str]:
    match = _REQUEST_NUMBER.search(client_reference or "")
    return match.group(1) if match else None


_TITLE_CLIENT = re.compile(r"^\s*[^:]{2,30}:\s*")
_TITLE_NUMBER = re.compile(r"\s*\(\s*\d{4,7}\s*\)\s*$")


def role_title(job_title: str) -> str:
    """Rola do pola „Title” imiennika: bez „Nordea: ” z przodu i numeru na końcu."""

    title = _TITLE_NUMBER.sub("", _TITLE_CLIENT.sub("", job_title or "")).strip()
    return (title or (job_title or "").strip())[:80]


def rate_text(value: float) -> str:
    """Stawka do pola „Offered rate”: ``163`` albo ``163.5``."""

    text = f"{value:.2f}".rstrip("0").rstrip(".")
    return text or "0"


def why_points_from_html(html: Optional[str]) -> list[str]:
    """Punkty sekcji „Why our candidate?” z HTML zatwierdzonej wersji CV."""

    blocks = dz_review.html_blocks(html)
    return [
        block.text
        for block, section in zip(blocks, _effective_sections(blocks))
        if section == "why_points" and block.kind != "h" and block.text.strip()
    ]


@dataclass(frozen=True)
class CvFile:
    candidate_stage_id: int
    version: int
    filename: str
    why_points: tuple[str, ...]
    job_id: int


@dataclass(frozen=True)
class BotItem:
    stage_id: int
    candidate_id: int
    job_id: int
    candidate_name: str
    process_state_version: int
    target_stage_def_id: Optional[int]
    blockers: tuple[str, ...]
    #: Pozycja dla bota (bez adresu CV — dokłada go bieg); ``None`` przy brakach.
    payload: Optional[dict[str, Any]]
    #: Rekrutacje, z których wzięto brakujące dane (numer od klienta albo tytuł).
    data_from: tuple[str, ...] = ()
    cv: Optional[CvFile] = None
    extra: dict[str, Any] = field(default_factory=dict)


def _card_fields(card: Optional[RecommendationCard]) -> dict[str, Any]:
    if card is None:
        return {}
    current, previous = split_fields(card.fields_notes or {}, card.fields_manual or {})
    return {**previous, **current}


def merge_card_values(
    own: Mapping[str, Any],
    others: Iterable[tuple[str, Mapping[str, Any]]],
) -> tuple[dict[str, Any], list[str]]:
    """Pola Warunków pary, braki z innych kart (najnowsza pierwsza).

    Zwraca (pola, etykiety rekrutacji, z których coś wzięto).
    """

    values: dict[str, Any] = {
        key: own[key] for key in CARD_KEYS if has_value(key, own.get(key))
    }
    used: list[str] = []
    for label, fields in others:
        for key in CARD_KEYS:
            if key in values or not has_value(key, fields.get(key)):
                continue
            values[key] = fields[key]
            if label not in used:
                used.append(label)
    return values, used


def build_payload(
    *,
    stage_id: int,
    first_name: str,
    last_name: str,
    job_title: str,
    job_location: Optional[str],
    remote_policy: Optional[str],
    onsite_days_per_week: Optional[int],
    request_no: Optional[str],
    rate: Optional[tuple[float, Optional[str], Optional[str]]],
    available_date: Optional[date],
    card: Mapping[str, Any],
    profile_city: Optional[str],
    cv: Optional[CvFile],
    accepted: bool,
    qc_blocking_failed: int,
    today: date,
    delivery_lead_id: Optional[int],
    delivery_lead_active: bool,
) -> tuple[tuple[str, ...], Optional[dict[str, Any]]]:
    """Braki i pozycja dla bota — czysta reguła, bez bazy."""

    blockers: list[str] = []
    account = CPRO_ACCOUNTS.get(delivery_lead_id) if delivery_lead_active else None
    if account is None:
        blockers.append(BLOCK_NO_CPRO_ACCOUNT)
    if not accepted:
        blockers.append(BLOCK_NOT_ACCEPTED)
    if rate is None or rate[0] is None:
        blockers.append(BLOCK_NO_RATE)
    elif (rate[1] or "hourly") != "hourly" or (rate[2] or "PLN").upper() != "PLN":
        blockers.append(BLOCK_RATE_UNIT)
    if request_no is None:
        blockers.append(BLOCK_NO_REQUEST)
    if cv is None:
        blockers.append(BLOCK_NO_CV)
    elif not cv.why_points:
        blockers.append(BLOCK_NO_WHY)
    if qc_blocking_failed:
        blockers.append(BLOCK_QC)
    location = card.get("location") or {}
    work_mode = card.get("work_mode") or {}
    city = offer_text.city_label(location.get("raw")) or offer_text.city_label(
        profile_city
    )
    if city is None:
        blockers.append(BLOCK_NO_CITY)
    citizenship = offer_text.citizenship((card.get("nationality") or {}).get("raw"))
    if citizenship is None:
        blockers.append(BLOCK_NO_CITIZENSHIP)
    if blockers:
        return tuple(blockers), None

    assert (
        rate is not None and cv is not None and city is not None and account is not None
    )
    when = offer_text.availability(
        today=today, available_date=available_date, card_value=card.get("availability")
    )
    former = offer_text.former_at_client(card.get("worked_at_client"))
    office = offer_text.office_city(
        work_mode.get("office_city") or location.get("raw") or profile_city,
        job_location,
    )
    days = onsite_days_per_week or work_mode.get("onsite_days_per_week")
    points = list(cv.why_points)
    payload = {
        "ref": stage_id,
        "request_number": request_no,
        "request_title": job_title,
        "cpro_account": {
            "delivery_lead_id": delivery_lead_id,
            "delivery_lead_name": account[0],
            "vault_entry": account[1],
        },
        "candidate": {
            "first_name": first_name.strip(),
            "last_name": last_name.strip(),
            "citizenship": citizenship,
            "profile_title": role_title(job_title),
            "profile_description": offer_text.motivation(points),
        },
        "offer": {
            "rate": rate_text(float(rate[0])),
            "currency": "PLN",
            "available_from": when.available_from.isoformat(),
            "physical_location": offer_text.physical_location(
                city=city,
                office=office,
                remote_policy=remote_policy,
                onsite_days_per_week=days if isinstance(days, int) else None,
                availability_phrase=when.phrase,
                former=former,
            ),
            "former_employee": former.employee,
            "former_consultant": former.consultant,
            "motivation": offer_text.motivation(points),
            "cv_file_name": offer_text.safe_filename(cv.filename),
            "cv_format": "pdf",
            "cv_version": cv.version,
        },
    }
    return (), payload


async def _accepted_movers(db: AsyncSession, mover_ids: set[int]) -> set[int]:
    if not mover_ids:
        return set()
    users = list((await db.scalars(select(User).where(User.id.in_(mover_ids)))).all())
    await resolve_effective_access(db, users)
    return {u.id for u in users if has_permission(u, ProductAction.recruitment_manage)}


async def _finalized_cvs(
    db: AsyncSession, candidate_ids: set[int], client_job_ids: set[int]
) -> dict[tuple[int, int], CvFile]:
    """Zatwierdzone CV firmowe osób w rekrutacjach klienta: (osoba, rekrutacja) → plik.

    Najnowszy zatwierdzony wiersz pary wygrywa (CV wrzucane do Cpro to to, co
    przeszło QC i akceptację, nigdy szkic „SZKIC_…”).
    """

    if not candidate_ids or not client_job_ids:
        return {}
    rows = (
        await db.execute(
            select(
                CandidateStageCV.candidate_id,
                CandidateStageCV.job_id,
                CandidateStageCV.candidate_stage_id,
                CandidateStageCV.branded_docx_filename,
                CvDocumentVersion.version,
                CvDocumentVersion.docx_filename,
                CvDocumentVersion.content_html,
            )
            .join(
                CvDocumentVersion,
                (CvDocumentVersion.candidate_stage_cv_id == CandidateStageCV.id)
                & (CvDocumentVersion.version == CandidateStageCV.branded_version),
            )
            .where(
                CandidateStageCV.candidate_id.in_(sorted(candidate_ids)),
                CandidateStageCV.job_id.in_(sorted(client_job_ids)),
                CandidateStageCV.branded_status == "finalized",
                CvDocumentVersion.docx_content.is_not(None),
            )
            .order_by(CandidateStageCV.branded_finalized_at.desc().nullslast())
        )
    ).all()
    out: dict[tuple[int, int], CvFile] = {}
    for row in rows:
        key = (row.candidate_id, row.job_id)
        if key in out:
            continue
        out[key] = CvFile(
            candidate_stage_id=row.candidate_stage_id,
            version=row.version,
            filename=offer_text.safe_filename(
                row.docx_filename or row.branded_docx_filename
            ),
            why_points=tuple(why_points_from_html(row.content_html)),
            job_id=row.job_id,
        )
    return out


def _job_label(job: Job) -> str:
    return request_number(job.client_reference) or job.title[:60]


async def load_items(
    db: AsyncSession,
    *,
    now: datetime,
    today: date,
    stage_ids: Optional[Iterable[int]] = None,
    tasks: Optional[list[board.BoardTask]] = None,
) -> list[BotItem]:
    """Pozycje kolejki Cpro (cała kolejka albo wskazane karty) z brakami.

    ``tasks`` — zadania kolejki, gdy wołający już je policzył (okno kolejki).
    """

    from app.api.board_tasks import _availability  # noqa: PLC0415 — jedno źródło dat

    wanted = set(stage_ids) if stage_ids is not None else None
    if tasks is None:
        tasks = list((await board.load_snapshot(db, now=now)).tasks)
    tasks = [
        t
        for t in tasks
        if t.kind == board.KIND_CPRO_TO_SEND
        and (wanted is None or t.stage_id in wanted)
    ]
    if not tasks:
        return []
    pairs = [(t.candidate_id, t.job_id) for t in tasks]
    candidate_ids = {t.candidate_id for t in tasks}
    rates = await latest_client_rates(db, pairs)
    dates = await _availability(db, candidate_ids)
    accepted = await _accepted_movers(
        db, {t.moved_by for t in tasks if t.moved_by is not None}
    )
    candidates = {
        c.id: c
        for c in (
            await db.scalars(
                select(Candidate).where(Candidate.id.in_(sorted(candidate_ids)))
            )
        ).all()
    }
    queue_jobs = {
        j.id: j
        for j in (
            await db.scalars(
                select(Job).where(Job.id.in_(sorted({t.job_id for t in tasks})))
            )
        ).all()
    }
    delivery_lead_ids = {
        j.delivery_lead_id
        for j in queue_jobs.values()
        if j.delivery_lead_id in CPRO_ACCOUNTS
    }
    active_delivery_lead_ids = set(
        (
            await db.scalars(
                select(User.id).where(
                    User.id.in_(sorted(delivery_lead_ids)), User.is_active.is_(True)
                )
            )
        ).all()
    )
    client_ids = {j.client_id for j in queue_jobs.values() if j.client_id is not None}
    client_jobs = {
        j.id: j
        for j in (
            await db.scalars(select(Job).where(Job.client_id.in_(sorted(client_ids))))
        ).all()
    }
    cards: dict[tuple[int, int], RecommendationCard] = {
        (card.candidate_id, card.job_id): card
        for card in (
            await db.scalars(
                select(RecommendationCard).where(
                    RecommendationCard.candidate_id.in_(sorted(candidate_ids)),
                    RecommendationCard.job_id.in_(sorted(client_jobs)),
                )
            )
        ).all()
    }
    cvs = await _finalized_cvs(db, candidate_ids, set(client_jobs))

    items: list[BotItem] = []
    for t in tasks:
        job = queue_jobs.get(t.job_id)
        person = candidates.get(t.candidate_id)
        if job is None or person is None:
            continue
        own = _card_fields(cards.get((t.candidate_id, t.job_id)))
        others = sorted(
            (
                card
                for (cand, job_id), card in cards.items()
                if cand == t.candidate_id
                and job_id != t.job_id
                and client_jobs.get(job_id) is not None
                and client_jobs[job_id].client_id == job.client_id
            ),
            key=lambda c: c.updated_at or now,
            reverse=True,
        )
        values, used = merge_card_values(
            own,
            ((_job_label(client_jobs[c.job_id]), _card_fields(c)) for c in others),
        )
        cv = cvs.get((t.candidate_id, t.job_id))
        if cv is None:
            same_client = [
                found
                for (cand, job_id), found in cvs.items()
                if cand == t.candidate_id
                and client_jobs.get(job_id) is not None
                and client_jobs[job_id].client_id == job.client_id
            ]
            if same_client:
                cv = same_client[0]
                label = _job_label(client_jobs[cv.job_id])
                if label not in used:
                    used.append(label)
        rate = rates.get((t.candidate_id, t.job_id))
        blockers, payload = build_payload(
            stage_id=t.stage_id,
            first_name=person.name,
            last_name=person.lastname,
            job_title=t.job_title,
            job_location=job.location,
            remote_policy=getattr(job.remote_policy, "value", job.remote_policy),
            onsite_days_per_week=job.onsite_days_per_week,
            request_no=request_number(job.client_reference),
            rate=rate,
            available_date=dates.get(t.candidate_id),
            card=values,
            profile_city=person.city,
            cv=cv,
            accepted=t.moved_by in accepted,
            qc_blocking_failed=t.qc_blocking_failed,
            today=today,
            delivery_lead_id=job.delivery_lead_id,
            delivery_lead_active=job.delivery_lead_id in active_delivery_lead_ids,
        )
        if payload is not None and used:
            payload["data_from"] = list(used)
        items.append(
            BotItem(
                stage_id=t.stage_id,
                candidate_id=t.candidate_id,
                job_id=t.job_id,
                candidate_name=t.candidate_name,
                process_state_version=t.process_state_version,
                target_stage_def_id=t.target_stage_def_id,
                blockers=blockers,
                payload=payload,
                data_from=tuple(used),
                cv=cv,
                extra={"delivery_lead_id": job.delivery_lead_id},
            )
        )
    return items


async def stage_still_queued(
    db: AsyncSession, stage_id: int
) -> Optional[CandidateStage]:
    """Wiersz karty, jeśli wciąż jest najnowszym wierszem pary (karta nie ruszona)."""

    stage = await db.get(CandidateStage, stage_id)
    if stage is None:
        return None
    latest = await db.scalar(
        select(CandidateStage.id)
        .where(
            CandidateStage.candidate_id == stage.candidate_id,
            CandidateStage.job_id == stage.job_id,
        )
        .order_by(CandidateStage.moved_at.desc(), CandidateStage.id.desc())
        .limit(1)
    )
    return stage if latest == stage_id else None
