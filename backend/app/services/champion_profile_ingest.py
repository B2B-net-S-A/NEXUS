"""Ingest profili Championa z plików rekrutacji Traffita (runda 3).

Produkcyjny następca ad-hocowych ``scripts/adhoc_2026_08_champion_notes/
{champ_parse_v3,champ_ingest}.py`` (import 949 ofert, 13-14.08). Powód
istnienia: Integration API Traffita NIE wystawia plików rekrutacji (tylko
kandydackie), a sesyjny endpoint webowy (``/api/file/fileContent/{id}``,
~0,2 s — namierzony 18.08, wcześniej znana ścieżka wisiała >45 s) działa
WYŁĄCZNIE z cookies zalogowanej przeglądarki. Serwer nie ma więc jak sam
pobrać pliku — pobiera collector w sesji Chrome i POST-uje bajty tutaj.

Kontrakt zapisu jest 1:1 z importem sierpniowym (te same semantyki, ten sam
kształt ``champion_dict``): FILL_EMPTY na ``jobs.champion_profile`` oraz na
``must_skills``/``nice_skills`` — profil uzupełnia braki, nigdy nie nadpisuje
istniejących danych; reindeks oferty + ``mark_stale_for_job`` (outbox nie robi
stale dla ofert — bez tego cache serwowałby score'y sprzed Championa).
"""

from __future__ import annotations

import io
import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.models.job import Job

logger = logging.getLogger(__name__)

MAX_FILE_BYTES = 10 * 1024 * 1024
ALLOWED_EXTENSIONS = ("docx", "pdf")
PARSE_MODEL = "claude-haiku-4-5-20251001"

# Prompt v3 — sprawdzony na 1095 plikach importu sierpniowego. Zmiana treści
# = inne wyniki parsowania; bump wersji w _parser przy każdej edycji.
PARSER_VERSION = "champion_parse:v3:haiku-4.5"

PROMPT = """Z dokumentu "Profil Championa" (opis idealnego kandydata uzgodniony z klientem; sekcje: informacje o projekcie, profil kandydata MUST/NICE, kontekst projektu, screening, success strategy, informacja o kliencie, standardy rekrutacji) wyciągnij DOKŁADNIE tę strukturę JSON:
{
 "role_name": str|null,
 "seniority_min_years": int|null,          // np. z "Minimum 10 lat doświadczenia"
 "must_skills": [{"name": str}],           // sekcja MUST-HAVE, punkt=wpis, skracaj do esencji
 "nice_skills": [{"name": str}],           // sekcja NICE-TO-HAVE
 "rate_value": float|null,                 // sama liczba, np. 122.50
 "rate_raw": str|null,                     // stawka dokładnie jak w dokumencie
 "location": str|null,                     // lokalizacja kandydata/biura
 "work_mode": "stacjonarnie"|"hybrydowo"|"zdalnie"|null,
 "basics": {"onsite_days_per_week": int|null, "candidate_location_pref": str|null, "language": str|null},
 "start_date": str|null,
 "contract_length": str|null,              // np. "3-5 miesięcy z możliwością przedłużenia"
 "sectors": [str],                         // branże z wymagań/kontekstu (banking, fintech, płatności...)
 "project_context": {"about": str, "responsibilities": str, "selling_points": str},
   // about: cel+charakter, max 4 zdania; responsibilities: obowiązki (może być lista po przecinkach);
   // selling_points: "Co przekona kandydata do oferty?" + najważniejsze atuty klienta z sekcji 6
 "screening_questions": [{"id": "q1", "question": str, "ideal_answer": str, "deal_breaker": str}],
   // WSZYSTKIE pytania z sekcji SCREENING, z pełnymi idealnymi odpowiedziami i deal-breakerami
 "sourcing": {"keywords": str, "target_companies": str, "notes": str},
   // keywords: frazy z "Kluczowe słowa do wyszukiwania" rozdzielone przecinkami;
   // target_companies: "Firmy docelowe" jako tekst z priorytetami;
   // notes: "Uwagi / plan działania" — ZWŁASZCZA wskazówki typu "nie zawężamy do X"
 "disqualifiers": [str],                   // twarde wykluczenia, jeśli dokument je podaje
 "client_standards": {"priority_rules": str|null, "offlimit": bool|null, "contract_type": str|null, "cv_language": str|null}
   // priority_rules: reguły typu "kandydaci z bankowością w pierwszej kolejności"
}
Zasady: NICZEGO nie wymyślaj — brak sekcji/informacji = null/pusta wartość. Cytuj wiernie, skracaj tylko redakcyjnie. Zwróć SAM JSON.

DOKUMENT:
"""


