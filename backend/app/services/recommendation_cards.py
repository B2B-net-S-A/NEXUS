"""Karta rekomendacji pary (kandydat, rekrutacja) — reguły (0413).

Karta to PROJEKCJA notatek rekrutera plus pola wpisane w NEXUSIE:

* ``fields_notes`` — przeliczane od zera z notatek pary rodzaju „karta”
  i „fakty ze screeningu” (``recommendation_card_parser``). Nowsza notatka
  wygrywa pole po polu; każde pole pamięta notatkę-źródło i jej datę.
* ``fields_manual`` — wpisane w NEXUSIE. Zawsze wygrywają z notatką.
* ``note_answers`` — pytania i odpowiedzi z najnowszej notatki, która je ma.
  Tylko do odczytu: NIE trafiają do arkusza screeningu (arkusz zmienia
  punktację i wychodzi do klienta).

Czego ten moduł świadomie nie robi:

* nie zapisuje niczego w profilu kandydata — fakty profilu (stawka,
  dostępność, tryb pracy) wypełnia nocny odczyt notatek;
* nie podaje narodowości żadnemu modelowi ani dopasowaniu. Importować go mogą
  tylko moduły z listy w ``test_recommendation_cards.py``.

Ponowne dodanie osoby do rekrutacji (kolejna próba procesu): wartości sprzed
początku bieżącej próby są podpowiedzią (``previous``), a kompletność liczy
się od nowa. Rozstrzyga data pola, nie osobny licznik.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable, Mapping, Optional

from sqlalchemy import func, select, text, tuple_
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.note import Note
from app.models.recommendation_card import RecommendationCard
from app.models.recruitment_process import RecruitmentProcess
from app.services.recommendation_card_rules import (  # noqa: F401 — jedno wejście dla wołających
    CARD_KINDS,
    EDITABLE_FIELDS,
    LABELS,
    REQUIRED_FIELDS,
    NoteInput,
    completeness,
    current_answers,
    is_current,
    legacy_text,
    manual_value,
    max_length,
    merge_questions,
    project_notes,
    split_fields,
)


def attempt_started(process: object) -> Optional[datetime]:
    """Początek bieżącej próby procesu — tylko gdy osoba wróciła do rekrutacji."""
    if process is None or (getattr(process, "attempt_no", None) or 1) <= 1:
        return None
    return getattr(process, "opened_at", None) or getattr(process, "created_at", None)


def card_summary(
    fields_notes: Mapping[str, object],
    fields_manual: Mapping[str, object],
    note_answers: object,
    *,
    started: Optional[datetime] = None,
) -> dict[str, object]:
    """Stan karty dla plakietek i wymagań ruchu — bez treści pól."""
    current, _ = split_fields(fields_notes, fields_manual, attempt_started=started)
    state = completeness(current)
    answers = current_answers(note_answers, attempt_started=started)
    return {
        "status": state["status"],
        "missing": state["missing"],
        "missing_labels": [LABELS[key] for key in state["missing"]],
        "answers": len(answers["items"]) if answers else 0,
    }


async def summaries_for_job(
    db: AsyncSession,
    *,
    job_id: int,
    started_by_candidate: Mapping[int, Optional[datetime]],
) -> dict[int, dict[str, object]]:
    """Stan kart osób z jednej rekrutacji — jedno zapytanie na tablicę.

    Osoba bez wiersza karty nie ma wpisu (ekran mówi wtedy „bez karty”).
    """
    if not started_by_candidate:
        return {}
    rows = await db.execute(
        select(
            RecommendationCard.candidate_id,
            RecommendationCard.fields_notes,
            RecommendationCard.fields_manual,
            RecommendationCard.note_answers,
        ).where(
            RecommendationCard.job_id == job_id,
            RecommendationCard.candidate_id.in_(sorted(started_by_candidate)),
        )
    )
    return {
        candidate_id: card_summary(
            notes or {},
            manual or {},
            answers,
            started=started_by_candidate.get(candidate_id),
        )
        for candidate_id, notes, manual, answers in rows.all()
    }


async def summaries_for_pairs(
    db: AsyncSession, pairs: Iterable[tuple[int, int]]
) -> dict[tuple[int, int], dict[str, object]]:
    """Stan kart dla par (kandydat, rekrutacja) z wielu rekrutacji.

    Dwa zapytania niezależnie od liczby par: karty i najnowsza próba procesu
    (wartości sprzed bieżącej próby nie liczą się do kompletności).
    """
    wanted = sorted(set(pairs))
    if not wanted:
        return {}
    pair = tuple_(RecommendationCard.candidate_id, RecommendationCard.job_id)
    cards = (
        await db.execute(
            select(
                RecommendationCard.candidate_id,
                RecommendationCard.job_id,
                RecommendationCard.fields_notes,
                RecommendationCard.fields_manual,
                RecommendationCard.note_answers,
            ).where(pair.in_(wanted))
        )
    ).all()
    if not cards:
        return {}
    process_pair = tuple_(RecruitmentProcess.candidate_id, RecruitmentProcess.job_id)
    processes = await db.execute(
        select(RecruitmentProcess)
        .where(process_pair.in_([(c, j) for c, j, *_ in cards]))
        .order_by(
            RecruitmentProcess.candidate_id,
            RecruitmentProcess.job_id,
            RecruitmentProcess.attempt_no.desc(),
            RecruitmentProcess.id.desc(),
        )
        .distinct(RecruitmentProcess.candidate_id, RecruitmentProcess.job_id)
    )
    started = {
        (p.candidate_id, p.job_id): attempt_started(p) for p in processes.scalars()
    }
    return {
        (candidate_id, job_id): card_summary(
            notes or {},
            manual or {},
            answers,
            started=started.get((candidate_id, job_id)),
        )
        for candidate_id, job_id, notes, manual, answers in cards
    }


async def load_notes(
    db: AsyncSession, *, candidate_id: int, job_id: int
) -> list[NoteInput]:
    rows = await db.execute(
        select(
            Note.id,
            Note.content,
            func.coalesce(Note.source_created_at, Note.created_at),
        ).where(
            Note.candidate_id == candidate_id,
            Note.job_id == job_id,
            Note.kind.in_(CARD_KINDS),
            Note.source_deleted_at.is_(None),
            Note.parent_note_id.is_(None),
        )
    )
    return [NoteInput(id=row[0], content=row[1] or "", at=row[2]) for row in rows.all()]


async def rebuild_pair(db: AsyncSession, *, candidate_id: int, job_id: int) -> bool:
    """Przelicza pola z notatek pary. Zwraca True, gdy karta się zmieniła.

    Pól wpisanych ręcznie nie dotyka. Karty bez żadnej treści nie zakłada,
    a istniejącej nie kasuje — zostaje z pustymi polami z notatek.
    """
    fields, answers = project_notes(
        await load_notes(db, candidate_id=candidate_id, job_id=job_id)
    )
    table = RecommendationCard.__table__
    if not fields and not answers:
        result = await db.execute(
            table.update()
            .where(
                table.c.candidate_id == candidate_id,
                table.c.job_id == job_id,
                (table.c.fields_notes != text("'{}'::jsonb"))
                | (table.c.note_answers != text("'{}'::jsonb")),
            )
            .values(fields_notes={}, note_answers={}, updated_at=func.now())
        )
        return bool(result.rowcount)
    insert = pg_insert(table).values(
        candidate_id=candidate_id,
        job_id=job_id,
        fields_notes=fields,
        note_answers=answers,
    )
    result = await db.execute(
        insert.on_conflict_do_update(
            constraint="uq_recommendation_cards_pair",
            set_={
                "fields_notes": insert.excluded.fields_notes,
                "note_answers": insert.excluded.note_answers,
                "updated_at": func.now(),
            },
            where=(
                table.c.fields_notes.is_distinct_from(insert.excluded.fields_notes)
                | table.c.note_answers.is_distinct_from(insert.excluded.note_answers)
            ),
        )
    )
    return bool(result.rowcount)


_MERGE_MANUAL_SQL = text(
    "UPDATE recommendation_cards AS kept SET "
    "fields_manual = dup.fields_manual || kept.fields_manual, updated_at = now() "
    "FROM recommendation_cards AS dup "
    "WHERE kept.candidate_id = :survivor AND dup.candidate_id = :duplicate "
    "AND dup.job_id = kept.job_id AND dup.fields_manual <> '{}'::jsonb"
)
_MERGE_DROP_SQL = text(
    "DELETE FROM recommendation_cards AS dup USING recommendation_cards AS kept "
    "WHERE kept.candidate_id = :survivor AND dup.candidate_id = :duplicate "
    "AND dup.job_id = kept.job_id"
)


async def merge_manual_fields(
    db: AsyncSession, *, survivor_id: int, duplicate_id: int
) -> None:
    """Scalanie kandydatów: obie osoby mają kartę tej samej rekrutacji.

    Pola wpisane ręcznie łączymy (przy tym samym polu wygrywa karta
    ocalałego), a kartę duplikatu zdejmujemy — pola z notatek i tak przeliczą
    się z notatek przepiętych na ocalałego. Domyślna reguła scalania („nowszy
    wiersz wygrywa”) skasowałaby ręczne pola starszej karty.
    """
    params = {"survivor": survivor_id, "duplicate": duplicate_id}
    await db.execute(_MERGE_MANUAL_SQL, params)
    await db.execute(_MERGE_DROP_SQL, params)


async def load_card(
    db: AsyncSession, *, candidate_id: int, job_id: int, for_update: bool = False
) -> Optional[RecommendationCard]:
    query = select(RecommendationCard).where(
        RecommendationCard.candidate_id == candidate_id,
        RecommendationCard.job_id == job_id,
    )
    if for_update:
        query = query.with_for_update()
    return await db.scalar(query)


async def save_manual(
    db: AsyncSession,
    *,
    candidate_id: int,
    job_id: int,
    changes: Mapping[str, Optional[str]],
    user_id: int,
    now: Optional[datetime] = None,
    attempt_started: Optional[datetime] = None,
) -> tuple[RecommendationCard, list[str]]:
    """Zapisuje pola wpisane w NEXUSIE; ``None`` zdejmuje pole ręczne.

    Zwraca kartę i listę pól, które naprawdę się zmieniły. Ta sama wartość
    wysłana ponownie nie jest zmianą — chyba że pole pochodzi sprzed bieżącej
    próby procesu (``attempt_started``): wtedy zapis potwierdza podpowiedź
    i pole zaczyna się liczyć do kompletności.
    """
    moment = now or datetime.now(timezone.utc)
    table = RecommendationCard.__table__
    await db.execute(
        pg_insert(table)
        .values(candidate_id=candidate_id, job_id=job_id)
        .on_conflict_do_nothing(constraint="uq_recommendation_cards_pair")
    )
    card = await load_card(
        db, candidate_id=candidate_id, job_id=job_id, for_update=True
    )
    assert card is not None  # wiersz założony wyżej, kaskada nie zdąży go zdjąć
    manual = dict(card.fields_manual or {})
    changed: list[str] = []
    for key, raw in changes.items():
        value = (raw or "").strip()
        if not value:
            if manual.pop(key, None) is not None:
                changed.append(key)
            continue
        existing = manual.get(key) or {}
        if str(existing.get("raw") or "") == value and is_current(
            existing, attempt_started
        ):
            continue
        manual[key] = manual_value(key, value, user_id=user_id, now=moment)
        changed.append(key)
    if changed:
        card.fields_manual = manual
        card.updated_by = user_id
        await db.flush()
    return card, changed
