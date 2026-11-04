#!/usr/bin/env python3
"""Ile ludzie zmieniają w CV z generatora: zatwierdzone CV etapu w okresie.

Tylko odczyt (transakcja ``READ ONLY``). Drukuje same liczby, bez nazwisk i treści
CV. Baza to pierwszy szkic odtworzony z ``render_payload`` i sprawdzony zapisanym
skrótem (`services/cv_edit_measure.py`). Dla każdego CV liczy się ostatnia wersja
zatwierdzona w okresie. Daty to kalendarz firmy, koniec okresu wchodzi do zakresu.

Użycie (w kontenerze backendu)::

    python -m scripts.cv_edit_report --from 2026-10-06 --to 2026-11-02
    python -m scripts.cv_edit_report --days 28

Model generatora bierze się z ``ai_provider_calls`` (ta sama osoba, 10 minut od
założenia dokumentu), bo ``editorial_provenance`` modelu nie zapisuje.
"""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
import hashlib
from pathlib import Path
from statistics import median
import sys
from typing import Iterable, Optional
from zoneinfo import ZoneInfo

from sqlalchemy import bindparam, text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.database import AsyncSessionLocal, engine  # noqa: E402
from app.core.scheduling import DEFAULT_TZ, business_today  # noqa: E402
from app.services.cv_edit_measure import (  # noqa: E402
    SECTIONS,
    TOTAL,
    SectionEdit,
    compare_cv,
    first_draft_is_reproduced,
    generator_first_draft_html,
)
from app.services.skill_taxonomy_loader import refresh_alias_map  # noqa: E402

ALL_MODELS = "wszystkie"
UNKNOWN_MODEL = "nieznany"
AMBIGUOUS_MODEL = "niejednoznaczny"
_ROWS = (*SECTIONS, TOTAL)
_ROW_LABELS = {
    "summary": "podsumowanie",
    "skills": "umiejętności",
    "experience": "doświadczenie",
    "education": "edukacja",
    "other": "pozostałe",
    TOTAL: "całe CV",
}
_SOURCE_LABELS = {
    "document": "plik Word",
    "generated_other_job": "kopia z innej rekrutacji",
}

_FINISHED_SQL = text(
    """
    SELECT DISTINCT ON (v.candidate_stage_cv_id)
           v.content_html, v.render_metadata, v.generated_document_id,
           d.render_payload
    FROM cv_document_versions v
    LEFT JOIN cv_generated_documents d ON d.id = v.generated_document_id
    WHERE v.candidate_stage_cv_id IS NOT NULL
      AND v.approved_at >= :start AND v.approved_at < :end
    ORDER BY v.candidate_stage_cv_id, v.approved_at DESC, v.version DESC
    """
)
_MODELS_SQL = text(
    """
    SELECT DISTINCT d.id AS document_id, c.model
    FROM cv_generated_documents d
    JOIN ai_operations o
      ON o.feature = 'cv_generator'
     AND o.actor_key = COALESCE('user:' || d.created_by::text, 'system')
    JOIN ai_provider_calls c
      ON c.operation_id = o.id
     AND c.outcome = 'response'
     AND c.created_at >= d.created_at
     AND c.created_at < d.created_at + INTERVAL '10 minutes'
    WHERE d.id IN :ids
    """
).bindparams(bindparam("ids", expanding=True))


@dataclass(frozen=True)
class FinishedCv:
    content_html: str
    metadata: Optional[dict]
    render_payload: Optional[dict]
    generated_document_id: Optional[int]
    source: Optional[str]
    model: str


@dataclass(frozen=True)
class SectionStats:
    n: int
    unchanged_share: Optional[float]
    median_added: Optional[float]
    median_removed: Optional[float]
    median_added_changed: Optional[float]
    median_removed_changed: Optional[float]


@dataclass(frozen=True)
class Group:
    n: int
    sections: dict[str, SectionStats]


@dataclass(frozen=True)
class Report:
    finished: int
    counted: int
    excluded: dict[str, int]
    byte_identical: int
    groups: dict[str, Group]


def generator_model(models: set[str]) -> str:
    if not models:
        return UNKNOWN_MODEL
    return next(iter(models)) if len(models) == 1 else AMBIGUOUS_MODEL


def period_bounds(start: date, end: date) -> tuple[datetime, datetime]:
    """Początek włącznie i koniec wyłącznie, w kalendarzu firmy."""
    zone = ZoneInfo(DEFAULT_TZ)
    return (
        datetime.combine(start, time.min, tzinfo=zone),
        datetime.combine(end + timedelta(days=1), time.min, tzinfo=zone),
    )


def _exclusion(cv: FinishedCv) -> Optional[str]:
    if cv.generated_document_id is None or not cv.render_payload:
        return _SOURCE_LABELS.get(cv.source or "", "bez dokumentu generatora")
    if not (cv.metadata or {}).get("generated_editor_html_sha256"):
        return "brak skrótu pierwszego szkicu"
    if not first_draft_is_reproduced(cv.render_payload, cv.metadata):
        return "baza nie odtwarza pierwszego szkicu"
    return None


