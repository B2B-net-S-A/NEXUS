#!/usr/bin/env python3
"""Ile ludzie zmieniają w CV z generatora: zatwierdzone CV etapu w okresie.

Tylko odczyt (transakcja ``READ ONLY``). Drukuje same liczby, bez nazwisk i treści
CV. Baza to start edytora zapisany przy podpięciu szkicu (od E3, 07.11.2026),
a dla CV sprzed E3 pierwszy szkic odtworzony z ``render_payload`` i sprawdzony
zapisanym skrótem (`services/cv_edit_measure.py`). Dla każdego CV liczy się
ostatnia wersja zatwierdzona w okresie. Daty to kalendarz firmy, koniec okresu
wchodzi do zakresu.

``--weekly`` czyta wpisy ``cv_approved_edit_summary`` (`services/cv_edit_summary.py`)
i drukuje odsetek CV bez poprawek per klient i tydzień — żeby było widać efekt
zmian generatora. Nazwa klienta to firma, nie osoba; wydruk zostaje w sesji.

Użycie (w kontenerze backendu)::

    python -m scripts.cv_edit_report --from 2026-10-06 --to 2026-11-02
    python -m scripts.cv_edit_report --days 28
    python -m scripts.cv_edit_report --weekly --days 56

Model generatora bierze się z ``ai_provider_calls`` (ta sama osoba, 10 minut od
założenia dokumentu), bo ``editorial_provenance`` modelu nie zapisuje.
"""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from statistics import median
import sys
from typing import Iterable, Optional
from zoneinfo import ZoneInfo

from sqlalchemy import bindparam, text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.database import AsyncSessionLocal, engine  # noqa: E402
from app.core.scheduling import DEFAULT_TZ, business_today  # noqa: E402
from app.services.cv_edit_summary import (  # noqa: E402
    ACTION as EDIT_SUMMARY_ACTION,
    START_HTML_KEY,
    STATUS_BOLD_ONLY,
    STATUS_CHANGED,
    STATUS_UNCHANGED,
)
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


# Ostatni wpis każdego CV w tygodniu (ponowne zatwierdzenie liczy się raz).
_WEEKLY_SQL = text(
    """
    WITH last AS (
        SELECT DISTINCT ON (a.entity_id, week)
               a.entity_id,
               date_trunc('week', a.created_at AT TIME ZONE :tz)::date AS week,
               a.details->>'status' AS status,
               a.details->'changed_parts' AS changed_parts,
               NULLIF(a.details->>'job_id', '')::int AS job_id
        FROM activities a
        WHERE a.action = :action
          AND a.entity_type = 'candidate_stage_cv'
          AND a.created_at >= :start AND a.created_at < :end
        ORDER BY a.entity_id, week, a.created_at DESC, a.id DESC
    )
    SELECT l.week, j.client_id, c.name AS client_name, l.status, l.changed_parts
    FROM last l
    LEFT JOIN jobs j ON j.id = l.job_id
    LEFT JOIN clients c ON c.id = j.client_id
    """
)
ALL_CLIENTS = "wszyscy klienci"
NO_CLIENT = "bez klienta"


@dataclass(frozen=True)
class WeeklyRow:
    week: date
    client: str
    status: str
    changed_parts: tuple[str, ...]


@dataclass(frozen=True)
class WeeklyCell:
    n: int
    unchanged: int
    bold_only: int
    changed: int
    top_parts: tuple[tuple[str, int], ...]

    @property
    def unchanged_share(self) -> Optional[float]:
        return self.unchanged / self.n if self.n else None


