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
CLIENT_REFERENCE_MARKER = "client_reference_from_title_2026_10"
_RECOMPUTE_CHUNK = 500

_WHITESPACE = re.compile(r"\s+")
_ZOB = re.compile(r"\bZOB[\s_-]*(\d+)\b", re.IGNORECASE)
_EMPTY_BRACKETS = re.compile(r"[\(\[]\s*[\)\]]")
# Numery zapytań w nazwach od klienta (15.10.2026, zmierzone na produkcji):
# „IT Analyst – RITM0869306”, „Tester_PKN/5/000177/26”, „…_PKN500023226”,
# „…_EITE500011826”, „IT Analyst Replacement (42946)”, „UX Researcher (6762)”.
_RITM = re.compile(r"(?<![A-Za-z0-9])RITM\d{6,}(?!\d)", re.IGNORECASE)
_TENDER = re.compile(r"(?<![A-Za-z0-9])(?:PKN|EITE)(?:/5/\d{6}/\d{2}|5\d{8,})(?!\d)")
_PAREN_NUMBER = re.compile(r"\(\s*(\d{4,6})\s*\)")
_TRAILING_DIGITS = re.compile(r"(\d+)\s*$")
# D4: kody Nordei, które odczyt maila brał za numer zapytania („PEP4989”, „TP#45854”).
_INTERNAL_CODE = re.compile(r"^\s*(?:PEP|TP)(?![A-Za-z])", re.IGNORECASE)
_PAREN_ONLY = re.compile(r"^\s*\(\s*(\d{4,6})\s*\)\s*$")
_LETTER = re.compile(r"[^\W\d_]")


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


def client_reference_parts(reference: Optional[str]) -> list[str]:
    """„42928, 42927” → dwa numery: jedna rekrutacja na kilka zapytań klienta."""
    return [part.strip() for part in (reference or "").split(",") if part.strip()]


def _year_or_ours(number: str, ours: Optional[re.Match[str]]) -> bool:
    if len(number) == 4 and 1900 <= int(number) <= 2099:
        return True
    return bool(ours) and number == ours.group(1)


def reference_from_title(
    title: Optional[str], reference_number: Optional[str] = None
) -> Optional[str]:
    """Numer zapytania z nazwy od klienta — tylko znane formaty, bez zgadywania.

    Kolejność formatów: ZOB (PKO; także w naszym numerze z archiwum), RITM
    (BNP), PKN/EITE (Orlen, Energa), 4–6 cyfr w nawiasie (Nordea, Alior).
    Wygrywa pierwszy format, który coś znajdzie. ZOB tylko jednoznaczny (jak
    od 0380); w pozostałych kilka różnych numerów to jedna rekrutacja na kilka
    zapytań → „42928, 42927”. Cztery cyfry 1900–2099 w nawiasie to rok,
    a liczba równa końcówce naszego numeru („…/IT/4918”) — nasz numer.
    """
    zob = {m for value in (title, reference_number) for m in _ZOB.findall(value or "")}
    if zob:
        return f"ZOB {next(iter(zob))}" if len(zob) == 1 else None
    text = title or ""
    for pattern in (_RITM, _TENDER):
        found = list(dict.fromkeys(m.group(0) for m in pattern.finditer(text)))
        if found:
            return ", ".join(found)[:CLIENT_REFERENCE_MAX]
    ours = _TRAILING_DIGITS.search(reference_number or "")
    found = list(
        dict.fromkeys(
            n for n in _PAREN_NUMBER.findall(text) if not _year_or_ours(n, ours)
        )
    )
    return ", ".join(found)[:CLIENT_REFERENCE_MAX] if found else None


def reference_swallows_role(title: Optional[str], reference: Optional[str]) -> bool:
    """Czy „numer u klienta” to w istocie nazwa roli z nazwy od klienta.

    Po wycięciu takiego numeru z nazwy nie zostaje żadna litera. Produkcja
    20.10.2026: „PL_IT_Developer_expert_TP#40379 (43020)” z numerem
    „PL_IT_Developer_expert_TP#40379” — CV dostały nagłówek „(43020)”.
    """
    raw = _clean(title)
    if not _LETTER.search(raw) or not client_reference_parts(reference):
        return False
    return not _LETTER.search(_strip_reference(raw, reference))


