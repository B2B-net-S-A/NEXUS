"""QC CV — automatyczna kontrola CV firmowego przed wysłaniem do klienta (0361).

Rekrutacja v5 (decyzje Artura 23.09.2026): ręczny przegląd DZ zastępuje
kontrola liczona przez kod. To, co dotąd sprawdzał Dominik, i to, co klient
odsyłał jako błędy, jest listą sprawdzeń — deterministyczną, więc ten sam CV
daje ten sam wynik przy każdym otwarciu:

* blokujące: must-have w CV, pogrubione, opisane zdaniem w każdej roli,
  w której są w oryginale; CV nie twierdzi niczego spoza oryginału i notatek;
  lata doświadczenia z nagłówka zgodne z historią; każda rola ma daty;
  reguły klienta (bez stawek i kontaktu kandydata, zrzut zgody RODO),
* uwagi (nigdy nie blokują): pogrubione nice-to-have, pisownia technologii,
  tytuł CV zgodny ze stanowiskiem.

QC jest twardą bramką przed „CV wysłane”/Cpro (`assert_qc_passed`); obejście
zatwierdza Delivery Lead albo admin z powodem (wiersz `cv_qc_runs` z
`override_reason`). GPT-6 Luna (klucz ``dz_review``) PROPONUJE zdania do
brakujących ról — wyłącznie z faktów oryginału i notatek, z dosłownym
cytatem; serwer odrzuca propozycję, której cytatu nie ma w źródłach.
Zmianę w CV zawsze zatwierdza rekruter (`apply_action`).

Źródła (CV firmowe, oryginał, wymagania) czyta `dz_review.load_sources` —
ta sama reguła co dawny przegląd DZ.
"""

from __future__ import annotations

import hashlib
import html as html_lib
import json
import logging
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any, Optional

from fastapi import HTTPException
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.candidate_stage_cv import CandidateStageCV
from app.models.cv_generated_document import CvGeneratedDocument
from app.models.cv_qc_run import CvQcRun
from app.models.recruitment_pipeline import CandidateStage
from app.services import dz_review as dz
from app.services.dz_review import Block, Requirement, Role

logger = logging.getLogger(__name__)

FIXES_PROMPT_VERSION = "cv-qc-fixes-v1"
NOTES_TEXT_MAX = 12_000
NOTES_MAX_ROWS = 60
PROMPT_ORIGINAL_MAX = 15_000
PROMPT_ROLE_MAX = 2_000
MAX_FIXES = 12
PROPOSED_TEXT_MAX = 600
SOURCE_QUOTE_MAX = 300
DESCRIPTIVE_MIN_WORDS = 6
HEADER_BLOCKS = 6
TITLE_BLOCKS = 3

BLOCKING_KEYS = (
    "must_in_cv",
    "must_bolded",
    "must_in_roles",
    "no_unsupported",
    "years_header",
    "dates",
    "client_rules",
)
# `bold_unsupported` jest uwagą, nie blokadą: CV po angielsku z polskiego
# oryginału (i odwrotnie) pogrubia tłumaczenia, których w oryginale nie ma
# dosłownie — blokada zatrzymywałaby poprawne CV.
WARNING_KEYS = ("nice_bolded", "spelling", "title_matches_role", "bold_unsupported")

LABELS = {
    "must_in_cv": "Wszystkie must-have są w CV",
    "must_bolded": "Must-have są pogrubione",
    "must_in_roles": "Must-have opisane w każdej roli z oryginału",
    "no_unsupported": "CV nie twierdzi niczego spoza oryginału",
    "years_header": "Lata doświadczenia zgodne z historią",
    "dates": "Każda rola ma daty",
    "client_rules": "Reguły klienta (stawki, kontakt, zgoda RODO)",
    "nice_bolded": "Nice-to-have są pogrubione",
    "spelling": "Pisownia technologii",
    "title_matches_role": "Tytuł CV zgodny ze stanowiskiem",
    "bold_unsupported": "Pogrubienia mają pokrycie w oryginale",
}

# Sekcje generatora, które niosą szablon, a nie treść: nagłówek roli
# (stanowisko + daty), pracodawca, etykiety („Obowiązki”) i „Rozważany na…”.
_NON_CONTENT_SECTIONS = {"role", "employer", "duties_label", "considered"}
_TECH_SECTIONS = {"technologies", "skills"}


# ── Heurystyki tekstu ────────────────────────────────────────────────────────

_TECH_LABEL = re.compile(
    r"(?:^|(?<=[\s.;]))(?:technologie|technologies|tech\s*stack|stack|tech|"
    r"narz[eę]dzia|tools|[sś]rodowisko|environment|umiej[eę]tno[sś]ci|skills)"
    r"\s*:",
    re.IGNORECASE,
)
_LIST_SPLIT = re.compile(r"[,;|·•]")
_WORD = re.compile(r"[^\W_]+(?:[.#+\-][^\W_]+)*[#+]*", re.UNICODE)


def _norm(text: Optional[str]) -> str:
    return " ".join((text or "").replace("**", "").split()).casefold()


def word_count(text: str) -> int:
    return len(_WORD.findall(text or ""))


def is_tech_list(text: str) -> bool:
    """Czy blok to lista technologii, a nie zdanie o pracy kandydata.

    Lista = zaczyna się etykietą („Technologie:”, „Stack:”…) albo ponad
    połowa elementów rozdzielonych przecinkami to krótkie nazwy (≤ 3 słowa).
    „Rozwijała moduł SEPA w Java 11, Spring Boot i Kafka dla 2 mln klientów”
    ma dwa długie człony — to zdanie, nie lista.
    """

    body = (text or "").strip()
    if not body:
        return False
    if _TECH_LABEL.match(body):
        return True
    parts = [p.strip() for p in _LIST_SPLIT.split(body) if p.strip()]
    if len(parts) < 3:
        return False
    short = sum(1 for p in parts if word_count(p) <= 3)
    return short / len(parts) > 0.5


def strip_tech_tail(text: str) -> str:
    """Zdanie bez doklejonej listy technologii („… Technologie: Java, Spring”).

    Termin, który stoi tylko w takim ogonie, nie jest opisem pracy.
    """

    match = _TECH_LABEL.search(text or "")
    if match and match.start() > 0:
        return text[: match.start()].strip()
    return (text or "").strip()


def is_descriptive(text: str) -> bool:
    body = strip_tech_tail(text)
    return word_count(body) >= DESCRIPTIVE_MIN_WORDS and not is_tech_list(body)


def _phrase_in_sources(phrase: str, sources: str) -> bool:
    """Czy pogrubiona fraza ma pokrycie w oryginale/notatkach.

    Łagodnie: całe słowo (jak wyszukiwarka) albo każde słowo frazy obecne
    w źródłach — „Java 11” pokrywa „Java (wersja 11)”. Fałszywa blokada
    kosztuje więcej niż przepuszczona odmiana zapisu.
    """

    probe = Requirement(label=phrase, alternatives=(phrase,))
    if not dz._patterns(phrase) or dz._found(sources, probe):
        return True
    words = [w.casefold() for w in _WORD.findall(phrase) if len(w) >= 2]
    haystack = _norm(sources)
    return bool(words) and all(w in haystack for w in words)


def match_in(text: str, req: Requirement) -> Optional[str]:
    """Dosłowny fragment tekstu, w którym występuje wymaganie (albo None)."""

    for name in req.terms or req.alternatives:
        for pattern in dz._patterns(name):
            found = pattern.search(text or "")
            if found:
                return found.group(0)
    return None


def described_in_blocks(req: Requirement, blocks: list[Block]) -> bool:
    """Czy w bloku roli jest zdanie z terminem, mówiące, co kandydat zrobił."""

    for block in blocks:
        if block.kind == "h" or block.section in _NON_CONTENT_SECTIONS:
            continue
        if block.section in _TECH_SECTIONS:
            continue
        if not is_descriptive(block.text):
            continue
        if dz._found(strip_tech_tail(block.text), req):
            return True
    return False


# ── Role w CV firmowym (z indeksami bloków) ─────────────────────────────────


@dataclass
class CvRole:
    role: Role
    blocks: list[int] = field(default_factory=list)


def cv_roles(blocks: list[Block], orig_roles: list[Role]) -> list[CvRole]:
    """Role CV firmowego z indeksami bloków — lustro `dz.generated_roles`.

    Znaczniki generatora (``data-cv-section="role"``) wygrywają; bez nich
    (CV wklejone ręcznie) rola to bloki od wzmianki o firmie z oryginału do
    wzmianki o następnej firmie.
    """

    roles: list[CvRole] = []
    current: Optional[dict] = None
    in_experience = False

    def close() -> None:
        nonlocal current
        if current is not None:
            roles.append(
                CvRole(
                    role=Role(
                        label=dz._role_label(current["company"], current["title"]),
                        company=current["company"],
                        text="\n".join(current["lines"]),
                        title=current["title"],
                    ),
                    blocks=current["idx"],
                )
            )
        current = None

    for i, block in enumerate(blocks):
        if block.kind == "h":
            in_experience = block.section == "experience"
            close()
            continue
        if not in_experience:
            continue
        if block.section == "role":
            close()
            current = {
                "title": block.text,
                "company": None,
                "lines": [block.text],
                "idx": [i],
            }
        elif current is not None:
            if block.section == "employer" and current["company"] is None:
                current["company"] = block.text.split(" · ")[0].strip()
            current["lines"].append(block.text)
            current["idx"].append(i)
    close()
    if roles:
        return roles

    hits: list[tuple[int, Role]] = []
    for orig in orig_roles:
        needle = (orig.company or "").strip().casefold()
        if len(needle) < 3:
            continue
        for i, block in enumerate(blocks):
            if needle in block.text.casefold():
                hits.append((i, orig))
                break
    hits.sort(key=lambda h: h[0])
    out: list[CvRole] = []
    for n, (start, orig) in enumerate(hits):
        end = hits[n + 1][0] if n + 1 < len(hits) else len(blocks)
        idx = list(range(start, end))
        out.append(
            CvRole(
                role=Role(
                    label=orig.label,
                    company=orig.company,
                    text="\n".join(blocks[j].text for j in idx),
                    title=orig.title,
                ),
                blocks=idx,
            )
        )
    return out


