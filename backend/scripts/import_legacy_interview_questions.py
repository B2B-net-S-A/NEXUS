"""Import archiwum pytań z interview (Excel rekruterów) do banku pytań (25.09.2026).

Rekruterzy przez lata zapisywali w Excelu „Pytania z interview”, o co klient
pytał kandydata na rozmowie: arkusz = klient, wiersz = rola + notatka. Ten
skrypt zamienia notatki na pojedyncze pytania w ``interview_questions`` ze
źródłem ``legacy_import`` (migracja 0383) i przypina je do starej rekrutacji,
z której pochodzą. Do nowych rekrutacji docierają WYŁĄCZNIE po roli
(``client_question_archive``, tiery 1/2 prep-kitu) — nigdy jako „najnowsze
pytania klienta” i nigdy do oceny prepu.

Przebieg (w kontenerze backendu; Excel NIE trafia do repo — niesie nazwiska)::

    docker cp "Pytania z interview.xlsx" <backend>:/tmp/legacy_q.xlsx
    docker exec <backend> python -m scripts.import_legacy_interview_questions \\
        --xlsx /tmp/legacy_q.xlsx --plan /tmp/legacy_q_plan.json \\
        --review /tmp/legacy_q_review.xlsx
    # człowiek przegląda arkusz, dopiero potem:
    docker exec <backend> python -m scripts.import_legacy_interview_questions \\
        --apply /tmp/legacy_q_plan.json

* Przebieg z ``--plan`` woła model (GPT-6 Luna) i NICZEGO nie zapisuje.
* ``--apply`` zapisuje dokładnie przejrzany plan, bez ponownego modelu;
  powtórka nic nie dubluje (dedup po kliencie i znormalizowanym tekście).
* ``--retag plan.json --plan nowy.json`` przelicza same tagi technologii
  w gotowym planie (bez modelu) — po poprawce rozpoznawania technologii.
* ``--rollback`` usuwa pytania ``legacy_import`` (przypięcia znikają kaskadą)
  i przypięcia, które import dodał do pytań już istniejących (``pinned_ids``
  z paragonu); pytania, które klient zadał znowu w debriefie, mają już źródło
  ``client_debrief`` i zostają.

Paragon w ``app_settings['legacy_interview_questions_import']``: same liczby
i ID. Pytanie przechodzi, tylko gdy cytat występuje w notatce, a treść nie
zawiera żadnej osoby wymienionej w notatce.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import re
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

logger = logging.getLogger("legacy_interview_questions")

RECEIPT_KEY = "legacy_interview_questions_import"
PLAN_VERSION = 1
MAX_ENTRY_CHARS = 12_000
MAX_QUESTION_CHARS = 300
PIN_ORDER_BASE = 20_000.0

# Arkusz → klient (same ID z produkcji, sprawdzone 25.09.2026). Pierwsze ID to
# klient, do którego trafia pytanie bez rozpoznanej rekrutacji; pozostałe to
# rodzina rekordów tej firmy — rekrutacja z numeru może należeć do każdego
# z nich i wtedy wygrywa jej klient.
SHEET_CLIENTS: dict[str, tuple[int, ...]] = {
    "NORDEA": (11,),
    "PKO BP": (26, 58468),
    "CeZ": (115, 37721),
    "BNP": (12, 53, 54, 55, 56, 57, 58, 74, 38334, 52),
    "EY": (14,),
    "PWC": (136,),
    "KIR": (32, 5124),
    "ORLEN": (35,),
    "ALIOR": (39, 38333),
    "BIK": (18,),
    # Decyzja Artura 25.09.2026: „Santander” to dziś ERSTE (ex Santander).
    "SANTANDER": (103,),
    "Credit Agricole": (116, 38342, 72, 5182),
    "BANK POCZTOWY": (16,),
    "POLKOMTEL": (15,),
    "PANSA": (153,),
    "PFRON": (122, 58469),
    "XPERI": (45,),
    "VELOBANK": (37,),
    "mLeasing": (23,),
    "ATOS": (17,),
    "ERGO": (13, 38337),
    "Energa": (41,),
    "Tauron": (151, 38341),
    "WEDEL": (155, 5249, 5244),
    "PGE": (25,),
    "PKP": (146, 137),
    "XTB": (127,),
}
# Decyzja Artura 25.09.2026: pytania generyczne, nie od klienta.
SKIPPED_SHEETS = frozenset({"Wszystkie"})
# Arkusz, w którym dane zaczynają się w wierszu nagłówka.
HEADERLESS_SHEETS = frozenset({"WEDEL"})

_REF_RE = re.compile(
    # Bez `\b` z lewej: „S4HANA_EITE500011826” — podkreślnik to znak słowa.
    r"\((\d{4,6})\)|(?<![A-Za-z0-9])(RFQ_\d+(?:_\d{4})?|RITM\d+|ITVM-\d+|EITE\d+)\b"
)
_REPLACEMENT_RE = re.compile(
    r"\s*[-–]?\s*zast[eę]pstwo za:?.*$", re.IGNORECASE | re.DOTALL
)
# Nawias z samymi słowami z wielkiej litery = czyjeś imię i nazwisko.
_NAME_PAREN_RE = re.compile(
    r"\(\s*[A-ZŁŚŻŹĆŃÓĘĄ][\wąćęłńóśźż]+(?:[\s-]+[A-ZŁŚŻŹĆŃÓĘĄ][\wąćęłńóśźż]+)+\s*\)"
)
_WS_RE = re.compile(r"\s+")
_QUESTION_TYPES = {"technical", "behavioral", "motivation", "experience"}


# ── Excel → wpisy ────────────────────────────────────────────────────────────


@dataclass
class Entry:
    sheet: str
    row: int
    client_ids: tuple[int, ...]
    role: str
    refs: list[str]
    text: str


def extract_refs(role: str) -> list[str]:
    """Numery rekrutacji z nazwy roli („(40665)”, „RFQ_27_2026”, „ITVM-5894”)."""
    refs: list[str] = []
    for m in _REF_RE.finditer(role or ""):
        ref = m.group(1) or m.group(2)
        if ref and ref not in refs:
            refs.append(ref)
    return refs


def clean_role(role: str) -> str:
    """Nazwa roli bez nazwisk („zastępstwo za: …”, nawias z imieniem)."""
    text = _REPLACEMENT_RE.sub("", role or "")
    text = _NAME_PAREN_RE.sub("", text)
    return _WS_RE.sub(" ", text).strip(" -–")


def parse_workbook(path: Path) -> tuple[list[Entry], list[str]]:
    """Wpisy z arkuszy klientów + nazwy arkuszy pominiętych (bez klienta)."""
    import openpyxl

    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    entries: list[Entry] = []
    unknown: list[str] = []
    for ws in wb.worksheets:
        title = ws.title.strip()
        if title in SKIPPED_SHEETS:
            continue
        client_ids = SHEET_CLIENTS.get(title)
        if client_ids is None:
            unknown.append(title)
            continue
        last_role = ""
        for idx, row in enumerate(ws.iter_rows(values_only=True), start=1):
            if idx == 1 and title not in HEADERLESS_SHEETS:
                continue
            if not row or not any(c not in (None, "") for c in row):
                continue
            role_cell = str(row[0]).strip() if row[0] not in (None, "") else ""
            text = "\n".join(str(c).strip() for c in row[1:] if c not in (None, ""))
            if role_cell:
                last_role = role_cell
            if not text.strip():
                continue
            role_raw = role_cell or last_role
            entries.append(
                Entry(
                    sheet=title,
                    row=idx,
                    client_ids=client_ids,
                    role=clean_role(role_raw),
                    refs=extract_refs(role_raw),
                    text=text.strip()[:MAX_ENTRY_CHARS],
                )
            )
    return entries, unknown


# ── odpowiedź modelu → pytania ───────────────────────────────────────────────


@dataclass
class Rejected:
    sheet: str
    row: int
    role: str
    reason: str
    question: str = ""


@dataclass
class PlannedQuestion:
    sheet: str
    row: int
    client_id: int
    role: str
    source_job_id: Optional[int]
    source_job_title: Optional[str]
    competence_category_id: Optional[int]
    question: str
    quote: str
    topic: Optional[str]
    ideal_answer: Optional[str]
    question_type: Optional[str]
    skill_tags: list[str] = field(default_factory=list)


def question_hash(text: str) -> str:
    """Ten sam klucz co debrief (`interview_cycle._question_hash`)."""
    norm = _WS_RE.sub(" ", text.strip().lower())
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()


def _person_tokens(people: list[Any]) -> set[str]:
    """Imiona i nazwiska z listy osób modelu (każde słowo osobno, ≥ 3 znaki)."""
    tokens: set[str] = set()
    for person in people or []:
        if not isinstance(person, str):
            continue
        for word in re.split(r"[\s-]+", person):
            word = word.strip(".,;:()\"'")
            if len(word) >= 3:
                tokens.add(word.lower())
    return tokens


def _mentions_person(text: str, tokens: set[str]) -> bool:
    words = {w.lower() for w in re.findall(r"[\wąćęłńóśźżĄĆĘŁŃÓŚŹŻ]+", text or "")}
    return bool(words & tokens)


def _parse_json(raw: str) -> Any:
    text = (raw or "").strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("brak JSON-a w odpowiedzi")
    return json.loads(text[start : end + 1])


def validate_model_output(
    entry: Entry, payload: Any
) -> tuple[list[dict[str, Any]], list[Rejected]]:
    """Pytania z odpowiedzi modelu, które przechodzą kontrolę kodu.

    Cytat musi być w notatce (model nie może dopisać pytania, którego nie
    było), treść nie może nieść osoby wymienionej w notatce, a oczekiwana
    odpowiedź zostaje tylko, gdy też jest cytatem.
    """
    from app.services.academy_rules import quote_in_text

    kept: list[dict[str, Any]] = []
    rejected: list[Rejected] = []
    if not isinstance(payload, dict):
        return kept, [
            Rejected(entry.sheet, entry.row, entry.role, "zły kształt odpowiedzi")
        ]
    people = _person_tokens(payload.get("people") or [])
    seen: set[str] = set()
    for item in payload.get("questions") or []:
        if not isinstance(item, dict):
            continue
        question = _WS_RE.sub(" ", str(item.get("question") or "")).strip()
        quote = str(item.get("quote") or "").strip()
        if not question:
            continue

        def reject(reason: str, _q: str = question) -> None:
            rejected.append(Rejected(entry.sheet, entry.row, entry.role, reason, _q))

        if not quote_in_text(quote, entry.text):
            reject("cytat spoza notatki")
            continue
        if len(question) > MAX_QUESTION_CHARS:
            reject("pytanie dłuższe niż 300 znaków")
            continue
        if _mentions_person(question, people):
            reject("osoba w treści pytania")
            continue
        key = question_hash(question)
        if key in seen:
            continue
        seen.add(key)
        ideal = str(item.get("ideal_answer") or "").strip() or None
        if ideal and (
            not quote_in_text(ideal, entry.text) or _mentions_person(ideal, people)
        ):
            ideal = None
        topic = str(item.get("topic") or "").strip() or None
        if topic and _mentions_person(topic, people):
            topic = None
        qtype = str(item.get("question_type") or "").strip().lower()
        kept.append(
            {
                "question": question,
                "quote": quote,
                "topic": topic,
                "ideal_answer": ideal,
                "question_type": qtype if qtype in _QUESTION_TYPES else None,
            }
        )
    return kept, rejected


# ── baza: rekrutacja źródłowa ────────────────────────────────────────────────


@dataclass
class SourceJob:
    id: int
    client_id: int
    title: str
    competence_category_id: Optional[int]


def _norm_title(text: str) -> str:
    return _WS_RE.sub(" ", (text or "").strip().lower())


async def resolve_source_job(db: Any, entry: Entry) -> Optional[SourceJob]:
    """Stara rekrutacja wpisu: po numerze, a bez numeru po identycznym tytule.

    Tylko jedno trafienie przypina — przy kilku zgadywanie przypięłoby pytania
    do cudzej roli.
    """
    from sqlalchemy import func, or_, select

    from app.models.job import Job

    cols = (Job.id, Job.client_id, Job.title, Job.competence_category_id)
    family = list(entry.client_ids)
    for ref in entry.refs:
        rows = (
            await db.execute(
                select(*cols).where(
                    Job.client_id.in_(family),
                    or_(
                        Job.client_reference == ref,
                        Job.title.op("~")(
                            rf"(^|[^0-9A-Za-z]){re.escape(ref)}([^0-9]|$)"
                        ),
                    ),
                )
            )
        ).all()
        if len(rows) == 1:
            return SourceJob(*rows[0])
    if entry.refs or not entry.role:
        return None
    rows = (
        await db.execute(
            select(*cols).where(
                Job.client_id.in_(family),
                func.lower(func.regexp_replace(func.trim(Job.title), r"\s+", " ", "g"))
                == _norm_title(entry.role),
            )
        )
    ).all()
    return SourceJob(*rows[0]) if len(rows) == 1 else None


async def _cc_ids_by_slug(db: Any) -> dict[str, int]:
    from sqlalchemy import select

    from app.models.competence_category import CompetenceCategory

    rows = (
        await db.execute(select(CompetenceCategory.slug, CompetenceCategory.id))
    ).all()
    return {slug: cc_id for slug, cc_id in rows}


# ── model ────────────────────────────────────────────────────────────────────


def _call_model(prompt: str) -> str:
    """Jedno wywołanie modelu (w wątku). Osobna funkcja — testy ją podmieniają."""
    from app.models.ai_feature import AIFeatureKey
    from app.services.ai_models import fallbacks_for, model_for
    from app.services.claude_client import call_claude_text
    from app.services.llm_prompts import LEGACY_INTERVIEW_QUESTIONS

    feature = AIFeatureKey.interview_question_import
    return call_claude_text(
        model=model_for(feature),
        fallback_models=fallbacks_for(feature),
        max_tokens=4000,
        thinking={"type": "disabled"},
        system=LEGACY_INTERVIEW_QUESTIONS.system_prompt or "",
        messages=[{"role": "user", "content": prompt}],
    )


def _render(entry: Entry) -> str:
    from app.services.llm_prompts import LEGACY_INTERVIEW_QUESTIONS
    from app.services.prompt_fencing import fence

    body = f"Rola: {entry.role}\n\nNotatka rekrutera:\n{entry.text}"
    return LEGACY_INTERVIEW_QUESTIONS.render(entry=fence("entry", body))


async def _model_payload(entry: Entry) -> Any:
    from fastapi.concurrency import run_in_threadpool

    from app.core.database import AsyncSessionLocal
    from app.models.ai_feature import AIFeatureKey
    from app.services.ai_quota import ai_feature

    async with AsyncSessionLocal() as db:
        async with ai_feature(db, AIFeatureKey.interview_question_import, user_id=None):
            await db.commit()  # nie trzymaj połączenia na czas modelu
            raw = await run_in_threadpool(_call_model, _render(entry))
        await db.commit()
    return _parse_json(raw)


# ── plan ─────────────────────────────────────────────────────────────────────


def _tags(question: str, topic: Optional[str]) -> list[str]:
    from app.services.question_suggestions import mentioned_technologies

    return sorted(mentioned_technologies(" ".join(p for p in (question, topic) if p)))


async def build_plan(entries: list[Entry], *, concurrency: int = 4) -> dict[str, Any]:
    """Model + walidacja + rekrutacja źródłowa dla każdego wpisu. Bez zapisu."""
    from app.core.database import AsyncSessionLocal
    from app.services.job_cc import classify_job_title_to_cc_slug
    from app.services.skill_taxonomy_loader import refresh_alias_map

    await refresh_alias_map()
    async with AsyncSessionLocal() as db:
        cc_by_slug = await _cc_ids_by_slug(db)
        sources: dict[int, Optional[SourceJob]] = {}
        for i, entry in enumerate(entries):
            sources[i] = await resolve_source_job(db, entry)

    planned: list[PlannedQuestion] = []
    rejected: list[Rejected] = []
    failed: list[dict[str, Any]] = []
    sem = asyncio.Semaphore(max(1, concurrency))

    async def one(i: int, entry: Entry) -> None:
        async with sem:
            try:
                payload = await _model_payload(entry)
            except Exception as exc:  # noqa: BLE001 — jeden wpis nie zatrzymuje reszty
                failed.append(
                    {
                        "sheet": entry.sheet,
                        "row": entry.row,
                        "error": type(exc).__name__,
                    }
                )
                logger.warning(
                    "wpis %s:%s — model: %s", entry.sheet, entry.row, type(exc).__name__
                )
                return
        kept, dropped = validate_model_output(entry, payload)
        rejected.extend(dropped)
        source = sources.get(i)
        cc_id = source.competence_category_id if source else None
        if cc_id is None:
            slug = classify_job_title_to_cc_slug(entry.role)
            cc_id = cc_by_slug.get(slug) if slug else None
        for item in kept:
            planned.append(
                PlannedQuestion(
                    sheet=entry.sheet,
                    row=entry.row,
                    client_id=source.client_id if source else entry.client_ids[0],
                    role=entry.role,
                    source_job_id=source.id if source else None,
                    source_job_title=source.title if source else None,
                    competence_category_id=cc_id,
                    skill_tags=_tags(item["question"], item["topic"]),
                    **item,
                )
            )

    await asyncio.gather(*(one(i, e) for i, e in enumerate(entries)))
    planned.sort(key=lambda q: (q.sheet, q.row, q.question))
    rejected.sort(key=lambda r: (r.sheet, r.row))
    return {
        "version": PLAN_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "entries": len(entries),
        "entries_with_source_job": sum(1 for s in sources.values() if s),
        "questions": [asdict(q) for q in planned],
        "rejected": [asdict(r) for r in rejected],
        "failed": failed,
    }


async def retag_plan(plan: dict[str, Any]) -> dict[str, Any]:
    """Przelicza `skill_tags` pytań planu bieżącą taksonomią. Bez modelu i zapisu."""
    from app.services.skill_taxonomy_loader import refresh_alias_map

    await refresh_alias_map()
    questions = [
        {**q, "skill_tags": _tags(q["question"], q.get("topic"))}
        for q in plan.get("questions") or []
    ]
    return {**plan, "questions": questions}


def plan_sha256(plan: dict[str, Any]) -> str:
    body = json.dumps(plan.get("questions") or [], sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def write_review(plan: dict[str, Any], path: Path) -> None:
    """Arkusz do przeglądu: jeden arkusz na klienta + „Odrzucone” i „Błędy”."""
    import openpyxl

    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    headers = [
        "Wiersz Excela",
        "Rola",
        "Rekrutacja (id)",
        "Rekrutacja (tytuł)",
        "Pytanie",
        "Cytat z notatki",
        "Oczekiwana odpowiedź",
        "Typ",
        "Technologie",
        "Kategoria (id)",
    ]
    by_sheet: dict[str, list[dict[str, Any]]] = {}
    for q in plan.get("questions") or []:
        by_sheet.setdefault(q["sheet"], []).append(q)
    for sheet, items in by_sheet.items():
        ws = wb.create_sheet(sheet[:31])
        ws.append(headers)
        for q in items:
            ws.append(
                [
                    q["row"],
                    q["role"],
                    q["source_job_id"],
                    q["source_job_title"],
                    q["question"],
                    q["quote"],
                    q["ideal_answer"],
                    q["question_type"],
                    ", ".join(q["skill_tags"]),
                    q["competence_category_id"],
                ]
            )
    ws = wb.create_sheet("Odrzucone")
    ws.append(["Arkusz", "Wiersz Excela", "Rola", "Powód", "Pytanie"])
    for r in plan.get("rejected") or []:
        ws.append([r["sheet"], r["row"], r["role"], r["reason"], r["question"]])
    ws = wb.create_sheet("Błędy")
    ws.append(["Arkusz", "Wiersz Excela", "Błąd"])
    for f in plan.get("failed") or []:
        ws.append([f["sheet"], f["row"], f["error"]])
    wb.save(path)


# ── zapis ────────────────────────────────────────────────────────────────────


async def apply_plan(db: Any, plan: dict[str, Any]) -> dict[str, Any]:
    """Zapisuje plan. Idempotentne; commit robi wołający."""
    from sqlalchemy import select

    from app.models.app_setting import AppSetting
    from app.models.interview_question import (
        InterviewQuestion,
        InterviewQuestionSource,
        InterviewQuestionType,
        JobQuestion,
        JobQuestionAddedBySource,
    )

    if plan.get("version") != PLAN_VERSION:
        raise ValueError("nieznana wersja planu")
    inserted: list[int] = []
    pinned_ids: list[int] = []
    reused = 0
    pinned = 0
    for n, q in enumerate(plan.get("questions") or []):
        norm = question_hash(q["question"])
        question = await db.scalar(
            select(InterviewQuestion).where(
                InterviewQuestion.client_id == q["client_id"],
                InterviewQuestion.normalized_text_hash == norm,
            )
        )
        if question is None:
            question = InterviewQuestion(
                text=q["question"],
                ideal_answer=q.get("ideal_answer"),
                client_id=q["client_id"],
                competence_category_id=q.get("competence_category_id"),
                skill_tags=list(q.get("skill_tags") or []),
                question_type=(
                    InterviewQuestionType(q["question_type"])
                    if q.get("question_type")
                    else None
                ),
                source=InterviewQuestionSource.legacy_import,
                normalized_text_hash=norm,
                created_by=None,
            )
            db.add(question)
            await db.flush()
            inserted.append(question.id)
        else:
            reused += 1
        job_id = q.get("source_job_id")
        if job_id is None:
            continue
        exists = await db.scalar(
            select(JobQuestion.id).where(
                JobQuestion.job_id == job_id, JobQuestion.question_id == question.id
            )
        )
        if exists is None:
            link = JobQuestion(
                job_id=job_id,
                question_id=question.id,
                is_pinned=True,
                added_by_source=JobQuestionAddedBySource.manual,
                added_by_user_id=None,
                order_index=PIN_ORDER_BASE + n,
            )
            db.add(link)
            await db.flush()
            pinned += 1
            pinned_ids.append(link.id)
    receipt = {
        "plan_sha256": plan_sha256(plan),
        "applied_at": datetime.now(timezone.utc).isoformat(),
        "questions_in_plan": len(plan.get("questions") or []),
        "inserted": len(inserted),
        "reused": reused,
        "pinned": pinned,
        "inserted_ids": inserted,
        # Przypięcia importu — także do pytań, które już były w banku
        # (``reused``). Rollback zdejmuje je po id; kaskada z usuniętych
        # pytań archiwum obejmuje wyłącznie nowe pytania.
        "pinned_ids": pinned_ids,
    }
    setting = await db.get(AppSetting, RECEIPT_KEY)
    if setting is None:
        db.add(AppSetting(key=RECEIPT_KEY, value={"runs": [receipt]}))
    else:
        value = dict(setting.value or {})
        value["runs"] = [*(value.get("runs") or []), receipt]
        setting.value = value
    return receipt


async def rollback(db: Any) -> int:
    """Usuwa pytania z archiwum (ich przypięcia kasują się kaskadą) oraz
    przypięcia, które import dodał do pytań już istniejących w banku (id
    z paragonu, ``pinned_ids``). Commit robi wołający."""
    from sqlalchemy import delete

    from app.models.app_setting import AppSetting
    from app.models.interview_question import (
        InterviewQuestion,
        InterviewQuestionSource,
        JobQuestion,
    )

    setting = await db.get(AppSetting, RECEIPT_KEY)
    pin_ids = sorted(
        {
            int(pin_id)
            for run in ((setting.value or {}).get("runs") or [] if setting else [])
            for pin_id in (run.get("pinned_ids") or [])
        }
    )
    unpinned = 0
    if pin_ids:
        # Wyłącznie przypięcia bez człowieka — ktoś mógł je od tego czasu
        # przejąć ręcznie (nie da się, ale warunek jest tani i bezpieczny).
        unpinned = int(
            (
                await db.execute(
                    delete(JobQuestion).where(
                        JobQuestion.id.in_(pin_ids),
                        JobQuestion.added_by_user_id.is_(None),
                    )
                )
            ).rowcount
            or 0
        )
    result = await db.execute(
        delete(InterviewQuestion).where(
            InterviewQuestion.source == InterviewQuestionSource.legacy_import
        )
    )
    removed = int(result.rowcount or 0)
    if setting is not None:
        value = dict(setting.value or {})
        value["rolled_back"] = [
            *(value.get("rolled_back") or []),
            {
                "at": datetime.now(timezone.utc).isoformat(),
                "removed": removed,
                "unpinned": unpinned,
            },
        ]
        setting.value = value
    return removed


# ── CLI ──────────────────────────────────────────────────────────────────────


async def _main(args: argparse.Namespace) -> int:
    from app.core.database import AsyncSessionLocal

    if args.rollback:
        async with AsyncSessionLocal() as db:
            removed = await rollback(db)
            await db.commit()
        print(f"KONIEC rollback: usunięto {removed}")
        return 0
    if args.retag:
        plan = json.loads(Path(args.retag).read_text(encoding="utf-8"))
        plan = await retag_plan(plan)
        Path(args.plan).write_text(
            json.dumps(plan, ensure_ascii=False, indent=1), encoding="utf-8"
        )
        if args.review:
            write_review(plan, Path(args.review))
        tagged = sum(1 for q in plan["questions"] if q["skill_tags"])
        print(f"KONIEC retag: pytania={len(plan['questions'])} z_tagami={tagged}")
        return 0
    if args.apply:
        plan = json.loads(Path(args.apply).read_text(encoding="utf-8"))
        async with AsyncSessionLocal() as db:
            receipt = await apply_plan(db, plan)
            await db.commit()
        summary = {
            k: v for k, v in receipt.items() if k not in ("inserted_ids", "pinned_ids")
        }
        print(f"KONIEC apply: {summary}")
        return 0
    entries, unknown = parse_workbook(Path(args.xlsx))
    if unknown:
        print(f"UWAGA: arkusze bez klienta (pominięte): {unknown}")
    if args.limit:
        entries = entries[: args.limit]
    plan = await build_plan(entries, concurrency=args.concurrency)
    Path(args.plan).write_text(
        json.dumps(plan, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    if args.review:
        write_review(plan, Path(args.review))
    print(
        "KONIEC plan: wpisy={entries} z_rekrutacją={with_job} pytania={q} "
        "odrzucone={r} błędy={f}".format(
            entries=plan["entries"],
            with_job=plan["entries_with_source_job"],
            q=len(plan["questions"]),
            r=len(plan["rejected"]),
            f=len(plan["failed"]),
        )
    )
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--xlsx", help="Excel „Pytania z interview” → plan (bez zapisu)")
    mode.add_argument("--apply", help="Zapisz przejrzany plan JSON")
    mode.add_argument("--retag", help="Przelicz tagi technologii w planie JSON")
    mode.add_argument("--rollback", action="store_true", help="Usuń pytania z archiwum")
    parser.add_argument("--plan", help="Gdzie zapisać plan JSON (z --xlsx)")
    parser.add_argument("--review", help="Arkusz XLSX do przeglądu (z --xlsx)")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--concurrency", type=int, default=4)
    args = parser.parse_args(argv)
    if (args.xlsx or args.retag) and not args.plan:
        parser.error("--xlsx i --retag wymagają --plan")
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    return asyncio.run(_main(args))


if __name__ == "__main__":
    raise SystemExit(main())