def _median(values: list[float]) -> Optional[float]:
    return median(values) if values else None


def _section_stats(edits: list[SectionEdit]) -> SectionStats:
    with_base = [edit for edit in edits if edit.base_words]
    changed = [edit for edit in with_base if edit.changed]
    return SectionStats(
        n=len(with_base),
        unchanged_share=1 - len(changed) / len(with_base) if with_base else None,
        median_added=_median([edit.added_share for edit in with_base]),
        median_removed=_median([edit.removed_share for edit in with_base]),
        median_added_changed=_median([edit.added_share for edit in changed]),
        median_removed_changed=_median([edit.removed_share for edit in changed]),
    )


def _group(edits: list[dict[str, SectionEdit]]) -> Group:
    return Group(
        n=len(edits),
        sections={row: _section_stats([e[row] for e in edits]) for row in _ROWS},
    )


def build_report(cvs: Iterable[FinishedCv]) -> Report:
    finished = 0
    byte_identical = 0
    excluded: dict[str, int] = {}
    by_model: dict[str, list[dict[str, SectionEdit]]] = {}
    for cv in cvs:
        finished += 1
        reason = _exclusion(cv)
        if reason:
            excluded[reason] = excluded.get(reason, 0) + 1
            continue
        current = hashlib.sha256(cv.content_html.encode()).hexdigest()
        byte_identical += current == cv.metadata["generated_editor_html_sha256"]
        baseline = generator_first_draft_html(cv.render_payload)
        by_model.setdefault(cv.model, []).append(compare_cv(baseline, cv.content_html))
    everyone = [edits for group in by_model.values() for edits in group]
    groups = {ALL_MODELS: _group(everyone)} if everyone else {}
    for model in sorted(by_model):
        groups[model] = _group(by_model[model])
    return Report(
        finished=finished,
        counted=len(everyone),
        excluded=excluded,
        byte_identical=byte_identical,
        groups=groups,
    )


def _percent(value: Optional[float]) -> str:
    return "-" if value is None else f"{value * 100:.1f}%"


def format_report(report: Report, start: date, end: date) -> str:
    lines = [
        f"Zmiany ludzi w CV z generatora, zatwierdzone {start} – {end}",
        f"Zatwierdzone CV etapu: {report.finished}, policzone: {report.counted}",
    ]
    lines += [f"  pominięte, {k}: {v}" for k, v in sorted(report.excluded.items())]
    if not report.groups:
        lines.append("Brak CV do policzenia w tym okresie.")
        return "\n".join(lines)
    lines.append(f"Bajt w bajt jak pierwszy szkic: {report.byte_identical}")
    for name, group in report.groups.items():
        lines += ["", f"Model: {name} (n={group.n})"]
        lines.append(
            f"{'sekcja':<15}{'n':>5}{'bez zmian':>11}{'dodane':>9}{'usunięte':>10}"
            f"{'dodane zm.':>12}{'usunięte zm.':>14}"
        )
        for row in _ROWS:
            stats = group.sections[row]
            lines.append(
                f"{_ROW_LABELS[row]:<15}{stats.n:>5}"
                f"{_percent(stats.unchanged_share):>11}"
                f"{_percent(stats.median_added):>9}"
                f"{_percent(stats.median_removed):>10}"
                f"{_percent(stats.median_added_changed):>12}"
                f"{_percent(stats.median_removed_changed):>14}"
            )
    lines += [
        "",
        "dodane/usunięte: mediana udziału słów względem pierwszego szkicu;",
        "„zm.”: mediana tylko wśród CV ze zmianą tekstu w tej sekcji.",
    ]
    return "\n".join(lines)


async def _load_finished(db, start: datetime, end: datetime) -> list[FinishedCv]:
    rows = (await db.execute(_FINISHED_SQL, {"start": start, "end": end})).all()
    ids = {row.generated_document_id for row in rows if row.generated_document_id}
    models: dict[int, set[str]] = {}
    if ids:
        calls = await db.execute(_MODELS_SQL, {"ids": sorted(ids)})
        for call in calls:
            models.setdefault(call.document_id, set()).add(call.model)
    return [
        FinishedCv(
            content_html=row.content_html or "",
            metadata=row.render_metadata,
            render_payload=row.render_payload,
            generated_document_id=row.generated_document_id,
            source=(row.render_metadata or {}).get("source"),
            model=generator_model(models.get(row.generated_document_id, set())),
        )
        for row in rows
    ]


async def _run(start: date, end: date) -> str:
    try:
        await refresh_alias_map()
        async with AsyncSessionLocal() as db:
            await db.execute(text("SET TRANSACTION READ ONLY"))
            cvs = await _load_finished(db, *period_bounds(start, end))
        return format_report(build_report(cvs), start, end)
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--from", dest="start", type=date.fromisoformat)
    parser.add_argument("--to", dest="end", type=date.fromisoformat)
    parser.add_argument("--days", type=int, default=28)
    args = parser.parse_args()
    end = args.end or business_today()
    start = args.start or end - timedelta(days=args.days - 1)
    print(asyncio.run(_run(start, end)))


if __name__ == "__main__":
    main()
