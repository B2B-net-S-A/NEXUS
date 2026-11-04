"""Gotowe CV etapu z INNEJ rekrutacji tej samej osoby → szkic tej rekrutacji.

12.10.2026 (pomiar na produkcji): 16 z 22 auto-CV z dwóch tygodni powstało
dla osób, które miały już gotowe CV, a rekruter poprawiał je drugi raz.
Kopia z generatora (`select-generated` z innej rekrutacji) renderuje treść od
nowa z danych generatora, więc gubi ręczne poprawki. Tu kopiujemy CV ETAPU —
to, co rekruter zatwierdził albo zostawił w szkicu.

Reguły, które łatwo cofnąć:

* Kopia jest odłączona (bez ``generated_document_id``): nazwa pliku i wymóg
  zgody RODO liczą się z klienta rekrutacji DOCELOWEJ.
* Metadane kopii powstają z listy dozwolonych kluczy, nigdy przez przepisanie
  metadanych źródła. Skrót treści generatora dałby kopii fałszywe
  „zweryfikowane” przy zatwierdzaniu, a migawka reguł — limity cudzego klienta.
* Zrzut zgody jedzie z kopią wyłącznie przy tym samym kliencie (decyzja
  Artura 12.10.2026); zgoda dla jednego klienta nie trafia do CV dla innego.
* Tytuł w nagłówku podmieniamy tylko w treści z generatora — nagłówek pliku
  Word pochodzi z pliku i bywa samym nazwiskiem.
"""

from __future__ import annotations

import hashlib
import logging
import re
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.models.candidate import Candidate
from app.models.candidate_stage_cv import CandidateStageCV
from app.models.client import Client
from app.models.job import Job
from app.models.recruitment_pipeline import CandidateStage
from app.models.user import User
from app.services import cv_consent_gate
from app.services.candidate_stage_cv_service import (
    DetachedCopySettings,
    detached_copy_settings,
)
from app.services.cv_qc import EditableCv
from app.services.html_sanitizer import sanitize_cv_html

logger = logging.getLogger(__name__)

# Etykiety linii pod nagłówkiem (`docx_renderer.TRANSLATIONS`) — po zapisie
# w edytorze akapit traci klasę `considered`, zostaje sam tekst.
_CONSIDERED_LABELS = ("rozważany na stanowisko:", "considered for:")
_NAME_SEPARATORS = (" – ", " — ", " - ")
_H1 = re.compile(r"<h1[\s>/]", re.IGNORECASE)
_H2 = re.compile(r"<h2[\s>/]", re.IGNORECASE)
_P = re.compile(r"<p[\s>/]", re.IGNORECASE)


def _name_part(header: str) -> Optional[str]:
    """Część nagłówka po OSTATNIM łączniku („stanowisko – imię nazwisko”)."""
    cut = max(
        (header.rfind(sep) + len(sep) for sep in _NAME_SEPARATORS if sep in header),
        default=-1,
    )
    name = header[cut:].strip() if cut >= 0 else ""
    return name or None


def retitle_copied_html(
    html: str, *, title: Optional[str], blind: bool, fallback_name: Optional[str] = None
) -> str:
    """Nagłówek kopii dostaje tytuł rekrutacji docelowej; reszta bez zmian.

    Pierwsze ``<h1>`` staje się „tytuł – imię nazwisko” (CV blind: sam tytuł),
    a linia „Rozważany na stanowisko” między nagłówkiem a pierwszą sekcją
    znika — tak samo jak w kopii renderowanej z danych generatora. Imię
    i nazwisko zostaje w pisowni z nagłówka (rekruter mógł je skrócić);
    ``fallback_name`` wchodzi tylko, gdy nagłówek nie ma łącznika. Dokument
    bez ``<h1>`` wraca nietknięty.
    """
    title = (title or "").strip()
    if not title or not html:
        return html
    doc = EditableCv.parse(html)
    header: Optional[int] = None
    zone_end = len(doc.blocks)
    for index, (start, _end) in enumerate(doc.spans):
        raw = doc.tokens[start]["raw"] if start is not None else ""
        if header is None:
            if _H1.match(raw):
                header = index
        elif _H2.match(raw):
            zone_end = index
            break
    if header is None:
        return html
    start, end = doc.spans[header]
    if end is None:
        return html
    name = None if blind else _name_part(doc.blocks[header].text) or fallback_name
    doc.tokens[start + 1] = {
        "k": "data",
        "text": f"{title} – {name.strip()}" if name and name.strip() else title,
    }
    for position in range(start + 2, end):
        doc.tokens[position] = None
    for index in range(header + 1, zone_end):
        start, end = doc.spans[index]
        if start is None or end is None or not _P.match(doc.tokens[start]["raw"]):
            continue
        text = " ".join(doc.blocks[index].text.lower().split())
        if text.startswith(_CONSIDERED_LABELS):
            for position in range(start, end + 1):
                doc.tokens[position] = None
            break
    return sanitize_cv_html(doc.html())


