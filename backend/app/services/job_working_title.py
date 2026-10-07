"""Trzy nazwy rekrutacji (0380, decyzja Artura 25.09.2026).

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

Do tytułu trafiają wyłącznie must-have będące NAZWĄ („Java”, „CI/CD”,
„React (Hooks)”). Pozycja wpisana zdaniem — więcej niż trzy słowa, ponad 40
znaków albo z przecinkiem, średnikiem, dwukropkiem czy pauzą — jest pomijana
(:func:`_is_prose`), i to ZANIM wybierzemy dwie pierwsze: zdanie na początku
listy nie zabiera miejsca technologii. Produkcja 02.10.2026: „Analityk
Biznesowo-Systemowy KYC/AML · Minimum 5 lat doświadczenia w an…”.

Dopóki ``working_title_auto`` jest ``True``, tytuł przelicza się przy zapisie
Championa i przy zmianie tytułu albo must-have rekrutacji. Ręczny zapis
wyłącza automat; pusty zapis go przywraca.
"""

from __future__ import annotations

import re
from typing import Any, Iterable, Optional

from sqlalchemy import bindparam, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.app_setting import AppSetting
from app.models.job import Job
from app.services import champion_view

SEPARATOR = " · "
MAX_LEN = 255
CLIENT_REFERENCE_MAX = 120
MUST_IN_TITLE = 2
# Must-have dłuższe niż tyle słów albo znaków to zdanie, nie nazwa.
MUST_MAX_WORDS = 3
MUST_MAX_CHARS = 40
# Znaki zdania. „/”, „&”, nawiasy, „+”, „#” i „.” świadomie poza listą:
# „CI/CD”, „PL/SQL”, „C++”, „.NET”, „React (Hooks)” to nazwy.
PROSE_MARKS = (",", ";", ":", "–", "—")
BACKFILL_MARKER = "job_names_backfill_0380"
PROSE_FIX_MARKER = "job_working_title_prose_fix_2026_10"
_RECOMPUTE_CHUNK = 500

_WHITESPACE = re.compile(r"\s+")
_ZOB = re.compile(r"\bZOB[\s_-]*(\d+)\b", re.IGNORECASE)
_EMPTY_BRACKETS = re.compile(r"[\(\[]\s*[\)\]]")


def _clean(value: Any) -> str:
    return _WHITESPACE.sub(" ", value).strip() if isinstance(value, str) else ""


def _is_prose(name: str) -> bool:
    """Czy pozycja must-have jest zdaniem (``name`` po :func:`_clean`)."""
    return (
        len(name.split(" ")) > MUST_MAX_WORDS
        or len(name) > MUST_MAX_CHARS
        or any(mark in name for mark in PROSE_MARKS)
    )


def _dictionary_loaded() -> bool:
    from app.services.skill_normalize import CANONICAL_CATEGORY  # noqa: PLC0415

    return bool(CANONICAL_CATEGORY)


