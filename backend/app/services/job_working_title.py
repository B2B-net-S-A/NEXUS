"""Trzy nazwy rekrutacji (0378, decyzja Artura 25.09.2026).

* ``jobs.title`` — nazwa od klienta. Idzie do klienta (stanowisko w CV, nazwa
  pliku, Cpro) i do wektora oferty, więc jej znaczenie się nie zmienia.
* ``jobs.client_reference`` — numer zapytania klienta (ZOB, SAP, numer w Cpro).
* ``jobs.working_title`` — tytuł dla rekrutera, np.
  „Java Developer · Java, Kafka · 5+ lat · Payments”. Tylko ekrany wewnętrzne,
  nigdy do klienta.

Tytuł dla rekrutera składa KOD z danych, które wyczytało AI albo wpisał DL —
te same dane dają ten sam tytuł, więc dwie rekrutacje da się porównać wzrokiem.
Reguła ma lustro w ``frontend/src/lib/job-names.ts`` (podgląd na żywo na
``/jobs/new``) i wspólny plik przypadków
``frontend/src/lib/__fixtures__/job-working-title-cases.json``.

Dopóki ``working_title_auto`` jest ``True``, tytuł przelicza się przy zapisie
Championa i przy zmianie tytułu albo must-have rekrutacji. Ręczny zapis
wyłącza automat; pusty zapis go przywraca.
"""

from __future__ import annotations

import re
from typing import Any, Iterable, Optional

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.app_setting import AppSetting
from app.models.job import Job
from app.services import champion_view

SEPARATOR = " · "
MAX_LEN = 255
CLIENT_REFERENCE_MAX = 120
MUST_IN_TITLE = 2
BACKFILL_MARKER = "job_names_backfill_0378"

_WHITESPACE = re.compile(r"\s+")
_ZOB = re.compile(r"\bZOB[\s_-]*(\d+)\b", re.IGNORECASE)


def _clean(value: Any) -> str:
    return _WHITESPACE.sub(" ", value).strip() if isinstance(value, str) else ""


def _years_label(years: int) -> str:
    if years == 1:
        return "1+ rok"
    if years % 10 in (2, 3, 4) and years % 100 not in (12, 13, 14):
        return f"{years}+ lata"
    return f"{years}+ lat"


def compose_working_title(
    role: Optional[str],
    must: Iterable[Any] = (),
    min_years: Optional[int] = None,
    domain: Optional[str] = None,
) -> Optional[str]:
    """``{rola} · {must1}, {must2} · {N}+ lat · {dziedzina}``; pusty człon znika.

    Bez roli i bez must-have zwraca ``None`` — ekran pokaże wtedy nazwę od
    klienta. Za długi wynik traci człony od końca, a sama rola jest przycinana.
    """
    role_text = _clean(role)
    names: list[str] = []
    seen: set[str] = set()
    for item in must or ():
        name = _clean(item.get("name") if isinstance(item, dict) else item)
        if name and name.casefold() not in seen:
            seen.add(name.casefold())
            names.append(name)
        if len(names) == MUST_IN_TITLE:
            break
    if not role_text and not names:
        return None
    parts = [role_text, ", ".join(names)]
    if isinstance(min_years, int) and not isinstance(min_years, bool) and min_years > 0:
        parts.append(_years_label(min_years))
    parts.append(_clean(domain))
    parts = [part for part in parts if part]
    while len(parts) > 1 and len(SEPARATOR.join(parts)) > MAX_LEN:
        parts.pop()
    return SEPARATOR.join(parts)[:MAX_LEN].rstrip()


def normalize_client_reference(value: Any) -> Optional[str]:
    clean = _clean(value)[:CLIENT_REFERENCE_MAX].strip()
    return clean or None


def reference_from_title(*values: Optional[str]) -> Optional[str]:
    """Jednoznaczny numer ZOB z tytułu albo numeru wewnętrznego (archiwum)."""
    found = {match for value in values for match in _ZOB.findall(value or "")}
    return f"ZOB {next(iter(found))}" if len(found) == 1 else None


def _strip_reference(title: str, reference: Optional[str]) -> str:
    out = _ZOB.sub("", title)
    if reference:
        out = re.sub(re.escape(reference), "", out, flags=re.IGNORECASE)
    return out


def working_title_for_job(job: Any, client_names: Iterable[str] = ()) -> Optional[str]:
    """Tytuł dla rekrutera z Championa, a bez niego z kolumn rekrutacji."""
    from app.services.job_public_profile import default_public_title

    role = champion_view.basics(job).get("role_name")
    if not _clean(role):
        raw = _strip_reference(job.title or "", getattr(job, "client_reference", None))
        role = default_public_title(raw, list(client_names)) if _clean(raw) else None
    must = champion_view.stack(job).get("must") or list(job.must_skills or [])
    domain = next(
        (
            item["name"]
            for item in champion_view.experience(job).get("domains", [])
            if item.get("level", "must") == "must"
        ),
        None,
    )
    return compose_working_title(
        role, must, champion_view.seniority_min_years(job), domain
    )


async def refresh_working_title(db: AsyncSession, job: Job) -> bool:
    """Przelicz tytuł przy włączonym automacie. ``True`` = wartość się zmieniła."""
    if not job.working_title_auto:
        return False
    from app.services.job_public_profile import _client_names

    names = await _client_names(db, job.client_id)
    value = working_title_for_job(job, names)
    if value == job.working_title:
        return False
    job.working_title = value
    return True


def job_display_title_expr():
    """SQL: tytuł na ekrany wewnętrzne — tytuł dla rekrutera, a bez niego nazwa od klienta."""
    return func.coalesce(Job.working_title, Job.title)


def display_title(job: Any) -> str:
    return _clean(getattr(job, "working_title", None)) or _clean(job.title)


async def fill_missing_job_names(db: AsyncSession) -> Optional[dict[str, int]]:
    """Jednorazowo: tytuł dla rekrutera i numer ZOB dla istniejących rekrutacji.

    Rusza wyłącznie puste pola (``working_title IS NULL`` przy włączonym
    automacie, ``client_reference IS NULL``). Marker w ``app_settings`` +
    advisory lock → drugi start kończy się od razu. Wołający commituje.
    Paragon: same liczby.
    """
    from app.services.job_public_profile import _client_names

    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:key))"), {"key": BACKFILL_MARKER}
    )
    if await db.get(AppSetting, BACKFILL_MARKER):
        return None
    jobs = (
        await db.scalars(
            select(Job).where(
                (Job.working_title.is_(None) & Job.working_title_auto)
                | Job.client_reference.is_(None)
            )
        )
    ).all()
    names_cache: dict[Optional[int], list[str]] = {}
    titles = references = 0
    for job in jobs:
        if job.client_reference is None:
            reference = reference_from_title(job.title, job.reference_number)
            if reference:
                job.client_reference = reference
                references += 1
        if job.working_title is None and job.working_title_auto:
            if job.client_id not in names_cache:
                names_cache[job.client_id] = await _client_names(db, job.client_id)
            value = working_title_for_job(job, names_cache[job.client_id])
            if value:
                job.working_title = value
                titles += 1
    receipt = {
        "jobs_seen": len(jobs),
        "working_titles": titles,
        "client_references": references,
    }
    db.add(AppSetting(key=BACKFILL_MARKER, value=receipt))
    return receipt