# ── Metadane kopii odłączonej ────────────────────────────────────────────────


def job_label(job: Optional[Job]) -> Optional[str]:
    """Krótka nazwa rekrutacji do plakietki („ZOB-1725”, bez numeru — tytuł)."""
    if job is None:
        return None
    return (job.reference_number or job.title or "").strip() or None


def copy_origin(
    kind: str, *, label: Optional[str] = None, job_id: Optional[int] = None
) -> dict:
    """Skąd przyszła treść kopii — czyta to karta „CV do klienta”."""
    return {
        "kind": kind,
        "label": (label or "").strip() or None,
        "job_id": job_id,
        "selected_at": datetime.now(timezone.utc).isoformat(),
    }


def detached_metadata(
    settings: DetachedCopySettings,
    *,
    source: str,
    template: bytes,
    origin: dict,
    consent: Optional[bytes] = None,
    **details: Any,
) -> dict:
    """Metadane CV etapu bez dokumentu generatora — jedno miejsce dla każdej kopii.

    ``source`` zostaje przy dwóch wartościach, które czyta `_draft_source`:
    ``document`` (treść z pliku Word) i ``generated_other_job`` (treść
    z generatora); każda inna zrobiłaby z kopii „stary szablon” tylko do
    odczytu. Pochodzenie niesie ``origin``. Wymóg zgody klienta docelowego
    jest zamrażany tutaj — blokada pobrania (`cv_consent_gate`) czyta go
    z kopii, bo wiersza generatora nie ma.
    """
    metadata = {
        **details,
        "source": source,
        "client_id": settings.client_id,
        "template_sha256": hashlib.sha256(template).hexdigest(),
        "consent_sha256": hashlib.sha256(consent).hexdigest() if consent else None,
        "origin": origin,
    }
    if settings.requires_consent:
        metadata[cv_consent_gate.FROZEN_REQUIREMENT_KEY] = True
    return metadata


# ── CV etapu z innych rekrutacji ─────────────────────────────────────────────


def _pair_order() -> tuple:
    # Porządek „CV pary” jak w `_branded_cv_summary_for_pair`: zatwierdzone
    # wygrywa ze szkicem, w obrębie statusu — najnowszy etap.
    return (
        (CandidateStageCV.branded_status == "finalized").desc(),
        CandidateStage.moved_at.desc(),
        CandidateStage.id.desc(),
    )


def _is_legacy(from_generator: Optional[bool], metadata: Optional[dict]) -> bool:
    """Stary szablon „CV firmowe” (z e-mailem i telefonem) — nie do kopiowania."""
    return not from_generator and (metadata or {}).get("source") != "document"


