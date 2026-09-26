"""Kontekst klienta dla propozycji profilu Championa (strona /jobs/new).

Trzy źródła, wszystkie już w bazie, żadne nie woła modelu:

* karta klienta (`client_playbooks`): co mówić kandydatowi o kliencie, reguły
  priorytetu;
* do trzech profili Championa z WCZEŚNIEJSZYCH rekrutacji tego klienta
  (18 miesięcy), wybranych po wspólnych słowach tytułu z treścią requestu —
  bez wektorów, bo rekrutacja jeszcze nie istnieje;
* pytania, które klient zadawał na rozmowach (bank `interview_questions`,
  źródło `client_debrief`);
* pytania z archiwum rozmów (źródło `legacy_import`, 0383) — WYŁĄCZNIE te,
  które pytają o technologie wymienione w requeście
  (`client_question_archive`). Nigdy „najnowsze N” archiwum: u Nordei to
  tysiąc pytań z kilkudziesięciu ról.

Kontekst trafia do modelu jako materiał do PROPOZYCJI (frazy, argumenty,
pytania), nigdy jako fakty o nowej rekrutacji. Nie niesie nazwisk: z profili
historycznych bierzemy wyłącznie opis projektu, frazy wyszukiwania, pytania
screeningowe i argumenty — bez „insightów konsultanta” i notatek, w których
padają imiona.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.client_playbook import ClientPlaybook
from app.models.interview_question import InterviewQuestion, InterviewQuestionSource
from app.models.job import Job
from app.services import champion_view
from app.services.champion_document import folded

HISTORY_WINDOW_DAYS = 548
MAX_PAST_PROFILES = 3
MAX_DEBRIEF_QUESTIONS = 15
MAX_ARCHIVE_QUESTIONS = 10
_CANDIDATE_POOL = 40
_FIELD_CAP = 400
_WORD = re.compile(r"[a-z0-9+#.]{3,}")


def _words(text: str) -> set[str]:
    return set(_WORD.findall(folded(text or "")))


def _cap(value: Any, limit: int = _FIELD_CAP) -> str:
    return value.strip()[:limit] if isinstance(value, str) else ""


def _compact_profile(job: Job) -> dict[str, Any]:
    profile = job.champion_profile or {}
    project = champion_view.project(profile)
    search = champion_view.search(profile)
    client = champion_view.client(profile)
    experience = champion_view.experience(profile)
    return {
        "title": _cap(job.title, 160),
        "project_about": _cap(project.get("about")),
        "search_keywords": _cap(search.get("keywords")),
        "target_companies": _cap(search.get("target_companies")),
        "selling_points": _cap(client.get("selling_points")),
        "domains": [item["name"] for item in experience.get("domains") or []][:6],
        "certifications": [
            item["name"] for item in experience.get("certifications") or []
        ][:6],
        "screening_questions": [
            _cap(q.get("question"), 200)
            for q in champion_view.screening_questions(profile)
            if isinstance(q, dict) and q.get("question")
        ][:5],
    }


async def debrief_questions(db: AsyncSession, client_id: int) -> list[str]:
    rows = (
        await db.execute(
            select(InterviewQuestion.text)
            .where(
                InterviewQuestion.client_id == client_id,
                InterviewQuestion.source == InterviewQuestionSource.client_debrief,
            )
            .order_by(InterviewQuestion.id.desc())
            .limit(MAX_DEBRIEF_QUESTIONS)
        )
    ).scalars()
    return [_cap(text, 300) for text in rows if isinstance(text, str) and text.strip()]


async def archive_questions_for_request(
    db: AsyncSession, client_id: int, request_text: str
) -> list[str]:
    """Pytania z archiwum rozmów o technologie, które padają w requeście."""
    from app.services.client_question_archive import archive_questions_for_role
    from app.services.question_suggestions import mentioned_technologies

    matches = await archive_questions_for_role(
        db,
        client_id=client_id,
        requirement_names=mentioned_technologies(request_text or ""),
        limit=MAX_ARCHIVE_QUESTIONS,
    )
    return [_cap(m.question.text, 300) for m in matches]


async def load_client_context(
    db: AsyncSession, *, client_id: int, request_text: str
) -> dict[str, Any]:
    playbook = await db.scalar(
        select(ClientPlaybook).where(ClientPlaybook.client_id == client_id)
    )
    since = datetime.now(timezone.utc) - timedelta(days=HISTORY_WINDOW_DAYS)
    # Data otwarcia, nie importu: `created_at` rekrutacji z Traffita to maj
    # 2026 dla całego archiwum, więc okno i „najnowsze” wybierały losowo
    # (runda 7, R7-V3-1 — bliźniak listy praktykanta).
    started = func.coalesce(Job.opened_at, Job.created_at)
    jobs = (
        (
            await db.execute(
                select(Job)
                .where(
                    Job.client_id == client_id,
                    Job.champion_profile.is_not(None),
                    started >= since,
                )
                .order_by(started.desc(), Job.id.desc())
                .limit(_CANDIDATE_POOL)
            )
        )
        .scalars()
        .all()
    )
    request_words = _words(request_text)
    ranked = sorted(
        (job for job in jobs if champion_view.project(job).get("about")),
        key=lambda job: len(_words(job.title or "") & request_words),
        reverse=True,
    )
    return {
        "playbook": {
            "about_for_candidate": _cap(
                getattr(playbook, "about_for_candidate", None), 800
            ),
            "priority_rules": _cap(getattr(playbook, "priority_rules", None), 600),
        }
        if playbook is not None
        else None,
        "past_profiles": [_compact_profile(job) for job in ranked[:MAX_PAST_PROFILES]],
        "debrief_questions": await debrief_questions(db, client_id),
        "archive_questions_same_technologies": await archive_questions_for_request(
            db, client_id, request_text
        ),
    }


def render_client_context(context: Optional[dict[str, Any]]) -> str:
    """Kontekst jako JSON dla promptu; brak danych = jawne „(brak)”."""
    if not context:
        return "(brak)"
    useful = {
        key: value
        for key, value in context.items()
        if value and (not isinstance(value, dict) or any(value.values()))
    }
    if not useful:
        return "(brak)"
    from app.services.prompt_fencing import json_for_prompt

    return json_for_prompt(useful)[:9000]
