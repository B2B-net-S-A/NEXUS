"""Karta rekomendacji pary (kandydat, rekrutacja) — reguły (0413).

Karta to PROJEKCJA notatek rekrutera plus pola wpisane w NEXUSIE:

* ``fields_notes`` — przeliczane od zera z notatek pary rodzaju „karta”
  i „fakty ze screeningu” (``recommendation_card_parser``). Nowsza notatka
  wygrywa pole po polu; każde pole pamięta notatkę-źródło i jej datę.
* ``fields_manual`` — wpisane w NEXUSIE. Zawsze wygrywają z notatką.
* ``note_answers`` — pytania i odpowiedzi z najnowszej notatki, która je ma.
  Od 07.10.2026 (decyzje Artura, zmiana reguły 0413) ``screening_note_sync``
  przepisuje je do arkusza screeningu pary z pochodzeniem ``note_sync`` —
  arkusz widzi klient i liczy się w ocenie. Arkusza wypełnionego przez
  człowieka automat nie dotyka.

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
from typing import Any, Iterable, Mapping, Optional

from sqlalchemy import ColumnElement, func, select, text, tuple_
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.client import Client
from app.models.job import Job
from app.models.note import Note
from app.models.recommendation_card import RecommendationCard
from app.models.recruitment_process import RecruitmentProcess
from app.models.user import User
from app.services.client_identity import client_display_name_expression
from app.services.recommendation_card_rules import (  # noqa: F401 — jedno wejście dla wołających
    CARD_KINDS,
    CARD_ORIGINS,
    DISPLAY_LABELS,
    EDITABLE_FIELDS,
    KEYWORDS_MAX,
    LABELS,
    PHRASABLE_FIELDS,
    REQUIRED_FIELDS,
    NoteInput,
    attach_deal_breakers,
    completeness,
    current_answers,
    is_current,
    latest_facts,
    legacy_text,
    manual_value,
    max_length,
    merge_questions,
    note_answer_rows,
    note_contributions,
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
    """Stan karty dla plakietek i wymagań ruchu.

    Z treści pól przechodzą tylko dwie rzeczy, których potrzebuje „Przesuń
    dalej”: stawka kandydata w PLN/h (podpowiedź w oknie stawki — widzi ją
    każda rola) i to, czy karta zna dostępność.
    """
    current, _ = split_fields(fields_notes, fields_manual, attempt_started=started)
    state = completeness(current)
    answers = current_answers(note_answers, attempt_started=started)
    return {
        "status": state["status"],
        "missing": state["missing"],
        "missing_labels": [DISPLAY_LABELS[key] for key in state["missing"]],
        "answers": len(answers["items"]) if answers else 0,
        "rate_hourly": _hourly_rate(current.get("rate")),
        "availability": "availability" in current,
    }


def card_rate_hourly(field: object) -> Optional[float]:
    """Publiczne wejście do ``_hourly_rate`` (podpowiedzi formularza umowy)."""
    return _hourly_rate(field)


def _hourly_rate(field: object) -> Optional[float]:
    """Stawka z karty jako PLN/h — tylko gdy parser odczytał ją bez zgadywania."""
    if not isinstance(field, Mapping):
        return None
    value = field.get("value")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if field.get("currency") != "PLN" or field.get("period") != "h":
        return None
    # Widełki („130–150 zł/h”) to nie jedna stawka — nie podpowiadamy dolnej.
    if field.get("value_max") is not None:
        return None
    return float(value)


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
    provenance: Optional[Mapping[str, Mapping[str, Any]]] = None,
) -> tuple[RecommendationCard, list[str]]:
    """Zapisuje pola wpisane w NEXUSIE; ``None`` zdejmuje pole ręczne.

    Zwraca kartę i listę pól, które naprawdę się zmieniły. Ta sama wartość
    wysłana ponownie nie jest zmianą — chyba że pole pochodzi sprzed bieżącej
    próby procesu (``attempt_started``): wtedy zapis potwierdza podpowiedź
    i pole zaczyna się liczyć do kompletności.

    ``provenance`` (0421): pochodzenie pola przyjętego z notatki albo zdania
    ułożonego z haseł — ``{pole: {origin, keywords?, note_id?}}``.
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
        manual[key] = manual_value(
            key,
            value,
            user_id=user_id,
            now=moment,
            provenance=(provenance or {}).get(key),
        )
        changed.append(key)
    if changed:
        card.fields_manual = manual
        card.updated_by = user_id
        await db.flush()
    return card, changed


# ── Karty jednej osoby w profilu kandydata (etap 6, 03.10.2026) ────────────

TRAFFIT_SOURCE = "traffit"