def role_pairs(
    blocks: list[Block], original_text: str, experience: Any
) -> tuple[list[Role], list[CvRole], list[Optional[int]]]:
    """Role oryginału, role CV i indeks roli CV dla każdej roli oryginału."""

    orig = dz.original_roles(experience, original_text)
    roles = cv_roles(blocks, orig)
    paired = dz.pair_roles(orig, [r.role for r in roles])
    index_of = {id(r.role): n for n, r in enumerate(roles)}
    return orig, roles, [index_of.get(id(p)) if p is not None else None for p in paired]


# ── Lata doświadczenia ──────────────────────────────────────────────────────

_ONGOING = re.compile(
    r"obecnie|present|now|current|do\s+dzi|nadal|teraz|ongoing", re.IGNORECASE
)
_YM = re.compile(r"(?:(\d{4})[-./](\d{1,2}))|(?:(\d{1,2})[-./](\d{4}))|(\d{4})")


def _ym(value: Any, *, end: bool, today: date) -> Optional[int]:
    """„2021-03” / „03.2021” / „2021” / „obecnie” → indeks miesiąca."""

    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if _ONGOING.search(text):
        return today.year * 12 + today.month - 1
    m = _YM.search(text)
    if not m:
        return None
    if m.group(1):
        year, month = int(m.group(1)), int(m.group(2))
    elif m.group(4):
        year, month = int(m.group(4)), int(m.group(3))
    else:
        # Sam rok: początek roku przy starcie, koniec roku przy końcu —
        # tolerancja ±1 roku w sprawdzeniu pokrywa to przybliżenie.
        year, month = int(m.group(5)), (12 if end else 1)
    if not 1 <= month <= 12 or not 1950 <= year <= today.year + 1:
        return None
    return year * 12 + month - 1


def experience_years(
    experience: Any, *, today: Optional[date] = None
) -> Optional[float]:
    """Suma lat z dat historii zatrudnienia (bez podwójnego liczenia nakładek).

    `None`, gdy którakolwiek rola nie ma czytelnej daty startu — wynik z
    niepełnej historii zaniżałby lata i fałszywie blokował CV.
    """

    today = today or date.today()
    now_idx = today.year * 12 + today.month - 1
    intervals: list[tuple[int, int]] = []
    entries = [e for e in (experience or []) if isinstance(e, dict)]
    if not entries:
        return None
    for e in entries:
        start_raw = e.get("start") or e.get("start_date") or e.get("from")
        end_raw = e.get("end") or e.get("end_date") or e.get("to")
        dates = e.get("dates")
        if start_raw is None and isinstance(dates, str):
            # Myślnik między datami, nie wewnątrz „2019-03”.
            parts = re.split(
                r"\s+[–—-]\s+|\s*[–—]\s*|\s+do\s+|\s+to\s+", dates, maxsplit=1
            )
            start_raw = parts[0]
            end_raw = parts[1] if len(parts) > 1 else "obecnie"
        start = _ym(start_raw, end=False, today=today)
        if start is None:
            return None
        finish = _ym(end_raw, end=True, today=today) if end_raw else now_idx
        if finish is None:
            finish = now_idx
        finish = min(finish, now_idx)
        if finish >= start:
            intervals.append((start, finish))
    if not intervals:
        return None
    intervals.sort()
    total = 0
    cur_start, cur_end = intervals[0]
    for start, finish in intervals[1:]:
        if start <= cur_end + 1:
            cur_end = max(cur_end, finish)
        else:
            total += cur_end - cur_start + 1
            cur_start, cur_end = start, finish
    total += cur_end - cur_start + 1
    return total / 12


# „Ponad 8 lat doświadczenia”, „8+ lat doświadczenia w IT”, „10 years of
# experience”. Liczba lat w konkretnej technologii („5 lat w Java”) nie jest
# łącznym stażem — wymagamy słowa „doświadczenie/experience” tuż obok.
_YEARS_HEADER = re.compile(
    r"(?P<approx>ponad|powy[zż]ej|over|more\s+than)?\s*"
    r"(?<![\d.,])(?P<n>\d{1,2})\s*(?P<plus>\+)?\s*"
    r"(?:lat|lata|roku|years?|yrs)\b(?:\s+\S+){0,2}?\s+"
    r"(?:do[sś]wiadczeni|(?:of\s+)?(?:\w+\s+)?experience)",
    re.IGNORECASE,
)


def header_years(blocks: list[Block]) -> Optional[tuple[int, bool, str]]:
    """(N, „co najmniej”, cytat) z pierwszych bloków CV albo None."""

    seen = 0
    for block in blocks:
        if block.kind == "h":
            continue
        seen += 1
        if seen > HEADER_BLOCKS:
            break
        m = _YEARS_HEADER.search(block.text)
        if m:
            at_least = bool(m.group("approx") or m.group("plus"))
            return int(m.group("n")), at_least, m.group(0).strip()
    return None


def years_consistent(claimed: int, at_least: bool, actual: float) -> bool:
    """Tolerancja ±1 roku; „ponad N”/„N+” = co najmniej N−1."""

    whole = int(actual)
    if at_least:
        return whole >= claimed - 1
    return abs(claimed - whole) <= 1


# ── Daty ról ────────────────────────────────────────────────────────────────

_DATE_IN_ROLE = re.compile(
    r"\b(?:0?[1-9]|1[0-2])[./](?:19|20)\d{2}\b|\b(?:19|20)\d{2}\b|"
    r"\bobecnie\b|\bpresent\b|\bnow\b",
    re.IGNORECASE,
)


def role_has_dates(blocks: list[Block], indices: list[int]) -> bool:
    if not indices:
        return False
    # Pierwsze bloki roli (nagłówek, pracodawca) i blok tuż przed nią —
    # CV wklejone ręcznie bywają w układzie „2019–2021 | Firma”.
    window = [indices[0] - 1, *indices[:3]]
    return any(
        0 <= i < len(blocks) and _DATE_IN_ROLE.search(blocks[i].text) for i in window
    )


# ── Reguły klienta: stawki, kontakt ─────────────────────────────────────────

_RATE_WORD = re.compile(r"stawk|\brate\b|wynagrodz|salary|zarobk", re.IGNORECASE)
_AMOUNT = re.compile(
    r"\d[\d\s.,]*\s*(?:z[łl]|pln|eur|€|usd|\$)(?:\s*/\s*(?:h|godz|md|dzie[nń]|mies))?"
    r"|\d[\d\s.,]*\s*/\s*(?:h|godz|md)\b",
    re.IGNORECASE,
)
_PHONE_LIKE = re.compile(r"\+?\d[\d\s\-().]{7,}\d")


def rate_mentions(blocks: list[Block]) -> list[str]:
    out: list[str] = []
    for block in blocks:
        if _RATE_WORD.search(block.text) and _AMOUNT.search(block.text):
            out.append(block.text[:120])
    return out


def contact_leaks(text: str, email: Optional[str], phone: Optional[str]) -> list[str]:
    out: list[str] = []
    low = (text or "").casefold()
    if email and email.strip() and email.strip().casefold() in low:
        out.append("e-mail kandydata")
    digits = re.sub(r"\D", "", phone or "")
    if len(digits) >= 9:
        tail = digits[-9:]
        for m in _PHONE_LIKE.finditer(text or ""):
            if re.sub(r"\D", "", m.group(0)).endswith(tail):
                out.append("telefon kandydata")
                break
    return out


# ── Pisownia technologii ────────────────────────────────────────────────────

# (poprawna pisownia, wzorzec wszystkich zapisów). Każde trafienie różne od
# poprawnej pisowni to uwaga. Kolejność = kolejność zgłaszania.
_SPELLING: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("JavaScript", re.compile(r"\bjava\s?script\b", re.IGNORECASE)),
    ("TypeScript", re.compile(r"\btype\s?script\b", re.IGNORECASE)),
    ("PostgreSQL", re.compile(r"\bpostgres(?:ql)?\b|\bpostgre\b", re.IGNORECASE)),
    ("Node.js", re.compile(r"\bnode\s?\.?\s?js\b", re.IGNORECASE)),
    ("Kubernetes", re.compile(r"\bkubernet[ae]s\b", re.IGNORECASE)),
    ("GitLab", re.compile(r"\bgit\s?lab\b", re.IGNORECASE)),
    ("GitHub", re.compile(r"\bgit\s?hub\b", re.IGNORECASE)),
    ("MySQL", re.compile(r"\bmy\s?sql\b", re.IGNORECASE)),
    ("MongoDB", re.compile(r"\bmongo\s?db\b", re.IGNORECASE)),
    (".NET", re.compile(r"(?<![\w.])\.net\b|\bdot\s?net\b", re.IGNORECASE)),
    ("C#", re.compile(r"\bc\s?sharp\b|(?<!\w)c#", re.IGNORECASE)),
    ("Spring Boot", re.compile(r"\bspring\s?boot\b", re.IGNORECASE)),
)
_URLISH = re.compile(r"\S+@\S+|https?://\S+|www\.\S+|\b[\w-]+\.(?:com|pl|io|org)\S*")