async def list_reusable_stage_cvs(
    db: AsyncSession, *, candidate_id: int, target_job_id: int, user: User
) -> list[dict]:
    """Gotowe CV etapu tej osoby z INNYCH rekrutacji — jedno na rekrutację.

    Bez bajtów (szablon, zgoda, oryginał) i bez zapisu. Zakres jak przy
    każdej liście rekrutacji: tylko te, które użytkownik może czytać.
    """
    from app.api.recruitment_access import job_read_scope_clause

    target_client_id = await db.scalar(
        select(Job.client_id).where(Job.id == target_job_id)
    )
    rows = (
        await db.execute(
            select(
                CandidateStageCV.job_id,
                CandidateStageCV.candidate_stage_id,
                CandidateStageCV.branded_status,
                CandidateStageCV.branded_version,
                CandidateStageCV.branded_language,
                CandidateStageCV.branded_template,
                CandidateStageCV.branded_updated_at,
                CandidateStageCV.branded_from_generator,
                CandidateStageCV.branded_render_metadata,
                CandidateStageCV.branded_consent_content.is_not(None).label(
                    "has_consent"
                ),
                Job.title,
                Job.reference_number,
                Job.client_id,
                func.coalesce(Client.display_name, Client.name).label("client_name"),
                User.name.label("updated_by_name"),
            )
            .join(
                CandidateStage,
                CandidateStage.id == CandidateStageCV.candidate_stage_id,
            )
            .join(Job, Job.id == CandidateStageCV.job_id)
            .outerjoin(Client, Client.id == Job.client_id)
            .outerjoin(User, User.id == CandidateStageCV.branded_updated_by)
            .where(
                CandidateStageCV.candidate_id == candidate_id,
                CandidateStageCV.job_id != target_job_id,
                CandidateStageCV.branded_status.in_(("draft", "finalized")),
                func.length(func.coalesce(CandidateStageCV.branded_draft_html, "")) > 0,
                job_read_scope_clause(user, CandidateStageCV.job_id),
            )
            .order_by(CandidateStageCV.job_id, *_pair_order())
        )
    ).all()
    items: dict[int, dict] = {}
    for row in rows:
        if row.job_id in items or _is_legacy(
            row.branded_from_generator, row.branded_render_metadata
        ):
            continue
        items[row.job_id] = {
            "job_id": row.job_id,
            "stage_id": row.candidate_stage_id,
            "job_title": row.title,
            "reference_number": row.reference_number,
            "client_name": row.client_name,
            "status": row.branded_status,
            "version": row.branded_version or 1,
            "language": row.branded_language,
            "blind": row.branded_template == "blind",
            "updated_at": row.branded_updated_at,
            "updated_by_name": row.updated_by_name,
            "consent_carried": bool(
                row.has_consent
                and target_client_id is not None
                and row.client_id == target_client_id
            ),
        }
    oldest = datetime.min.replace(tzinfo=timezone.utc)
    return sorted(
        items.values(),
        key=lambda item: (item["status"] == "finalized", item["updated_at"] or oldest),
        reverse=True,
    )


async def reusable_pair_cv(
    db: AsyncSession, *, candidate_id: int, job_id: int
) -> Optional[CandidateStageCV]:
    """CV etapu pary do skopiowania (albo ``None``): ta sama reguła co lista."""
    rows = (
        await db.execute(
            select(
                CandidateStageCV.id,
                CandidateStageCV.branded_from_generator,
                CandidateStageCV.branded_render_metadata,
            )
            .join(
                CandidateStage,
                CandidateStage.id == CandidateStageCV.candidate_stage_id,
            )
            .where(
                CandidateStageCV.candidate_id == candidate_id,
                CandidateStageCV.job_id == job_id,
                CandidateStageCV.branded_status.in_(("draft", "finalized")),
                func.length(func.coalesce(CandidateStageCV.branded_draft_html, "")) > 0,
            )
            .order_by(*_pair_order())
        )
    ).all()
    for row in rows:
        if not _is_legacy(row.branded_from_generator, row.branded_render_metadata):
            return await db.get(CandidateStageCV, row.id)
    return None


def _blind_guard(source_metadata: dict, *, blind: bool, candidate) -> dict:
    """Zakaz danych osoby w CV blind jedzie z kopią (sprawdza go zatwierdzenie)."""
    terms = source_metadata.get("blind_identity_terms")
    if not blind:
        return {"blind_identity_guard": False, "blind_identity_terms": []}
    if source_metadata.get("blind_identity_guard") is True and isinstance(terms, list):
        return {"blind_identity_guard": True, "blind_identity_terms": list(terms)}
    # Kopia blind sprzed zapisu zakazu: przynajmniej imię i nazwisko osoby.
    names = [
        part.strip()
        for part in (
            getattr(candidate, "name", None),
            getattr(candidate, "lastname", None),
        )
        if isinstance(part, str) and part.strip()
    ]
    return {
        "blind_identity_guard": True,
        "blind_identity_terms": list(dict.fromkeys([" ".join(names), *names])),
    }


