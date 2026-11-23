"""„Klient coś zmienił” — zmiana od klienta w Profilu Championa (23.11.2026).

Zgłoszenie DL-a: klient nagle wymaga Pythona, a zmiana w wymaganiach, opisie
i pytaniach to dziś kilka osobnych szuflad i zapisów (442079: 4 zapisy
w 25 min). DL wkleja mail albo opisuje zmianę, model proponuje listę zmian
z cytatem, DL odznacza albo poprawia, a zapis idzie zwykłą drogą profilu
(`_save_champion_profile`), więc wersja w „Zmiany” i karta dla rekruterów
powstają jak przy każdym zapisie. Makiety i decyzja Artura:
https://claude.ai/artifact/8LzfUqcUmrivAN2RRz6V8F (wariant A + Jarvis).

Wynik modelu to dane z zewnątrz: każda zmiana przechodzi `clean_changes`
przeciw obecnemu profilowi, tak samo zmiany odesłane przez front po edycji.
Krytycznych model nie ustawia — krytyczne DL wybiera świadomie w edytorze
wierszy (`umiejetnosci-krytyczne-i-bramka-v9.md`).
"""

from __future__ import annotations

import copy
import logging
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.champion import (
    EXPERIENCE_ITEM_MAX_CHARS,
    EXPERIENCE_ITEMS_MAX,
    STACK_ITEM_MAX_CHARS,
)

logger = logging.getLogger(__name__)

TEXT_MIN_CHARS = 10
TEXT_MAX_CHARS = 20_000
CHANGES_MAX = 20
QUOTE_MAX_CHARS = 300
NOTES_MAX_CHARS = 600
QUESTION_MAX_CHARS = 2_000
QUESTION_HINT_MAX_CHARS = 1_000
FIELD_MAX_CHARS = 6_000
QUESTIONS_MAX = 15
GAP_PEOPLE_MAX = 30

FAILED = (
    "Nie udało się przygotować zmian. Spróbuj ponownie albo zmień bloki "
    "ręcznie przyciskami „Edytuj”."
)
NOTHING = "W treści nie widać zmiany w wymaganiach, opisie ani pytaniach."

# Pola tekstowe, które model może przepisać w całości (front pokazuje różnicę).
TEXT_FIELDS: dict[str, str] = {
    "project.about": "O projekcie",
    "project.responsibilities": "Obowiązki",
    "client.selling_points": "Co powiedzieć kandydatowi",
}
ROW_LEVELS = ("must", "nice")
OPS = (
    "row_add",
    "row_remove",
    "row_level",
    "notes_append",
    "talk_add",
    "question_add",
    "question_remove",
    "question_edit",
    "text_edit",
)

# Etapy osób w procesie dla „Co to zmienia”. Oferta i dalej to już za późno
# na dopytanie, a „wstrzymany” nie jest w pracy — tych nie liczymy.
BEFORE_SCREENING = ("identified", "screening_pending")
AFTER_SCREENING = (
    "screening_completed",
    "internal_review",
    "internally_approved",
    "submission_preparation",
    "submission_approved",
    "submission_dispatch_pending",
)
AT_CLIENT = (
    "submitted_to_client",
    "client_review",
    "client_interview_scheduled",
    "client_interview_completed",
    "feedback_pending",
    "client_approved",
)


def _clip(value: Any, limit: int) -> str:
    if not isinstance(value, str):
        return ""
    text = " ".join(value.split()) if "\n" not in value else value.strip()
    return text[:limit].strip()


def _one_line(value: Any, limit: int) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(value.split())[:limit].strip()


def _key(word: str) -> str:
    return " ".join(word.split()).casefold()


# ── profil → wiersze ─────────────────────────────────────────────────────────


def _names(items: Any) -> list[str]:
    out: list[str] = []
    for item in items or ():
        name = item.get("name") if isinstance(item, dict) else item
        if isinstance(name, str) and name.strip():
            out.append(" ".join(name.split()))
    return out


def current_rows(profile: dict[str, Any]) -> list[dict[str, Any]]:
    """Wiersze wymagań profilu; profil sprzed wierszy czytany z must / nice."""
    stack = profile.get("stack") or {}
    rows = stack.get("rows")
    if isinstance(rows, list):
        out = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            words = [w for w in _names(row.get("words")) if w]
            if words:
                level = row.get("level") if row.get("level") in ROW_LEVELS else "must"
                out.append({"words": words, "level": level})
        return out
    return [{"words": [n], "level": "must"} for n in _names(stack.get("must"))] + [
        {"words": [n], "level": "nice"} for n in _names(stack.get("nice"))
    ]


