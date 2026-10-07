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

from app.core.terminal_failure import terminal_operation
from app.models.candidate import Candidate
from app.services.cv_enrichment import normalize_llm_skills
from app.models.ai_feature import AIFeatureKey
from app.services import note_kinds
from app.services.recommendation_card_parser import AI_HIDDEN_FIELDS, redact_card_text
from app.services.ai_models import fallbacks_for, model_for

logger = logging.getLogger(__name__)

# Bump przy każdej zmianie promptu/schematu — wchodzi do fingerprinta, więc
# unieważnia ekstrakcje policzone starszą wersją (płacą ponownie dopiero gdy
# pętla do nich dojdzie, w ramach budżetu per bieg). Bump NIE przelicza
# korpusu wstecz — `_select_stale_candidates` wybiera po dacie notatki vs
# stemplu ekstrakcji, fingerprint tu tylko pomija duplikaty w pętli.
# v6 (03.10.2026): prompt bez zmian, zmienia się WSAD — model nie dostaje już
# wpisów automatu, maili, „nie odbiera”, terminów ani wpisów Delivery Leada
# o stawce do klienta (`note_kinds.FACTS_EXCLUDED_KINDS`), a karty rekomendacji
# idą pierwsze. Nowa wersja = doganianie przeliczy fakty policzone ze starego
# wsadu („Wyślijmy za 161 zł/h” bywało czytane jako stawka kandydata).
PROMPT_VERSION = "v6-note-kinds"
EXTRACTION_MODEL = model_for(AIFeatureKey.notes_extraction)
NOTES_LIMIT = 20
BLOB_CHAR_LIMIT = 12000
# Jedna długa notatka nie może zjeść całego wsadu (pomiar 03.10.2026: u 858
# kandydatów wsad był ucięty, u 359 przez jeden wątek mailowy).
NOTE_CHAR_LIMIT = 4000
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
 "preferences": {"remote_only": bool|null, "work_modes": ["remote"|"hybrid"|"onsite"], "max_onsite_days_per_week": int|null, "locations": [str], "sectors_prefer": [str], "sectors_avoid": [str], "other": str|null},
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
- "work_modes": tryby pracy, które kandydat WPROST akceptuje: "remote"
  (zdalnie), "hybrid" (hybrydowo / część dni w biurze), "onsite"
  (stacjonarnie / codziennie w biurze). Kilka, gdy akceptuje kilka
  ("hybrydowo albo stacjonarnie" = ["hybrid","onsite"]); brak wzmianki = [].
