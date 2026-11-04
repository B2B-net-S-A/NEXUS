"""Pomiar odczytu pliku Profilu Championa na /jobs/new (D4) — tylko odczyt, same liczby.

Co mierzy na plikach requestów z produkcji (``job_files``, ``source='request'``):

* ile plików ma które rozszerzenie i ile z nich to wypełniony albo pusty wzór
  Profilu Championa (czytany z tabel, bez modelu);
* ile znaków traciła stara ścieżka (plik spłaszczony do tekstu) na limicie
  20 000 znaków;
* dla wypełnionych wzorów przypiętych do rekrutacji: zgodność pól odczytu
  z tym, co zostało zapisane w rekrutacji (``agree | differ | reader_empty |
  job_empty``).

Te same liczby (bez porównania z rekrutacją) dla wzorów z repo —
``tests/fixtures/champion`` i ``app/assets/champion`` — gdy są w obrazie.

Zasady:

* transakcja ``READ ONLY``; pliki są tylko czytane z wolumenu (słownik
  umiejętności wczytuje ten sam odczyt co przy starcie aplikacji);
* bez modelu. ``--with-ai`` dokłada porównanie ze starą ścieżką (odczyt AI
  spłaszczonego tekstu wzoru) — jedyny zapis to wtedy telemetria kosztu AI;
* na wyjściu WYŁĄCZNIE liczby pod stałymi etykietami: żadnych nazw plików,
  klientów ani treści dokumentów (logi produkcji i to repo są publiczne).
  Logowanie aplikacji jest na czas biegu wyłączone, a z wyjątków zostaje sama
  nazwa klasy.

W kontenerze backendu::

    python -m scripts.eval_champion_file_read --limit 200

Przed wdrożeniem modułu czytnika (nie ma go jeszcze w obrazie) — paczka
z treścią modułu, przez stdin::

    python3 backend/scripts/eval_champion_file_read.py --bundle > /tmp/eval_champion_bundle.py
    ssh … "docker exec -i <backend> python - --limit 200" < /tmp/eval_champion_bundle.py
"""

from __future__ import annotations

import argparse
import asyncio
import importlib
import json
import logging
import re
import sys
import types
from collections import Counter
from decimal import Decimal
from pathlib import Path
from typing import Any, Optional

READER_MODULE = "app.services.job_intake_champion_file"
# Treść modułu czytnika — pusta w repo; wypełnia ją `--bundle`, żeby skrypt
# dało się uruchomić przez stdin w obrazie, który modułu jeszcze nie ma.
MODULE_SOURCE = ""

EXTENSIONS = ("docx", "pdf", "txt")
FIELDS = (
    "role",
    "must",
    "nice",
    "seniority",
    "rate",
    "work_mode",
    "office_days",
    "office_city",
    "language",
    "about",
    "responsibilities",
    "questions",
    "deal_breakers",
    "selling_points",
)

_FILES_SQL = """
    SELECT f.file_path,
           f.job_id IS NOT NULL AS attached,
           COALESCE(j.client_id, i.client_id) AS client_id,
           j.rate_budget_hourly,
           CAST(j.remote_policy AS text) AS remote_policy,
           j.onsite_days_per_week,
           j.location,
           j.champion_profile
    FROM job_files f
    LEFT JOIN jobs j ON j.id = f.job_id
    LEFT JOIN job_intake_forms i ON i.id = f.intake_form_id
    WHERE f.source = 'request'
    ORDER BY f.id DESC
    LIMIT :n
"""


def load_reader() -> Any:
    """Moduł czytnika: z paczki (`MODULE_SOURCE`) albo z obrazu."""
    if not MODULE_SOURCE:
        return importlib.import_module(READER_MODULE)
    module = types.ModuleType(READER_MODULE)
    # Przed `exec`: moduł szuka siebie w `sys.modules` (dataclass, logger).
    sys.modules[READER_MODULE] = module
    exec(compile(MODULE_SOURCE, READER_MODULE, "exec"), module.__dict__)
    return module


def bundle() -> str:
    """Ten skrypt z wpisaną treścią modułu czytnika (do uruchomienia przez stdin)."""
    here = Path(__file__).resolve()
    module = here.parents[1] / "app" / "services" / "job_intake_champion_file.py"
    source = here.read_text(encoding="utf-8")
    marker = 'MODULE_SOURCE = ""\n'
    if marker not in source:
        raise SystemExit("Nie znaleziono miejsca na treść modułu czytnika.")
    filled = f"MODULE_SOURCE = {module.read_text(encoding='utf-8')!r}\n"
    return source.replace(marker, filled, 1)


def _backend_root() -> Path:
    here = globals().get("__file__")
    if here and Path(here).is_file():
        return Path(here).resolve().parents[1]
    return Path.cwd()  # uruchomienie przez stdin: katalog roboczy kontenera