def client_reference_for_title(
    title: Optional[str],
    reference: Any,
    reference_number: Optional[str] = None,
) -> Optional[str]:
    """Numer u klienta do zapisu: nazwa roli w polu numeru ustępuje numerowi
    z nazwy w znanym formacie (:func:`reference_from_title`) albo pustce."""
    clean = normalize_client_reference(reference)
    if clean and reference_swallows_role(title, clean):
        return reference_from_title(title, reference_number)
    return clean


def _strip_reference(title: str, reference: Optional[str]) -> str:
    out = _ZOB.sub("", title)
    for part in client_reference_parts(reference):
        # Granica bez liter i cyfr: numer „4521” nie wycina kawałka „145210”.
        # Łącznik przed kodem schodzi razem z nim — „Power BI_PKN500023226”
        # zostawiałoby „Power BI_” w nagłówku CV.
        out = re.sub(
            rf"[_\s]*(?<![A-Za-z0-9]){re.escape(part)}(?![A-Za-z0-9])",
            "",
            out,
            flags=re.IGNORECASE,
        )
    # „Programista Java (ZOB 48213)” → bez numeru zostawałyby puste nawiasy.
    return _EMPTY_BRACKETS.sub("", out)


# Dopiski z nazw rekrutacji od klienta, których nie ma w CV (D2, 13.10.2026):
# zmierzone na tytułach produkcji. Każdy wzorzec zdejmuje kawałek z brzegu
# tytułu albo kod; rdzeń roli zostaje bez tłumaczenia.
_CV_TITLE_TRAILING = (
    # „… (51234)”, „… (ZOB-2949)”, „… (ITVM-5894)”: sam numer albo kod z 3–6
    # liter i co najmniej 4 cyframi. „(K8s)”, „(Senior)”, certyfikaty
    # „(PL-300)”, „(AZ-305)”, „(ISO 27001)” i „(SQL 2019)” zostają.
    re.compile(r"\s*[\(\[]\s*(?:\d{3,}|(?!ISO\b)[A-Z]{3,6}[-_]\d{4,})\s*[\)\]]\s*$"),
    # „… RITM0864052”, „…, Pep: 1234”
    re.compile(r"[\s,;:\-–—|/]*\b(?:RITM|REQ)\d+\s*$", re.I),
    # „_PeP: 4985” (26.10.2026): „_” to też granica, a dla ``\b`` — litera.
    re.compile(r"[\s,;_]*(?<![A-Za-z0-9])Pep\s*:?\s*\d+\s*$", re.I),
    # Nordea (26.10.2026, D4): kod stanowiska „_TP#40379”, „- TP ID 40942”.
    re.compile(r"[\s,;_\-–—]*(?<![A-Za-z0-9])TP\s*(?:#|ID\b)\s*\d+\s*$"),
    # „… - Replacement for Jan K”: imię zastępowanej osoby nie idzie ani do
    # klienta, ani do kandydata.
    re.compile(r"[\s,;_\-–—]*(?<![A-Za-z0-9])replacement(?:\s+for\b.*)?\s*$", re.I),
    # „…Power BI_PKN500023226”, „…NIS2_EITERFP2026016”
    re.compile(r"[_\s]+[A-Z]{2,}[A-Z0-9]*\d{5,}\s*$"),
    # „… - 3.iteracja”, „… – 2 tura”
    re.compile(r"\s*[-–—,]\s*\d+\s*\.?\s*(?:iteracja|iteration|tura|edycja)\s*$", re.I),
    # „… x1 CZII Zamówienie 18”: od znacznika liczby osób do końca
    re.compile(r"\s+x\d+\b.*$", re.I),
    re.compile(r"\s*\b(?:zamówienie|zamowienie|order)\s*(?:nr\.?\s*)?\d+\s*$", re.I),
    # „… - MVB project”: nazwa projektu klienta po roli
    re.compile(r"\s*[-–—]\s*[^-–—]{1,40}?\b(?:project|projekt)\s*$", re.I),
    # „(dodatkowy profil)”, „(pilne)”: dopisek procesu, nie rola
    re.compile(
        r"\s*\((?:dodatkowy profil|additional profile|pilne|urgent|replacement)\)\s*$",
        re.I,
    ),
)
_PL_CITY = (
    r"(?:Warsaw|Warszawa|Gdansk|Gdańsk|Gdynia|Sopot|Krakow|Kraków|Cracow|Wroclaw"
    r"|Wrocław|Poznan|Poznań|Lodz|Łódź|Katowice|Szczecin|Lublin|Bydgoszcz|Torun"
    r"|Toruń|Rzeszow|Rzeszów|Bialystok|Białystok|Olsztyn|Kielce|Opole|Remote"
    r"|Zdalnie|Hybrid|Hybrydowo)"
)
_CV_TITLE_LEADING = (
    # „Poland - Warsaw/Gdansk/Gdynia IT Analyst”, „Polska - Java Developer”:
    # tylko kraj i znane miasta, żeby pierwsze słowo roli nie wzięło się za miasto.
    re.compile(
        rf"^(?:Poland|Polska)\s*[-–—]\s*(?:{_PL_CITY}(?:\s*/\s*{_PL_CITY})*"
        r"\s*[-–—]?\s*)?",
        re.I,
    ),
    # „PRJ 4412 - …”, „PEP 4986/ 4987 - …”, „SP1 - …”: kod z separatorem.
    # Bez separatora to technologia roli („MS365 Administrator”, „DB2 …”).
    re.compile(
        r"^(?:[A-Z]{2,}\d+\b\s*[-–—:]\s*"
        r"|[A-Z]{2,}\s\d+(?:\s*/\s*\d+)*\s*[-–—:]\s*)"
    ),
    # „BCCM RRP: SP1 …” — co najmniej dwa skróty projektu z dwukropkiem, razem
    # z kodem tuż po nich. Jeden skrót („SQL: …”, „AWS: …”) zostaje.
    re.compile(r"^(?:[A-Z0-9]{2,}\s+)+[A-Z0-9]{2,}:\s*(?:[A-Z]{2,}\d+\s+)?"),
    # „PL-EBSD-IT Analyst” (co najmniej dwa kody), „RFX-wsparcie…” (kod przed
    # małą literą). „UI-UX Designer” i „SAP-ABAP Developer” zostają.
    re.compile(r"^(?:(?:[A-Z]{2,5}-){2,}(?=[A-Z])|[A-Z]{2,5}-(?=[a-ząćęłńóśźż]))"),
    # Nordea (26.10.2026, D4): „Replacement- …”, kraj „PL_”/„PL - ” (nie
    # „PL/SQL”, „PL-SQL”, „PL_SQL”), kod „PEP4989_”, liczba osób „3 x ”,
    # „…Services_Role: ” (tylko po „_” — „(Key Role: …)” to część nazwy).
    re.compile(r"^replacement\s*[-–—:_]\s*", re.I),
    re.compile(r"^PL\s*[-_–—]\s*(?!SQL\b)"),
    re.compile(r"^PEP\d+[_\s-]+", re.I),
    re.compile(r"^\d+\s*[xX]\s+"),
    re.compile(r"^[^:()]{1,60}?_Role:\s*"),
)


