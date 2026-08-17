"""Ekstrakcja faktów z notatek rekruterskich → ``cv_extracted_data._notes_insights``.

Repo-izacja i konsolidacja czterech ad-hocowych skryptów z importu 08.2026
(``notes_extract_full`` v1, ``notes_extract_v2``, ``notes_ingest``,
``notes_fill_columns``), które do tej pory żyły wyłącznie na serwerze prod.
Jeden prompt (unia schematów v1+v2), jedna polityka zapisu, jeden punkt wejścia
dla pętli cyklicznej (``app.tasks.notes_insights_sync``).

Inwarianty (z decyzji importu — nie zmieniać bez powrotu do nich):
- Notatki NIGDY nie trafiają do wektorów ani do promptów uzasadnień —
  ekstrakcja jest jedynym wywołaniem AI, a jej wynik jest strukturalny.
- ``client_vetoes`` są ZAPISYWANE do insights, ale nigdy nie tworzą
  automatycznie konfliktów — przegląd ręczny.
- Kolumny kandydata wypełniamy FILL_EMPTY; jedyny dozwolony overwrite to
  stawka, którą sami wcześniej wpisaliśmy z notatek (marker ``_rate_from_notes``
  albo równość kolumny z poprzednią wartością insights).
- Skills: APPEND z dedupem przez ``normalize_llm_skills``; kandydat z
  ``_manual_override_skills`` jest nietykalny.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Optional, Sequence

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified
from starlette.concurrency import run_in_threadpool

from app.models.candidate import AvailabilityStatus, Candidate
from app.services.cv_enrichment import normalize_llm_skills

logger = logging.getLogger(__name__)

# Bump przy każdej zmianie promptu/schematu — wchodzi do fingerprinta, więc
# unieważnia ekstrakcje policzone starszą wersją (płacą ponownie dopiero gdy
# pętla do nich dojdzie, w ramach budżetu per bieg).
PROMPT_VERSION = "v3-union"
EXTRACTION_MODEL = "claude-haiku-4-5-20251001"
NOTES_LIMIT = 20
BLOB_CHAR_LIMIT = 12000
MIN_BLOB_CHARS = 60

# Unia schematów v1 (stawka/dostępność/preferencje/języki/veta) i v2
# (umiejętności z dowodami, zaangażowanie, relokacja, uprawnienia).
PROMPT = """Z wewnętrznych notatek rekruterów o kandydacie wyciągnij FAKTY do struktury JSON (dane do dopasowywania kandydata do projektów — nic nie trafia do klienta):
{
 "expected_rate": {"value": float|null, "currency": str|null, "period": "h"|"md"|"month"|null, "raw": str|null, "as_of": "YYYY-MM"|null},
 "rate_flexibility": str|null,
 "availability": {"raw": str|null, "notice_period": str|null, "available_from": str|null},
 "not_looking_until": str|null,
 "current_engagement": {"employer": str|null, "project": str|null, "ends_at": str|null, "raw": str|null},
 "preferences": {"remote_only": bool|null, "locations": [str], "sectors_prefer": [str], "sectors_avoid": [str], "other": str|null},
 "relocation": {"willing": bool|null, "targets": [str]},
 "contract_form_preference": "b2b"|"uop"|"any"|null,
 "languages_observed": [{"name": str, "level": str|null}],
 "skills_evidenced": [{"name": str, "evidence": str}],
 "skills_gaps_observed": [{"name": str, "evidence": str}],
 "certifications": [str],
 "years_confirmed": int|null,
 "work_permit_status": str|null,
 "security_clearance": str|null,
 "client_vetoes": [{"client": str, "reason": str}],
 "matching_facts": str|null
}
Zasady:
- WYŁĄCZNIE fakty z notatek — zero domysłów; brak informacji = null/pusta lista.
- Daty notatek w nagłówkach [YYYY-MM-DD]; przy sprzecznościach NAJNOWSZA wzmianka
  wygrywa (dla stawki wpisz jej datę jako "as_of").
