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
_CLAIM_PATH = re.compile(r"/why_points/(\d{1,6})\Z")


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
        "status": status
        if isinstance(status, str) and status in REVIEW_STATUSES
        else None,
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


async def stage_issues(
    db: AsyncSession,
    csv: CandidateStageCV,
    pair: Optional[tuple[int, int]] = None,
) -> dict:
    """Uwagi generatora i kontroli AI dla CV etapu otwartego w edytorze.

    Kontrola AI dotyczy ostatniej ZATWIERDZONEJ wersji (biegnie po „Zapisz”);
    front sam sprawdza, które uwagi nadal mają swoje miejsce w bieżącej treści.
    ``pair`` (kandydat, rekrutacja) — uwagi oznaczone „To nieprawda” (D5)
    trafiają do ``dismissed`` zamiast na listę.
    """
    issues = await _raw_issues(db, csv)
    if pair is not None:
        await _split_dismissed(db, issues, pair)
    return issues


async def _split_dismissed(
    db: AsyncSession, issues: dict, pair: tuple[int, int]
) -> None:
    from app.services import cv_finding_dismissals as dismissals

    active = {
        d["key"]: d for d in await dismissals.active(db, *pair, ("generator", "review"))
    }
    dismissed: list[dict] = []
    if not active:
        issues["dismissed"] = dismissed
        return
    kept: list[str] = []
    for text in issues["generator_warnings"]:
        hit = active.get(dismissals.text_key(text))
        if hit is not None and hit["source"] == "generator":
            dismissed.append(
                {
                    "source": "generator",
                    "text": text,
                    "status": None,
                    "dismissal": hit["view"],
                }
            )
        else:
            kept.append(text)
    issues["generator_warnings"] = kept
    review = issues["content_review"]
    still: list[dict] = []
    for finding in review["findings"]:
        hit = active.get(dismissals.text_key(finding["text"], finding["status"]))
        if hit is not None and hit["source"] == "review":
            dismissed.append({"source": "review", **finding, "dismissal": hit["view"]})
        else:
            still.append(finding)
    review["findings"] = still
    issues["dismissed"] = dismissed


async def dismiss(
    db: AsyncSession,
    csv: CandidateStageCV,
    *,
    pair: tuple[int, int],
    stage_id: int,
    source: str,
    text: str,
    status: Optional[str],
    reason: str,
    note: Optional[str],
    user_id: int,
) -> dict:
    """„To nieprawda” przy uwadze generatora albo kontroli AI. Uwagę bierzemy
    z bieżącej listy — tekst od klienta musi się z nią zgadzać. Bez commitu."""
    from app.services import cv_finding_dismissals as dismissals

    reason, note = dismissals.validate_reason(reason, note)
    issues = await _raw_issues(db, csv)
    wanted = " ".join((text or "").split())
    if source == "generator":
        present = any(
            " ".join(w.split()) == wanted for w in issues["generator_warnings"]
        )
        status = None
    else:
        present = any(
            " ".join(f["text"].split()) == wanted and f["status"] == status
            for f in issues["content_review"]["findings"]
        )
    if not wanted or not present:
        raise dismissals.DismissError("Tej uwagi już nie ma — odśwież panel.")
    db.add(
        dismissals.new_row(
            candidate_id=pair[0],
            job_id=pair[1],
            stage_id=stage_id,
            source=source,
            check_key=source,
            key=dismissals.text_key(wanted, status),
            label=wanted,
            reason=reason,
            note=note,
            quote=None,
            blocking=False,
            user_id=user_id,
        )
    )
    await db.flush()
    return await stage_issues(db, csv, pair)


async def restore(
    db: AsyncSession,
    csv: CandidateStageCV,
    *,
    pair: tuple[int, int],
    dismissal_id: int,
    user_id: int,
) -> dict:
    from app.services import cv_finding_dismissals as dismissals

    await dismissals.restore(
        db,
        dismissal_id=dismissal_id,
        candidate_id=pair[0],
        job_id=pair[1],
        user_id=user_id,
    )
    await db.flush()
    return await stage_issues(db, csv, pair)


async def _raw_issues(db: AsyncSession, csv: CandidateStageCV) -> dict:
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
        "dismissed": [],
    }