def cv_role_title(
    title: Optional[str],
    client_reference: Optional[str] = None,
    client_names: Iterable[str] = (),
) -> str:
    """Nazwa roli od klienta do nagłówka CV i nazwy pliku (D2, 13.10.2026).

    ``jobs.title`` bez prefiksu klienta, numerów zapytania, kodów projektu,
    lokalizacji i dopisków procesu — bez tłumaczenia i bez zmiany seniority.
    Kody zdejmujemy tylko wtedy, gdy zostaje rola z co najmniej dwóch słów
    albo jednego słowa z co najmniej 4 literami. Nigdy pusty napis, gdy tytuł
    był niepusty. QC CV porównuje nagłówek z tą samą wartością.
    """
    raw = _clean(title)
    if not raw:
        return ""
    names = list(client_names)
    stripped = _clean(_strip_reference(raw, client_reference))
    role = _role_without_codes(stripped or raw, names)
    # 21.10.2026: „numer u klienta” będący całą nazwą roli zostawiał w nagłówku
    # sam numer — „(43020) – Imię Nazwisko” (Nordea). Bez liter to nie rola.
    if stripped != raw and not _LETTER.search(role):
        role = _role_without_codes(raw, names)
    return role


def _role_without_codes(base: str, names: list[str]) -> str:
    # Tylko prefiks klienta ze strony kariery: jej usuwanie nawiasów z cyfrą
    # zjadało „(K8s)” z nazwy roli.
    from app.services.job_public_profile import _strip_client_prefix

    text = _clean(_strip_client_prefix(base, names)) or base
    while True:
        before = text
        for pattern in _CV_TITLE_TRAILING:
            text = pattern.sub("", text).strip(" -–—,/")
        for pattern in _CV_TITLE_LEADING:
            candidate = pattern.sub("", text, count=1).strip(" -–—,/:")
            if _is_role(candidate):
                text = candidate
        text = _clean(_strip_client_prefix(text, names)) or text
        if text == before:
            break
    # Nordea pisze człony nazwy przez „_”: „IT_Developer_expert” to słowa,
    # „Transaction Monitoring_IT Developer Expert” — dwie części nazwy.
    if "_" in text:
        sep = " – " if " " in text else " "
        # „PL_SQL” to technologia, nie kraj przed nazwą.
        text = re.sub(r"\s*(?<!\bPL)_+\s*", sep, text).strip(" –")
    text = _clean(text)
    # „RFX-wsparcie…” → „Wsparcie…”; nazwa bez zmian („iOS Developer”, „dbt
    # Engineer”) zostaje z małej litery.
    if text and text != base and text.split()[0].islower():
        text = text[0].upper() + text[1:]
    return text or base


