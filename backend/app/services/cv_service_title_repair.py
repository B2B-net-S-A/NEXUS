"""Jednorazowo: CV etapu z nazwą usługi w nagłówku i nazwie pliku (03.11.2026).

Do #2872 CV z rekrutacji PKO nazwanych przedmiotem usługi dostawały nagłówek
„usługi programistyczne – Imię Nazwisko” i plik „ZOB-3156_usługi programistyczne_…”.
Poprawka kodu nie zmienia gotowych dokumentów. Decyzja Artura: objąć wszystkie CV
w otwartych rekrutacjach, także zatwierdzone i z etapu „Rozmowa”.

- Zły nagłówek w szkicu: podmiana nazwy w ``<h1>`` i w nazwie pliku.
- Zły nagłówek w CV zatwierdzonym: zatwierdzona wersja zostaje zamrożona bez zmian,
  jak przy „Nowej wersji”, a nowy szkic czeka na zatwierdzenie człowieka.
- Dobry nagłówek (człowiek go poprawił, plik z profilu): tylko nazwa pliku, także na
  zamrożonych wersjach. Treści i sum kontrolnych nie rusza, więc bez zatwierdzania.
  Plik dostaje nazwę z nagłówka, żeby oba mówiły to samo.

Bez roli w Championie nagłówek zostaje. Nazwa pliku ustawiona ręcznie zostaje.
Wiersze ``cv_generated_documents`` zostają historią generacji. Stare wartości są
w ``activities``, a paragon ma same liczby (repo i logi są publiczne).

Marker w ``app_settings`` + advisory lock → drugi start kończy się od razu. Ponad
``MAX_ROWS`` krok niczego nie zmienia i nie stawia markera: zgoda była na 29 CV.
"""

from __future__ import annotations

import html as html_lib
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.activity import Activity
from app.models.app_setting import AppSetting
from app.models.candidate_stage_cv import CandidateStageCV
from app.models.cv_document_version import CvDocumentVersion
from app.models.job import Job

MARKER = "cv_service_title_repair_2026_11"
MAX_ROWS = 40
_H1 = re.compile(r"<h1>([^<]*)</h1>")
_FILENAME = re.compile(r"^(ZOB[^_]*_)(.+)(_[^_]+\.docx)$")
_RESERVED = re.compile(r'[\\/:*?"<>|\x00-\x1f]')
_NAME_SEPARATOR = " – "


@dataclass(frozen=True)
class Planned:
    html: Optional[str]
    filename: Optional[str]
    old_position: Optional[str]
    new_position: Optional[str]


def planned_change(
    html: Optional[str],
    filename: Optional[str],
    role: str,
    *,
    blind: bool,
    custom_filename: bool,
) -> Optional[Planned]:
    """Co zmienić w CV etapu; ``None`` = nic. Bez bazy, żeby liczyć to w teście."""
    from app.services.job_working_title import is_service_title

    role_usable = bool(role) and not is_service_title(role)
    new_html = None
    final_position = None
    old_position = None
    match = _H1.search(html or "")
    if match:
        inner = match.group(1)
        position_raw, name_part = inner, ""
        if not blind and _NAME_SEPARATOR in inner:
            head, tail = inner.rsplit(_NAME_SEPARATOR, 1)
            position_raw, name_part = head, f"{_NAME_SEPARATOR}{tail}"
        position = html_lib.unescape(position_raw).strip()
        final_position = position
        if is_service_title(position):
            final_position = None
            if role_usable:
                old_position = position
                final_position = role
                header = f"{html_lib.escape(role, quote=False)}{name_part}"
                new_html = f"{html[: match.start(1)]}{header}{html[match.end(1) :]}"
    elif role_usable:
        final_position = role

    new_filename = None
    parts = _FILENAME.match(filename or "")
    if (
        parts
        and final_position
        and not custom_filename
        and is_service_title(parts.group(2))
    ):
        clean = re.sub(r"\s+", " ", _RESERVED.sub("", final_position)).strip()
        new_filename = f"{parts.group(1)}{clean}{parts.group(3)}"
    if new_html is None and new_filename is None:
        return None
    return Planned(new_html, new_filename, old_position, final_position)