- "max_onsite_days_per_week": TYLKO gdy kandydat wprost nazwał limit dni w
  biurze (0-7; "tylko zdalnie"/"wyłącznie zdalnie" = 0; "hybryda 2 dni w
  biurze" = 2; "raz w tygodniu" = 1; "stacjonarnie 5 dni" = 5); bez liczby
  wprost → null. Nie zgaduj liczby z samego słowa "hybrydowo".
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


async def load_note_rows(db: AsyncSession, candidate_id: int) -> list[tuple]:
    """(id, updated_at, dzień warszawski created_at, content, dzień notatki).

    Najnowsze najpierw. Ostatnia kolumna to dzień warszawski
    ``coalesce(source_created_at, created_at)`` — od niego liczymy dostępność
    z notatek (``notes_profile_fill.notes_days``, decyzja 07.10.2026).

    Runda 8 (R8-X1-5): dzień notatki liczony w Europe/Warsaw, nie w UTC sesji —
    notatka z 00:30 dostawała w prompcie datę poprzedniego dnia, a model liczył
    od niej dostępność („od przyszłego miesiąca”).
    """
    return (await load_note_rows_bulk(db, [candidate_id])).get(candidate_id, [])


async def load_note_rows_bulk(
    db: AsyncSession, candidate_ids: Sequence[int]
) -> dict[int, list[tuple]]:
    """``load_note_rows`` dla wielu kandydatów naraz — TEN SAM wybór notatek.

    Jedyne miejsce, które wybiera notatki wejścia odczytu: nocna ekstrakcja
    (przez ``load_note_rows``) i domknięcie historii
    (``notes_profile_backfill``) liczą z nich ten sam „dzień notatki”.
    """
    if not candidate_ids:
        return {}
    # Wybór: tylko notatki, które wolno czytać modelowi; karty rekomendacji
    # i fakty ze screeningu mają pierwszeństwo przed limitem (u 373 kandydatów
    # karta wypadała poza 20 najnowszych). Wynik nadal od najnowszej.
    priority = ", ".join(f"'{kind}'" for kind in note_kinds.AI_PRIORITY_KINDS)
    result = await db.execute(
        text(
            "SELECT candidate_id, id, updated_at, "
            "(created_at AT TIME ZONE 'Europe/Warsaw')::date AS d, content, "
            "(COALESCE(source_created_at, created_at) AT TIME ZONE 'Europe/Warsaw')"
            "::date AS note_day "
            "FROM ("
            "SELECT candidate_id, id, updated_at, created_at, source_created_at, "
            "content, row_number() OVER (PARTITION BY candidate_id "
            f"ORDER BY (kind IN ({priority})) DESC NULLS LAST, created_at DESC) "
            "AS rn FROM notes "
            f"WHERE candidate_id = ANY(:ids) AND {note_kinds.facts_readable_sql()}"
            ") picked WHERE rn <= :lim ORDER BY candidate_id, created_at DESC"
        ),
        {"ids": list(candidate_ids), "lim": NOTES_LIMIT},
    )
    out: dict[int, list[tuple]] = {}
    for row in result.all():
        out.setdefault(row[0], []).append(tuple(row[1:]))
    return out


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


# Szacunek scrapera w notatce formularza aplikacji (audyt 06.10.2026, D5):
# „→ szacunek stawki B2B: 48 zł/h netto (dolny próg widełek ÷ 168 h) — …”.
# To dolny próg widełek UoP podzielony przez godziny, nie stawka podana przez
# kandydata — model czytał go jako oczekiwaną stawkę B2B i wpisywał z powrotem
# stawkę cofniętą narzędziem ``scraper_rate_revert``. Linia ginie przed
# modelem; reszta notatki (widełki miesięczne) zostaje. ``[^<\n]*`` — notatka
# bywa HTML-em w jednej linii.
_SCRAPER_RATE_ESTIMATE_RE = re.compile(
    r"(?:→|-&gt;|->)?[ \t]*szacunek stawki B2B:[^<\n]*", re.IGNORECASE
)


def strip_scraper_rate_estimate(content: str) -> str:
    return _SCRAPER_RATE_ESTIMATE_RE.sub("", content)


def build_notes_blob(rows: Sequence[tuple]) -> str:
    # 0413: narodowość z karty rekomendacji nie trafia do żadnego modelu.
    blob = "\n\n".join(
        f"[{r[2]}]\n"
        + redact_card_text(strip_scraper_rate_estimate(r[3]), AI_HIDDEN_FIELDS)[
            :NOTE_CHAR_LIMIT
        ]
        for r in rows
        if r[3]
    )
    return blob[:BLOB_CHAR_LIMIT]


def _close_open_json(text_value: str) -> str:
    """Domknij urwane stringi/nawiasy w uciętym JSON-ie (konserwatywnie).

    Pierwszy bieg na prodzie pokazał realny przypadek: bogate notatki →
    odpowiedź ucięta na max_tokens w środku tablicy → JSONDecodeError →
    kandydat w ``errors`` i codzienna reselekcja. Domknięcie traci najwyżej
    ogon dokumentu — częściowe insights są lepsze niż wieczny błąd. Na
    poprawnym JSON-ie to no-op (pusty stos, poza stringiem).
    """
    stack: list[str] = []
    in_string = False
    escaped = False
    for ch in text_value:
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch in "{[":
            stack.append(ch)
        elif ch in "}]":
            if stack:
                stack.pop()
    repaired = text_value
    if in_string:
        repaired += '"'
    for opener in reversed(stack):
        repaired += "}" if opener == "{" else "]"
    return repaired


def _validated_insights(parsed: Any) -> dict:
    """Reject malformed container shapes before any candidate fields are written."""
    if not isinstance(parsed, dict):
        raise ValueError("invalid_notes_response")
    objects = {
        "expected_rate",
        "availability",
        "current_engagement",
        "preferences",
        "relocation",
    }
    object_lists = {
        "languages_observed",
        "skills_evidenced",
        "skills_gaps_observed",
        "client_vetoes",
    }
    for key in _INSIGHT_KEYS:
        value = parsed.get(key)
        if value is None:
            continue
        if key in objects:
            valid = isinstance(value, dict)
        elif key in object_lists:
            valid = isinstance(value, list) and all(
                isinstance(item, dict) for item in value
            )
        elif key == "certifications":
            valid = isinstance(value, list) and all(
                isinstance(item, str) for item in value
            )
        elif key == "years_confirmed":
            valid = isinstance(value, (int, float)) and not isinstance(value, bool)
        else:
            valid = isinstance(value, str)
        if not valid:
            raise ValueError("invalid_notes_field_type")
    return parsed


_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
# Z separatorem tysięcy („1 200”) i bez — „150 160” to też dwie osobne liczby.
_GROUPED_NUMBER_RE = re.compile(r"\d{1,3}(?:[ \u00a0]\d{3})+(?:[.,]\d+)?")
_PLAIN_NUMBER_RE = re.compile(r"\d+(?:[.,]\d+)?")


def _numbers_in(text_value: str) -> set[Decimal]:
    """Liczby zapisane w notatkach (bez dat z nagłówków ``[RRRR-MM-DD]``)."""
    found: set[Decimal] = set()
    cleaned = _DATE_RE.sub(" ", text_value)
    tokens = _GROUPED_NUMBER_RE.findall(cleaned) + _PLAIN_NUMBER_RE.findall(cleaned)
    for token in tokens:
        compact = token.replace(" ", "").replace("\u00a0", "").replace(",", ".")
        try:
            found.add(Decimal(compact))
        except ArithmeticError:
            continue
    return found


def _drop_ungrounded_rate(parsed: dict, notes_blob: str) -> dict:
    """Stawka, której kwoty nie ma w notatkach, nie wchodzi do profilu.

    Każdy model czasem dopisuje wartość spoza tekstu (pomiar 22.09.2026:
    0,15–0,55 takich wartości na kandydata), a stawka PLN/h z notatek zasila
    bramkę budżetu. Kwota zostaje w ``ungrounded_value`` — do wglądu, nie do
    zapisu.
    """
    rate = parsed.get("expected_rate")
    if not isinstance(rate, dict):
        return parsed
    # Do profilu idzie wyłącznie PLN/h; „UoP od 20 tysięcy” miesięcznie model
    # słusznie zamienia na 20000, a ta kwota zostaje tylko na karcie.
    if str(rate.get("currency") or "").upper() != "PLN" or rate.get("period") != "h":
        return parsed
    value = rate.get("value")
    if value is None or isinstance(value, bool):
        return parsed
    try:
        amount = Decimal(str(value))
    except ArithmeticError:
        return parsed
    if amount in _numbers_in(notes_blob):
        return parsed
    parsed["expected_rate"] = {**rate, "value": None, "ungrounded_value": value}
    return parsed


@terminal_operation("notes-extraction")
async def extract_insights(notes_blob: str) -> dict:
    """Jedno wywołanie Haiku → sparsowany dict (unia v1+v2).

    Rzuca przy błędzie transportu/parsowania — wołający decyduje, czy liczy to
    jako błąd biegu, czy pomija kandydata.
    """
    from app.services.claude_client import call_claude

    msg = await run_in_threadpool(
        call_claude,
        model=EXTRACTION_MODEL,
        fallback_models=fallbacks_for(AIFeatureKey.notes_extraction),
        # 4000, nie 2500: unia schematów v1+v2 przy bogatych notatkach
        # potrafiła przekroczyć 2500 i ucinała JSON (prod, id=25176).
        max_tokens=4000,
        temperature=0,
        thinking={"type": "disabled"},
        messages=[{"role": "user", "content": PROMPT + notes_blob}],
    )
    raw = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
    start = raw.find("{")
    if start < 0:
        raise ValueError("brak obiektu JSON w odpowiedzi modelu")
    payload = raw[start : raw.rfind("}") + 1] if raw.rfind("}") > start else raw[start:]
    try:
        parsed = _validated_insights(json.loads(payload))
    except json.JSONDecodeError:
        # Naprawa dostaje PEŁNY ogon (raw[start:]), nie payload ucięty na
        # ostatnim '}' — przy uciętej odpowiedzi wcześniejszy wewnętrzny '}'
        # obcinał wszystko za sobą, zanim naprawa cokolwiek zobaczyła.
        # Postamble po poprawnym JSON-ie nieosiągalny: wtedy pierwszy parse
        # payloadu po prostu się udaje.
        parsed = _validated_insights(json.loads(_close_open_json(raw[start:])))
    return _drop_ungrounded_rate(parsed, notes_blob)


def stamp_no_content(
    candidate: Candidate, *, fingerprint: str, now_iso: Optional[str] = None
) -> None:
    """Ostempluj kandydata bez ekstrahowalnych notatek (bez wywołania AI).

    Bez tego stempla kandydaci ze śladowymi notatkami (klasa „no_content"
    z importu 08.2026, ~setki–tysiące) wracali do selekcji KAŻDEGO dnia
    i zjadali cały budżet biegu na pomijanie samych siebie — pierwszy bieg
    na prodzie: selected=300, skipped_short=299, extracted=0. Stempel
    zachowuje ewentualne istniejące fakty (aktualizuje tylko meta-klucze),
    a zmiana notatek w przyszłości unieważnia go przez znacznik czasu.
    """
    now = now_iso or datetime.now(timezone.utc).isoformat()
    extracted = (
        dict(candidate.cv_extracted_data)
        if isinstance(candidate.cv_extracted_data, dict)
        else {}
    )
    prior = extracted.get("_notes_insights")
    insights = dict(prior) if isinstance(prior, dict) else {}
    insights["_input_hash"] = fingerprint
    insights["_extracted_at"] = now
    insights["_v2_extracted_at"] = now
    insights["_no_content"] = True
    extracted["_notes_insights"] = insights
    candidate.cv_extracted_data = extracted
    flag_modified(candidate, "cv_extracted_data")


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


def apply_insights(
    candidate: Candidate,
    parsed: dict,
    *,
    fingerprint: str,
    now_iso: Optional[str] = None,
    as_of: Optional[date] = None,
    latest_note_day: Optional[date] = None,
) -> dict[str, Any]:
    """Zastosuj wynik ekstrakcji do kandydata (mutuje obiekt ORM, bez commitu).

    ``as_of`` — dzień najnowszej notatki wejścia, która mówi o dostępności
    (``notes_days(rows).availability``): od niego liczymy „od zaraz” i okres
    wypowiedzenia, nie od dziś. ``latest_note_day`` — dzień najnowszej
    notatki wejścia (``notes_days(rows).latest``), odniesienie dla pełnej daty
    i miesiąca, gdy notatki o dostępności nie ma.

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
        "avail_date_updated": 0,
        "avail_date_cleared": 0,
        "status_set": 0,
        "locked_skills": 0,
        "onsite_days_filled": 0,
        "remote_modes_filled": 0,
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
    insights["_extractor"] = f"notes_insights:{PROMPT_VERSION}:{EXTRACTION_MODEL}"
    insights["_input_hash"] = fingerprint

    changed = False

    # ── skills: APPEND z dedupem, szanuj ręczną blokadę ────────────────────
    evidenced = parsed.get("skills_evidenced") or []
    if evidenced and (
        extracted.get("_manual_override_skills")
        or getattr(candidate, "skills_manually_curated", False)
    ):
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

    # ── expected_rate → kolumna: FILL_EMPTY + aktualizacja własnego wpisu ──
    rate = (
        parsed.get("expected_rate")
        if isinstance(parsed.get("expected_rate"), dict)
        else {}
    )
    from app.services.candidate_profile_rate import write_profile_rate

    value = _safe_rate_value(rate.get("value"))
    currency = str(rate.get("currency") or "").strip().upper()
    prior_write = prior.get("_rate_written")
    version = getattr(candidate, "profile_rate_version", 0) or 0
    # Legacy boolean markers or coincidentally equal amounts prove no ownership.
    ours = isinstance(prior_write, dict) and prior_write == {
        "amount": str(candidate.expected_rate_hourly),
        "currency": candidate.expected_rate_currency,
        "version": version,
    }
    if ours:
        insights["_rate_from_notes"] = True
        insights["_rate_written"] = prior_write
    if value is not None:
        if currency != "PLN" or rate.get("period") != "h":
            # Retain the raw pair in insights for review; never relabel foreign
            # currency or infer an absent currency as canonical PLN/hour.
            insights["_rate_requires_verification"] = True
        elif (
            0 < value < 2000
            and not extracted.get("_manual_override_rate")
            and (candidate.expected_rate_hourly is None or ours)
        ):
            new_rate = Decimal(str(value)).quantize(Decimal("0.01"))
            if (
                candidate.expected_rate_hourly != new_rate
                or candidate.expected_rate_currency != "PLN"
            ):
                was_empty = candidate.expected_rate_hourly is None
                stats["rate_audit"] = write_profile_rate(
                    candidate, new_rate, source="notes_ai"
                )
                stats["rate_written" if was_empty else "rate_updated"] = 1
                changed = True
            insights["_rate_from_notes"] = True
            insights["_rate_written"] = {
                "amount": str(candidate.expected_rate_hourly),
                "currency": candidate.expected_rate_currency,
                "version": candidate.profile_rate_version,
            }

    # ── lata, dostępność, okres wypowiedzenia, tryb pracy (FILL_EMPTY) ─────
    # Jedna reguła z jednorazowym domknięciem historii
    # (`notes_profile_fill.plan_profile_fill`): wartość człowieka i CV zostaje
    # zawsze, dostępność liczona od dnia notatki („stan na” w znaczniku).
    from app.services.notes_profile_fill import apply_profile_fill, plan_profile_fill

    had_date = candidate.availability_date is not None
    changes, markers = plan_profile_fill(
        candidate,
        parsed,
        prior=prior,
        as_of=as_of,
        latest_note_day=latest_note_day,
        # Notatka o dostępności zniknęła albo zmieniła treść — data, którą
        # sami wpisaliśmy, nie może zostać jako fakt bez źródła (07.10.2026).
        release_stale_availability=True,
    )
    apply_profile_fill(candidate, changes)
    insights.update(markers)
    for field, key in (
        ("years_it_experience", "years_filled"),
        ("notice_period", "notice_filled"),
        ("availability_status", "status_set"),
        ("remote_modes", "remote_modes_filled"),
        ("max_onsite_days_per_week", "onsite_days_filled"),
    ):
        if field in changes:
            stats[key] = 1
    if "availability_date" in changes:
        if changes["availability_date"] is None:
            stats["avail_date_cleared"] = 1
        else:
            stats["avail_date_updated" if had_date else "avail_date_filled"] = 1
    if changes:
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