async def cv_role_title_for_job(db: AsyncSession, job: Any) -> str:
    """:func:`cv_role_title` rekrutacji z bazy — z nazwami i aliasami klienta.

    Jedno wejście dla generatora i kopii CV etapu (plik Word, CV z profilu,
    CV z innej rekrutacji). Do 15.10.2026 kopia brała surowy ``jobs.title``
    i u PKO nazwa pliku miała numer zapytania dwa razy
    („ZOB-2949_… (ZOB-2949)_….docx”), a nagłówek kopii — numer zapytania.
    """
    from app.services.job_public_profile import _client_names

    return cv_role_title(
        job.title,
        getattr(job, "client_reference", None),
        await _client_names(db, job.client_id),
    )


def _is_role(text: str) -> bool:
    words = text.split()
    return len(words) >= 2 or (len(words) == 1 and len(words[0]) >= 4)


def working_title_for_job(job: Any, client_names: Iterable[str] = ()) -> Optional[str]:
    """Tytuł dla rekrutera z Championa, a bez niego z kolumn rekrutacji."""
    from app.services.job_public_profile import (
        _strip_client_prefix,
        default_public_title,
    )

    names = list(client_names)
    reference = getattr(job, "client_reference", None)
    role = champion_view.basics(job).get("role_name")
    if _clean(role):
        # D6 (15.10.2026): rola w Championie bywa przepisaną nazwą od klienta
        # („Nordea: Expert IT Analyst … (42758)”). Klient i numer stoją obok
        # tytułu, więc z roli schodzi tylko prefiks klienta i numer — nie
        # każdy nawias z cyfrą, jak na stronie kariery („(K8s)” zostaje).
        stripped = _strip_client_prefix(
            _clean(_strip_reference(role, reference)), names
        )
        role = stripped if _clean(stripped) else role
    else:
        raw = _strip_reference(job.title or "", reference).rstrip(" _")
        role = default_public_title(raw, names) if _clean(raw) else None
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