- "skills_evidenced": tylko umiejętności realnie POTWIERDZONE w rozmowie /
  screeningu / odpowiedziach (evidence = krótki cytat lub parafraza z notatki).
  NIE przepisuj skilli wspomnianych wyłącznie jako "w CV".
- "skills_gaps_observed": wyłącznie braki techniczne nazwane wprost; ZERO ocen
  miękkich i opinii personalnych.
- "matching_facts": 2-3 zdania samych faktów istotnych przy doborze, bez opinii.
Zwróć SAM JSON.

NOTATKI (od najnowszej):
"""

# Klucze przenoszone 1:1 z odpowiedzi modelu do insights (niepuste wartości).
_INSIGHT_KEYS = (
    "expected_rate",
    "rate_flexibility",
    "availability",
    "not_looking_until",
    "current_engagement",
    "preferences",
    "relocation",
    "contract_form_preference",
    "languages_observed",
    "skills_evidenced",
    "skills_gaps_observed",
    "certifications",
    "years_confirmed",
    "work_permit_status",
    "security_clearance",
    "client_vetoes",
    "matching_facts",
)

_NOTICE_RE = re.compile(
    r"(\d+)\s*(tydz|tyg|week|mies|miesiąc|miesiec|month|dni|dzień|dzien|day|mc)", re.I
)
_ASAP_RE = re.compile(r"od zaraz|asap|natychmiast|od ręki|immediately", re.I)
_ISO_RE = re.compile(r"(\d{4})-(\d{1,2})-(\d{1,2})")


async def load_note_rows(db: AsyncSession, candidate_id: int) -> list[tuple]:
    """(id, updated_at, created_at::date, content) — najnowsze najpierw."""
    result = await db.execute(
        text(
            "SELECT id, updated_at, created_at::date AS d, content FROM notes "
            "WHERE candidate_id = :c ORDER BY created_at DESC LIMIT :lim"
        ),
        {"c": candidate_id, "lim": NOTES_LIMIT},
    )
    return list(result.all())


def notes_fingerprint(rows: Sequence[tuple]) -> str:
    """Odcisk wejścia: id+updated_at notatek + wersja promptu + model.

    Zmiana dowolnej składowej → kandydat płaci ponownie; brak zmian → pętla
    pomija bez wywołania AI. To jest cały mechanizm "tylko zmienieni płacą".
    """
    payload = json.dumps(
        {
            "prompt": PROMPT_VERSION,
            "model": EXTRACTION_MODEL,
            "notes": sorted((int(r[0]), str(r[1] or "")) for r in rows),
        },
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def build_notes_blob(rows: Sequence[tuple]) -> str:
    blob = "\n\n".join(f"[{r[2]}]\n{r[3]}" for r in rows if r[3])
    return blob[:BLOB_CHAR_LIMIT]


async def extract_insights(notes_blob: str) -> dict:
    """Jedno wywołanie Haiku → sparsowany dict (unia v1+v2).

    Rzuca przy błędzie transportu/parsowania — wołający decyduje, czy liczy to
    jako błąd biegu, czy pomija kandydata.
    """
    from app.services.claude_client import call_claude

    msg = await run_in_threadpool(
        call_claude,
        model=EXTRACTION_MODEL,
        max_tokens=2500,
        temperature=0,
        thinking={"type": "disabled"},
        messages=[{"role": "user", "content": PROMPT + notes_blob}],
    )
    raw = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
    start, end = raw.find("{"), raw.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("brak obiektu JSON w odpowiedzi modelu")
    return json.loads(raw[start : end + 1])


def _safe_rate_value(raw: Any) -> Optional[float]:
    """Wartość stawki z odpowiedzi modelu — liczba albo None, NIGDY wyjątek.

    Haiku potrafi zwrócić "150-200" lub inny nienumeryczny string; goły
    ``float(value)`` rzucałby wtedy z ``apply_insights``, kandydat lądowałby
    w ``errors`` bez zapisu ``_input_hash`` i wracał do selekcji każdego dnia
    — pętla-trucizna zjadająca budżet biegu. Stringi numeryczne ("150")
    przechodzą, bo import 08.2026 zapisywał wartości modelu verbatim i takie
    wiersze istnieją w ``prior``.
    """
    if isinstance(raw, bool) or raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _parse_notice(raw: Any) -> Optional[tuple[int, str]]:
    if not isinstance(raw, str):
        return None
    m = _NOTICE_RE.search(raw)
    if not m:
        return None
    n, unit = int(m.group(1)), m.group(2).lower()
    if unit.startswith(("tydz", "tyg", "week")):
        return n, "weeks"
    if unit.startswith(("mies", "month", "mc")):
        return n, "months"
    return n, "days"


def apply_insights(
    candidate: Candidate,
    parsed: dict,
    *,
    fingerprint: str,
    now_iso: Optional[str] = None,
) -> dict[str, int]:
    """Zastosuj wynik ekstrakcji do kandydata (mutuje obiekt ORM, bez commitu).

    Zwraca statystyki zmian; ``changed`` > 0 oznacza, że wołający powinien
    zbudować reindeks + unieważnić cache score'ów tego kandydata.
    """
    stats = {
        "changed": 0,
        "skills_added": 0,
        "years_filled": 0,
        "rate_written": 0,
        "rate_updated": 0,
        "notice_filled": 0,
        "avail_date_filled": 0,
        "status_set": 0,
        "locked_skills": 0,
    }
    now = now_iso or datetime.now(timezone.utc).isoformat()
    extracted = (
        dict(candidate.cv_extracted_data)
        if isinstance(candidate.cv_extracted_data, dict)
        else {}
    )
    prior = extracted.get("_notes_insights")
    prior = prior if isinstance(prior, dict) else {}
    insights: dict[str, Any] = {}
    for key in _INSIGHT_KEYS:
        value = parsed.get(key)
        if value not in (None, [], {}):
            insights[key] = value
    insights["_extracted_at"] = now
    insights["_v2_extracted_at"] = now
    insights["_extractor"] = f"notes_insights:{PROMPT_VERSION}:haiku-4.5"
    insights["_input_hash"] = fingerprint

    changed = False

    # ── skills: APPEND z dedupem, szanuj ręczną blokadę ────────────────────
    evidenced = parsed.get("skills_evidenced") or []
    if evidenced and extracted.get("_manual_override_skills"):
        stats["locked_skills"] = 1
    elif evidenced:
        names = [
            s.get("name") for s in evidenced if isinstance(s, dict) and s.get("name")
        ]
        normalized = normalize_llm_skills(names) or []
        existing = candidate.skills if isinstance(candidate.skills, list) else []
        have = {
            str(s.get("name", "")).casefold() for s in existing if isinstance(s, dict)
        }
        new_items = [s for s in normalized if s["name"].casefold() not in have]
        if new_items:
            candidate.skills = existing + new_items
            stats["skills_added"] = len(new_items)
            changed = True

    # ── years_confirmed → years_it_experience (FILL_EMPTY) ─────────────────
    yc = parsed.get("years_confirmed")
    if (
        candidate.years_it_experience is None
        and isinstance(yc, (int, float))
        and not isinstance(yc, bool)
        and 0 < yc <= 60
    ):
        candidate.years_it_experience = int(yc)
        stats["years_filled"] = 1
        changed = True

    # ── expected_rate → kolumna: FILL_EMPTY + aktualizacja własnego wpisu ──
    rate = (
        parsed.get("expected_rate")
        if isinstance(parsed.get("expected_rate"), dict)
        else {}
    )
    value = _safe_rate_value(rate.get("value"))
    if value is not None and rate.get("period") == "h" and 0 < value < 2000:
        new_rate = Decimal(str(value))
        if candidate.expected_rate_hourly is None:
            candidate.expected_rate_hourly = new_rate
            if not candidate.expected_rate_currency:
                candidate.expected_rate_currency = (rate.get("currency") or "PLN")[:3]
            insights["_rate_from_notes"] = True
            stats["rate_written"] = 1
            changed = True
        else:
            # Overwrite dozwolony wyłącznie dla wartości, którą sami wpisaliśmy
            # z notatek (marker albo równość z poprzednią ekstrakcją) — świeższa
            # notatka aktualizuje nasz własny wpis, nigdy ludzki.
            prior_rate = prior.get("expected_rate")
            prior_value = _safe_rate_value(
                prior_rate.get("value") if isinstance(prior_rate, dict) else None
            )
            ours = bool(prior.get("_rate_from_notes")) or (
                prior_value is not None
                and candidate.expected_rate_hourly == Decimal(str(prior_value))
            )
            if ours and candidate.expected_rate_hourly != new_rate:
                candidate.expected_rate_hourly = new_rate
                insights["_rate_from_notes"] = True
                stats["rate_updated"] = 1
                changed = True
            elif ours:
                insights["_rate_from_notes"] = True

    # ── dostępność → kolumny (FILL_EMPTY) ──────────────────────────────────
    availability = parsed.get("availability")
    availability = availability if isinstance(availability, dict) else {}
    if candidate.notice_period is None:
        parsed_notice = _parse_notice(
            availability.get("notice_period")
        ) or _parse_notice(availability.get("raw"))
        if parsed_notice:
            candidate.notice_period, candidate.notice_period_unit = parsed_notice
            stats["notice_filled"] = 1
            changed = True
    if candidate.availability_date is None:
        m = _ISO_RE.search(str(availability.get("available_from") or ""))
        if m:
            try:
                candidate.availability_date = date(
                    int(m.group(1)), int(m.group(2)), int(m.group(3))
                )
                stats["avail_date_filled"] = 1
                changed = True
            except ValueError:
                pass
    raw_txt = " ".join(
        str(availability.get(k) or "")
        for k in ("raw", "notice_period", "available_from")
    )
    current_status = getattr(
        candidate.availability_status, "value", candidate.availability_status
    )
    if current_status == "unknown" and _ASAP_RE.search(raw_txt):
        candidate.availability_status = AvailabilityStatus.actively_looking
        stats["status_set"] = 1
        changed = True

    extracted["_notes_insights"] = insights
    candidate.cv_extracted_data = extracted
    flag_modified(candidate, "cv_extracted_data")
    stats["changed"] = 1 if changed else 0
    return stats


def legacy_row_is_fresh(
    prior_insights: Any, latest_note_at: Optional[datetime]
) -> bool:
    """Czy ekstrakcja sprzed wprowadzenia fingerprinta jest nadal aktualna.

    Import 08.2026 zapisał insights BEZ ``_input_hash``. Traktowanie ich
    wszystkich jako przeterminowane oznaczałoby ponowne płacenie za ~14k
    kandydatów bez żadnej zmiany w danych. Zamiast tego: wiersz legacy jest
    świeży, dopóki kandydat nie dostał notatki NOWSZEJ niż jego znacznik
    ekstrakcji — wtedy (i tylko wtedy) płaci ponownie, już z fingerprintem.
    """
    if not isinstance(prior_insights, dict):
        return False
    stamp_raw = prior_insights.get("_v2_extracted_at") or prior_insights.get(
        "_extracted_at"
    )
    if not isinstance(stamp_raw, str):
        return False
    try:
        stamp = datetime.fromisoformat(stamp_raw)
    except ValueError:
        return False
    if latest_note_at is None:
        return True
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    latest = latest_note_at
    if latest.tzinfo is None:
        latest = latest.replace(tzinfo=timezone.utc)
    return latest <= stamp