def _row_index(rows: list[dict[str, Any]], word: str) -> Optional[int]:
    """Wiersz, którego pierwsze słowo albo któreś słowo to ``word``."""
    key = _key(word)
    for i, row in enumerate(rows):
        if _key(row["words"][0]) == key:
            return i
    for i, row in enumerate(rows):
        if any(_key(w) == key for w in row["words"]):
            return i
    return None


def _critical_keys(profile: dict[str, Any]) -> set[str]:
    stack = profile.get("stack") or {}
    return {_key(n) for n in stack.get("critical") or () if isinstance(n, str)}


def _get_field(profile: dict[str, Any], path: str) -> str:
    section, field = path.split(".")
    value = (profile.get(section) or {}).get(field)
    return value if isinstance(value, str) else ""


def profile_excerpt(profile: dict[str, Any]) -> dict[str, Any]:
    """Ta część profilu, którą widzi model (bez osób, kwot i kontaktów)."""
    critical = _critical_keys(profile)
    rows = []
    for row in current_rows(profile):
        level = row["level"]
        if level == "must" and _key(row["words"][0]) in critical:
            level = "critical"
        rows.append({"word": row["words"][0], "level": level})
    experience = profile.get("experience") or {}
    return {
        "requirements": rows,
        "notes": _get_field(profile, "stack.notes"),
        "talk_items": _names(experience.get("skills")),
        "questions": [
            {
                "id": q.get("id"),
                "question": q.get("question", ""),
                "ideal_answer": q.get("ideal_answer", ""),
                "deal_breaker": q.get("deal_breaker", ""),
            }
            for q in profile.get("screening_questions") or ()
            if isinstance(q, dict) and q.get("id")
        ],
        **{path: _get_field(profile, path) for path in TEXT_FIELDS},
    }


# ── walidacja zmian (model i front) ──────────────────────────────────────────


def _question_ids(profile: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(q["id"]): q
        for q in profile.get("screening_questions") or ()
        if isinstance(q, dict) and q.get("id")
    }


def _clean_one(  # noqa: C901 — jedna gałąź na rodzaj zmiany, czytelniej razem
    raw: dict[str, Any],
    profile: dict[str, Any],
    rows: list[dict[str, Any]],
    seen: set[tuple[str, str]],
) -> Optional[dict[str, Any]]:
    op = raw.get("op")
    if op not in OPS:
        return None
    quote = _one_line(raw.get("quote"), QUOTE_MAX_CHARS)
    base: dict[str, Any] = {"op": op, "quote": quote}

    if op == "row_add":
        word = _one_line(raw.get("word"), STACK_ITEM_MAX_CHARS)
        level = raw.get("level") if raw.get("level") in ROW_LEVELS else "must"
        if not word or (op, _key(word)) in seen:
            return None
        index = _row_index(rows, word)
        if index is not None:
            if rows[index]["level"] == level:
                return None
            return {
                **base,
                "op": "row_level",
                "word": rows[index]["words"][0],
                "level": level,
                "before": rows[index]["level"],
            }
        seen.add((op, _key(word)))
        return {**base, "word": word, "level": level}

    if op in ("row_remove", "row_level"):
        word = _one_line(raw.get("word"), STACK_ITEM_MAX_CHARS)
        index = _row_index(rows, word) if word else None
        if index is None or (op, _key(word)) in seen:
            return None
        seen.add((op, _key(word)))
        row = rows[index]
        if op == "row_remove":
            return {**base, "word": row["words"][0], "before": row["level"]}
        level = raw.get("level") if raw.get("level") in ROW_LEVELS else None
        if level is None or level == row["level"]:
            return None
        return {**base, "word": row["words"][0], "level": level, "before": row["level"]}

    if op == "notes_append":
        text = _one_line(raw.get("text"), NOTES_MAX_CHARS)
        if not text or text.casefold() in _get_field(profile, "stack.notes").casefold():
            return None
        return {**base, "text": text}

    if op == "talk_add":
        name = _one_line(raw.get("name"), EXPERIENCE_ITEM_MAX_CHARS)
        level = raw.get("level") if raw.get("level") in ROW_LEVELS else "must"
        existing = {
            _key(n) for n in _names((profile.get("experience") or {}).get("skills"))
        }
        if not name or _key(name) in existing or (op, _key(name)) in seen:
            return None
        seen.add((op, _key(name)))
        return {**base, "name": name, "level": level}

    questions = _question_ids(profile)
    if op == "question_add":
        question = _clip(raw.get("question"), QUESTION_MAX_CHARS)
        if not question:
            return None
        return {
            **base,
            "question": question,
            "ideal_answer": _clip(raw.get("ideal_answer"), QUESTION_HINT_MAX_CHARS),
            "deal_breaker": _clip(raw.get("deal_breaker"), QUESTION_HINT_MAX_CHARS),
        }
    if op in ("question_remove", "question_edit"):
        # Model podaje id pytania jako `id`, front odsyła `question_id`
        # (`id` zmiany to jej numer „c1”…).
        qid = str(raw.get("question_id") or raw.get("id") or "")
        if qid not in questions or (op, qid) in seen:
            return None
        seen.add((op, qid))
        current = questions[qid]
        if op == "question_remove":
            return {**base, "question_id": qid, "before": current.get("question", "")}
        after = {
            field: _clip(raw.get(field), limit)
            for field, limit in (
                ("question", QUESTION_MAX_CHARS),
                ("ideal_answer", QUESTION_HINT_MAX_CHARS),
                ("deal_breaker", QUESTION_HINT_MAX_CHARS),
            )
            if isinstance(raw.get(field), str)
        }
        after = {k: v for k, v in after.items() if v != (current.get(k) or "")}
        if not after or after.get("question") == "":
            return None
        before = {k: current.get(k) or "" for k in after}
        return {**base, "question_id": qid, "after": after, "before": before}

    # text_edit
    field = raw.get("field")
    if field not in TEXT_FIELDS or (op, field) in seen:
        return None
    after = _clip(raw.get("after"), FIELD_MAX_CHARS)
    before = _get_field(profile, field)
    if not after or after == before.strip():
        return None
    seen.add((op, field))
    return {
        **base,
        "field": field,
        "label": TEXT_FIELDS[field],
        "before": before,
        "after": after,
    }


