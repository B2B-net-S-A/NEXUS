"""Co system już wie o tym CV — dane panelu „Do poprawy” w edytorze.

Edytor CV 2, PR 2 (decyzja Artura 12.10.2026): uwagi generatora i wynik
kontroli AI mają stać przy tekście, w edytorze, a nie w toaście po zamknięciu
okna. QC ma własną trasę (`api/cv_qc.py`); tu są dwa pozostałe źródła.

Kontrola AI zapisuje tylko wskaźniki (`/why_points/<i>`) i statusy. Tekst
linii odtwarzamy z treści, która była sprawdzana — wyłącznie przy zgodnym
skrócie treści i tej samej wersji podziału na linie. Wszystko tutaj jest
dodatkiem do edytora: zły zapis w metadanych daje pustą listę, nie błąd.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.candidate_stage_cv import CandidateStageCV
from app.models.cv_document_version import CvDocumentVersion
from app.models.cv_generated_document import CvGeneratedDocument
from app.services.cv_editor_review import EDITOR_REVIEW_VERSION, _review_lines

REVIEW_STATUSES = frozenset({"verified", "reviewed", "unverified"})
MAX_WARNINGS = 100
MAX_WARNING_CHARS = 500
_CLAIM_PATH = re.compile(r"/why_points/(\d+)\Z")


def generator_warnings(value: Any) -> list[str]:
    """Uwagi generatora jako lista napisów — bez pustych i bez innych typów."""
    if not isinstance(value, list):
        return []
    texts = [
        item.strip()[:MAX_WARNING_CHARS] for item in value if isinstance(item, str)
    ]
    return [text for text in texts if text][:MAX_WARNINGS]


def review_findings(receipt: Any, content_html: Optional[str]) -> dict:
    """Wynik kontroli AI z tekstem linii, do których odnoszą się uwagi."""
    if not isinstance(receipt, dict):
        return {"status": None, "findings": []}
    status = receipt.get("status")
    result: dict = {
        "status": status if status in REVIEW_STATUSES else None,
        "findings": [],
    }
    found = receipt.get("findings")
    if not isinstance(found, dict) or not content_html:
        return result
    if receipt.get("editor_review_version") != EDITOR_REVIEW_VERSION:
        return result
    if receipt.get("html_sha256") != hashlib.sha256(content_html.encode()).hexdigest():
        return result
    try:
        lines = _review_lines(content_html)
    except Exception:  # noqa: BLE001 — panel jest dodatkiem, nie warunkiem edytora
        return result
    statuses = found.get("statuses")
    statuses = statuses if isinstance(statuses, dict) else {}
    paths = found.get("paths")
    for path in paths if isinstance(paths, list) else []:
        match = _CLAIM_PATH.match(path) if isinstance(path, str) else None
        if match and int(match.group(1)) < len(lines):
            result["findings"].append(
                {
                    "text": lines[int(match.group(1))][0],
                    "status": str(statuses.get(path) or "unsupported"),
                }
            )
    return result


async def stage_issues(db: AsyncSession, csv: CandidateStageCV) -> dict:
    """Uwagi generatora i kontroli AI dla CV etapu otwartego w edytorze.

    Kontrola AI dotyczy ostatniej ZATWIERDZONEJ wersji (biegnie po „Zapisz”);
    front sam sprawdza, które uwagi nadal mają swoje miejsce w bieżącej treści.
    """
    warnings: Any = None
    if csv.generated_document_id is not None:
        # Sama kolumna: wiersz generatora niesie pliki binarne.
        warnings = await db.scalar(
            select(CvGeneratedDocument.warnings).where(
                CvGeneratedDocument.id == csv.generated_document_id
            )
        )
    approved = (
        await db.execute(
            select(
                CvDocumentVersion.version,
                CvDocumentVersion.content_html,
                CvDocumentVersion.render_metadata,
            )
            .where(CvDocumentVersion.candidate_stage_cv_id == csv.id)
            .order_by(CvDocumentVersion.version.desc())
            .limit(1)
        )
    ).first()
    if approved is not None:
        version, html, metadata = approved
    elif csv.branded_status == "finalized":
        version, html, metadata = (
            csv.branded_version,
            csv.branded_draft_html,
            csv.branded_render_metadata,
        )
    else:
        version, html, metadata = None, None, None
    receipt = (
        (metadata or {}).get("content_review") if isinstance(metadata, dict) else None
    )
    return {
        "generated_document_id": csv.generated_document_id,
        "generator_warnings": generator_warnings(warnings),
        "content_review": {**review_findings(receipt, html), "version": version},
    }