async def _plan(db: AsyncSession) -> list[tuple[int, Planned]]:
    from app.services.job_working_title import cv_role_title_for_job

    rows = (
        await db.execute(
            select(
                CandidateStageCV.id,
                CandidateStageCV.job_id,
                CandidateStageCV.branded_draft_html,
                CandidateStageCV.branded_docx_filename,
                CandidateStageCV.branded_template,
                CandidateStageCV.branded_render_metadata,
            )
            .join(Job, Job.id == CandidateStageCV.job_id)
            .where(
                Job.status == "published",
                CandidateStageCV.branded_docx_filename.op("~*")("_us[łl]ug"),
            )
            .order_by(CandidateStageCV.id)
        )
    ).all()
    roles: dict[int, str] = {}
    planned: list[tuple[int, Planned]] = []
    for row in rows:
        if row.job_id not in roles:
            roles[row.job_id] = await cv_role_title_for_job(
                db, await db.get(Job, row.job_id)
            )
        change = planned_change(
            row.branded_draft_html,
            row.branded_docx_filename,
            roles[row.job_id],
            blind=row.branded_template == "blind",
            custom_filename=bool(
                (row.branded_render_metadata or {}).get("custom_filename")
            ),
        )
        if change is not None:
            planned.append((row.id, change))
    return planned


def _receipt_key(status: Optional[str], change: Planned) -> str:
    if change.html is None:
        return (
            "filename_only_finalized"
            if status == "finalized"
            else "filename_only_draft"
        )
    return "new_draft_to_approve" if status == "finalized" else "draft_header"


async def repair_service_title_cvs(
    db: AsyncSession, *, apply: bool = True
) -> Optional[dict[str, Any]]:
    """Popraw CV etapu albo, przy ``apply=False``, tylko policz. Wołający commituje."""
    from app.services.cv_document_versions import freeze_approved_version

    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:key))"), {"key": MARKER}
    )
    if await db.get(AppSetting, MARKER):
        return None
    planned = await _plan(db)
    receipt: dict[str, Any] = {
        "planned": len(planned),
        "draft_header": 0,
        "new_draft_to_approve": 0,
        "filename_only_draft": 0,
        "filename_only_finalized": 0,
        "versions_renamed": 0,
    }
    if len(planned) > MAX_ROWS:
        return {**receipt, "aborted_over_limit": True}
    versions = CvDocumentVersion.__table__
    for csv_id, change in planned:
        query = select(CandidateStageCV).where(CandidateStageCV.id == csv_id)
        if apply:
            query = query.with_for_update()
        csv = await db.scalar(query)
        status = csv.branded_status
        receipt[_receipt_key(status, change)] += 1
        if not apply:
            continue
        old_filename = csv.branded_docx_filename
        reopened = change.html is not None and status == "finalized"
        if reopened:
            await freeze_approved_version(db, csv, docx_filename=old_filename)
            csv.branded_version += 1
            csv.branded_status = "draft"
            csv.branded_finalized_at = None
            csv.branded_finalized_by = None
            csv.branded_snapshot_path = None
            csv.branded_snapshot_filename = None
            csv.branded_snapshot_size_bytes = None
        if change.html is not None:
            csv.branded_draft_html = change.html
            csv.edit_revision = (csv.edit_revision or 0) + 1
            csv.branded_updated_at = datetime.now(timezone.utc)
        if change.filename is not None:
            csv.branded_docx_filename = change.filename
            # Wersja ze starym nagłówkiem zostaje ze starą nazwą: to ten sam dokument.
            if change.html is None:
                result = await db.execute(
                    versions.update()
                    .where(
                        versions.c.candidate_stage_cv_id == csv.id,
                        versions.c.docx_filename == old_filename,
                    )
                    .values(docx_filename=change.filename)
                )
                receipt["versions_renamed"] += result.rowcount or 0
        db.add(
            Activity(
                entity_type="candidate_stage_cv",
                entity_id=csv.id,
                action="branded_cv_service_title_repair",
                details={
                    "candidate_stage_id": csv.candidate_stage_id,
                    "old_position": change.old_position,
                    "new_position": change.new_position,
                    "old_filename": old_filename,
                    "reopened": reopened,
                },
            )
        )
    if apply:
        db.add(AppSetting(key=MARKER, value=receipt))
    return receipt