def _reference_after_fill(
    current: Optional[str], found: Optional[str]
) -> tuple[Optional[str], str]:
    """Numer po uzupełnieniu i rodzaj zmiany (``""`` = bez zmiany).

    Puste pole dostaje numer z nazwy. Wypełnione zostaje, z dwoma wyjątkami:
    „(42855)” traci nawiasy, a kod Nordei z odczytu maila (PEP…, TP#…)
    ustępuje numerowi z nawiasu w nazwie (D4, 15.10.2026).
    """
    if not _clean(current):
        return (found, "filled") if found else (current, "")
    paren = _PAREN_ONLY.match(current or "")
    if paren:
        return paren.group(1), "normalized"
    if _INTERNAL_CODE.match(current or "") and found and found[0].isdigit():
        return found, "replaced"
    return current, ""


async def fill_client_references_from_titles(
    db: AsyncSession, *, only_job_ids: Optional[set[int]] = None
) -> Optional[dict[str, int]]:
    """Jednorazowo: numer u klienta z nazwy od klienta (15.10.2026).

    Backfill 0380 znał tylko ZOB, więc numer Nordei „(42946)”, BNP „RITM…”,
    Orlenu i Energi „PKN…/EITE…” został wyłącznie w nazwie. Pola nie nadpisuje
    (wyjątki: :func:`_reference_after_fill`), ``updated_at`` nie podbija.
    Potem przelicza automatyczne tytuły dla rekrutera, które dostały numer
    albo zaczynają się nazwą klienta lub zawierają swój numer (D6). Marker
    w ``app_settings`` + advisory lock → drugi start kończy się od razu.
    Wołający commituje. Paragon: same liczby (repo i logi są publiczne).
    ``only_job_ids`` zawęża przebieg — wyłącznie dla testów (bez markera).
    """
    from app.services.job_public_profile import _client_names, _strip_client_prefix

    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:key))"),
        {"key": CLIENT_REFERENCE_MARKER},
    )
    if only_job_ids is None and await db.get(AppSetting, CLIENT_REFERENCE_MARKER):
        return None
    query = select(
        Job.id,
        Job.title,
        Job.reference_number,
        Job.client_reference,
        Job.working_title,
        Job.working_title_auto,
        Job.client_id,
    ).order_by(Job.id)
    if only_job_ids is not None:
        query = query.where(Job.id.in_(only_job_ids))
    rows = (await db.execute(query)).all()
    counts = {"filled": 0, "multi": 0, "normalized": 0, "replaced": 0}
    updates: list[dict[str, Any]] = []
    refresh: list[int] = []
    names_cache: dict[Optional[int], list[str]] = {}
    for row in rows:
        found = reference_from_title(row.title, row.reference_number)
        reference, change = _reference_after_fill(row.client_reference, found)
        if change:
            counts[change] += 1
            counts["multi"] += len(client_reference_parts(reference)) > 1
            updates.append(
                {"jid": row.id, "old": row.client_reference, "cref": reference}
            )
        working = _clean(row.working_title)
        if not row.working_title_auto or not (change or working):
            continue
        if row.client_id not in names_cache:
            names_cache[row.client_id] = await _client_names(db, row.client_id)
        if (
            change
            or _strip_client_prefix(working, names_cache[row.client_id]) != working
            or any(part in working for part in client_reference_parts(reference))
        ):
            refresh.append(row.id)
    if updates:
        table = Job.__table__
        await db.execute(
            table.update()
            .where(
                table.c.id == bindparam("jid"),
                # Ktoś zmienił numer w trakcie — jego wartość wygrywa.
                table.c.client_reference.is_not_distinct_from(
                    bindparam("old", type_=table.c.client_reference.type)
                ),
            )
            .values(client_reference=bindparam("cref"), updated_at=table.c.updated_at),
            updates,
        )
    titles = 0
    for start in range(0, len(refresh), _RECOMPUTE_CHUNK):
        titles += await refresh_working_titles_for_ids(
            db, refresh[start : start + _RECOMPUTE_CHUNK]
        )
    receipt = {
        "jobs_seen": len(rows),
        "client_references": counts["filled"],
        "multi": counts["multi"],
        "normalized": counts["normalized"],
        "replaced_internal_codes": counts["replaced"],
        "working_titles": titles,
    }
    if only_job_ids is None:
        db.add(AppSetting(key=CLIENT_REFERENCE_MARKER, value=receipt))
    return receipt