def extract_document_text(file_bytes: bytes, filename: str) -> Optional[str]:
    """Tekst z docx (akapity + tabele, dedup komórek) albo pdf (extractor CV)."""
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext == "docx":
        try:
            import docx

            d = docx.Document(io.BytesIO(file_bytes))
            parts = [p.text for p in d.paragraphs if p.text.strip()]
            for t in d.tables:
                for row in t.rows:
                    cells = [c.text.strip() for c in row.cells if c.text.strip()]
                    if cells:
                        parts.append(" | ".join(dict.fromkeys(cells)))
            return "\n".join(parts)
        except Exception:
            logger.exception("champion-ingest: docx nieczytelny (%s)", filename)
            return None
    if ext == "pdf":
        import tempfile
        from pathlib import Path

        from app.services.cv_text_extractor import extract_text

        try:
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=True) as tmp:
                tmp.write(file_bytes)
                tmp.flush()
                return extract_text(tmp.name, Path(filename).name)
        except Exception:
            logger.exception("champion-ingest: pdf nieczytelny (%s)", filename)
            return None
    return None


async def parse_champion_document(text: str) -> dict:
    """LLM parse tekstu profilu → dict schematu v3. Rzuca ValueError na śmieci."""
    from app.services.claude_client import call_claude

    msg = await run_in_threadpool(
        call_claude,
        model=PARSE_MODEL,
        max_tokens=6000,
        temperature=0,
        thinking={"type": "disabled"},
        messages=[{"role": "user", "content": PROMPT + text[:14_000]}],
    )
    raw = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
    if "{" not in raw or "}" not in raw:
        raise ValueError("model nie zwrócił obiektu JSON")
    # `_loads_cv_json` toleruje dokładnie te defekty, które Haiku produkuje na
    # profilach Championa: nieucieczkowany `"` w prozie (`Expecting ','
    # delimiter`), puste-wartość-przecinki, ucięty ogon. Import sierpniowy
    # użył gołego `json.loads` i te trudne pliki zostały jako luki — repair
    # je odzyskuje. Strict-first, więc dobry JSON nie jest ruszany.
    from app.services.cv_generator_b2b.standalone_service import _loads_cv_json

    try:
        parsed = _loads_cv_json(raw)
    except (json.JSONDecodeError, ValueError) as exc:
        raise ValueError(f"nieparsowalny JSON profilu: {exc}") from exc
    if not isinstance(parsed, dict):
        raise ValueError("wynik parsowania nie jest obiektem")
    return parsed


def build_champion_dict(parsed: dict, file_id: Optional[int]) -> dict:
    """Kształt `jobs.champion_profile` — 1:1 z importem 08.2026."""
    basics = parsed.get("basics") or {}
    return {
        "basics": {
            "onsite_days_per_week": basics.get("onsite_days_per_week"),
            "candidate_location_pref": basics.get("candidate_location_pref")
            or parsed.get("location"),
            "language": basics.get("language"),
        },
        "project_context": parsed.get("project_context") or {},
        "screening_questions": parsed.get("screening_questions") or [],
        "sourcing": parsed.get("sourcing") or {},
        "role_name": parsed.get("role_name"),
        "seniority_min_years": parsed.get("seniority_min_years"),
        "rate_value": parsed.get("rate_value"),
        "rate_raw": parsed.get("rate_raw"),
        "work_mode": parsed.get("work_mode"),
        "start_date": parsed.get("start_date"),
        "contract_length": parsed.get("contract_length"),
        "sectors": parsed.get("sectors") or [],
        "disqualifiers": parsed.get("disqualifiers") or [],
        "client_standards": parsed.get("client_standards") or {},
        "_source": (
            f"traffit_recruitment_file:{file_id}"
            if file_id is not None
            else "champion_upload"
        ),
        "_parsed_at": datetime.now(timezone.utc).isoformat(),
        "_parser": PARSER_VERSION,
    }


def _is_empty_skills(value: Any) -> bool:
    return not (isinstance(value, list) and len(value) > 0)