def weekly_table(rows: Iterable[WeeklyRow]) -> dict[str, dict[date, WeeklyCell]]:
    """Klient → tydzień → liczby; pierwszy klucz to wszyscy klienci razem."""
    grouped: dict[str, dict[date, list[WeeklyRow]]] = {}
    for row in rows:
        for client in (ALL_CLIENTS, row.client):
            grouped.setdefault(client, {}).setdefault(row.week, []).append(row)
    table: dict[str, dict[date, WeeklyCell]] = {}
    for client in sorted(grouped, key=lambda name: (name != ALL_CLIENTS, name)):
        table[client] = {}
        for week in sorted(grouped[client]):
            cell = grouped[client][week]
            parts: dict[str, int] = {}
            for row in cell:
                for part in row.changed_parts:
                    parts[part] = parts.get(part, 0) + 1
            table[client][week] = WeeklyCell(
                n=len(cell),
                unchanged=sum(row.status == STATUS_UNCHANGED for row in cell),
                bold_only=sum(row.status == STATUS_BOLD_ONLY for row in cell),
                changed=sum(row.status == STATUS_CHANGED for row in cell),
                top_parts=tuple(
                    sorted(parts.items(), key=lambda item: (-item[1], item[0]))[:3]
                ),
            )
    return table


def format_weekly(
    table: dict[str, dict[date, WeeklyCell]], start: date, end: date
) -> str:
    lines = [f"CV bez poprawek per klient i tydzień, zatwierdzone {start} – {end}"]
    if not table:
        lines.append("Brak wpisów — zatwierdzenia sprzed E3 (07.11.2026) ich nie mają.")
        return "\n".join(lines)
    for client, weeks in table.items():
        lines += ["", client]
        lines.append(
            f"{'tydzień od':<12}{'n':>5}{'bez zmian':>11}{'pogrub.':>9}"
            f"{'zmiany':>8}  najczęściej zmieniane"
        )
        for week, cell in weeks.items():
            parts = ", ".join(f"{part} {count}" for part, count in cell.top_parts)
            lines.append(
                f"{week.isoformat():<12}{cell.n:>5}"
                f"{_percent(cell.unchanged_share):>11}{cell.bold_only:>9}"
                f"{cell.changed:>8}  {parts or '-'}"
            )
    lines += [
        "",
        "„bez zmian”: odsetek CV zatwierdzonych tak, jak wstawił je generator;",
        "„pogrub.” i „zmiany”: liczba CV; części = liczba CV ze zmianą tekstu w części.",
    ]
    return "\n".join(lines)


async def _load_weekly(db, start: datetime, end: datetime) -> list[WeeklyRow]:
    rows = await db.execute(
        _WEEKLY_SQL,
        {"tz": DEFAULT_TZ, "action": EDIT_SUMMARY_ACTION, "start": start, "end": end},
    )
    return [
        WeeklyRow(
            week=row.week,
            client=row.client_name or NO_CLIENT,
            status=row.status or "",
            changed_parts=tuple(row.changed_parts or ()),
        )
        for row in rows
    ]


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


def _stored_start(cv: FinishedCv) -> Optional[str]:
    start = (cv.metadata or {}).get(START_HTML_KEY)
    return start if isinstance(start, str) and start.strip() else None


def _exclusion(cv: FinishedCv) -> Optional[str]:
    if _stored_start(cv):
        return None
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
        baseline = _stored_start(cv) or generator_first_draft_html(cv.render_payload)
        byte_identical += cv.content_html == baseline
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


async def _run(start: date, end: date, *, weekly: bool = False) -> str:
    try:
        if weekly:
            async with AsyncSessionLocal() as db:
                await db.execute(text("SET TRANSACTION READ ONLY"))
                rows = await _load_weekly(db, *period_bounds(start, end))
            return format_weekly(weekly_table(rows), start, end)
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
    parser.add_argument(
        "--weekly",
        action="store_true",
        help="odsetek CV bez poprawek per klient i tydzień (wpisy od E3)",
    )
    args = parser.parse_args()
    end = args.end or business_today()
    start = args.start or end - timedelta(days=args.days - 1)
    print(asyncio.run(_run(start, end, weekly=args.weekly)))


if __name__ == "__main__":
    main()