def _extension(path: Path) -> str:
    """Rozszerzenie z białej listy — nietypowe mogłoby być kawałkiem nazwy pliku."""
    ext = path.suffix.lower().lstrip(".")
    return ext if ext in EXTENSIONS else "other"


def _norm(value: Any) -> Any:
    """Wartość pola do porównania; ``None`` = puste."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float, Decimal)):  # kolumna stawki to Decimal
        return round(float(value), 2)
    if isinstance(value, (list, tuple, set)):
        items = sorted({item for item in (_norm(v) for v in value) if item is not None})
        return tuple(items) or None
    text = re.sub(r"\s+", " ", str(value)).strip().casefold()
    return text or None


def verdict(reader_value: Any, other_value: Any, other: str = "job") -> Optional[str]:
    """``agree | differ | reader_empty | <other>_empty``; ``None``, gdy oba puste."""
    left, right = _norm(reader_value), _norm(other_value)
    if left is None and right is None:
        return None
    if left is None:
        return "reader_empty"
    if right is None:
        return f"{other}_empty"
    return "agree" if left == right else "differ"


def _cities(value: Any) -> list[str]:
    return [part for part in re.split(r"\s*,\s*", str(value or "")) if part]


def intake_values(intake: dict[str, Any]) -> dict[str, Any]:
    """Pola odczytu (wzór albo AI) w kształcie do porównania."""
    questions = intake.get("screening_questions") or []
    return {
        "role": intake.get("role_name"),
        "must": intake.get("must"),
        "nice": intake.get("nice"),
        "seniority": intake.get("seniority_min_years"),
        "rate": intake.get("rate_budget_hourly"),
        "work_mode": intake.get("remote_policy"),
        "office_days": intake.get("onsite_days_per_week"),
        "office_city": _cities(intake.get("office_city")),
        "language": intake.get("language"),
        "about": intake.get("project_about"),
        "responsibilities": intake.get("responsibilities"),
        "questions": [q.get("question") for q in questions],
        "deal_breakers": [q.get("deal_breaker") for q in questions],
        "selling_points": intake.get("selling_points"),
    }


def job_values(row: Any) -> dict[str, Any]:
    """To, co zapisano w rekrutacji: kolumny i Profil Championa."""
    from app.services import champion_intake

    profile = champion_intake.content(row.champion_profile)
    basics, stack, project = profile["basics"], profile["stack"], profile["project"]
    questions = profile["screening_questions"]
    return {
        "role": basics.get("role_name"),
        "must": [item["name"] for item in stack["must"]],
        "nice": [item["name"] for item in stack["nice"]],
        "seniority": basics.get("seniority_min_years"),
        "rate": row.rate_budget_hourly
        if row.rate_budget_hourly is not None
        else basics.get("rate_value"),
        "work_mode": row.remote_policy,
        "office_days": row.onsite_days_per_week,
        "office_city": _cities(row.location),
        "language": basics.get("language"),
        "about": project.get("about"),
        "responsibilities": project.get("responsibilities"),
        "questions": [q.get("question") for q in questions],
        "deal_breakers": [q.get("deal_breaker") for q in questions],
        "selling_points": profile["client"].get("selling_points"),
    }


def compare(
    reader: dict[str, Any], other: dict[str, Any], label: str = "job"
) -> dict[str, str]:
    out: dict[str, str] = {}
    for field in FIELDS:
        result = verdict(reader.get(field), other.get(field), label)
        if result is not None:
            out[field] = result
    return out


def _bump(report: dict[str, Any], section: str, key: str, by: int = 1) -> None:
    report.setdefault(section, Counter())[key] += by


def read_file(
    reader: Any, path: Path, report: dict[str, Any]
) -> tuple[Optional[dict], str]:
    """Liczy jeden plik. Zwraca (odczyt wzoru albo ``None``, tekst starej ścieżki)."""
    from app.services.cv_text_extractor import extract_text
    from app.services.job_request_intake import MAX_REQUEST_CHARS, MIN_REQUEST_CHARS

    ext = _extension(path)
    _bump(report, "by_extension", ext)
    if ext == "other":
        return None, ""
    intake: Optional[dict] = None
    name = f"plik.{ext}"  # prawdziwa nazwa pliku nie wchodzi do żadnego wywołania
    if ext == "docx":
        try:
            profile = reader.read_champion_form(path.read_bytes(), name)
        except reader.EmptyChampionForm:
            profile = None
            _bump(report, "champion", "blank")
        else:
            if profile is None:
                _bump(report, "champion", "not_champion")
            else:
                _bump(report, "champion", "filled")
                intake = reader.intake_from_champion(profile).as_dict()
                _bump(report, "champion", "missing_codes", len(intake["missing"]))
                _bump(report, "champion", "advisories", len(intake["advisories"]))
    # Stara ścieżka: plik spłaszczony do tekstu i ucięty na limicie.
    text = (extract_text(str(path), name) or "").strip()
    _bump(report, "old_path_text", "files")
    _bump(report, "old_path_text", "chars", len(text))
    if len(text) < MIN_REQUEST_CHARS:
        _bump(report, "old_path_text", "too_short")
    lost = max(0, len(text) - MAX_REQUEST_CHARS)
    if lost:
        _bump(report, "old_path_text", "over_limit")
        _bump(report, "old_path_text", "chars_lost", lost)
    if ext == "pdf" and reader.looks_like_champion_text(text):
        _bump(report, "champion", "pdf_looks_like")
    return intake, text[:MAX_REQUEST_CHARS]


def _safe(report: dict[str, Any], action: Any) -> Any:
    """Błąd jednego pliku to liczba pod nazwą klasy wyjątku — nigdy jego treść."""
    try:
        return action()
    except Exception as exc:  # noqa: BLE001 — liczymy awarie, bieg idzie dalej
        _bump(report, "errors", type(exc).__name__)
        return None


def fixtures_report(reader: Any) -> dict[str, Any]:
    """Wzory z repo (gdy są w obrazie) — te same liczby, bez bazy."""
    root = _backend_root()
    report: dict[str, Any] = {"files": 0}
    for folder in ("tests/fixtures/champion", "app/assets/champion"):
        for path in sorted((root / folder).glob("*.docx")):
            report["files"] += 1
            _safe(report, lambda path=path: read_file(reader, path, report))
    return report


async def _ai_values(client_id: int, text: str) -> dict[str, Any]:
    """Stara ścieżka: odczyt AI spłaszczonego tekstu (telemetria kosztu = jedyny zapis)."""
    from app.core.database import AsyncSessionLocal
    from app.models.ai_feature import AIFeatureKey
    from app.services import job_request_intake as request_intake
    from app.services.ai_quota import ai_feature

    async with AsyncSessionLocal() as db:
        async with ai_feature(db, AIFeatureKey.champion_draft, user_id=None):
            await db.commit()
            result = await request_intake.read_request(
                db, client_id=client_id, request_text=text
            )
        await db.rollback()
    return intake_values(result.as_dict())


async def production_report(reader: Any, limit: int, with_ai: bool) -> dict[str, Any]:
    from sqlalchemy import text as sql

    from app.core.database import AsyncSessionLocal
    from app.services import storage_service
    from app.services.skill_taxonomy_loader import refresh_alias_map

    # Wiersze wymagań liczy ta sama reguła co w aplikacji — potrzebuje słownika.
    await refresh_alias_map()
    async with AsyncSessionLocal() as db:
        await db.execute(sql("SET TRANSACTION READ ONLY"))
        rows = (await db.execute(sql(_FILES_SQL), {"n": limit})).all()
        await db.rollback()

    report: dict[str, Any] = {"rows": len(rows), "attached_to_job": 0}
    for row in rows:
        report["attached_to_job"] += bool(row.attached)
        # Komunikat wyjątku niesie ścieżkę z nazwą pliku — zostaje sama klasa
        # (`FileNotFoundError` = pliku nie ma już na wolumenie).
        path = _safe(
            report, lambda row=row: storage_service.get_job_file_path(row.file_path)
        )
        if path is None:
            continue
        intake, old_text = _safe(
            report, lambda path=path: read_file(reader, path, report)
        ) or (None, "")
        if intake is None:
            continue
        values = intake_values(intake)
        if row.attached:
            saved = _safe(report, lambda row=row: job_values(row))
            for field, result in compare(values, saved or {}).items():
                _bump(report, f"reader_vs_job.{field}", result)
        if with_ai and row.client_id is not None and old_text:
            try:
                ai = await _ai_values(row.client_id, old_text)
            except Exception as exc:  # noqa: BLE001 — liczymy awarie modelu
                _bump(report, "errors", f"ai_{type(exc).__name__}")
                continue
            _bump(report, "ai", "calls")
            for field, result in compare(values, ai, "ai").items():
                _bump(report, f"reader_vs_ai.{field}", result)
    return report


def render(report: dict[str, Any]) -> str:
    return json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True)


async def main(limit: int, with_ai: bool) -> None:
    # Biblioteki i aplikacja logują nazwy plików i ścieżki — wyjście tego
    # skryptu trafia do publicznego logu, więc na czas biegu logów nie ma.
    logging.disable(logging.CRITICAL)
    reader = load_reader()
    from app.core.database import engine

    try:
        report = {
            "fixtures": fixtures_report(reader),
            "request_files": await production_report(reader, limit, with_ai),
        }
    finally:
        await engine.dispose()
    print(render(report))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=200)
    parser.add_argument("--with-ai", action="store_true")
    parser.add_argument("--bundle", action="store_true")
    args = parser.parse_args()
    if args.bundle:
        sys.stdout.write(bundle())
    else:
        asyncio.run(main(args.limit, args.with_ai))