async def copy_stage_cv(
    db: AsyncSession,
    target: CandidateStageCV,
    source: CandidateStageCV,
    *,
    user_id: Optional[int],
    reassign: bool = False,
) -> bool:
    """CV etapu z innej rekrutacji → SZKIC ``target``. Bez commitu.

    Wołający trzyma blokadę wiersza ``target`` i sprawdził rewizję; ``source``
    jest tylko czytane (bez blokady — edytor trzyma swój wiersz i blokuje
    kandydata, więc blokada tutaj groziłaby zakleszczeniem). Zwraca, czy
    z kopią pojechał zrzut zgody.
    """
    from app.api.candidate_stage_cv import _write_stage_draft
    from app.services.cv_document_assets import default_template

    source_metadata = source.branded_render_metadata or {}
    from_document = source_metadata.get("source") == "document"
    blind = source.branded_template == "blind"
    language = source.branded_language or "pl"
    candidate = await db.get(Candidate, target.candidate_id)
    masked_name = None
    if blind:
        masked_name = "Candidate" if language == "en" else "Kandydat"
    settings = await detached_copy_settings(db, target, masked_name=masked_name)
    source_job = await db.get(Job, source.job_id)
    html = source.branded_draft_html or ""
    if not from_document:
        html = retitle_copied_html(
            html,
            title=settings.job_title,
            blind=blind,
            fallback_name=" ".join(
                part for part in (candidate.name, candidate.lastname) if part
            )
            if candidate is not None
            else None,
        )
    template = source.branded_template_content or await run_in_threadpool(
        default_template
    )
    # Decyzja Artura 12.10.2026: zrzut zgody jedzie z CV tylko w obrębie tego
    # samego klienta; zgoda dla jednego klienta nie trafia do CV dla innego.
    same_client = (
        source_job is not None
        and settings.client_id is not None
        and source_job.client_id == settings.client_id
    )
    consent = source.branded_consent_content if same_client else None
    metadata = detached_metadata(
        settings,
        source="document" if from_document else "generated_other_job",
        template=template,
        consent=consent,
        origin=copy_origin(
            "reassign" if reassign else "stage_copy",
            label=job_label(source_job),
            job_id=source.job_id,
        ),
        source_stage_cv_id=source.id,
        source_job_id=source.job_id,
        **_blind_guard(source_metadata, blind=blind, candidate=candidate),
    )
    if consent:
        metadata["consent_carried_from_stage_id"] = source.candidate_stage_id
    await _write_stage_draft(
        db,
        target,
        html=html,
        template=template,
        consent=consent,
        filename=settings.filename,
        metadata=metadata,
        blind=blind,
        language=language,
        generated_document_id=None,
        from_generator=bool(source.branded_from_generator),
        user_id=user_id,
        activity_action=(
            "branded_cv_carried_on_reassign"
            if reassign
            else "branded_cv_copied_from_other_job"
        ),
        activity_details={
            "source_stage_cv_id": source.id,
            "source_job_id": source.job_id,
            "consent_carried": bool(consent),
        },
    )
    return bool(consent)


async def carry_on_reassign(
    db: AsyncSession,
    target: CandidateStageCV,
    *,
    source_job_id: int,
    user_id: Optional[int],
) -> bool:
    """„Match” DL-a: CV z rekrutacji źródłowej jako szkic nowej. Nigdy nie rzuca.

    Match od razu wysyła osobę do klienta, więc CV jedzie z nią. Zwykłe
    przepięcie tego nie woła od 27.10.2026 (CV po trzech potwierdzeniach,
    `add_candidates_to_job`). W savepoincie: awaria kopii nie może cofnąć
    dodania osoby do rekrutacji. Wołający zrobił `flush` przed wywołaniem,
    żeby ten `except` nie połknął cudzego błędu zapisu.

    Ta sama reguła co ręczny wybór (`select-stage-cv`): treść CV powstała dla
    rekrutacji źródłowej, więc przenosi ją tylko ten, kto może ją tam czytać.
    Propozycja przepięcia powstaje dla każdej połączonej rekrutacji, a dodanie
    z „Do przejrzenia” sprawdza wyłącznie rekrutację docelową — bez tego
    warunku hak byłby drogą dookoła bramki odczytu. Odmowa i brak osoby
    działającej to „nie przenoś”, nie błąd.
    """
    from fastapi import HTTPException

    from app.api.recruitment_access import ensure_job_read_access

    if user_id is None:
        return False
    # Przed savepointem: jego wycofanie wygasza zmieniony wiersz, a odczyt
    # wygaszonego pola w `except` sam by rzucił.
    target_stage_id = target.candidate_stage_id
    try:
        async with db.begin_nested():
            if target.branded_status != "none":
                return False
            actor = await db.get(User, user_id)
            if actor is None:
                return False
            await ensure_job_read_access(db, actor, source_job_id)
            source = await reusable_pair_cv(
                db, candidate_id=target.candidate_id, job_id=source_job_id
            )
            if source is None:
                return False
            await copy_stage_cv(db, target, source, user_id=user_id, reassign=True)
            await db.flush()
        return True
    except HTTPException:
        return False
    except Exception as exc:  # noqa: BLE001 — kopia CV nigdy nie psuje przepięcia
        logger.warning(
            "[stage_cv_copy] carry skipped stage=%s source_job=%s: %s",
            target_stage_id,
            source_job_id,
            type(exc).__name__,
        )
        return False
