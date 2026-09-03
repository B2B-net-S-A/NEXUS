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
from app.models.ai_feature import AIFeatureKey
from app.services.ai_models import model_for

logger = logging.getLogger(__name__)

MAX_FILE_BYTES = 10 * 1024 * 1024
ALLOWED_EXTENSIONS = ("docx", "pdf")
PARSE_MODEL = model_for(AIFeatureKey.champion_profile_parse)

# Prompt v4 — szablon 7-sekcyjny (09.2026). v3 był sprawdzony na 1095 plikach
# importu sierpniowego; v4 zmienia KSZTAŁT WYJŚCIA (siedem sekcji zamiast
# płaskiej listy), nie zakres wydobywanych faktów.
#
# Prompt opisuje nagłówki OBU szablonów, bo stary krąży po firmie w kilkuset
# kopiach i będzie wgrywany jeszcze długo po tym, jak nowy stanie się
# obowiązujący. Parser rozumiejący wyłącznie nowe nagłówki zamieniłby każdy
# starszy dokument w pusty profil — i to po cichu, bo brak sekcji to u nas
# poprawny wynik, nie błąd.
#
# Zmiana treści = inne wyniki parsowania; bump wersji w _parser przy każdej edycji.
PARSER_VERSION = "champion_parse:v5:haiku-4.5"