def clean_changes(raw: Any, profile: dict[str, Any]) -> list[dict[str, Any]]:
    """Zmiany sprawdzone przeciw obecnemu profilowi, z numerami ``c1``…"""
    if not isinstance(raw, list):
        return []
    rows = current_rows(profile)
    seen: set[tuple[str, str]] = set()
    out: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        change = _clean_one(item, profile, rows, seen)
        if change is not None:
            out.append(change)
        if len(out) >= CHANGES_MAX:
            break
    return [{"id": f"c{i}", **change} for i, change in enumerate(out, start=1)]


# ── zastosowanie (czysta funkcja) ────────────────────────────────────────────


def apply_changes(
    profile: dict[str, Any], changes: list[dict[str, Any]]
) -> dict[str, Any]:
    """Ładunek zapisu profilu: tylko sekcje, których dotyczą zmiany.

    Zmiany muszą przejść `clean_changes` na tym samym profilu. Wiersze idą
    jako `stack.rows`; `must`, `nice`, krytyczne i wiersze wyszukiwania
    wyprowadza zapis (`expand_patch`), a zdanie wpisane jako wiersz przenosi
    do rozmowy `separate_talk_items` — jak przy edycji ręcznej.
    """
    profile = copy.deepcopy(profile)
    rows = current_rows(profile)
    touched: set[str] = set()
    stack = dict(profile.get("stack") or {})
    experience = dict(profile.get("experience") or {})
    project = dict(profile.get("project") or {})
    client = dict(profile.get("client") or {})
    questions = [
        dict(q) for q in profile.get("screening_questions") or () if isinstance(q, dict)
    ]
    sections = {"project": project, "client": client}

    for change in changes:
        op = change["op"]
        if op == "row_add":
            rows.append({"words": [change["word"]], "level": change["level"]})
            touched.add("stack")
        elif op == "row_remove":
            index = _row_index(rows, change["word"])
            if index is not None:
                rows.pop(index)
                touched.add("stack")
        elif op == "row_level":
            index = _row_index(rows, change["word"])
            if index is not None:
                rows[index] = {**rows[index], "level": change["level"]}
                touched.add("stack")
        elif op == "notes_append":
            base = str(stack.get("notes") or "").strip()
            stack["notes"] = "\n".join(p for p in (base, change["text"]) if p)
            touched.add("stack")
        elif op == "talk_add":
            skills = list(experience.get("skills") or [])
            if len(skills) < EXPERIENCE_ITEMS_MAX:
                skills.append(
                    {
                        "name": change["name"],
                        "level": change["level"],
                        "min_years": None,
                        "note": "",
                    }
                )
                experience["skills"] = skills
                touched.add("experience")
        elif op == "question_add":
            if len(questions) < QUESTIONS_MAX:
                used = {q.get("id") for q in questions}
                n = len(questions) + 1
                while f"q{n}" in used:
                    n += 1
                questions.append(
                    {
                        "id": f"q{n}",
                        "question": change["question"],
                        "ideal_answer": change.get("ideal_answer", ""),
                        "deal_breaker": change.get("deal_breaker", ""),
                    }
                )
                touched.add("screening_questions")
        elif op == "question_remove":
            questions = [q for q in questions if q.get("id") != change["question_id"]]
            touched.add("screening_questions")
        elif op == "question_edit":
            for q in questions:
                if q.get("id") == change["question_id"]:
                    q.update(change["after"])
            touched.add("screening_questions")
        elif op == "text_edit":
            section, field = change["field"].split(".")
            sections[section][field] = change["after"]
            touched.add(section)

    payload: dict[str, Any] = {}
    if "stack" in touched:
        stack["rows"] = rows
        payload["stack"] = stack
    if "experience" in touched:
        payload["experience"] = experience
    if "screening_questions" in touched:
        payload["screening_questions"] = questions
    if "project" in touched:
        payload["project"] = project
    if "client" in touched:
        payload["client"] = client
    return payload