def _url_spans(text: str) -> list[tuple[int, int]]:
    return [m.span() for m in _URLISH.finditer(text)]


def spelling_issues(text: str) -> list[tuple[str, str]]:
    """[(zapis w CV, poprawna pisownia)] bez adresów e-mail i URL-i."""

    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    spans = _url_spans(text or "")
    for right, pattern in _SPELLING:
        for m in pattern.finditer(text or ""):
            if m.group(0) == right:
                continue
            if any(a <= m.start() < b for a, b in spans):
                continue
            if m.group(0) not in seen:
                seen.add(m.group(0))
                out.append((m.group(0), right))
    return out


def fix_spelling(text: str) -> tuple[str, int]:
    spans = _url_spans(text)
    count = 0

    for right, pattern in _SPELLING:

        def repl(m: re.Match[str], right: str = right) -> str:
            nonlocal count
            if m.group(0) == right or any(a <= m.start() < b for a, b in spans):
                return m.group(0)
            count += 1
            return right

        text = pattern.sub(repl, text)
        spans = _url_spans(text)
    return text, count


# ── Tytuł ───────────────────────────────────────────────────────────────────

_SENIORITY = re.compile(
    r"\b(?:senior|mid|middle|regular|junior|lead|principal|staff|starszy|"
    r"m[lł]odszy|ekspert|expert)\b",
    re.IGNORECASE,
)


def core_title(title: Optional[str]) -> str:
    base = re.sub(r"\([^)]*\)", " ", title or "")
    base = _SENIORITY.sub(" ", base)
    base = re.sub(r"\s*[/|–—-]\s*$", "", base.strip())
    return " ".join(base.split()).strip(" -–—/|,")


# ── Sprawdzenia ─────────────────────────────────────────────────────────────


@dataclass
class QcInput:
    must: list[Requirement]
    nice: list[Requirement]
    blocks: list[Block]
    has_cv: bool
    bold_known: bool
    original_text: str
    experience: Any
    notes_text: str = ""
    job_title: Optional[str] = None
    candidate_email: Optional[str] = None
    candidate_phone: Optional[str] = None
    # None = reguła klienta nie wymaga zgody; "ok" | "missing" | "manual".
    consent: Optional[str] = None
    today: Optional[date] = None


def _check(
    key: str, status: str, summary: str, items: Optional[list[dict]] = None
) -> dict:
    return {
        "key": key,
        "label": LABELS[key],
        "severity": "blocking" if key in BLOCKING_KEYS else "warning",
        "status": status,
        "summary": summary,
        "items": items or [],
    }


def _item(
    *,
    requirement: Optional[str] = None,
    role: Optional[str] = None,
    detail: Optional[str] = None,
    fix: Optional[str] = None,
    term: Optional[str] = None,
    role_index: Optional[int] = None,
) -> dict:
    return {
        "requirement": requirement,
        "role": role,
        "detail": detail,
        "fix": fix,
        "term": term,
        "role_index": role_index,
    }


def _status(items: list[dict], *, manual: bool = False) -> str:
    if items:
        return "fail"
    return "manual" if manual else "pass"


def compute_checks(data: QcInput) -> list[dict]:
    """Wszystkie sprawdzenia QC w kolejności kontraktu. Czysta funkcja."""

    if not data.has_cv:
        checks = [
            _check(
                "must_in_cv",
                "fail",
                "Brak CV firmowego",
                [
                    _item(
                        detail="Nie ma jeszcze CV firmowego dla tej rekrutacji.",
                        fix="generate_cv",
                    )
                ],
            )
        ]
        for key in (*BLOCKING_KEYS[1:], *WARNING_KEYS):
            checks.append(_check(key, "skip", "Brak CV"))
        return checks

    blocks = data.blocks
    gen_text = dz.blocks_text(blocks)
    bolds = dz.bold_texts(blocks)
    bold_joined = "\n".join(bolds)
    original = data.original_text or ""
    sources = original + "\n" + (data.notes_text or "")
    checks: list[dict] = []
    bold_unsupported: list[dict] = []

    # 1. Must-have w CV.
    in_cv = {req.label: bool(dz._found(gen_text, req)) for req in data.must}
    missing = [
        _item(
            requirement=req.label,
            detail=(
                "Brak w CV — w oryginale jest, dopisz w roli."
                if original and dz._found(original, req)
                else "Brak w CV i w oryginale — zapytaj kandydata."
            ),
            fix="ai" if original and dz._found(original, req) else "ask_candidate",
        )
        for req in data.must
        if not in_cv[req.label]
    ]
    if not data.must:
        checks.append(_check("must_in_cv", "skip", "Rekrutacja nie ma must-have"))
    else:
        checks.append(
            _check(
                "must_in_cv",
                _status(missing),
                f"{len(data.must) - len(missing)}/{len(data.must)}",
                missing,
            )
        )

    # 2. Must-have pogrubione (tylko te, które w CV są).
    present = [req for req in data.must if in_cv[req.label]]
    if not present:
        checks.append(_check("must_bolded", "skip", "Brak must-have w CV"))
    elif not data.bold_known:
        checks.append(
            _check("must_bolded", "manual", "Pogrubień nie da się odczytać z PDF-a")
        )
    else:
        not_bold = [
            _item(
                requirement=req.label,
                detail="Jest w CV, ale nie jest pogrubione.",
                fix="bold_all",
                term=match_in(gen_text, req),
            )
            for req in present
            if not (bolds and dz._found(bold_joined, req))
        ]
        checks.append(
            _check(
                "must_bolded",
                _status(not_bold),
                f"{len(present) - len(not_bold)}/{len(present)}",
                not_bold,
            )
        )

    # 3. Must-have opisane w każdej roli, w której są w oryginale.
    orig_roles, roles, pairs = role_pairs(blocks, original, data.experience)
    if not data.must or not orig_roles:
        checks.append(_check("must_in_roles", "skip", "Brak ról w historii kandydata"))
    elif not roles:
        checks.append(
            _check(
                "must_in_roles", "manual", "Nie rozpoznano ról w CV — sprawdź ręcznie"
            )
        )
    else:
        role_items: list[dict] = []
        checked = 0
        for req in data.must:
            for orig, idx in zip(orig_roles, pairs):
                if idx is None or not dz._found(orig.text, req):
                    continue  # rola pominięta w CV albo bez tego wymagania
                checked += 1
                role_blocks = [blocks[i] for i in roles[idx].blocks]
                role_text = "\n".join(b.text for b in role_blocks)
                if not dz._found(role_text, req):
                    detail = "Brak w tej roli, a w oryginale jest."
                elif not described_in_blocks(req, role_blocks):
                    detail = (
                        "Jest tylko na liście technologii — dopisz zdanie, co "
                        "kandydat w tej roli z tym robił."
                    )
                else:
                    continue
                role_items.append(
                    _item(
                        requirement=req.label,
                        role=orig.label,
                        detail=detail,
                        fix="ai",
                        role_index=idx,
                    )
                )
        checks.append(
            _check(
                "must_in_roles",
                _status(role_items),
                (
                    f"{len(role_items)} do uzupełnienia"
                    if role_items
                    else f"{checked} ról OK"
                ),
                role_items,
            )
        )

    # 4. Nic spoza oryginału i notatek.
    if not original.strip():
        checks.append(
            _check(
                "no_unsupported",
                "manual",
                "Brak tekstu oryginalnego CV — sprawdź ręcznie",
            )
        )
    else:
        unsupported: list[dict] = []
        must_labels = {r.label for r in data.must}
        for req in [*data.must, *data.nice]:
            term = match_in(gen_text, req)
            if term is None or dz._found(sources, req):
                continue
            is_must = req.label in must_labels
            unsupported.append(
                _item(
                    requirement=req.label,
                    detail=(
                        "Jest w CV, a nie ma tego w oryginale ani w notatkach — "
                        + ("zapytaj kandydata." if is_must else "usuń albo potwierdź.")
                    ),
                    fix="ask_candidate" if is_must else "remove_term",
                    term=term,
                )
            )
        if data.bold_known:
            wanted = [*data.must, *data.nice]
            seen: set[str] = set()
            for phrase in bolds:
                key = phrase.casefold()
                if key in seen or len(phrase) > 40 or word_count(phrase) > 3:
                    continue
                seen.add(key)
                if not re.search(r"[^\W\d_]", phrase):
                    continue
                if any(dz._found(phrase, r) for r in wanted):
                    continue
                if _phrase_in_sources(phrase, sources):
                    continue
                bold_unsupported.append(
                    _item(
                        requirement=None,
                        detail=(
                            "Pogrubione w CV, a nie ma tego w oryginale ani "
                            "w notatkach."
                        ),
                        fix="remove_term",
                        term=phrase,
                    )
                )
        checks.append(
            _check(
                "no_unsupported",
                _status(unsupported),
                f"{len(unsupported)} do wyjaśnienia" if unsupported else "OK",
                unsupported,
            )
        )

    # 5. Lata w nagłówku.
    claim = header_years(blocks)
    if claim is None:
        checks.append(_check("years_header", "skip", "Brak lat w nagłówku CV"))
    else:
        claimed, at_least, quote = claim
        actual = experience_years(data.experience, today=data.today)
        if actual is None:
            checks.append(
                _check(
                    "years_header",
                    "manual",
                    f"„{quote}” — historia bez pełnych dat, sprawdź ręcznie",
                )
            )
        elif years_consistent(claimed, at_least, actual):
            checks.append(
                _check("years_header", "pass", f"{claimed} vs {int(actual)} z historii")
            )
        else:
            checks.append(
                _check(
                    "years_header",
                    "fail",
                    f"{claimed} vs {int(actual)} z historii",
                    [
                        _item(
                            detail=(
                                f"Nagłówek mówi „{quote}”, a z dat historii "
                                f"wychodzi {int(actual)}."
                            ),
                            term=quote,
                        )
                    ],
                )
            )

    # 6. Daty każdej roli.
    if not roles:
        checks.append(_check("dates", "skip", "Nie rozpoznano ról w CV"))
    else:
        no_dates = [
            _item(role=r.role.label, detail="Rola bez dat.", role_index=n)
            for n, r in enumerate(roles)
            if not role_has_dates(blocks, r.blocks)
        ]
        checks.append(
            _check(
                "dates",
                _status(no_dates),
                f"{len(roles) - len(no_dates)}/{len(roles)}",
                no_dates,
            )
        )

    # 7. Reguły klienta.
    rule_items: list[dict] = []
    for quote in rate_mentions(blocks):
        rule_items.append(
            _item(detail=f"Stawka w CV: „{quote}”. Usuń — stawek w CV nie wysyłamy.")
        )
    for what in contact_leaks(gen_text, data.candidate_email, data.candidate_phone):
        rule_items.append(_item(detail=f"CV zawiera {what}. Usuń dane kontaktowe."))
    if data.consent == "missing":
        rule_items.append(
            _item(
                detail="Klient wymaga zrzutu zgody RODO pod CV — brak zrzutu.",
                fix="upload_consent",
            )
        )
    consent_manual = data.consent == "manual"
    checks.append(
        _check(
            "client_rules",
            _status(rule_items, manual=consent_manual),
            (
                f"{len(rule_items)} do poprawy"
                if rule_items
                else "Zgodę RODO sprawdź ręcznie"
                if consent_manual
                else "OK"
            ),
            rule_items,
        )
    )

    # Uwagi.
    nice_present = [req for req in data.nice if dz._found(gen_text, req)]
    if not nice_present:
        checks.append(_check("nice_bolded", "skip", "Brak nice-to-have w CV"))
    elif not data.bold_known:
        checks.append(
            _check("nice_bolded", "manual", "Pogrubień nie da się odczytać z PDF-a")
        )
    else:
        nice_items = [
            _item(
                requirement=req.label,
                detail="Jest w CV, ale nie jest pogrubione.",
                fix="bold_all",
                term=match_in(gen_text, req),
            )
            for req in nice_present
            if not (bolds and dz._found(bold_joined, req))
        ]
        checks.append(
            _check(
                "nice_bolded",
                _status(nice_items),
                f"{len(nice_present) - len(nice_items)}/{len(nice_present)}",
                nice_items,
            )
        )

    spell = [
        _item(detail=f"„{wrong}” → „{right}”", fix="spelling", term=wrong)
        for wrong, right in spelling_issues(gen_text)
    ]
    checks.append(
        _check(
            "spelling",
            _status(spell),
            f"{len(spell)} do poprawy" if spell else "OK",
            spell,
        )
    )

    title = core_title(data.job_title)
    if not title:
        checks.append(_check("title_matches_role", "skip", "Rekrutacja bez tytułu"))
    else:
        head = " ".join(b.text for b in blocks[:TITLE_BLOCKS])
        ok = _norm(title) in _norm(head)
        checks.append(
            _check(
                "title_matches_role",
                "pass" if ok else "fail",
                "OK" if ok else f"Brak „{title}” na początku CV",
                []
                if ok
                else [
                    _item(
                        detail=(
                            f"Początek CV nie mówi „{title}” — sprawdź tytuł "
                            "i stanowisko w nagłówku."
                        )
                    )
                ],
            )
        )
    if not original.strip() or not data.bold_known:
        checks.append(
            _check("bold_unsupported", "skip", "Nie da się porównać z oryginałem")
        )
    else:
        checks.append(
            _check(
                "bold_unsupported",
                _status(bold_unsupported),
                f"{len(bold_unsupported)} do wyjaśnienia" if bold_unsupported else "OK",
                bold_unsupported,
            )
        )
    return checks