PROMPT = """Z dokumentu "Profil Championa" (opis idealnego kandydata uzgodniony z klientem) wyciągnij DOKŁADNIE tę strukturę JSON.

Dokument może być w jednym z dwóch układów:
* NOWY (7 sekcji): 1. Podstawowe informacje, 2. Co wpisać (search), 3. Stack technologiczny, 4. O projekcie, 5. Pytania screeningowe, 6. O kliencie, 7. Dokumenty
* STARY: informacje o projekcie, profil kandydata MUST/NICE, kontekst projektu, screening, success strategy, informacja o kliencie, standardy rekrutacji

{
 "basics": {
   "role_name": str|null,
   "seniority_min_years": int|null,        // np. z "Minimum 10 lat doświadczenia"
   "rate_value": float|null,               // sama liczba, np. 122.50
   "rate_raw": str|null,                   // stawka dokładnie jak w dokumencie
   "work_mode": "stacjonarnie"|"hybrydowo"|"zdalnie"|null,
   "onsite_days_per_week": int|null,
   "candidate_location_pref": str|null,    // LOKALIZACJA BIURA (gdzie jest praca); stary wzór nazywał to „Lokalizacja kandydata"
   "language": str|null,                   // JĘZYK PRACY wymagany od kandydata, NIE język dokumentu CV
   "deadline": str|null,                   // termin na dostarczenie kandydatów do TEJ oferty
   "start_date": str|null,
   "contract_length": str|null             // np. "3-5 miesięcy z możliwością przedłużenia"
 },
 "search": {
   "keywords": str,                        // sekcja "Co wpisać"/"Kluczowe słowa do wyszukiwania" — frazy po przecinku, DOSŁOWNIE tak, jak wpisuje się je w wyszukiwarkę
   "target_companies": str,                // "Firmy docelowe" jako tekst z priorytetami
   "disqualifiers": [str],                 // twarde wykluczenia, jeśli dokument je podaje
   "notes": str                            // "Uwagi / plan działania" — ZWŁASZCZA wskazówki typu "nie zawężamy do X"
 },
 "stack": {
   "must": [{"name": str}],                // sekcja MUST-HAVE / "Stack technologiczny" — technologie, JEDNA NA WPIS, bez zdań opisowych
   "nice": [{"name": str}],                // sekcja NICE-TO-HAVE
   "notes": str                            // niuanse wersji/zakresu, np. "Java 17+, nie Java 8"
 },
 "project": {
   "about": str,                           // cel i charakter projektu, MAKSYMALNIE 2 ZDANIA
   "responsibilities": str                 // obowiązki na stanowisku (może być lista po przecinkach)
 },
 "screening_questions": [{"id": "q1", "question": str, "ideal_answer": str, "deal_breaker": str}],
   // WSZYSTKIE pytania z sekcji SCREENING / "Pytania od Delivery Leada", z pełnymi idealnymi odpowiedziami i deal-breakerami
 "client": {
   "about": str,                           // "O kliencie" / "Co powiedzieć o Kliencie"
   "selling_points": str,                  // "Co przekona kandydata do oferty?" + atuty klienta
   "priority_rules": str,                  // reguły typu "kandydaci z bankowością w pierwszej kolejności"
   "offlimit": bool|null,
   "contract_type": str|null,
   "cv_language": str|null,
   "consultant_insight": str,              // "INSIGHT OD KONSULTANTA" — co mówi nasz człowiek już pracujący u klienta
   "historical_questions": str,            // "Historyczne pytania" klienta
   "sectors": [str]                        // branże z wymagań/kontekstu (banking, fintech, płatności...)
 },
 "documents": [{"name": str, "url": str}]  // sekcja "Dokumenty" — nazwa + link; pomiń pozycje bez linku
}
Zasady: NICZEGO nie wymyślaj — brak sekcji/informacji = null/pusta wartość. Cytuj wiernie, skracaj tylko redakcyjnie.
"project.about" skróć do maksymalnie 2 zdań nawet jeśli dokument ma dłuższy opis — resztę pomiń, NIE przenoś do innych pól.
"stack.must"/"stack.nice" to POJEDYNCZE technologie ("Java", "Kubernetes"), nie całe wymagania zdaniami — zdanie opisowe zamień na samą technologię, którą opisuje.
Zwróć SAM JSON.

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
    start, end = raw.find("{"), raw.rfind("}")
    if start == -1 or end <= start:
        # Brak obiektu ALBO `}` przed `{` (zdegenerowane) — precyzyjny komunikat
        # zamiast zrzucania tego na _loads_cv_json (który dałby mniej czytelny
        # błąd "nieparsowalny JSON").
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
    """Kształt `jobs.champion_profile` — siedem sekcji szablonu 09.2026.

    Prompt v4 zwraca już posekcjonowany JSON, więc ta funkcja głównie go
    przepisuje, ale robi to POLEM PO POLU zamiast `dict(parsed)`. Przepisanie
    hurtem wpuściłoby do bazy dowolny klucz, który model wymyśli, a JSONB nie ma
    nikogo, kto by to odsiał — pole halucynowane raz zostaje w dokumencie na
    zawsze i wygląda jak dana.

    Toleruje też odpowiedź w kształcie v3 (płaskie `rate_value`, `project_context`,
    `sourcing`): `ChampionProfile` i tak migruje stary kształt przy odczycie, więc
    profil sparsowany starszym promptem pozostaje w pełni czytelny.
    """
    basics = parsed.get("basics") or {}
    search = parsed.get("search") or {}
    stack = parsed.get("stack") or {}
    project = parsed.get("project") or {}
    client = parsed.get("client") or {}

    def _skills(raw: Any) -> list[dict]:
        out: list[dict] = []
        for item in raw or []:
            name = item.get("name") if isinstance(item, dict) else item
            if isinstance(name, str) and name.strip():
                out.append({"name": name.strip()})
        return out

    def _documents(raw: Any) -> list[dict]:
        """Pozycja bez linku jest POMIJANA — sekcja 7 to wskaźniki, nie lista tytułów.

        Wpis z samą nazwą renderowałby się jako dokument, którego nie da się
        otworzyć: gorzej niż jego brak, bo obiecuje coś, czego nie ma.
        """
        out: list[dict] = []
        for item in raw or []:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            url = str(item.get("url") or "").strip()
            if name and url:
                out.append({"name": name, "url": url})
        return out

    return {
        "basics": {
            "role_name": basics.get("role_name") or parsed.get("role_name"),
            "seniority_min_years": basics.get("seniority_min_years")
            or parsed.get("seniority_min_years"),
            "rate_value": basics.get("rate_value") or parsed.get("rate_value"),
            "rate_raw": basics.get("rate_raw") or parsed.get("rate_raw"),
            "work_mode": basics.get("work_mode") or parsed.get("work_mode"),
            "onsite_days_per_week": basics.get("onsite_days_per_week"),
            "candidate_location_pref": basics.get("candidate_location_pref")
            or parsed.get("location"),
            "language": basics.get("language"),
            "start_date": basics.get("start_date") or parsed.get("start_date"),
            "deadline": basics.get("deadline") or parsed.get("deadline"),
            "contract_length": basics.get("contract_length")
            or parsed.get("contract_length"),
        },
        "search": {
            "keywords": search.get("keywords") or "",
            "target_companies": search.get("target_companies") or "",
            "disqualifiers": search.get("disqualifiers")
            or parsed.get("disqualifiers")
            or [],
            "notes": search.get("notes") or "",
            "sources": [],
        },
        "stack": {
            # Fallback na `must_skills`/`nice_skills` z v3: ten sam fakt pod inną
            # nazwą. Bez niego dokument sparsowany starszym promptem miałby pustą
            # sekcję 3 i wracał do zgadywania skilli regexem z prozy.
            "must": _skills(stack.get("must") or parsed.get("must_skills")),
            "nice": _skills(stack.get("nice") or parsed.get("nice_skills")),
            "notes": stack.get("notes") or "",
        },
        "project": {
            "about": project.get("about") or "",
            "responsibilities": project.get("responsibilities") or "",
        },
        "screening_questions": parsed.get("screening_questions") or [],
        "client": {
            "about": client.get("about") or "",
            "selling_points": client.get("selling_points") or "",
            "priority_rules": client.get("priority_rules") or "",
            "offlimit": client.get("offlimit"),
            "contract_type": client.get("contract_type"),
            "cv_language": client.get("cv_language"),
            "consultant_insight": client.get("consultant_insight") or "",
            "historical_questions": client.get("historical_questions") or "",
            "sectors": client.get("sectors") or parsed.get("sectors") or [],
        },
        "documents": _documents(parsed.get("documents")),
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

    # Skille czytamy z OBU kształtów odpowiedzi parsera: v4 zwraca je w sekcji
    # 3 (`stack.must` / `stack.nice`), v3 miał je płasko na wierzchu. Czytanie
    # samego v4 zepsułoby powtórne przetworzenie dokumentu sparsowanego wcześniej,
    # a czytanie samego v3 — każdy nowy dokument. Objaw w obie strony byłby ten
    # sam i cichy: `Job.must_skills` zostaje puste, scoring wraca do zgadywania
    # skilli regexem z prozy, nic nie sygnalizuje błędu.
    stack_section = parsed.get("stack") or {}
    stack_section = stack_section if isinstance(stack_section, dict) else {}
    parsed_must = stack_section.get("must") or parsed.get("must_skills") or []
    parsed_nice = stack_section.get("nice") or parsed.get("nice_skills") or []

    def _as_job_skills(raw: Any) -> list[dict]:
        out: list[dict] = []
        for item in raw:
            name = item.get("name") if isinstance(item, dict) else item
            if isinstance(name, str) and name.strip():
                out.append({"name": name.strip(), "level": None})
        return out

    if _is_empty_skills(job.must_skills) and parsed_must:
        skills = _as_job_skills(parsed_must)
        if skills:
            job.must_skills = skills
            outcome["must_written"] = True
            changed = True
    if _is_empty_skills(job.nice_skills) and parsed_nice:
        skills = _as_job_skills(parsed_nice)
        if skills:
            job.nice_skills = skills
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