# ── model ────────────────────────────────────────────────────────────────────


async def propose(
    db: AsyncSession,
    *,
    profile: dict[str, Any],
    role: str,
    text: str,
    user_id: Optional[int],
) -> dict[str, Any]:
    """Propozycja zmian z treści od klienta. Awaria modelu = ``status: failed``."""
    from app.models.ai_feature import AIFeatureKey
    from app.services.ai_models import model_for
    from app.services.ai_quota import ai_feature
    from app.services.champion_draft_service import _call_claude_json
    from app.services.llm_prompts import CHAMPION_CLIENT_CHANGE
    from app.services.prompt_fencing import fence, json_for_prompt

    model = model_for(AIFeatureKey.champion_draft)
    try:
        async with ai_feature(db, AIFeatureKey.champion_draft, user_id=user_id):
            await db.commit()
            raw = await _call_claude_json(
                prompt=CHAMPION_CLIENT_CHANGE.render(
                    role=_one_line(role, 200) or "nie podano",
                    profile=json_for_prompt(profile_excerpt(profile)),
                    text=fence("zmiana_od_klienta", text[:TEXT_MAX_CHARS]),
                ),
                system_prompt=CHAMPION_CLIENT_CHANGE.system_prompt or "",
                model=model,
                max_tokens=4000,
            )
    except Exception:  # noqa: BLE001 — AI to dodatek, nigdy bramka
        logger.warning("champion_client_change: model call failed", exc_info=True)
        return {"status": "failed", "changes": [], "note": "", "message": FAILED}
    raw = raw if isinstance(raw, dict) else {}
    changes = clean_changes(raw.get("changes"), profile)
    note = _one_line(raw.get("note"), NOTES_MAX_CHARS)
    return {
        "status": "ready",
        "changes": changes,
        "note": note if changes else "",
        "message": None if changes else NOTHING,
        "model": model,
    }


# ── skutki dla osób w procesie ───────────────────────────────────────────────


def gap_words(changes: list[dict[str, Any]]) -> list[str]:
    """Słowa, które stają się wymagane: nowy wiersz „musi mieć” albo awans."""
    return [
        c["word"]
        for c in changes
        if c["op"] in ("row_add", "row_level") and c.get("level") == "must"
    ]


def process_lead(
    *, owner: Optional[int], claimed: Optional[int], opened: Optional[int]
) -> Optional[int]:
    """Kto prowadzi kandydata: właściciel procesu, potem zajmujący, potem dodający.

    Kopia stagingu z 23.11: `owner_user_id` puste w 85% otwartych procesów,
    a `opened_by_user_id` to zwykle rekruter, który kandydata dodał.
    """
    return owner or claimed or opened