async def candidate_overview(
    db: AsyncSession,
    *,
    candidate_id: int,
    job_scope: Optional[ColumnElement[bool]] = None,
) -> dict[str, Any]:
    """Co karty rekomendacji mówią o osobie — do profilu kandydata.

    * ``facts`` — najświeższe ustalenie każdego pola (stawka, dostępność,
      tryb pracy, angielski, narodowość) z datą, źródłem i rekrutacją;
    * ``conversations`` — odpowiedzi na pytania zapisane w notatkach, po
      jednej pozycji na rekrutację, najnowsze pierwsze;
    * ``note_links`` — co z której notatki trafiło do karty.

    Czysty odczyt, stała liczba zapytań (karty, rekrutacje, notatki-źródła,
    autorzy). ``job_scope`` to zakres odczytu rekrutacji wołającego.
    """
    # Import leniwy: arkusz screeningu importuje wymagania ruchu, a te — ten moduł.
    from app.services import screening_sheets

    query = select(
        RecommendationCard.job_id,
        RecommendationCard.fields_notes,
        RecommendationCard.fields_manual,
        RecommendationCard.note_answers,
    ).where(RecommendationCard.candidate_id == candidate_id)
    if job_scope is not None:
        query = query.where(job_scope)
    cards = [
        {
            "job_id": row.job_id,
            "fields_notes": row.fields_notes or {},
            "fields_manual": row.fields_manual or {},
            "note_answers": row.note_answers,
        }
        for row in (await db.execute(query)).all()
    ]
    if not cards:
        return {"facts": [], "conversations": [], "note_links": []}

    jobs = {
        row.id: row
        for row in (
            await db.execute(
                select(
                    Job.id,
                    Job.title,
                    Job.champion_profile,
                    client_display_name_expression().label("client_name"),
                )
                .outerjoin(Client, Client.id == Job.client_id)
                .where(Job.id.in_(sorted({card["job_id"] for card in cards})))
            )
        ).all()
    }
    facts = latest_facts(cards)
    links = note_contributions(cards)
    notes = {}
    if links:
        notes = {
            row.id: row
            for row in (
                await db.execute(
                    select(Note.id, Note.author_id, Note.external_source).where(
                        Note.id.in_(sorted(links))
                    )
                )
            ).all()
        }
    author_ids = {row.author_id for row in notes.values() if row.author_id} | {
        value["by"] for value in facts.values() if isinstance(value.get("by"), int)
    }
    authors: dict[int, str] = {}
    if author_ids:
        authors = {
            row.id: row.name
            for row in (
                await db.execute(
                    select(User.id, User.name).where(User.id.in_(sorted(author_ids)))
                )
            ).all()
        }

    def _note_author(note_id: Any) -> Optional[str]:
        note = notes.get(note_id) if isinstance(note_id, int) else None
        return authors.get(note.author_id) if note and note.author_id else None

    def _job_title(job_id: Any) -> Optional[str]:
        job = jobs.get(job_id)
        return job.title if job else None

    fact_rows = [
        {
            "key": key,
            "label": DISPLAY_LABELS[key],
            "raw": str(value.get("raw") or "").strip(),
            "value": value.get("value"),
            "level": value.get("level"),
            "at": value.get("at"),
            "source": value["source"],
            "author_name": (
                authors.get(value["by"])
                if isinstance(value.get("by"), int)
                else _note_author(value.get("note_id"))
            ),
            "job_id": value.get("job_id"),
            "job_title": _job_title(value.get("job_id")),
        }
        for key, value in facts.items()
    ]

    conversations = []
    for card in cards:
        job = jobs.get(card["job_id"])
        answers = card["note_answers"]
        texts = screening_sheets.question_texts(job.champion_profile if job else None)
        rows = note_answer_rows(texts, answers)
        if not rows:
            continue
        note_id = answers.get("note_id")
        note = notes.get(note_id) if isinstance(note_id, int) else None
        conversations.append(
            {
                "job_id": card["job_id"],
                "job_title": job.title if job else None,
                "client_name": job.client_name if job else None,
                "answered_at": answers.get("at"),
                "author_name": _note_author(note_id),
                "note_id": note_id if isinstance(note_id, int) else None,
                "from_traffit": bool(note and note.external_source == TRAFFIT_SOURCE),
                "question_count": max(len(texts), len(rows)),
                "answers": rows,
            }
        )
    conversations.sort(
        key=lambda item: (item["answered_at"] or "", item["job_id"]), reverse=True
    )

    return {
        "facts": fact_rows,
        "conversations": conversations,
        "note_links": [
            {
                **link,
                "job_title": _job_title(link["job_id"]),
                "field_labels": [DISPLAY_LABELS[key] for key in link["fields"]],
            }
            for link in links.values()
        ],
    }