async def ingest_parsed_profile(
    db: AsyncSession, *, external_rid: int, file_id: int, parsed: dict
) -> dict:
    """Zapis FILL_EMPTY do oferty (traffit, rid) + reindeks + stale.

    Zwraca wynik per wiersz. `champion_skipped_nonempty` NIE jest błędem —
    profil już obecny znaczy, że nie mamy czego uzupełniać (idempotencja
    collectora: ponowny POST tego samego pliku jest tani i bezpieczny).
    """
    job = (
        await db.execute(
            select(Job).where(
                Job.external_source == "traffit",
                Job.external_id == str(external_rid),
            )
        )
    ).scalar_one_or_none()
    if job is None:
        return {"outcome": "no_job", "external_rid": external_rid}

    outcome: dict[str, Any] = {
        "outcome": "ok",
        "external_rid": external_rid,
        "job_id": job.id,
        "champion_written": False,
        "must_written": False,
        "nice_written": False,
    }

    changed = False
    existing = job.champion_profile
    champion_present = isinstance(existing, dict) and bool(existing)
    if not champion_present:
        job.champion_profile = build_champion_dict(parsed, file_id)
        outcome["champion_written"] = True
        changed = True

    if _is_empty_skills(job.must_skills) and (parsed.get("must_skills") or []):
        job.must_skills = [
            {"name": s["name"], "level": None}
            for s in parsed["must_skills"]
            if isinstance(s, dict) and s.get("name")
        ]
        outcome["must_written"] = True
        changed = True
    if _is_empty_skills(job.nice_skills) and (parsed.get("nice_skills") or []):
        job.nice_skills = [
            {"name": s["name"], "level": None}
            for s in parsed["nice_skills"]
            if isinstance(s, dict) and s.get("name")
        ]
        outcome["nice_written"] = True
        changed = True

    # Werdykt na KOŃCU, ze stanu faktycznego: "champion_skipped_nonempty"
    # wyłącznie gdy profil już był I nic innego nie dopisaliśmy — outcome
    # z dopisanym must/nice obok "skipped" byłby wewnętrznie sprzeczny
    # (endpoint dziś short-circuituje wcześniej, ale wywołanie bezpośrednie
    # nie może kłamać).
    if champion_present and not changed:
        outcome["outcome"] = "champion_skipped_nonempty"

    if changed:
        from app.services.index_outbox_service import JOB, record_bulk_reindex
        from app.services.match_score_cache import mark_stale_for_job

        await record_bulk_reindex(db, JOB, [job.id])
        # Outbox NIE robi stale dla ofert (robi dla kandydatów) — bez tego
        # cache serwowałby score'y liczone na ofercie sprzed Championa.
        await mark_stale_for_job(db, job.id)
        await db.commit()
    return outcome


_RID_RE = re.compile(r"^\d{1,8}$")


def oversize_precheck(declared_size: Optional[int]) -> Optional[str]:
    """Odrzuć PRZED wczytaniem, gdy klient podał Content-Length ponad limit.

    `UploadFile.size` jest wypełniony, gdy nagłówek Content-Length jest obecny —
    to pozwala odbić 200 MB payload bez buforowania go w pamięci. Gdy size jest
    None (chunked bez długości), pełna walidacja rozmiaru po wczytaniu i tak
    zadziała (validate_upload).
    """
    if declared_size is not None and declared_size > MAX_FILE_BYTES:
        return f"Plik przekracza limit {MAX_FILE_BYTES // (1024 * 1024)} MB"
    return None


def validate_upload(
    filename: str, size: int, external_rid: Optional[str] = None
) -> Optional[str]:
    """Komunikat błędu po polsku albo None gdy upload jest poprawny.

    ``external_rid=None`` = powierzchnia bez rekrutacji (upload w Talent
    Radarze) — sprawdzamy tylko plik.
    """
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in ALLOWED_EXTENSIONS:
        return f"Dozwolone rozszerzenia: {', '.join(ALLOWED_EXTENSIONS)} (dostałem: {ext or 'brak'})"
    if size <= 0:
        return "Pusty plik"
    if size > MAX_FILE_BYTES:
        return f"Plik przekracza limit {MAX_FILE_BYTES // (1024 * 1024)} MB"
    if external_rid is not None and not _RID_RE.match(external_rid or ""):
        return "external_rid musi być liczbą (id rekrutacji Traffit)"
    return None