def _stage_group(state: Optional[str]) -> Optional[str]:
    if state in BEFORE_SCREENING:
        return "before_screening"
    if state in AFTER_SCREENING:
        return "after_screening"
    if state in AT_CLIENT:
        return "at_client"
    return None


async def process_gaps(
    db: AsyncSession, job_id: int, words: list[str]
) -> list[dict[str, Any]]:
    """Osoby w otwartych procesach bez słowa w CV — per słowo.

    Przybliżenie „Szukaj w CV”: słowo w treści CV albo w umiejętnościach.
    Osoby po screeningu i u klienta wracają z imieniem, bo do nich idzie
    dzwonek „dopytaj”; reszta to liczby.
    """
    from sqlalchemy import String, cast, or_

    from app.models.candidate import Candidate
    from app.models.recruitment_process import ProcessStatus, RecruitmentProcess

    if not words:
        return []
    rows = (
        await db.execute(
            select(
                RecruitmentProcess.id,
                RecruitmentProcess.candidate_id,
                RecruitmentProcess.current_semantic_state,
                RecruitmentProcess.owner_user_id,
                RecruitmentProcess.claimed_by_user_id,
                RecruitmentProcess.opened_by_user_id,
                Candidate.name,
                Candidate.lastname,
            )
            .join(Candidate, Candidate.id == RecruitmentProcess.candidate_id)
            .where(
                RecruitmentProcess.job_id == job_id,
                RecruitmentProcess.status == ProcessStatus.open,
            )
        )
    ).all()
    open_total = sum(1 for r in rows if _stage_group(r.current_semantic_state))
    out: list[dict[str, Any]] = []
    for word in words:
        pattern = f"%{word}%"
        having = set(
            (
                await db.scalars(
                    select(Candidate.id).where(
                        Candidate.id.in_([r.candidate_id for r in rows] or [-1]),
                        or_(
                            Candidate.raw_cv_text.ilike(pattern),
                            cast(Candidate.skills, String).ilike(pattern),
                        ),
                    )
                )
            ).all()
        )
        counts = {"before_screening": 0, "after_screening": 0, "at_client": 0}
        people: list[dict[str, Any]] = []
        for r in rows:
            group = _stage_group(r.current_semantic_state)
            if group is None or r.candidate_id in having:
                continue
            counts[group] += 1
            if group != "before_screening" and len(people) < GAP_PEOPLE_MAX:
                people.append(
                    {
                        "process_id": r.id,
                        "candidate_id": r.candidate_id,
                        "name": f"{r.name or ''} {r.lastname or ''}".strip()
                        or f"Kandydat {r.candidate_id}",
                        "stage": group,
                        "owner_user_id": process_lead(
                            owner=r.owner_user_id,
                            claimed=r.claimed_by_user_id,
                            opened=r.opened_by_user_id,
                        ),
                    }
                )
        out.append(
            {
                "word": word,
                "open_total": open_total,
                "missing": counts,
                "people": people,
            }
        )
    return out


async def notify_gap_owners(
    db: AsyncSession,
    *,
    job: Any,
    gaps: list[dict[str, Any]],
    actor_id: int,
) -> int:
    """Dzwonek „dopytaj” do osób prowadzących kandydatów po screeningu i u klienta.

    Bez osoby prowadzącej dzwonek idzie do rekrutera rekrutacji. Autor zmiany
    dzwonka nie dostaje. Jeden dzwonek na osobę, z listą kandydatów.
    """
    from app.api.notifications import create_notification
    from app.models.notification import NotificationType

    by_owner: dict[int, list[str]] = {}
    for gap in gaps:
        for person in gap["people"]:
            owner = person["owner_user_id"] or job.recruiter_id
            if owner is None or owner == actor_id:
                continue
            line = f"{person['name']} — {gap['word']}"
            if line not in by_owner.setdefault(owner, []):
                by_owner[owner].append(line)
    link = f"/jobs/{job.id}?tab=board"
    for owner, lines in by_owner.items():
        shown = "; ".join(lines[:5]) + (
            f" i {len(lines) - 5} więcej" if len(lines) > 5 else ""
        )
        await create_notification(
            db=db,
            user_id=owner,
            title="Klient zmienił wymagania — dopytaj kandydatów",
            message=f"{job.title}: nowe wymaganie, którego nie ma w CV. Dopytaj: {shown}.",
            notification_type=NotificationType.champion_profile_updated,
            link=link,
            related_entity_type="job",
            related_entity_id=job.id,
        )
    return len(by_owner)