def _is_title_technology(label: str) -> bool:
    """Do tytułu wchodzą tylko technologie ze słownika (audyt 06.10.2026, P10).

    Słowa kluczowe wierszy („banking”, „communication”) to też must-have, ale
    w tytule zajmowały oba miejsca technologii. Reguła = ``critical_eligible``
    na etykiecie CAŁEGO wiersza („Kafka lub RabbitMQ”) — tę samą odpowiedź
    (`eligible` z ``POST /api/job-intake/critical-suggestion``) czyta podgląd
    tytułu na froncie (`lib/job-names.ts`). Działa wyłącznie przy wczytanym
    słowniku — bez niego (testy bez bazy) tytuł składa się jak dotąd, tak jak
    front przed odpowiedzią serwera; wspólny plik przypadków obowiązuje dalej.
    """
    from app.services.must_gate_terms import critical_eligible  # noqa: PLC0415

    return bool(label) and critical_eligible(label)


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
    Must-have wpisane zdaniem (:func:`_is_prose`) nie wchodzi do tytułu.
    """
    role_text = _clean(role)
    names: list[str] = []
    seen: set[str] = set()
    only_technologies = _dictionary_loaded()
    for item in must or ():
        # „Kafka lub RabbitMQ” w tytule to sama „Kafka” — zamienniki widać
        # w wymaganiach, a tytuł ma się mieścić w wierszu listy.
        label = _clean(item.get("name") if isinstance(item, dict) else item)
        name = label.split(" lub ")[0].strip()
        if only_technologies and not _is_title_technology(label):
            continue
        if name and not _is_prose(name) and name.casefold() not in seen:
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
    # „Programista Java (ZOB 48213)” → bez numeru zostawałyby puste nawiasy.
    return _EMPTY_BRACKETS.sub("", out)


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


async def fill_missing_job_names(
    db: AsyncSession, *, only_job_ids: Optional[set[int]] = None
) -> Optional[dict[str, int]]:
    """Jednorazowo: tytuł dla rekrutera i numer ZOB dla istniejących rekrutacji.

    Rusza wyłącznie puste pola (``working_title IS NULL`` przy włączonym
    automacie, ``client_reference IS NULL``) i NIE podbija ``updated_at`` —
    inaczej ponowny skan Targu (`rescan_recent_jobs`) objąłby naraz każdą
    rekrutację. Marker w ``app_settings`` + advisory lock → drugi start kończy
    się od razu. Wołający commituje. Paragon: same liczby. ``only_job_ids``
    zawęża przebieg — wyłącznie dla testów na wspólnej bazie (bez markera).
    """
    from types import SimpleNamespace

    from app.services.job_public_profile import _client_names

    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:key))"), {"key": BACKFILL_MARKER}
    )
    if only_job_ids is None and await db.get(AppSetting, BACKFILL_MARKER):
        return None
    missing = (Job.working_title.is_(None) & Job.working_title_auto) | (
        Job.client_reference.is_(None)
    )
    if only_job_ids is not None:
        missing = missing & Job.id.in_(only_job_ids)
    rows = (
        await db.execute(
            select(
                Job.id,
                Job.title,
                Job.reference_number,
                Job.client_reference,
                Job.working_title,
                Job.working_title_auto,
                Job.client_id,
                Job.must_skills,
                Job.champion_profile,
            ).where(missing)
        )
    ).all()
    names_cache: dict[Optional[int], list[str]] = {}
    updates: list[dict[str, Any]] = []
    titles = references = 0
    for row in rows:
        reference = row.client_reference
        if reference is None:
            reference = reference_from_title(row.title, row.reference_number)
            references += reference is not None
        working = row.working_title
        if working is None and row.working_title_auto:
            if row.client_id not in names_cache:
                names_cache[row.client_id] = await _client_names(db, row.client_id)
            view = SimpleNamespace(**{**row._mapping, "client_reference": reference})
            working = working_title_for_job(view, names_cache[row.client_id])
            titles += working is not None
        if reference != row.client_reference or working != row.working_title:
            updates.append({"jid": row.id, "cref": reference, "wtitle": working})
    if updates:
        table = Job.__table__
        await db.execute(
            table.update()
            .where(table.c.id == bindparam("jid"))
            .values(
                client_reference=func.coalesce(
                    table.c.client_reference, bindparam("cref")
                ),
                working_title=func.coalesce(table.c.working_title, bindparam("wtitle")),
                updated_at=table.c.updated_at,
            ),
            updates,
        )
    receipt = {
        "jobs_seen": len(rows),
        "working_titles": titles,
        "client_references": references,
    }
    if only_job_ids is None:
        db.add(AppSetting(key=BACKFILL_MARKER, value=receipt))
    return receipt


async def refresh_working_titles_for_ids(db: AsyncSession, job_ids: list[int]) -> int:
    """Przelicz tytuł dla rekrutera wskazanych rekrutacji z włączonym automatem.

    Runda 9 (R9-N15-7): woła go import Traffita dla rekrutacji nowych i tych,
    którym zmienił się ``title`` — tytuł dla rekrutera bez roli w Championie
    składa się z nazwy od klienta, a import go nie przeliczał. Nie podbija
    ``updated_at`` (zrobił to już upsert). Zwraca liczbę zmienionych wierszy.
    """
    from types import SimpleNamespace

    from app.services.job_public_profile import _client_names

    ids = sorted({int(job_id) for job_id in job_ids})
    if not ids:
        return 0
    rows = (
        await db.execute(
            select(
                Job.id,
                Job.title,
                Job.client_reference,
                Job.working_title,
                Job.client_id,
                Job.must_skills,
                Job.champion_profile,
            ).where(Job.id.in_(ids), Job.working_title_auto.is_(True))
        )
    ).all()
    names_cache: dict[Optional[int], list[str]] = {}
    updates: list[dict[str, Any]] = []
    for row in rows:
        if row.client_id not in names_cache:
            names_cache[row.client_id] = await _client_names(db, row.client_id)
        value = working_title_for_job(
            SimpleNamespace(**row._mapping), names_cache[row.client_id]
        )
        if value != row.working_title:
            updates.append({"jid": row.id, "wtitle": value})
    if updates:
        table = Job.__table__
        await db.execute(
            table.update()
            .where(table.c.id == bindparam("jid"), table.c.working_title_auto.is_(True))
            .values(working_title=bindparam("wtitle"), updated_at=table.c.updated_at),
            updates,
        )
    return len(updates)


async def recompute_auto_working_titles(
    db: AsyncSession, *, only_job_ids: Optional[set[int]] = None
) -> Optional[dict[str, int]]:
    """Jednorazowo: przelicz ISTNIEJĄCE automatyczne tytuły dla rekrutera.

    Po zmianie reguły (02.10.2026 — zdanie w must-have nie wchodzi do tytułu)
    stare tytuły zostałyby w bazie do najbliższego zapisu Championa. Idzie
    przez :func:`refresh_working_titles_for_ids`, więc ręcznych tytułów nie
    rusza i NIE podbija ``updated_at``. Marker w ``app_settings`` + advisory
    lock → drugi start kończy się od razu (``None``). Wołający commituje.
    Paragon: same liczby — bez tytułów i nazw (drukuje go publiczny workflow).
    ``only_job_ids`` zawęża przebieg — wyłącznie dla testów na wspólnej bazie
    (bez markera).
    """
    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:key))"), {"key": PROSE_FIX_MARKER}
    )
    if only_job_ids is None and await db.get(AppSetting, PROSE_FIX_MARKER):
        return None
    query = select(Job.id).where(Job.working_title_auto.is_(True)).order_by(Job.id)
    if only_job_ids is not None:
        query = query.where(Job.id.in_(only_job_ids))
    ids = list((await db.execute(query)).scalars())
    changed = 0
    for start in range(0, len(ids), _RECOMPUTE_CHUNK):
        changed += await refresh_working_titles_for_ids(
            db, ids[start : start + _RECOMPUTE_CHUNK]
        )
    receipt = {"jobs_seen": len(ids), "titles_changed": changed}
    if only_job_ids is None:
        db.add(AppSetting(key=PROSE_FIX_MARKER, value=receipt))
    return receipt
