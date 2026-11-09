"""Panel klienta pod linkiem z CV: token, lista osób, widoki publiczne i dla DL-a.

Reguły: ``docs/claude/klienci/panel-klienta-pod-linkiem.md``. Odpowiedzi
publiczne powstają wyłącznie z jawnych list pól w tym module, nigdy ze zrzutu
modelu: telefon, e-mail i oczekiwania kandydata nie mają tu żadnej drogi wyjścia.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import logging
import re
import secrets
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Iterable, Optional
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import defer, load_only
from starlette.concurrency import run_in_threadpool

from app.core.config import settings
from app.core.scheduling import business_date, business_today
from app.models.candidate import Candidate
from app.models.candidate_document import CandidateDocument, CandidateDocumentKind
from app.models.candidate_stage_cv import CandidateStageCV
from app.models.client import Client
from app.models.client_interview_slot_request import (
    OPEN_SLOT_STATUSES,
    ClientInterviewSlotRequest,
    all_slots_past,
)
from app.models.client_panel import (
    ClientPanel,
    ClientPanelCandidate,
    ClientPanelRequest,
    ClientPanelView,
)
from app.models.cv_document_version import CvDocumentVersion
from app.models.cv_generated_document import CvGeneratedDocument
from app.models.job import Job, JobStatus
from app.models.pipeline_template import PipelineStageDef
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.models.user import User
from app.services import client_panel_evidence as evidence_service
from app.services.board_stage_badges import board_column_for
from app.services.client_panel_schema import VIEW_ACTIONS
from app.services.client_panel_stamp import stamp_panel_link
from app.services.notes_profile_fill import availability_origin
from app.services.stage_client_rate import latest_client_rates

logger = logging.getLogger(__name__)

TOKEN_LENGTH = 16
PUBLIC_ID_LENGTH = 10
DEFAULT_VALID_DAYS = 60
MAX_VALID_DAYS = 365
ACTIVITY_LIMIT = 100
DETAIL_MAX = 120

_TOKEN_RE = re.compile(rf"^[a-z2-7]{{{TOKEN_LENGTH}}}$")
_PUBLIC_ID_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"
_CLOSED_COLUMNS = {"closed", "hired"}

MSG_NOT_FOUND = "Ten link nie istnieje albo został odwołany."
MSG_EXPIRED = "Ten link wygasł. Poproś o nowy osobę prowadzącą rekrutację."
# Ten tekst rozpoznaje ekran klienta (`panelFailureKind` w `ClientPanelApp.tsx`).
MSG_JOB_CLOSED = "Ta rekrutacja jest już zamknięta."
MSG_ENABLE_ON_CLOSED_JOB = (
    "Ta rekrutacja jest zamknięta. Link by nie działał, więc panelu nie da się włączyć."
)
MSG_PERSON_NOT_FOUND = "Nie znaleziono tej osoby w panelu."
MSG_CV_UNAVAILABLE = "CV tej osoby nie jest teraz dostępne w panelu."
MSG_FILE_NOT_FOUND = "Nie znaleziono tego pliku."


# ── Token ────────────────────────────────────────────────────────────────────


def compute_token(panel_id: int, nonce: str) -> str:
    """Token z sekretu aplikacji: da się go odtworzyć przy kolejnych CV, nie leży w bazie."""
    digest = hmac.new(
        settings.SECRET_KEY.encode(),
        f"client-panel:{panel_id}:{nonce}".encode(),
        hashlib.sha256,
    ).digest()
    # 16 znaków base32 = 80 bitów.
    return base64.b32encode(digest).decode().lower()[:TOKEN_LENGTH]


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def issue_token(panel: ClientPanel) -> str:
    """Nowy sekret linku; poprzedni przestaje działać."""
    panel.token_nonce = secrets.token_hex(16)
    token = compute_token(panel.id, panel.token_nonce)
    panel.token_sha256 = token_digest(token)
    return token


def current_token(panel: ClientPanel) -> Optional[str]:
    """Token panelu albo ``None``, gdy linku nie wydano."""
    if not panel.token_nonce:
        return None
    return compute_token(panel.id, panel.token_nonce)


def default_expiry(today: Optional[date] = None) -> datetime:
    """Koniec dnia firmy za ``DEFAULT_VALID_DAYS`` dni."""
    day = (today or business_today()) + timedelta(days=DEFAULT_VALID_DAYS)
    return datetime.combine(day, time(23, 59, 59), ZoneInfo(settings.BUSINESS_TZ))


def panel_urls(token: str, public_id: Optional[str] = None) -> tuple[str, str]:
    """(pełny adres, krótki adres do przepisania, bez schematu i osoby)."""
    base = settings.PUBLIC_BASE_URL.rstrip("/")
    full = f"{base}/k/{token}"
    parts = urlsplit(full)
    short = f"{parts.netloc}{parts.path}"
    return (f"{full}?c={public_id}" if public_id else full), short


def is_expired(panel: ClientPanel, now: Optional[datetime] = None) -> bool:
    if panel.expires_at is None:
        return False
    return panel.expires_at <= (now or datetime.now(timezone.utc))


async def load_public_panel(db: AsyncSession, token: str) -> tuple[ClientPanel, Job]:
    """Panel z linku: nieznany albo wyłączony = 404, wygasły = 410."""
    if not _TOKEN_RE.match(token or ""):
        raise HTTPException(status_code=404, detail=MSG_NOT_FOUND)
    panel = await db.scalar(
        select(ClientPanel).where(ClientPanel.token_sha256 == token_digest(token))
    )
    if panel is None or not panel.enabled:
        raise HTTPException(status_code=404, detail=MSG_NOT_FOUND)
    if is_expired(panel):
        raise HTTPException(status_code=410, detail=MSG_EXPIRED)
    job = await db.get(Job, panel.job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=MSG_NOT_FOUND)
    if job.status == JobStatus.closed:
        raise HTTPException(status_code=410, detail=MSG_JOB_CLOSED)
    return panel, job


# ── Osoby i ich CV ───────────────────────────────────────────────────────────


async def sent_pairs(db: AsyncSession, job_id: int) -> dict[int, datetime]:
    """{kandydat: pierwsza wysyłka CV}: etap „CV wysłane” za nimi, proces otwarty."""
    sent = dict(
        (
            await db.execute(
                select(CandidateStage.candidate_id, func.min(CandidateStage.moved_at))
                .where(
                    CandidateStage.job_id == job_id,
                    CandidateStage.stage == PipelineStage.cv_sent,
                )
                .group_by(CandidateStage.candidate_id)
            )
        ).all()
    )
    if not sent:
        return {}
    rows = await db.execute(
        select(
            CandidateStage.candidate_id,
            CandidateStage.stage,
            PipelineStageDef.name,
            PipelineStageDef.category,
            PipelineStageDef.terminal_type,
        )
        .outerjoin(PipelineStageDef, PipelineStageDef.id == CandidateStage.stage_def_id)
        .where(
            CandidateStage.job_id == job_id,
            CandidateStage.candidate_id.in_(sent),
        )
        .order_by(
            CandidateStage.candidate_id,
            CandidateStage.moved_at.desc(),
            CandidateStage.id.desc(),
        )
        .distinct(CandidateStage.candidate_id)
    )
    open_ids = {
        candidate_id
        for candidate_id, stage, name, category, terminal in rows.all()
        if board_column_for(
            name,
            getattr(stage, "value", stage),
            category=getattr(category, "value", category),
            terminal_type=getattr(terminal, "value", terminal),
        )
        not in _CLOSED_COLUMNS
    }
    return {cid: at for cid, at in sent.items() if cid in open_ids}


def _new_public_id() -> str:
    return "".join(secrets.choice(_PUBLIC_ID_ALPHABET) for _ in range(PUBLIC_ID_LENGTH))


async def ensure_candidate_rows(
    db: AsyncSession, panel_id: int, candidate_ids: Iterable[int]
) -> dict[int, ClientPanelCandidate]:
    """Wiersze osób panelu; brakujące dostają losowy identyfikator do linku."""
    wanted = sorted(set(candidate_ids))
    if not wanted:
        return {}
    rows = await candidate_rows(db, panel_id)
    missing = [cid for cid in wanted if cid not in rows]
    if missing:
        await db.execute(
            pg_insert(ClientPanelCandidate)
            .values(
                [
                    {
                        "panel_id": panel_id,
                        "candidate_id": cid,
                        "public_id": _new_public_id(),
                    }
                    for cid in missing
                ]
            )
            .on_conflict_do_nothing()
        )
        rows = await candidate_rows(db, panel_id)
    return rows


async def candidate_rows(
    db: AsyncSession, panel_id: int
) -> dict[int, ClientPanelCandidate]:
    found = await db.scalars(
        select(ClientPanelCandidate).where(ClientPanelCandidate.panel_id == panel_id)
    )
    return {row.candidate_id: row for row in found.all()}


@dataclass(frozen=True)
class PairCv:
    """CV firmowe pary: to samo, które daje „Pobierz” w karcie."""

    csv_id: int
    html: Optional[str]
    filename: Optional[str]
    language: str
    blind: bool
    title: Optional[str]


async def pair_cvs(
    db: AsyncSession, job_id: int, candidate_ids: Iterable[int]
) -> dict[int, PairCv]:
    """CV par jednym zapytaniem; zatwierdzone wygrywa ze szkicem, potem najnowsze.

    Ta sama kolejność co ``_branded_cv_summary_for_pair``. Same kolumny, bo
    wiersz etapu niesie bajty oryginalnego CV i obraz zgody.
    """
    wanted = sorted(set(candidate_ids))
    if not wanted:
        return {}
    rows = await db.execute(
        select(
            CandidateStageCV.id,
            CandidateStageCV.candidate_id,
            CandidateStageCV.branded_draft_html,
            CandidateStageCV.branded_docx_filename,
            CandidateStageCV.branded_language,
            CandidateStageCV.branded_template,
            CandidateStageCV.generated_document_id,
        )
        .join(CandidateStage, CandidateStage.id == CandidateStageCV.candidate_stage_id)
        .where(
            CandidateStage.job_id == job_id,
            CandidateStage.candidate_id.in_(wanted),
            CandidateStageCV.branded_status.in_(("draft", "finalized")),
        )
        .order_by(
            (CandidateStageCV.branded_status == "finalized").desc(),
            CandidateStage.moved_at.desc(),
            CandidateStage.id.desc(),
        )
    )
    chosen: dict[int, Any] = {}
    for row in rows.all():
        chosen.setdefault(row.candidate_id, row)
    generated_ids = {
        row.generated_document_id
        for row in chosen.values()
        if row.generated_document_id
    }
    generated = (
        {
            row.id: row
            for row in (
                await db.execute(
                    select(
                        CvGeneratedDocument.id,
                        CvGeneratedDocument.blind,
                        CvGeneratedDocument.render_payload,
                    ).where(CvGeneratedDocument.id.in_(generated_ids))
                )
            ).all()
        }
        if generated_ids
        else {}
    )
    out: dict[int, PairCv] = {}
    for candidate_id, row in chosen.items():
        document = generated.get(row.generated_document_id)
        payload = (
            document.render_payload
            if document is not None and isinstance(document.render_payload, dict)
            else {}
        )
        position = payload.get("position")
        out[candidate_id] = PairCv(
            csv_id=row.id,
            html=row.branded_draft_html,
            filename=row.branded_docx_filename,
            language=row.branded_language or "pl",
            blind=bool(
                row.branded_template == "blind"
                or (document is not None and document.blind)
                or payload.get("blind_cv")
            ),
            title=position if isinstance(position, str) and position.strip() else None,
        )
    return out


async def _load_people(
    db: AsyncSession, candidate_ids: Iterable[int]
) -> dict[int, Any]:
    wanted = sorted(set(candidate_ids))
    if not wanted:
        return {}
    rows = await db.execute(
        select(
            Candidate.id,
            Candidate.name,
            Candidate.lastname,
            Candidate.city,
            Candidate.availability_date,
            Candidate.cv_extracted_data,
        ).where(
            Candidate.id.in_(wanted),
            Candidate.external_deleted_at.is_(None),
        )
    )
    return {row.id: row for row in rows.all()}


def person_name(person: Any, cv: Optional[PairCv]) -> str:
    """Imię i nazwisko; przy CV blind zamaskowane jak w ``public_view``."""
    if cv is not None and cv.blind:
        return "Candidate" if cv.language == "en" else "Kandydat"
    return " ".join(p for p in (person.name, person.lastname) if p).strip()


def available_label(available_from: Optional[date], today: date) -> str:
    if available_from is None:
        return "do ustalenia"
    if available_from <= today:
        return "od zaraz"
    return f"od {available_from.strftime('%d.%m.%Y')}"


def _iso(value: Optional[date | datetime]) -> Optional[str]:
    return value.isoformat() if value is not None else None


def _day(moment: Optional[datetime]) -> Optional[str]:
    return business_date(moment).isoformat() if moment is not None else None


def _confirmed_at(person: Any) -> Optional[str]:
    """Kiedy dostępność sprawdzono: dzień z notatki, która ją wpisała."""
    origin = availability_origin(person)
    return _iso(origin.get("as_of")) if origin else None


def _rate(raw: Optional[tuple]) -> Optional[dict[str, Any]]:
    if raw is None:
        return None
    value, unit, currency = raw
    return {"value": f"{value:.2f}", "unit": unit, "currency": currency}


def _public_evidence(found: evidence_service.Evidence) -> dict[str, Any]:
    return {
        "status": found.status,
        "items": [
            {
                "kind": item.kind,
                "quote": item.quote,
                "term": item.term,
                "where": item.where,
                "dates": item.dates,
            }
            for item in found.items
        ],
    }


# ── Stan rozmowy i wątek ─────────────────────────────────────────────────────


async def _latest_slot_requests(
    db: AsyncSession, job_id: int, candidate_ids: Iterable[int]
) -> dict[int, ClientInterviewSlotRequest]:
    wanted = sorted(set(candidate_ids))
    if not wanted:
        return {}
    rows = await db.scalars(
        select(ClientInterviewSlotRequest)
        .where(
            ClientInterviewSlotRequest.job_id == job_id,
            ClientInterviewSlotRequest.candidate_id.in_(wanted),
        )
        .order_by(ClientInterviewSlotRequest.id.desc())
    )
    out: dict[int, ClientInterviewSlotRequest] = {}
    for row in rows.all():
        out.setdefault(row.candidate_id, row)
    return out


def _slots_lapsed(req: ClientInterviewSlotRequest) -> bool:
    return req.status in OPEN_SLOT_STATUSES and all_slots_past(
        req.slots or (), datetime.now(timezone.utc)
    )


def interview_block(req: Optional[ClientInterviewSlotRequest]) -> dict[str, Any]:
    if req is None:
        return {"status": "none", "slots": [], "chosen": None}
    if req.status == "cancelled":
        return {"status": "cancelled", "slots": [], "chosen": None}
    # Wszystkie terminy minęły: klient może podać nowe, serwer zastąpi ten wniosek.
    if _slots_lapsed(req):
        return {"status": "none", "slots": [], "chosen": None}
    slots = [
        {
            "start": slot.get("start"),
            "end": slot.get("end"),
            "window_end": slot.get("window_end"),
        }
        for slot in req.slots or []
    ]
    chosen = None
    # Wybór czekający na Delivery Leada nie jest jeszcze ustalonym terminem.
    if req.status == "confirmed" and req.chosen_index is not None:
        if 0 <= req.chosen_index < len(slots):
            chosen = {"start": slots[req.chosen_index]["start"]}
    return {"status": req.status, "slots": slots, "chosen": chosen}


def candidate_state(
    requests: Iterable[ClientPanelRequest],
    slot_request: Optional[ClientInterviewSlotRequest],
) -> str:
    """Stan osoby na liście klienta; najmocniejszy fakt wygrywa."""
    rows = list(requests)
    if any(row.kind == "not_fit" for row in rows):
        return "not_fit"
    if slot_request is not None:
        if slot_request.status == "confirmed":
            return "interview_confirmed"
        if slot_request.status in OPEN_SLOT_STATUSES and not _slots_lapsed(
            slot_request
        ):
            return "interview_requested"
    questions = [row for row in rows if row.kind == "question"]
    if any(row.status == "open" for row in questions):
        return "question_open"
    if any(row.status == "answered" for row in rows):
        return "answered"
    return "none"


async def _requests_by_candidate(
    db: AsyncSession, panel_id: int
) -> dict[int, list[ClientPanelRequest]]:
    rows = await db.scalars(
        select(ClientPanelRequest)
        .where(
            ClientPanelRequest.panel_id == panel_id,
            ClientPanelRequest.candidate_id.is_not(None),
        )
        .order_by(ClientPanelRequest.created_at, ClientPanelRequest.id)
    )
    out: dict[int, list[ClientPanelRequest]] = {}
    for row in rows.all():
        out.setdefault(row.candidate_id, []).append(row)
    return out


def thread_item(row: ClientPanelRequest) -> dict[str, Any]:
    return {
        "id": row.id,
        "kind": row.kind,
        "author": row.author_name,
        "at": _iso(row.created_at),
        "body": row.body,
        "answer": row.answer,
        "answered_at": _iso(row.answered_at),
    }


# ── Widoki publiczne ─────────────────────────────────────────────────────────


async def _job_title(db: AsyncSession, job: Job) -> str:
    """Nazwa roli jak w nagłówku CV, bez numeru zapytania w tytule."""
    from app.services.job_working_title import cv_role_title_for_job

    try:
        return (await cv_role_title_for_job(db, job)) or job.title
    except Exception:  # noqa: BLE001 — nazwa to dodatek, tytuł rekrutacji zawsze jest
        logger.exception("client panel: role title failed for job %s", job.id)
        return job.title


async def public_panel_view(
    db: AsyncSession, panel: ClientPanel, job: Job, focus_public_id: Optional[str]
) -> dict[str, Any]:
    requirements = evidence_service.requirements_from_job(
        job.must_skills, job.nice_skills
    )
    sent = await sent_pairs(db, job.id)
    rows = await ensure_candidate_rows(db, panel.id, sent)
    visible = [
        cid
        for cid in sent
        if cid in rows
        and not rows[cid].hidden
        and (panel.show_other_candidates or rows[cid].public_id == focus_public_id)
    ]
    people = await _load_people(db, visible)
    cvs = await pair_cvs(db, job.id, visible)
    rates = (
        await latest_client_rates(db, [(cid, job.id) for cid in visible])
        if panel.show_rate
        else {}
    )
    slot_requests = await _latest_slot_requests(db, job.id, visible)
    requests = await _requests_by_candidate(db, panel.id)
    today = business_today()
    candidates = []
    for cid in sorted(visible, key=lambda c: sent[c]):
        person = people.get(cid)
        if person is None:
            continue
        cv = cvs.get(cid)
        found = evidence_service.evidence_map(
            cv.html if cv else None, requirements, rows[cid].rejected_evidence or ()
        )
        in_projects, on_list, missing = evidence_service.counts(found)
        candidates.append(
            {
                "public_id": rows[cid].public_id,
                "name": person_name(person, cv),
                "title": cv.title if cv else None,
                "city": person.city,
                "available_from": _iso(person.availability_date),
                "available_label": available_label(person.availability_date, today),
                "available_confirmed_at": _confirmed_at(person),
                "rate": _rate(rates.get((cid, job.id))),
                "statuses": {key: item.status for key, item in found.items()},
                "in_projects": in_projects,
                "on_list": on_list,
                "missing": missing,
                "sent_at": _day(sent[cid]),
                "state": candidate_state(requests.get(cid, ()), slot_requests.get(cid)),
            }
        )
    client = await db.get(Client, job.client_id) if job.client_id else None
    owner = await db.get(User, job.delivery_lead_id) if job.delivery_lead_id else None
    return {
        "panel": {
            "expires_at": _iso(panel.expires_at),
            "show_rate": panel.show_rate,
            "allow_actions": panel.allow_actions,
            "show_other_candidates": panel.show_other_candidates,
        },
        "job": {
            "title": await _job_title(db, job),
            "reference": job.client_reference,
            "client_name": (client.name or client.display_name) if client else None,
            "request_text": job.description,
            "added_at": _day(job.created_at),
            "work_mode": getattr(job.remote_policy, "value", job.remote_policy),
            "location": job.location,
            "deadline": _iso(job.deadline),
        },
        "owner": {"name": owner.name if owner is not None else None},
        "requirements": [{"key": r.key, "label": r.label} for r in requirements],
        "candidates": candidates,
    }


@dataclass(frozen=True)
class VisiblePerson:
    candidate_id: int
    row: ClientPanelCandidate
    person: Any
    cv: Optional[PairCv]


async def visible_person(
    db: AsyncSession, panel: ClientPanel, job: Job, public_id: str
) -> VisiblePerson:
    """Osoba pod ``public_id``; ukryta, zamknięta albo cudza = 404."""
    row = await db.scalar(
        select(ClientPanelCandidate).where(
            ClientPanelCandidate.panel_id == panel.id,
            ClientPanelCandidate.public_id == public_id,
        )
    )
    if (
        row is None
        or row.hidden
        or row.candidate_id not in await sent_pairs(db, job.id)
    ):
        raise HTTPException(status_code=404, detail=MSG_PERSON_NOT_FOUND)
    person = (await _load_people(db, [row.candidate_id])).get(row.candidate_id)
    if person is None:
        raise HTTPException(status_code=404, detail=MSG_PERSON_NOT_FOUND)
    cv = (await pair_cvs(db, job.id, [row.candidate_id])).get(row.candidate_id)
    return VisiblePerson(row.candidate_id, row, person, cv)


async def _downloadable_cv_row(
    db: AsyncSession, cv: Optional[PairCv]
) -> Optional[tuple[CandidateStageCV, Optional[CvDocumentVersion]]]:
    """Wiersz CV, który wolno wydać: bez zgody RODO klienta pliku nie ma."""
    from app.services import cv_consent_gate as consent_gate

    if cv is None:
        return None
    # Bez bajtów oryginalnego CV: panel go nie wydaje.
    csv = await db.scalar(
        select(CandidateStageCV)
        .options(defer(CandidateStageCV.original_cv_content))
        .where(CandidateStageCV.id == cv.csv_id)
    )
    if csv is None:
        return None
    version = None
    if csv.branded_status == "finalized":
        version = await db.scalar(
            select(CvDocumentVersion).where(
                CvDocumentVersion.candidate_stage_cv_id == csv.id,
                CvDocumentVersion.version == csv.branded_version,
            )
        )
        if version is None or not version.docx_content:
            return None
    generated = (
        await db.scalar(
            select(CvGeneratedDocument)
            .options(load_only(CvGeneratedDocument.central_policy))
            .where(CvGeneratedDocument.id == csv.generated_document_id)
        )
        if csv.generated_document_id
        else None
    )
    try:
        consent_gate.ensure_copy_downloadable(generated, csv, version)
    except HTTPException:
        return None
    return csv, version


def _pdf_name(cv: PairCv) -> str:
    if cv.blind or not cv.filename:
        return "CV.pdf"
    return f"{cv.filename.rsplit('.', 1)[0]}.pdf"


async def _shared_documents(
    db: AsyncSession, visible: VisiblePerson
) -> list[CandidateDocument]:
    """Pliki w panelu: tylko wskazane przez DL-a, bo rodzaj dokumentu ustawia ręcznie rekruter."""
    shared = {int(i) for i in visible.row.shared_document_ids or []}
    if not shared:
        return []
    rows = await db.scalars(
        select(CandidateDocument)
        .where(
            CandidateDocument.candidate_id == visible.candidate_id,
            CandidateDocument.removed_at.is_(None),
            CandidateDocument.source_deleted_at.is_(None),
            CandidateDocument.outdated_at.is_(None),
        )
        .order_by(CandidateDocument.id)
    )
    return [doc for doc in rows.all() if doc.id in shared]


async def public_candidate_view(
    db: AsyncSession, panel: ClientPanel, job: Job, token: str, visible: VisiblePerson
) -> dict[str, Any]:
    cid, person, cv = visible.candidate_id, visible.person, visible.cv
    public_id = visible.row.public_id
    requirements = evidence_service.requirements_from_job(
        job.must_skills, job.nice_skills
    )
    found = evidence_service.evidence_map(
        cv.html if cv else None, requirements, visible.row.rejected_evidence or ()
    )
    rates = await latest_client_rates(db, [(cid, job.id)]) if panel.show_rate else {}
    today = business_today()
    base = f"/api/public/panel/{token}/candidates/{public_id}"
    downloadable = await _downloadable_cv_row(db, cv)
    thread = (await _requests_by_candidate(db, panel.id)).get(cid, [])
    slot_request = (await _latest_slot_requests(db, job.id, [cid])).get(cid)
    return {
        "public_id": public_id,
        "name": person_name(person, cv),
        "cv": {
            "available": downloadable is not None,
            "filename": _pdf_name(cv) if cv and downloadable else None,
            "url": f"{base}/cv.pdf" if downloadable else None,
        },
        "evidence": {key: _public_evidence(item) for key, item in found.items()},
        "terms": {
            "rate": _rate(rates.get((cid, job.id))),
            "available_label": available_label(person.availability_date, today),
            "available_confirmed_at": _confirmed_at(person),
            "city": person.city,
        },
        "files": [
            {
                "id": doc.id,
                "name": doc.filename,
                "kind": getattr(doc.document_kind, "value", doc.document_kind),
                "url": f"{base}/files/{doc.id}",
            }
            for doc in await _shared_documents(db, visible)
        ],
        "thread": [thread_item(row) for row in thread],
        "interview": interview_block(slot_request),
    }


async def candidate_pdf(db: AsyncSession, visible: VisiblePerson) -> tuple[bytes, str]:
    """PDF dokładnie tego CV, które daje „Pobierz”: bez ramki z linkiem."""
    from app.services.candidate_stage_cv_service import render_stage_editor_docx
    from app.services.cv_pdf_preview import PdfPreviewUnavailable, pdf_from_docx

    downloadable = await _downloadable_cv_row(db, visible.cv)
    if downloadable is None or visible.cv is None:
        raise HTTPException(status_code=404, detail=MSG_CV_UNAVAILABLE)
    csv, version = downloadable
    if version is not None:
        docx = version.docx_content
    else:
        docx, _ = await render_stage_editor_docx(csv, csv.branded_draft_html or "")
    name = _pdf_name(visible.cv)
    # Zamiana trwa sekundy: bez blokad i połączenia z bazą (jak `cv_pdf_preview`).
    await db.commit()
    try:
        return await pdf_from_docx(docx), name
    except PdfPreviewUnavailable as error:
        raise HTTPException(
            status_code=503,
            detail="Podgląd CV jest chwilowo niedostępny. Spróbuj za chwilę.",
        ) from error


async def shared_document_bytes(
    db: AsyncSession, visible: VisiblePerson, document_id: int
) -> tuple[bytes, CandidateDocument]:
    document = next(
        (d for d in await _shared_documents(db, visible) if d.id == document_id), None
    )
    if document is None:
        raise HTTPException(status_code=404, detail=MSG_FILE_NOT_FOUND)
    if document.storage_key:
        from app.services.object_storage import download_cv, is_available

        if is_available():
            return await asyncio.to_thread(download_cv, document.storage_key), document
    await db.refresh(document, attribute_names=["file_content"])
    if not document.file_content:
        raise HTTPException(status_code=404, detail=MSG_FILE_NOT_FOUND)
    return document.file_content, document


# ── Dziennik wejść ───────────────────────────────────────────────────────────


def hash_ip(ip: str, day: Optional[date] = None) -> str:
    """SHA-256 z IP i soli dnia: ta sama osoba jest tą samą tylko przez dobę."""
    salt = hmac.new(
        settings.SECRET_KEY.encode(),
        f"client-panel-view:{(day or business_today()).isoformat()}".encode(),
        hashlib.sha256,
    ).hexdigest()
    return hashlib.sha256(f"{salt}:{ip}".encode()).hexdigest()


async def log_view(
    db: AsyncSession,
    *,
    panel_id: int,
    action: str,
    ip: str,
    candidate_id: Optional[int] = None,
    detail: Optional[str] = None,
) -> None:
    """Wpis dziennika, zawsze best-effort: nie zatrzymuje odpowiedzi."""
    if action not in VIEW_ACTIONS:
        return
    try:
        async with db.begin_nested():
            db.add(
                ClientPanelView(
                    panel_id=panel_id,
                    candidate_id=candidate_id,
                    action=action,
                    detail=(detail or "")[:DETAIL_MAX] or None,
                    ip_hash=hash_ip(ip),
                )
            )
            await db.flush()
    except Exception:  # noqa: BLE001 — dziennik nie może wywrócić panelu
        logger.exception("client panel: view log failed for panel %s", panel_id)


# ── Widok dla Delivery Leada ─────────────────────────────────────────────────


async def panel_for_job(db: AsyncSession, job_id: int) -> Optional[ClientPanel]:
    return await db.scalar(select(ClientPanel).where(ClientPanel.job_id == job_id))


async def get_or_create_panel(
    db: AsyncSession, job_id: int, user_id: Optional[int]
) -> ClientPanel:
    await db.execute(
        pg_insert(ClientPanel)
        .values(job_id=job_id, created_by=user_id)
        .on_conflict_do_nothing(index_elements=[ClientPanel.job_id])
    )
    panel = await panel_for_job(db, job_id)
    assert panel is not None  # wiersz założony albo istniał przed chwilą
    return panel


def _weak_items(
    found: dict[str, evidence_service.Evidence],
    requirements: list[evidence_service.Requirement],
) -> list[dict[str, Any]]:
    labels = {req.key: req.label for req in requirements}
    return [
        {
            "key": key,
            "label": labels[key],
            "quote": item.items[0].quote if item.items else None,
            "where": item.items[0].where if item.items else None,
        }
        for key, item in found.items()
        if item.weak
    ]


async def _shareable_documents(
    db: AsyncSession, candidate_ids: Iterable[int]
) -> dict[int, list[dict[str, Any]]]:
    """Pliki osoby, które DL może wskazać klientowi; CV idzie osobną drogą."""
    wanted = sorted(set(candidate_ids))
    if not wanted:
        return {}
    rows = await db.execute(
        select(
            CandidateDocument.id,
            CandidateDocument.candidate_id,
            CandidateDocument.filename,
            CandidateDocument.document_kind,
        )
        .where(
            CandidateDocument.candidate_id.in_(wanted),
            CandidateDocument.document_kind != CandidateDocumentKind.cv,
            CandidateDocument.removed_at.is_(None),
            CandidateDocument.source_deleted_at.is_(None),
            CandidateDocument.outdated_at.is_(None),
        )
        .order_by(CandidateDocument.id.desc())
    )
    found: dict[int, list[dict[str, Any]]] = {}
    for row in rows.all():
        found.setdefault(row.candidate_id, []).append(
            {"id": row.id, "name": row.filename, "kind": row.document_kind.value}
        )
    return found


async def admin_view(db: AsyncSession, job: Job) -> dict[str, Any]:
    panel = await panel_for_job(db, job.id)
    requirements = evidence_service.requirements_from_job(
        job.must_skills, job.nice_skills
    )
    sent = await sent_pairs(db, job.id)
    rows = await ensure_candidate_rows(db, panel.id, sent) if panel else {}
    people = await _load_people(db, sent)
    cvs = await pair_cvs(db, job.id, sent)
    documents = await _shareable_documents(db, sent)
    candidates = []
    for cid in sorted(sent, key=lambda c: sent[c]):
        person = people.get(cid)
        if person is None:
            continue
        row = rows.get(cid)
        cv = cvs.get(cid)
        rejected = list(row.rejected_evidence or ()) if row else []
        found = evidence_service.evidence_map(
            cv.html if cv else None, requirements, rejected
        )
        in_projects, on_list, missing = evidence_service.counts(found)
        candidates.append(
            {
                "candidate_id": cid,
                # DL widzi prawdziwe imię; maska blind dotyczy tylko klienta.
                "name": " ".join(
                    p for p in (person.name, person.lastname) if p
                ).strip(),
                "public_id": row.public_id if row else None,
                "hidden": row.hidden if row else False,
                "in_projects": in_projects,
                "on_list": on_list,
                "missing": missing,
                "weak": _weak_items(found, requirements),
                "rejected_evidence": rejected,
                "shared_document_ids": (
                    list(row.shared_document_ids or ()) if row else []
                ),
                "documents": documents.get(cid, []),
            }
        )
    token = current_token(panel) if panel and panel.enabled else None
    url, short_url = panel_urls(token) if token else (None, None)
    total, last_at, people_count = (0, None, 0)
    open_requests = 0
    if panel is not None:
        total, last_at, people_count = (
            await db.execute(
                select(
                    func.count(ClientPanelView.id),
                    func.max(ClientPanelView.created_at),
                    func.count(func.distinct(ClientPanelView.ip_hash)),
                ).where(ClientPanelView.panel_id == panel.id)
            )
        ).one()
        open_requests = (
            await db.scalar(
                select(func.count(ClientPanelRequest.id)).where(
                    ClientPanelRequest.panel_id == panel.id,
                    ClientPanelRequest.status == "open",
                )
            )
        ) or 0
    return {
        "job_closed": job.status == JobStatus.closed,
        "enabled": bool(panel and panel.enabled),
        "show_rate": panel.show_rate if panel else True,
        "show_other_candidates": panel.show_other_candidates if panel else True,
        "allow_actions": panel.allow_actions if panel else True,
        "expires_at": _iso(panel.expires_at) if panel else None,
        "url": url,
        "short_url": short_url,
        "candidates": candidates,
        "views": {"total": total, "last_at": _iso(last_at), "people": people_count},
        "requests_open": open_requests,
    }


async def activity(db: AsyncSession, job_id: int) -> list[dict[str, Any]]:
    """Ostatnie wejścia, czytelnie; skrót IP zostaje w bazie."""
    panel = await panel_for_job(db, job_id)
    if panel is None:
        return []
    rows = await db.execute(
        select(
            ClientPanelView.created_at,
            ClientPanelView.action,
            ClientPanelView.detail,
            Candidate.name,
            Candidate.lastname,
        )
        .outerjoin(Candidate, Candidate.id == ClientPanelView.candidate_id)
        .where(ClientPanelView.panel_id == panel.id)
        .order_by(ClientPanelView.created_at.desc(), ClientPanelView.id.desc())
        .limit(ACTIVITY_LIMIT)
    )
    return [
        {
            "at": _iso(row.created_at),
            "action": row.action,
            "detail": row.detail,
            "candidate_name": (
                " ".join(p for p in (row.name, row.lastname) if p).strip() or None
            ),
        }
        for row in rows.all()
    ]


# ── Ramka w pobieranym pliku ─────────────────────────────────────────────────


async def stamp_for_download(
    db: AsyncSession,
    *,
    job_id: Optional[int],
    candidate_id: Optional[int],
    docx: bytes,
    language: Optional[str] = None,
) -> bytes:
    """Plik z ramką panelu, gdy panel rekrutacji działa; inaczej bez zmian.

    Zapisane bajty dokumentu zostają nietknięte. Żadna awaria nie zatrzymuje
    pobrania: najwyżej plik wychodzi bez ramki.
    """
    if not job_id or not candidate_id:
        return docx
    try:
        # Savepoint, nie rollback: pełne wycofanie wygasiłoby obiekty trasy,
        # która po tej funkcji czyta jeszcze nazwę pliku.
        async with db.begin_nested():
            panel = await panel_for_job(db, job_id)
            if panel is None or not panel.enabled or is_expired(panel):
                return docx
            job = await db.get(Job, job_id)
            if job is None or job.status == JobStatus.closed:
                return docx
            token = current_token(panel)
            if token is None:
                return docx
            rows = await ensure_candidate_rows(db, panel.id, [candidate_id])
            public_id = rows[candidate_id].public_id
            expires_at = panel.expires_at
        await db.commit()
    except Exception:  # noqa: BLE001 — ramka to dodatek do pliku
        logger.exception("client panel: stamp lookup failed for job %s", job_id)
        return docx
    url, short_url = panel_urls(token, public_id)
    return await run_in_threadpool(
        stamp_panel_link, docx, url, short_url, expires_at, language=language or "pl"
    )
