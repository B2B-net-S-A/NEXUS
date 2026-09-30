"""Teksty jednej rekrutacji „po ludzku” (tabela ``job_plain_briefs``, klucz AI `champion_draft`).

Wejście to fakty z profilu Championa, rekrutacji i karty klienta. Model
tylko je PRZEPISUJE zrozumiałym językiem; kod pilnuje, żeby nic nie dopisał:

* **Ugruntowanie.** Zdanie z liczbą, której nie ma w danych wejściowych, albo
  z technologią spoza danych jest usuwane. Pytanie kandydata bez odpowiedzi
  w danych = ``answer: null`` („brak w profilu”) — lista pytań jest stała.
* **Pytania screeningowe.** Wyłącznie istniejące ``screening_questions``
  (te same id, ta sama kolejność); brak przepisania = oryginał z profilu.
* **Płacimy tylko za zmianę.** ``inputs_hash`` (dane + wersja promptu + model)
  równy zapisanemu = brak wywołania.
* **AI to dodatek.** Awaria = ``status=failed`` ze starymi tekstami; nigdy 5xx.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import unicodedata
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.job import Job
from app.models.plain_knowledge import JobPlainBrief

logger = logging.getLogger(__name__)

FAILED = "Nie udało się przygotować wyjaśnienia — spróbuj „Odśwież”."
MAX_TERMS = 16
TEXT_CAP = 1500

# Stała lista pytań kandydata. Model tylko formułuje odpowiedź z danych.
CANDIDATE_QUESTIONS: tuple[tuple[str, str], ...] = (
    ("client", "Co to za klient?"),
    ("rate", "Ile płacą?"),
    ("work", "Co konkretnie będę robić?"),
    ("mode", "Zdalnie czy w biurze?"),
    ("start", "Od kiedy i na jak długo?"),
    ("process", "Jak wygląda rekrutacja u klienta?"),
    ("team", "Jak duży jest zespół?"),
)
_QA_SOURCES = {
    "client": "karta klienta",
    "rate": "sekcja 1",
    "work": "sekcja 5",
    "mode": "sekcja 1",
    "start": "sekcja 1",
    "process": "karta klienta",
    "team": "sekcja 5",
}


def _cap(value: Any, limit: int = TEXT_CAP) -> str:
    return re.sub(r"\s+", " ", value).strip()[:limit] if isinstance(value, str) else ""


def job_terms(job: Any) -> list[dict[str, Any]]:
    """Hasła słowniczka tej rekrutacji: must → nice → doświadczenie poza stackiem."""
    from app.services import champion_view
    from app.services.plain_knowledge.knowledge import researchable_term, term_key_for
    from app.services.skill_normalize import iter_skill_names

    profile = getattr(job, "champion_profile", None)
    stack = champion_view.stack(profile)
    must = [n for n in iter_skill_names(stack.get("must")) if n.strip()] or [
        n for n in iter_skill_names(getattr(job, "must_skills", None)) if n.strip()
    ]
    nice = [n for n in iter_skill_names(stack.get("nice")) if n.strip()] or [
        n for n in iter_skill_names(getattr(job, "nice_skills", None)) if n.strip()
    ]
    out: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add(name: str, level: str, label: str) -> None:
        if not researchable_term(name):
            return
        key = term_key_for(name)
        if not key or key in seen or len(out) >= MAX_TERMS:
            return
        seen.add(key)
        out.append(
            {
                "term_key": key,
                "display_name": name.strip()[:200],
                "level": level,
                "level_label": label,
            }
        )

    for name in must:
        add(name, "must", "wymagane")
    for name in nice:
        add(name, "nice", "mile widziane")
    exp = champion_view.experience(profile)
    for kind in ("domains", "certifications", "regulations"):
        for item in exp.get(kind) or []:
            years = item.get("min_years")
            label = "doświadczenie" + (
                f" · min. {years} lata" if isinstance(years, int) and years > 0 else ""
            )
            if item.get("level") == "nice":
                label = "mile widziane"
            add(item["name"], "experience", label)
    return out


def collect_inputs(
    job: Any,
    *,
    client_name: Optional[str],
    client_about: Optional[str],
    client_process: Optional[str],
    role_name: Optional[str],
) -> dict[str, Any]:
    """Fakty rekrutacji dla modelu. Czysta funkcja (testy, hash)."""
    from app.services import champion_view
    from app.services.dealbreaker_filters import resolve_job_budget_hourly
    from app.services.skill_normalize import iter_skill_names

    profile = getattr(job, "champion_profile", None)
    basics = champion_view.basics(profile)
    project = champion_view.project(profile)
    stack = champion_view.stack(profile)
    budget = resolve_job_budget_hourly(job)
    screening = [
        {
            "id": _cap(q.get("id"), 40),
            "question": _cap(q.get("question"), 500),
            "ideal_answer": _cap(q.get("ideal_answer"), 800),
            "deal_breaker": _cap(q.get("deal_breaker"), 500),
        }
        for q in champion_view.screening_questions(profile)
        if isinstance(q, dict)
        and _cap(q.get("id"), 40)
        and _cap(q.get("question"), 500)
    ]
    return {
        "title": _cap(getattr(job, "title", None), 255),
        "working_title": _cap(getattr(job, "working_title", None), 255),
        "role": _cap(role_name, 200),
        "client": _cap(client_name, 255),
        "client_about": _cap(client_about, 1200),
        "client_process": _cap(client_process, 1200),
        "budget_pln_hourly_b2b_net": round(float(budget)) if budget else None,
        "location": _cap(getattr(job, "location", None), 255),
        "work_mode": _cap(
            basics.get("work_mode") or getattr(job, "work_mode", None), 50
        ),
        "onsite_days_per_week": basics.get("onsite_days_per_week")
        or getattr(job, "onsite_days_per_week", None),
        "office": _cap(basics.get("candidate_location_pref"), 255),
        "start_date": _cap(basics.get("start_date"), 100),
        "contract_length": _cap(basics.get("contract_length"), 255),
        "seniority_min_years": basics.get("seniority_min_years"),
        "project_about": _cap(project.get("about")),
        "project_responsibilities": _cap(project.get("responsibilities")),
        "stack_must": [n for n in iter_skill_names(stack.get("must")) if n.strip()][
            :20
        ],
        "stack_nice": [n for n in iter_skill_names(stack.get("nice")) if n.strip()][
            :20
        ],
        "stack_notes": _cap(stack.get("notes"), 600),
        "selling_points": _cap(
            champion_view.client(profile).get("selling_points"), 1200
        ),
        "screening_questions": screening,
        "terms": [t["term_key"] for t in job_terms(job)],
    }


def inputs_hash(inputs: dict[str, Any], model: str) -> str:
    from app.services.llm_prompts import PLAIN_JOB_BRIEF

    payload = json.dumps(
        {"i": inputs, "v": PLAIN_JOB_BRIEF.version, "m": model},
        ensure_ascii=False,
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# ── ugruntowanie ────────────────────────────────────────────────────────────


def _fold(text: str) -> str:
    norm = unicodedata.normalize(
        "NFKD", (text or "").replace("ł", "l").replace("Ł", "L")
    )
    return norm.encode("ascii", "ignore").decode("ascii").casefold()


_NUM_RE = re.compile(r"\d+(?:[.,]\d+)?")
_WORD_RE = re.compile(r"[A-Za-zÀ-ž0-9+#./-]+")


def _norm_number(raw: str) -> str:
    """„170”, „170,00” i „170.0” to ta sama liczba; „170,99” — inna."""
    whole, _, frac = raw.replace(",", ".").partition(".")
    whole = whole.lstrip("0") or "0"
    frac = frac.rstrip("0")
    return f"{whole}.{frac}" if frac else whole


def _numbers(text: str) -> set[str]:
    compact = re.sub(r"(?<=\d)[ \u00a0](?=\d{3}\b)", "", text)
    return {_norm_number(raw) for raw in _NUM_RE.findall(compact)}


def _values(value: Any) -> list[str]:
    """Same WARTOŚCI danych wejściowych (bez kluczy JSON — „b2b” w nazwie klucza
    nie może uczynić liczby „2” faktem z profilu)."""
    if isinstance(value, dict):
        return [s for v in value.values() for s in _values(v)]
    if isinstance(value, (list, tuple)):
        return [s for v in value for s in _values(v)]
    if isinstance(value, bool) or value is None:
        return []
    if isinstance(value, (int, float)):
        return [
            _norm_number(repr(float(value)) if isinstance(value, float) else str(value))
        ]
    return [str(value)]


class Grounding:
    """Sprawdza, czy zdanie nie wnosi liczb ani technologii spoza danych wejściowych."""

    def __init__(self, inputs: dict[str, Any]) -> None:
        values = _values(inputs)
        self._numbers: set[str] = set()
        self._words: set[str] = set()
        for value in values:
            self._numbers |= _numbers(value)
            self._words |= {_fold(w.strip(".,")) for w in _WORD_RE.findall(value)}

    def sentence_ok(self, sentence: str) -> bool:
        from app.services.skill_normalize import is_taxonomy_technology

        if not _numbers(sentence) <= self._numbers:
            return False
        for word in _WORD_RE.findall(sentence):
            token = word.strip(".,")
            if len(token) < 2:
                continue
            # Całe słowo, nie podciąg: „Java” to nie „JavaScript”.
            if is_taxonomy_technology(token) and _fold(token) not in self._words:
                return False
        return True

    def clean(self, text: Any, limit: int = TEXT_CAP) -> Optional[str]:
        value = _cap(text, limit)
        if not value:
            return None
        sentences = re.split(r"(?<=[.!?])\s+", value)
        kept = [s for s in sentences if s and self.sentence_ok(s)]
        return " ".join(kept).strip() or None


def rate_sentence(inputs: dict[str, Any]) -> Optional[str]:
    """Stawka z profilu słowami — liczy ją kod, nie model (model gubił ją 29.09)."""
    budget = inputs.get("budget_pln_hourly_b2b_net")
    if not budget:
        return None
    return f"Do {budget} zł netto za godzinę na B2B."


def start_sentence(inputs: dict[str, Any]) -> Optional[str]:
    """Start i długość z profilu, gdy model ich nie podał (prod 30.09: profil
    miał „long term cooperation”, a ściąga mówiła „brak w profilu”)."""
    parts = []
    if inputs.get("start_date"):
        parts.append(f"Start: {inputs['start_date']}.")
    if inputs.get("contract_length"):
        parts.append(f"Długość współpracy: {inputs['contract_length']}.")
    return " ".join(parts) or None


# Zasady wysyłki CV z karty klienta to instrukcja dla rekrutera, nie odpowiedź
# dla kandydata (prod 30.09: „Jak wygląda rekrutacja u klienta?” mówiło o nazwie
# pliku CV). Zdanie o pliku, formacie CV albo notatce do wysyłki wypada.
_RECRUITER_ONLY_RE = re.compile(
    r"\b(plik\w*|nazw\w* plik\w*|format\w* CV|CV (należy|powinn\w*|musi)|notatk\w*|docx|pdf)\b",
    re.IGNORECASE,
)


def candidate_facing(text: Optional[str]) -> Optional[str]:
    """Usuwa zdania, które są instrukcją dla rekrutera (wysyłka i nazwa pliku CV)."""
    if not text:
        return text
    sentences = re.split(r"(?<=[.!?])\s+", text)
    kept = [s for s in sentences if s and not _RECRUITER_ONLY_RE.search(s)]
    return " ".join(kept).strip() or None


def _with_rate(pitch: Optional[str], inputs: dict[str, Any]) -> Optional[str]:
    """Tekst na start zawsze mówi stawkę, gdy profil ją zna (decyzja 29.09.2026)."""
    sentence = rate_sentence(inputs)
    if not pitch or not sentence:
        return pitch
    if str(inputs["budget_pln_hourly_b2b_net"]) in _numbers(pitch):
        return pitch
    return f"{pitch} Umowa B2B do {inputs['budget_pln_hourly_b2b_net']} zł netto za godzinę."


def shape_output(raw: Any, inputs: dict[str, Any]) -> dict[str, Any]:
    """Wynik modelu → pola tabeli, po kontroli ugruntowania. Czysta funkcja."""
    data = raw if isinstance(raw, dict) else {}
    g = Grounding(inputs)
    answers = data.get("answers") if isinstance(data.get("answers"), dict) else {}
    qa: list[dict[str, Any]] = []
    for key, question in CANDIDATE_QUESTIONS:
        answer = g.clean(answers.get(key), 600)
        if key == "rate":
            answer = rate_sentence(inputs)
        if key == "process":
            answer = candidate_facing(answer)
        if key == "start" and not answer:
            answer = start_sentence(inputs)
        if key == "client" and not inputs.get("client"):
            answer = None
        qa.append(
            {
                "key": key,
                "question": question,
                "answer": answer,
                "source": _QA_SOURCES[key] if answer else None,
            }
        )
    by_id = {
        _cap(item.get("id"), 40): item
        for item in (data.get("screening") or [])
        if isinstance(item, dict)
    }
    screening: list[dict[str, Any]] = []
    for q in inputs.get("screening_questions") or []:
        item = by_id.get(q["id"], {})
        good = g.clean(item.get("good"), 800) or (q["ideal_answer"] or None)
        reject = None
        if q.get("deal_breaker"):
            reject = g.clean(item.get("reject"), 500) or q["deal_breaker"]
        screening.append(
            {
                "question_id": q["id"],
                "question": q["question"],
                "why": g.clean(item.get("why"), 400),
                "good": good,
                "reject": reject,
                "original": {
                    "ideal_answer": q.get("ideal_answer") or None,
                    "deal_breaker": q.get("deal_breaker") or None,
                },
            }
        )
    notes_raw = (
        data.get("term_notes") if isinstance(data.get("term_notes"), dict) else {}
    )
    allowed_terms = set(inputs.get("terms") or [])
    term_notes = {
        key: note
        for key, note in (
            (k, g.clean(v, 300)) for k, v in notes_raw.items() if k in allowed_terms
        )
        if note
    }
    day = [
        s for s in (g.clean(v, 300) for v in (data.get("day_to_day") or [])[:3]) if s
    ]
    return {
        "one_liner": g.clean(data.get("one_liner"), 400),
        "example": g.clean(data.get("example"), 600),
        "day_to_day": day,
        "pitch": _with_rate(g.clean(data.get("pitch"), 1200), inputs),
        "candidate_qa": qa,
        "screening_plain": screening,
        "term_notes": term_notes,
    }


async def load_brief(db: AsyncSession, job_id: int) -> Optional[JobPlainBrief]:
    return await db.get(JobPlainBrief, job_id)


async def generate(
    db: AsyncSession,
    job: Job,
    inputs: dict[str, Any],
    *,
    user_id: Optional[int] = None,
) -> JobPlainBrief:
    """Liczy teksty (gdy trzeba) i zapisuje wiersz. Nigdy nie rzuca z powodu AI."""
    from app.models.ai_feature import AIFeatureKey
    from app.services.ai_models import model_for
    from app.services.ai_quota import ai_feature
    from app.services.champion_draft_service import _call_claude_json
    from app.services.llm_prompts import PLAIN_JOB_BRIEF
    from app.services.prompt_fencing import json_for_prompt

    job_id = job.id
    model = model_for(AIFeatureKey.champion_draft)
    digest = inputs_hash(inputs, model)
    stored = await load_brief(db, job_id)
    if stored is not None and stored.status == "ready" and stored.inputs_hash == digest:
        return stored

    shaped: Optional[dict[str, Any]] = None
    try:
        async with ai_feature(db, AIFeatureKey.champion_draft, user_id=user_id):
            await db.commit()
            raw = await _call_claude_json(
                prompt=PLAIN_JOB_BRIEF.render(data=json_for_prompt(inputs)),
                system_prompt=PLAIN_JOB_BRIEF.system_prompt or "",
                model=model,
                max_tokens=3500,
            )
        shaped = shape_output(raw, inputs)
    except Exception as exc:  # noqa: BLE001 — AI to dodatek, nigdy bramka
        logger.warning(
            "plain_job_brief: model call failed job=%s err=%s",
            job_id,
            type(exc).__name__,
        )
        await db.rollback()

    row = await db.get(
        JobPlainBrief, job_id, with_for_update=True, populate_existing=True
    )
    if row is None:
        row = JobPlainBrief(job_id=job_id)
        db.add(row)
    row.inputs_hash = digest
    row.generated_at = datetime.now(timezone.utc)
    if shaped is None or not (shaped.get("one_liner") or shaped.get("pitch")):
        row.status = "failed"
        row.message = FAILED
        if shaped is not None:
            row.screening_plain = shaped["screening_plain"]
    else:
        row.status = "ready"
        row.message = None
        row.model = model
        for key, value in shaped.items():
            setattr(row, key, value)
    await db.commit()
    return row


async def existing_job(db: AsyncSession, job_id: int) -> Optional[Job]:
    return await db.scalar(select(Job).where(Job.id == job_id))