def summarize(checks: list[dict]) -> tuple[bool, int, int]:
    """(passed, blocking_failed, warnings_count)."""

    blocking = sum(
        1 for c in checks if c["severity"] == "blocking" and c["status"] == "fail"
    )
    warnings = sum(
        1 for c in checks if c["severity"] == "warning" and c["status"] == "fail"
    )
    return blocking == 0, blocking, warnings


def fingerprint(blocks: list[Block]) -> str:
    return hashlib.sha256(
        dz.blocks_text(blocks, mark_bold=True).encode("utf-8")
    ).hexdigest()


def _checks_hash(checks: list[dict]) -> str:
    return hashlib.sha256(
        json.dumps(checks, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()


# ── Wczytanie kontekstu ─────────────────────────────────────────────────────


async def _notes_text(db: AsyncSession, candidate_id: int) -> str:
    """Notatki kandydata (wszystkie rekrutacje) — źródło faktów obok oryginału."""

    from app.models.note import Note

    rows = (
        await db.execute(
            select(Note.content)
            .where(
                Note.candidate_id == candidate_id,
                Note.source_deleted_at.is_(None),
            )
            .order_by(Note.created_at.desc(), Note.id.desc())
            .limit(NOTES_MAX_ROWS)
        )
    ).scalars()
    text = "\n".join(dz._strip_html(c) for c in rows if c)
    return text[:NOTES_TEXT_MAX]


async def _consent_state(db: AsyncSession, src: dz.ReviewSources) -> Optional[str]:
    """Stan zrzutu zgody RODO, gdy zatwierdzona reguła klienta go wymaga."""

    if src.generated is None or src.job.client_id is None:
        return None
    from app.services.cv_generator_b2b.client_rules import resolve_client_rule

    try:
        rule = await resolve_client_rule(db, src.job.client_id)
    except Exception:  # noqa: BLE001 — polityka chwilowo niedostępna (503)
        logger.warning("[cv_qc] client rule unavailable job=%s", src.job.id)
        return "manual"
    if not getattr(rule, "requires_rodo_consent_block", False):
        return None
    gen = src.generated
    if gen["source"] == "document":
        return "manual"
    if gen.get("stage_id"):
        attached = await db.scalar(
            select(CandidateStageCV.branded_consent_content.is_not(None)).where(
                CandidateStageCV.candidate_stage_id == gen["stage_id"]
            )
        )
        if attached:
            return "ok"
    if gen.get("generated_document_id"):
        payload = await db.scalar(
            select(CvGeneratedDocument.render_payload).where(
                CvGeneratedDocument.id == gen["generated_document_id"]
            )
        )
        if isinstance(payload, dict) and payload.get("consent_screenshot"):
            return "ok"
    return "missing"


def _qc_input(src: dz.ReviewSources, notes: str, consent: Optional[str]) -> QcInput:
    return QcInput(
        must=src.must,
        nice=src.nice,
        blocks=src.blocks,
        has_cv=src.generated is not None,
        bold_known=src.bold_known,
        original_text=(src.original.get("text") or ""),
        experience=src.candidate.experience,
        notes_text=notes,
        job_title=src.job.title,
        candidate_email=src.candidate.email,
        candidate_phone=src.candidate.phone,
        consent=consent,
    )


def _cv_payload(src: dz.ReviewSources) -> Optional[dict]:
    gen = src.generated
    if gen is None:
        return None
    return {
        "source": gen["source"],
        "editable": gen["source"] != "document",
        "stage_id": gen.get("stage_id"),
        "generated_document_id": gen.get("generated_document_id"),
        "document_id": gen.get("document_id"),
        "filename": gen.get("filename"),
        "bold_known": src.bold_known,
        "updated_at": gen.get("updated_at"),
        "blocks": [
            {"kind": b.kind, "section": b.section, "runs": b.runs} for b in src.blocks
        ],
    }


async def _latest_run(
    db: AsyncSession, candidate_id: int, job_id: int
) -> Optional[CvQcRun]:
    return await db.scalar(
        select(CvQcRun)
        .where(CvQcRun.candidate_id == candidate_id, CvQcRun.job_id == job_id)
        .order_by(CvQcRun.created_at.desc(), CvQcRun.id.desc())
        .limit(1)
    )


async def _latest_override(
    db: AsyncSession, candidate_id: int, job_id: int
) -> Optional[dict]:
    from app.models.user import User

    row = (
        await db.execute(
            select(CvQcRun.override_reason, CvQcRun.created_at, User.name)
            .outerjoin(User, User.id == CvQcRun.override_by_user_id)
            .where(
                CvQcRun.candidate_id == candidate_id,
                CvQcRun.job_id == job_id,
                CvQcRun.override_reason.is_not(None),
            )
            .order_by(CvQcRun.created_at.desc(), CvQcRun.id.desc())
            .limit(1)
        )
    ).first()
    if row is None:
        return None
    return {"reason": row.override_reason, "by_name": row.name, "at": row.created_at}


async def evaluate(
    db: AsyncSession, stage: CandidateStage
) -> tuple[dz.ReviewSources, list[dict], str]:
    """(źródła, sprawdzenia, tekst notatek) — bez zapisu."""

    src = await dz.load_sources(db, stage)
    notes = await _notes_text(db, src.candidate.id)
    consent = await _consent_state(db, src)
    return src, compute_checks(_qc_input(src, notes, consent)), notes


async def _store_run(
    db: AsyncSession,
    *,
    candidate_id: int,
    job_id: int,
    stage_id: int,
    fp: Optional[str],
    checks: list[dict],
    cv_source: Optional[str],
    user_id: Optional[int],
) -> tuple[int, datetime]:
    """Zapis przebiegu (bez commitu). Przebieg identyczny z najnowszym (to
    samo CV, te same wyniki) nie dostaje nowego wiersza — każde otwarcie okna
    QC nie może rozdmuchiwać tabeli."""

    passed, blocking_failed, warnings_count = summarize(checks)
    digest = _checks_hash(checks)
    latest = await _latest_run(db, candidate_id, job_id)
    if (
        latest is not None
        and latest.cv_fingerprint == fp
        and (latest.result or {}).get("checks_hash") == digest
    ):
        return latest.id, latest.created_at
    now = datetime.now(timezone.utc)
    row = CvQcRun(
        candidate_id=candidate_id,
        job_id=job_id,
        candidate_stage_id=stage_id,
        cv_fingerprint=fp,
        passed=passed,
        blocking_failed=blocking_failed,
        warnings_count=warnings_count,
        result={"checks": checks, "checks_hash": digest, "cv_source": cv_source},
        created_by_user_id=user_id,
        created_at=now,
    )
    db.add(row)
    await db.flush()
    return row.id, now


async def run_qc(
    db: AsyncSession,
    stage: CandidateStage,
    *,
    user_id: Optional[int],
    persist: bool = True,
    own_session: bool = False,
) -> dict:
    """QC pary z wiersza etapu (kształt `GET …/qc`). Wołający sprawdził dostęp.

    ``persist`` zapisuje przebieg w sesji wołającego (bez commitu);
    ``own_session`` — w osobnej, od razu zatwierdzonej sesji (bramka ruchu:
    przebieg odmowy ma przetrwać wycofanie ruchu).
    """

    src, checks, _ = await evaluate(db, stage)
    passed, blocking_failed, warnings_count = summarize(checks)
    run_id: Optional[int] = None
    computed_at = datetime.now(timezone.utc)
    if persist:
        store = dict(
            candidate_id=src.candidate.id,
            job_id=src.job.id,
            stage_id=stage.id,
            fp=fingerprint(src.blocks) if src.generated is not None else None,
            checks=checks,
            cv_source=(src.generated or {}).get("source"),
            user_id=user_id,
        )
        if own_session:
            from app.core.database import AsyncSessionLocal

            async with AsyncSessionLocal() as own:
                run_id, computed_at = await _store_run(own, **store)
                await own.commit()
        else:
            run_id, computed_at = await _store_run(db, **store)
    name = (
        " ".join(p for p in (src.candidate.name, src.candidate.lastname) if p)
        or "Kandydat"
    )
    return {
        "stage_id": stage.id,
        "candidate_id": src.candidate.id,
        "candidate_name": name,
        "job_id": src.job.id,
        "job_title": src.job.title,
        "client_name": src.client_name,
        "passed": passed,
        "blocking_failed": blocking_failed,
        "warnings_count": warnings_count,
        "override": await _latest_override(db, src.candidate.id, src.job.id),
        "run_id": run_id,
        "computed_at": computed_at,
        "cv": _cv_payload(src),
        "original_cv": {
            "source": src.original.get("source"),
            "filename": src.original.get("filename"),
            "text": src.original.get("text"),
        },
        "client_request": {
            "must": [r.label for r in src.must],
            "nice": [r.label for r in src.nice],
        },
        "checks": checks,
    }


async def record_override(
    db: AsyncSession, stage: CandidateStage, *, user_id: int, reason: str
) -> dict:
    """Obejście QC przez Delivery Leada/admina — wiersz przebiegu + Activity.

    Wiersz obejścia niesie wynik QC z tej chwili (odcisk CV i skrót wyników),
    więc kolejne otwarcie okna z tym samym CV czyta go zamiast dopisywać nowy.
    """

    from app.models.activity import Activity

    src, checks, _ = await evaluate(db, stage)
    passed, blocking_failed, warnings_count = summarize(checks)
    db.add(
        CvQcRun(
            candidate_id=src.candidate.id,
            job_id=src.job.id,
            candidate_stage_id=stage.id,
            cv_fingerprint=(
                fingerprint(src.blocks) if src.generated is not None else None
            ),
            passed=passed,
            blocking_failed=blocking_failed,
            warnings_count=warnings_count,
            result={
                "checks": checks,
                "checks_hash": _checks_hash(checks),
                "cv_source": (src.generated or {}).get("source"),
            },
            override_reason=reason,
            override_by_user_id=user_id,
            created_by_user_id=user_id,
            created_at=datetime.now(timezone.utc),
        )
    )
    db.add(
        Activity(
            entity_type="candidate_stage",
            entity_id=stage.id,
            action="cv_qc_override",
            user_id=user_id,
            details={
                "candidate_id": src.candidate.id,
                "job_id": src.job.id,
                "reason": reason,
                "blocking_failed": blocking_failed,
            },
        )
    )
    await db.flush()
    return await run_qc(db, stage, user_id=user_id, persist=True)


# ── Tablica i bramka ────────────────────────────────────────────────────────


async def pair_statuses(
    db: AsyncSession, pairs: Iterable[tuple[int, int]]
) -> dict[tuple[int, int], dict]:
    """Stan QC par (kandydat, rekrutacja) jednym zapytaniem.

    ``passed`` — najnowszy przebieg przeszedł; ``overridden`` — nie przeszedł,
    ale Delivery Lead/admin kiedyś przepuścił parę; ``failed``; ``unchecked``
    — pary nikt jeszcze nie sprawdzał.
    """

    wanted = {(int(c), int(j)) for c, j in pairs}
    out: dict[tuple[int, int], dict] = {
        pair: {"status": "unchecked", "blocking_failed": 0} for pair in wanted
    }
    if not wanted:
        return out
    has_override = (
        func.bool_or(CvQcRun.override_reason.is_not(None))
        .over(partition_by=(CvQcRun.candidate_id, CvQcRun.job_id))
        .label("has_override")
    )
    rows = await db.execute(
        select(
            CvQcRun.candidate_id,
            CvQcRun.job_id,
            CvQcRun.passed,
            CvQcRun.blocking_failed,
            has_override,
        )
        .where(
            CvQcRun.candidate_id.in_(sorted({c for c, _ in wanted})),
            CvQcRun.job_id.in_(sorted({j for _, j in wanted})),
        )
        .distinct(CvQcRun.candidate_id, CvQcRun.job_id)
        .order_by(
            CvQcRun.candidate_id,
            CvQcRun.job_id,
            CvQcRun.created_at.desc(),
            CvQcRun.id.desc(),
        )
    )
    for row in rows:
        pair = (row.candidate_id, row.job_id)
        if pair not in wanted:
            continue
        if row.passed:
            status = "passed"
        elif row.has_override:
            status = "overridden"
        else:
            status = "failed"
        out[pair] = {
            "status": status,
            "blocking_failed": 0 if row.passed else int(row.blocking_failed or 0),
        }
    return out


def gate_applies(
    current_column: Optional[str], target_column: str, target_is_cpro: bool
) -> bool:
    """Czy ruch przechodzi przez bramkę QC (lustro kontraktu v5).

    Bramka stoi przed „CV wysłane” i przed etapem Cpro, dla par z kolumn
    przed wysłaniem. Ruchy terminalne i wstecz nie są bramkowane.
    """

    if target_column != "cv_sent" and not target_is_cpro:
        return False
    return current_column in ("new", "screening", "verified", "cv_qc")


def _checks_word(n: int) -> str:
    if n == 1:
        return "1 sprawdzenie"
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return f"{n} sprawdzenia"
    return f"{n} sprawdzeń"


async def run_after_move(stage_id: int, user_id: Optional[int]) -> None:
    """QC w tle po wejściu karty do kolumny „QC CV” (24.09.2026).

    Bez tego tablica, przegląd DL i kolejka Cpro pokazywały „QC nie
    sprawdzone”, dopóki ktoś nie otworzył okna QC. Własna sesja, nigdy nie
    rzuca — ruch już się zapisał; awaria = brak przebiegu (liczy się przy
    otwarciu okna albo w bramce).
    """

    from app.core.database import AsyncSessionLocal

    try:
        async with AsyncSessionLocal() as db:
            stage = await db.get(CandidateStage, stage_id)
            if stage is None:
                return
            await run_qc(db, stage, user_id=user_id, persist=True)
            await db.commit()
    except Exception:  # noqa: BLE001 — automat nigdy nie psuje ruchu
        logger.warning(
            "[cv_qc] background run failed stage=%s", stage_id, exc_info=True
        )


async def assert_qc_passed(
    db: AsyncSession,
    *,
    candidate_id: int,
    job_id: int,
    user: Any,
    stage: Optional[CandidateStage] = None,
) -> Optional[dict]:
    """Bramka QC przed „CV wysłane”/Cpro: świeży przebieg albo 409.

    Przebieg jest zapisywany w OSOBNEJ sesji, więc przeżywa odmowę (handler
    wycofuje transakcję ruchu), a tablica i okno QC pokazują ten sam wynik.
    Wołać PRZED blokadami wierszy ruchu (kandydat FOR UPDATE) — zapis
    przebiegu bierze FOR KEY SHARE na kandydacie i rekrutacji.
    """

    from app.core.config import settings

    if not settings.CV_QC_GATE_ENABLED:
        return None
    if stage is None:
        stage = await db.scalar(
            select(CandidateStage)
            .where(
                CandidateStage.candidate_id == candidate_id,
                CandidateStage.job_id == job_id,
            )
            .order_by(CandidateStage.moved_at.desc(), CandidateStage.id.desc())
            .limit(1)
        )
    if stage is None:
        return None
    result = await run_qc(
        db,
        stage,
        user_id=getattr(user, "id", None),
        persist=True,
        own_session=True,
    )
    if result["passed"] or result["override"] is not None:
        return result
    count = max(1, int(result["blocking_failed"]))
    raise HTTPException(
        status_code=409,
        detail={
            "code": "CV_QC_FAILED",
            "message": f"CV nie przeszło QC: {_checks_word(count)} do poprawy.",
            "blocking_failed": result["blocking_failed"],
            "stage_id": stage.id,
            "candidate_id": candidate_id,
        },
    )


# ── Poprawki AI (Luna) ──────────────────────────────────────────────────────

_FIXES_PROMPT = """Jesteś redaktorem CV w firmie body-leasingowej IT. CV przygotowane
dla klienta nie pokazuje w niektórych rolach, co kandydat robił z technologiami
wymaganymi przez klienta. Dla każdego braku z listy zaproponuj JEDNO zdanie
punktu w tej roli.

Zasady:
1. Wyłącznie fakty z ORYGINALNEGO CV albo NOTATEK poniżej. Nie wymyślaj
   technologii, liczb, projektów ani efektów.
2. source_quote = dosłowny fragment (najwyżej 200 znaków) z oryginału albo
   notatek, który potwierdza zdanie. Bez takiego fragmentu pomiń brak.
3. current_text = dosłowny tekst istniejącego punktu tej roli w CV dla
   klienta, który Twoje zdanie zastępuje (rozszerza), albo null, gdy to nowy
   punkt.
4. Technologie z wymagań pogrubiaj: **Java**. Pisz w języku CV dla klienta,
   najwyżej 35 słów, w stylu pozostałych punktów.

BRAKI (wymaganie, rola, punkty tej roli w CV dla klienta, tekst roli z oryginału):
{items}

ORYGINALNE CV
{original}

NOTATKI REKRUTERÓW
{notes}

Zwróć WYŁĄCZNIE JSON:
{{"fixes": [{{"requirement": string, "role": string, "current_text": string | null,
"proposed_text": string, "source": "original" | "notes", "source_quote": string}}]}}
Najwyżej {max_fixes} propozycji. Gdy nic nie da się uczciwie dopisać: {{"fixes": []}}."""


def fixes_material(src: dz.ReviewSources, checks: list[dict], notes: str) -> dict:
    """Materiał dla modelu — ten sam dla skrótu i promptu."""

    by_key = {c["key"]: c for c in checks}
    original = src.original.get("text") or ""
    orig_roles, roles, _ = role_pairs(src.blocks, original, src.candidate.experience)
    orig_by_label = {r.label: r for r in orig_roles}
    req_by_label = {r.label: r for r in src.must}
    items: list[dict] = []
    for item in (by_key.get("must_in_roles") or {}).get("items") or []:
        idx = item.get("role_index")
        req = req_by_label.get(item.get("requirement") or "")
        if idx is None or req is None or not 0 <= idx < len(roles):
            continue
        cv_role = roles[idx]
        points = [
            src.blocks[i].text
            for i in cv_role.blocks
            if src.blocks[i].kind in ("li", "p")
            and src.blocks[i].section not in _NON_CONTENT_SECTIONS
        ]
        orig = orig_by_label.get(item.get("role") or "")
        items.append(
            {
                "requirement": req.label,
                "terms": list(req.terms or req.alternatives),
                "role": item["role"],
                "role_index": idx,
                "cv_role_label": cv_role.role.label,
                "cv_points": points,
                "original_role": (orig.text if orig else "")[:PROMPT_ROLE_MAX],
            }
        )
    return {
        "items": items,
        "original": original[:PROMPT_ORIGINAL_MAX],
        "notes": notes[:NOTES_TEXT_MAX],
        "cv": dz.blocks_text(src.blocks, mark_bold=True)[: dz.PROMPT_CV_MAX],
    }


def fixes_hash(material: dict, model: str) -> str:
    payload = json.dumps(
        {"v": FIXES_PROMPT_VERSION, "model": model, **material},
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _json_object(raw: str) -> dict:
    body = raw.strip()
    if body.startswith("```"):
        body = body.strip("`")
        if body.lower().startswith("json"):
            body = body[4:]
    start, end = body.find("{"), body.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("no JSON object in model output")
    return json.loads(body[start : end + 1])


def parse_fixes(raw: str, material: dict, digest: str) -> list[dict]:
    """JSON modelu → poprawki. Odrzuca propozycje bez cytatu ze źródeł.

    * cytat (znormalizowany) musi być w oryginale albo w notatkach — model nie
      może dopisać faktu, którego kandydat nie podał,
    * zdanie musi zawierać wymaganie,
    * ``current_text`` spoza punktów tej roli w CV = nowy punkt (null).
    """

    data = _json_object(raw)
    original = _norm(material.get("original"))
    notes = _norm(material.get("notes"))
    by_pair = {
        (_norm(i["requirement"]), _norm(i["role"])): i for i in material["items"]
    }
    out: list[dict] = []
    used: set[tuple[str, str]] = set()
    for entry in data.get("fixes") or []:
        if not isinstance(entry, dict):
            continue
        key = (
            _norm(str(entry.get("requirement") or "")),
            _norm(str(entry.get("role") or "")),
        )
        item = by_pair.get(key)
        if item is None or key in used:
            continue
        proposed = " ".join(str(entry.get("proposed_text") or "").split())
        quote = " ".join(str(entry.get("source_quote") or "").split())
        if not proposed or not quote or len(proposed) > PROPOSED_TEXT_MAX:
            continue
        nq = _norm(quote)
        if nq and nq in original:
            source = "original"
        elif nq and nq in notes:
            source = "notes"
        else:
            continue
        req = Requirement(
            label=item["requirement"],
            alternatives=tuple(item["terms"]),
            terms=tuple(item["terms"]),
        )
        if not dz._found(proposed.replace("**", ""), req):
            continue
        current = entry.get("current_text")
        current = " ".join(str(current).split()) if current else None
        if current and _norm(current) not in {_norm(p) for p in item["cv_points"]}:
            current = None
        used.add(key)
        out.append(
            {
                "id": f"f{len(out) + 1}-{digest[:12]}",
                "check_key": "must_in_roles",
                "requirement": item["requirement"],
                "role": item["role"],
                "role_index": item["role_index"],
                "cv_role_label": item["cv_role_label"],
                "current_text": current,
                "proposed_text": proposed,
                "source": source,
                "source_quote": quote[:SOURCE_QUOTE_MAX],
            }
        )
        if len(out) >= MAX_FIXES:
            break
    return out


def _fixes_prompt(material: dict) -> str:
    lines = []
    for n, item in enumerate(material["items"], 1):
        points = (
            "\n".join(f"    - {p}" for p in item["cv_points"]) or "    (brak punktów)"
        )
        lines.append(
            f"{n}. Wymaganie: {item['requirement']}\n   Rola: {item['role']}\n"
            f"   Punkty w CV dla klienta:\n{points}\n"
            f"   Z oryginału: {item['original_role'] or '(brak)'}"
        )
    return _FIXES_PROMPT.format(
        items="\n\n".join(lines),
        original=material["original"] or "(brak tekstu oryginału)",
        notes=material["notes"] or "(brak notatek)",
        max_fixes=MAX_FIXES,
    )


def _no_fixes(status: str) -> dict:
    return {"status": status, "cached": False, "fixes": []}


async def generate_fixes(
    db: AsyncSession, stage: CandidateStage, *, user_id: int
) -> dict:
    """Propozycje zdań dla braków `must_in_roles`. Nigdy nie rzuca.

    Pamięć per (wiersz etapu, skrót wejścia) w `dz_review_hints` — ten sam CV
    i te same braki czytają zapamiętany wynik zamiast płacić drugi raz.
    """

    from app.models.ai_feature import AIFeatureKey
    from app.models.dz_review_hint import DzReviewHint
    from app.services.ai_models import model_chain_for
    from app.services.llm_providers import api_key_configured

    try:
        src, checks, notes = await evaluate(db, stage)
    except Exception as exc:  # noqa: BLE001 — podpowiedź, nigdy 5xx
        logger.warning("[cv_qc] fixes context failed stage=%s: %s", stage.id, exc)
        return _no_fixes("unavailable")
    if src.generated is None:
        return _no_fixes("no_cv")
    if src.generated["source"] == "document":
        return _no_fixes("not_editable")
    material = fixes_material(src, checks, notes)
    if not material["items"]:
        return _no_fixes("ok")
    chain = model_chain_for(AIFeatureKey.dz_review)
    digest = fixes_hash(material, chain[0])
    cached = await db.scalar(
        select(DzReviewHint).where(
            DzReviewHint.candidate_stage_id == stage.id,
            DzReviewHint.input_hash == digest,
        )
    )
    if cached is not None:
        return {
            "status": "ok",
            "cached": True,
            "fixes": list((cached.payload or {}).get("fixes") or []),
        }
    if not api_key_configured(chain[0]):
        return _no_fixes("unavailable")

    from app.services.ai_quota import ai_feature
    from app.services.claude_client import call_claude, text_of

    try:
        async with ai_feature(db, AIFeatureKey.dz_review, user_id=user_id):
            await db.commit()
            message = await run_in_threadpool(
                call_claude,
                model=chain[0],
                fallback_models=chain[1:] or None,
                max_tokens=2500,
                thinking={"type": "disabled"},
                messages=[{"role": "user", "content": _fixes_prompt(material)}],
            )
        fixes = parse_fixes(text_of(message), material, digest)
    except Exception as exc:  # noqa: BLE001 — podpowiedź doradcza, nigdy bramka
        logger.warning(
            "[cv_qc] fixes failed stage=%s: %s", stage.id, type(exc).__name__
        )
        return _no_fixes("unavailable")
    model = getattr(message, "model", None) or chain[0]
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    await db.execute(
        pg_insert(DzReviewHint)
        .values(
            candidate_stage_id=stage.id,
            input_hash=digest,
            model=str(model)[:80],
            payload={"kind": "cv_qc_fixes", "fixes": fixes},
        )
        .on_conflict_do_nothing(constraint="uq_dz_review_hints_stage_hash")
    )
    await db.commit()
    return {"status": "ok", "cached": False, "fixes": fixes}


async def load_fix(db: AsyncSession, stage_id: int, fix_id: str) -> Optional[dict]:
    """Zapamiętana poprawka po id (``f<n>-<skrót wejścia>``)."""

    from app.models.dz_review_hint import DzReviewHint

    match = re.fullmatch(r"f\d{1,3}-([0-9a-f]{12})", fix_id or "")
    if not match:
        return None
    rows = (
        await db.execute(
            select(DzReviewHint.payload).where(
                DzReviewHint.candidate_stage_id == stage_id,
                DzReviewHint.input_hash.like(f"{match.group(1)}%"),
            )
        )
    ).scalars()
    for payload in rows:
        for fix in (payload or {}).get("fixes") or []:
            if isinstance(fix, dict) and fix.get("id") == fix_id:
                return fix
    return None


# ── Edycja HTML CV firmowego ────────────────────────────────────────────────


class ApplyError(Exception):
    """Poprawka nie da się nałożyć (422 z komunikatem po polsku)."""


class _EditableParser(dz._BlockParser):
    """`dz._BlockParser` + tokeny HTML i zakresy tokenów każdego bloku.

    Bloki wychodzą IDENTYCZNE jak z `dz.html_blocks` (ta sama klasa), więc
    indeksy ról policzone w QC wskazują te same bloki przy edycji. Tokeny
    pozwalają podmienić tekst w węzłach tekstowych bez naruszania znaczników.
    """

    def __init__(self) -> None:
        super().__init__()
        self.tokens: list[Optional[dict]] = []
        self.spans: list[tuple[Optional[int], Optional[int]]] = []
        self.ctx: dict[int, dict] = {}
        self._last: Optional[int] = None
        self._end: Optional[int] = None
        self._cur_start: Optional[int] = None

    def handle_starttag(self, tag, attrs):
        self.tokens.append({"k": "tag", "raw": self.get_starttag_text() or f"<{tag}>"})
        self._last = len(self.tokens) - 1
        self._end = None
        super().handle_starttag(tag, attrs)

    def handle_startendtag(self, tag, attrs):
        self.tokens.append({"k": "tag", "raw": self.get_starttag_text() or f"<{tag}/>"})
        self._last = len(self.tokens) - 1
        self._end = None
        dz._BlockParser.handle_starttag(self, tag, attrs)
        dz._BlockParser.handle_endtag(self, tag)

    def handle_endtag(self, tag):
        self.tokens.append({"k": "tag", "raw": f"</{tag}>"})
        self._end = len(self.tokens) - 1
        super().handle_endtag(tag)
        self._end = None

    def handle_data(self, data):
        self.tokens.append({"k": "data", "text": data})
        idx = len(self.tokens) - 1
        super().handle_data(data)
        self.ctx[idx] = {
            "bold": self._bold > 0,
            "skip": self._skip > 0,
            "block": self._current,
        }

    def _open(self, tag, attrs):
        super()._open(tag, attrs)
        self._cur_start = self._last

    def _append(self, data):
        if self._current is None:
            self._cur_start = None
        super()._append(data)

    def _flush(self):
        if self._current is not None and self._current.text:
            self.spans.append((self._cur_start, self._end))
        super()._flush()


@dataclass
class EditableCv:
    tokens: list[Optional[dict]]
    blocks: list[Block]
    spans: list[tuple[Optional[int], Optional[int]]]
    ctx: dict[int, dict]

    @classmethod
    def parse(cls, html: str) -> "EditableCv":
        parser = _EditableParser()
        parser.feed(html or "")
        parser.close()
        return cls(parser.tokens, parser.blocks, parser.spans, parser.ctx)

    def html(self) -> str:
        out: list[str] = []
        for tok in self.tokens:
            if tok is None:
                continue
            if tok["k"] == "data":
                out.append(html_lib.escape(tok["text"], quote=False))
            else:
                out.append(tok["raw"])
        return "".join(out)

    def block_index(self, block: Optional[Block]) -> Optional[int]:
        if block is None:
            return None
        for i, b in enumerate(self.blocks):
            if b is block:
                return i
        return None

    def data_tokens(self) -> Iterable[tuple[int, dict, dict]]:
        for i, tok in enumerate(self.tokens):
            if tok is not None and tok["k"] == "data" and i in self.ctx:
                yield i, tok, self.ctx[i]


def render_inline(text: str) -> str:
    """„…w **Java 11**…” → HTML z <b>; reszta escapowana."""

    body = re.sub(r"^\s*[-•]\s*", "", text or "").strip()
    parts = body.split("**")
    out = []
    for n, part in enumerate(parts):
        esc = html_lib.escape(part, quote=False)
        out.append(f"<b>{esc}</b>" if n % 2 == 1 and part.strip() else esc)
    return "".join(out)


def apply_ai_fix(
    html: str,
    fix: dict,
    text: str,
    *,
    original_text: str = "",
    experience: Any = None,
) -> str:
    doc = EditableCv.parse(html)
    rendered = render_inline(text)
    if not rendered.strip():
        raise ApplyError("Poprawka jest pusta.")
    orig_roles = dz.original_roles(experience, original_text)
    roles = cv_roles(doc.blocks, orig_roles)
    role_idx = fix.get("role_index")
    if not (isinstance(role_idx, int) and 0 <= role_idx < len(roles)) or (
        fix.get("cv_role_label") and roles[role_idx].role.label != fix["cv_role_label"]
    ):
        role_idx = next(
            (
                n
                for n, r in enumerate(roles)
                if r.role.label == fix.get("cv_role_label")
            ),
            None,
        )
    current = fix.get("current_text")
    if current:
        candidates = list(range(len(doc.blocks)))
        if role_idx is not None:
            candidates = roles[role_idx].blocks + candidates
        for i in candidates:
            start, end = doc.spans[i]
            if start is None or end is None:
                continue
            if _norm(doc.blocks[i].text) == _norm(current):
                doc.tokens[start + 1] = {"k": "tag", "raw": rendered}
                for j in range(start + 2, end):
                    doc.tokens[j] = None
                return doc.html()
        raise ApplyError(
            "Punkt, który miała zastąpić poprawka, zmienił się — odśwież propozycje."
        )
    if role_idx is None:
        raise ApplyError("Nie znaleziono tej roli w CV — dopisz zdanie w edytorze.")
    indices = roles[role_idx].blocks
    li_ends = [
        doc.spans[i][1]
        for i in indices
        if doc.blocks[i].kind == "li" and doc.spans[i][1] is not None
    ]
    if li_ends:
        at, insert = li_ends[-1], f"<li>{rendered}</li>"
    else:
        ends = [doc.spans[i][1] for i in indices if doc.spans[i][1] is not None]
        if not ends:
            raise ApplyError(
                "Nie znaleziono miejsca w roli — dopisz zdanie w edytorze."
            )
        at, insert = ends[-1], f"<ul><li>{rendered}</li></ul>"
    doc.tokens[at] = {"k": "tag", "raw": doc.tokens[at]["raw"] + insert}
    return doc.html()


def _wrap_matches(text: str, patterns: list[re.Pattern[str]]) -> tuple[str, int]:
    spans: list[tuple[int, int]] = []
    for pattern in patterns:
        for m in pattern.finditer(text):
            if m.end() > m.start() and not any(
                a < m.end() and m.start() < b for a, b in spans
            ):
                spans.append(m.span())
    if not spans:
        return html_lib.escape(text, quote=False), 0
    spans.sort()
    out, pos = [], 0
    for a, b in spans:
        out.append(html_lib.escape(text[pos:a], quote=False))
        out.append(f"<b>{html_lib.escape(text[a:b], quote=False)}</b>")
        pos = b
    out.append(html_lib.escape(text[pos:], quote=False))
    return "".join(out), len(spans)


def bold_all(html: str, requirements: list[Requirement]) -> tuple[str, int]:
    """Pogrub wystąpienia wymagań w treści (poza nagłówkami i szablonem)."""

    patterns: list[re.Pattern[str]] = []
    for req in requirements:
        for name in req.terms or req.alternatives:
            patterns.extend(dz._patterns(name))
    doc = EditableCv.parse(html)
    count = 0
    for i, tok, ctx in list(doc.data_tokens()):
        block = ctx["block"]
        if ctx["skip"] or ctx["bold"] or block is None:
            continue
        if block.kind == "h" or block.section in _NON_CONTENT_SECTIONS:
            continue
        wrapped, n = _wrap_matches(tok["text"], patterns)
        if n:
            doc.tokens[i] = {"k": "tag", "raw": wrapped}
            count += n
    return doc.html(), count


_SEP = r"\s*[,;/|·]\s*"


def remove_term(html: str, term: str) -> tuple[str, int]:
    """Usuń termin z list technologii i wyliczeń (element listy albo słowo
    z przecinkiem). Zdań z tym terminem nie przerabiamy — to robi człowiek."""

    patterns = dz._patterns(term)
    if not patterns:
        return html, 0
    doc = EditableCv.parse(html)
    count = 0
    target = _norm(term)
    for i, block in enumerate(doc.blocks):
        start, end = doc.spans[i]
        if (
            block.kind == "li"
            and _norm(block.text) == target
            and start is not None
            and end is not None
        ):
            for j in range(start, end + 1):
                doc.tokens[j] = None
            count += 1
    for i, tok, ctx in list(doc.data_tokens()):
        if doc.tokens[i] is None or ctx["skip"]:
            continue
        block = ctx["block"]
        if block is None or block.kind == "h":
            continue
        tech = block.section in _TECH_SECTIONS or is_tech_list(block.text)
        text = tok["text"]
        changed = 0
        for pattern in patterns:
            body = pattern.pattern
            text, n1 = re.subn(_SEP + f"(?:{body})", "", text, flags=pattern.flags)
            text, n2 = re.subn(f"(?:{body})" + _SEP, "", text, flags=pattern.flags)
            changed += n1 + n2
            if tech and re.fullmatch(rf"\s*(?:{body})\s*", text, flags=pattern.flags):
                text, n3 = "", 1
                changed += n3
                _strip_neighbour_separator(doc, i, block)
        if changed:
            doc.tokens[i] = {"k": "data", "text": text}
            count += changed
    return doc.html(), count


def _strip_neighbour_separator(doc: EditableCv, idx: int, block: Block) -> None:
    """Termin był całym węzłem („Java, <b>Docker</b>, Kafka”) — zdejmij
    przecinek z sąsiedniego węzła tego samego bloku."""

    tail = re.compile(_SEP + r"$")
    head = re.compile(r"^" + _SEP)
    for j in range(idx - 1, -1, -1):
        tok = doc.tokens[j]
        if tok is None or tok["k"] != "data":
            continue
        if doc.ctx.get(j, {}).get("block") is not block:
            break
        if tail.search(tok["text"]):
            doc.tokens[j] = {"k": "data", "text": tail.sub("", tok["text"])}
            return
        break
    for j in range(idx + 1, len(doc.tokens)):
        tok = doc.tokens[j]
        if tok is None or tok["k"] != "data":
            continue
        if doc.ctx.get(j, {}).get("block") is not block:
            return
        if head.search(tok["text"]):
            doc.tokens[j] = {"k": "data", "text": head.sub("", tok["text"])}
        return


def fix_spelling_html(html: str) -> tuple[str, int]:
    doc = EditableCv.parse(html)
    count = 0
    for i, tok, ctx in list(doc.data_tokens()):
        if ctx["skip"]:
            continue
        text, n = fix_spelling(tok["text"])
        if n:
            doc.tokens[i] = {"k": "data", "text": text}
            count += n
    return doc.html(), count


async def _editable_csv(
    db: AsyncSession, stage: CandidateStage, gen: dict, *, user_id: int
) -> CandidateStageCV:
    """Szkic CV firmowego pary do edycji (z blokadą wiersza).

    Gotowe CV z generatora bez szkicu na etapie jest najpierw podpinane jako
    szkic (ta sama ścieżka co „Zastąp szkic i otwórz edytor”); zatwierdzone
    CV wraca do szkicu jako nowa wersja — dotychczasowe linki zachowują
    zatwierdzoną treść, jak przy „Nowa wersja” w edytorze.
    """

    from app.api.candidate_stage_cv import apply_generated_to_stage_cv
    from app.models.activity import Activity
    from app.services.cv_document_versions import freeze_approved_version

    if gen["source"] in ("branded_draft", "branded_finalized"):
        csv = await db.scalar(
            select(CandidateStageCV)
            .where(CandidateStageCV.candidate_stage_id == gen["stage_id"])
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if csv is None:
            raise ApplyError("CV firmowe zniknęło — odśwież okno QC.")
    else:
        latest = await db.scalar(
            select(CandidateStage)
            .where(
                CandidateStage.candidate_id == stage.candidate_id,
                CandidateStage.job_id == stage.job_id,
            )
            .order_by(CandidateStage.moved_at.desc(), CandidateStage.id.desc())
            .limit(1)
        )
        target = latest or stage
        csv = await db.scalar(
            select(CandidateStageCV)
            .where(CandidateStageCV.candidate_stage_id == target.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if csv is None:
            csv = CandidateStageCV(
                candidate_stage_id=target.id,
                candidate_id=target.candidate_id,
                job_id=target.job_id,
            )
            db.add(csv)
            await db.flush()
        generated = await db.get(CvGeneratedDocument, gen["generated_document_id"])
        if generated is None:
            raise ApplyError("CV z generatora zniknęło — odśwież okno QC.")
        await apply_generated_to_stage_cv(
            db,
            csv,
            generated,
            user_id=user_id,
            activity_action="branded_cv_attached_by_qc",
        )
    if csv.branded_status == "finalized":
        previous = await freeze_approved_version(db, csv)
        csv.branded_version += 1
        csv.branded_status = "draft"
        csv.branded_finalized_at = None
        csv.branded_finalized_by = None
        csv.branded_snapshot_path = None
        csv.branded_snapshot_filename = None
        csv.branded_snapshot_size_bytes = None
        db.add(
            Activity(
                entity_type="candidate_stage_cv",
                entity_id=csv.id,
                action="branded_cv_new_version",
                user_id=user_id,
                details={
                    "candidate_stage_id": csv.candidate_stage_id,
                    "previous_version_id": previous.id,
                    "version": csv.branded_version,
                    "reason": "cv_qc",
                },
            )
        )
    return csv


async def apply_action(
    db: AsyncSession, stage: CandidateStage, payload: dict, *, user_id: int
) -> dict:
    """Nałóż poprawkę na szkic CV firmowego pary i policz QC od nowa.

    Rzuca `ApplyError` (422) dla poprawki, której nie da się nałożyć, oraz
    `HTTPException` 409 `CV_NOT_EDITABLE` dla CV spoza NEXUSA.
    """

    from app.models.activity import Activity
    from app.services.html_sanitizer import sanitize_cv_html

    src = await dz.load_sources(db, stage)
    gen = src.generated
    if gen is None:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "CV_MISSING",
                "message": "Najpierw wygeneruj CV firmowe dla tej rekrutacji.",
            },
        )
    if gen["source"] == "document":
        raise HTTPException(
            status_code=409,
            detail={
                "code": "CV_NOT_EDITABLE",
                "message": (
                    "To CV to plik spoza NEXUSA (Word/PDF) — popraw go w pliku "
                    "albo wygeneruj CV firmowe w NEXUSIE."
                ),
            },
        )
    action = payload.get("action")
    fix: Optional[dict] = None
    if action == "ai_fix":
        fix = await load_fix(db, stage.id, str(payload.get("fix_id") or ""))
        if fix is None:
            raise ApplyError("Nie ma takiej propozycji — odśwież propozycje poprawek.")
    elif action not in ("bold_all", "remove_term", "spelling"):
        raise ApplyError("Nieznana poprawka.")

    csv = await _editable_csv(db, stage, gen, user_id=user_id)
    html = csv.branded_draft_html or ""
    details: dict[str, Any] = {"candidate_stage_id": csv.candidate_stage_id}
    if action == "ai_fix":
        assert fix is not None
        text = str(payload.get("text") or fix["proposed_text"]).strip()
        if len(text) > 1000:
            raise ApplyError("Poprawka jest za długa (najwyżej 1000 znaków).")
        new_html = apply_ai_fix(
            html,
            fix,
            text,
            original_text=src.original.get("text") or "",
            experience=src.candidate.experience,
        )
        details.update(
            {
                "fix_id": fix["id"],
                "requirement": fix["requirement"],
                "edited": text != fix["proposed_text"],
            }
        )
    elif action == "bold_all":
        scope = payload.get("scope") or "must"
        reqs = src.nice if scope == "nice" else src.must
        new_html, count = bold_all(html, reqs)
        if not count:
            raise ApplyError("Nie ma nic do pogrubienia — wymagania są już pogrubione.")
        details.update({"scope": scope, "count": count})
    elif action == "remove_term":
        term = str(payload.get("term") or "").strip()
        if not term:
            raise ApplyError("Podaj termin do usunięcia.")
        new_html, count = remove_term(html, term)
        if not count:
            raise ApplyError(
                f"„{term}” nie stoi na liście technologii — usuń je w edytorze CV."
            )
        details.update({"term": term[:120], "count": count})
    else:
        new_html, count = fix_spelling_html(html)
        if not count:
            raise ApplyError("Nie ma pisowni do poprawienia.")
        details.update({"count": count})

    csv.branded_draft_html = sanitize_cv_html(new_html)
    csv.edit_revision += 1
    csv.branded_updated_at = datetime.now(timezone.utc)
    csv.branded_updated_by = user_id
    db.add(
        Activity(
            entity_type="candidate_stage_cv",
            entity_id=csv.id,
            action="cv_qc_fix_applied",
            user_id=user_id,
            details={"action": action, **details},
        )
    )
    await db.flush()
    return await run_qc(db, stage, user_id=user_id, persist=True)
