"""Rozdziały i podsumowanie nagrania szkolenia z transkryptu (0698, klucz AI F49).

Do S4 rozdziały liczyły się z planu agendy (suma minut poprzednich modułów), więc
skok do „modułu 3” trafiał obok, gdy trener się przeciągnął, a szkolenie pracownika
bez agendy nie miało rozdziałów wcale. Po imporcie transkryptu (``recordings.process``)
model z rejestru dzieli nagranie na rozdziały i pisze krótkie podsumowanie.

Wynik to dodatek, nigdy warunek: brak klucza, awaria modelu albo odpowiedź, której
nie da się użyć, zostawia rozdziały z agendy i nagranie bez podsumowania. Początek
rozdziału musi być znacznikiem jednej z linii transkryptu; inny kod odrzuca, bo
rozdział z wymyśloną sekundą przewija film w złe miejsce.

Model dostaje tekst wypowiedzi bez nazw mówców. Do logu idzie klasa błędu, nie treść.
Funkcja robi własne commity: połączenie wraca do puli na czas modelu.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

from fastapi.concurrency import run_in_threadpool
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ai_feature import AIFeatureKey
from app.models.training import Training, TrainingFile, TrainingTranscript
from app.services import teams_vtt
from app.services.llm_prompts import TRAINING_TRANSCRIPT_SUMMARY

logger = logging.getLogger(__name__)

FEATURE = AIFeatureKey.training_transcript_summary
MAX_TRANSCRIPT_CHARS = 200_000
MAX_SUMMARY_CHARS = 1_500
MAX_TITLE_CHARS = 120
MIN_CHAPTERS = 2
MAX_CHAPTERS = 12


def stamp(second: int) -> str:
    return f"{second // 3600:02d}:{second % 3600 // 60:02d}:{second % 60:02d}"


def _parse_stamp(value: Any) -> Optional[int]:
    if not isinstance(value, str):
        return None
    parts = value.strip().split(":")
    if not 2 <= len(parts) <= 3 or not all(p.isdigit() for p in parts):
        return None
    numbers = [int(p) for p in parts]
    if len(numbers) == 2:
        numbers.insert(0, 0)
    hours, minutes, seconds = numbers
    if minutes > 59 or seconds > 59:
        return None
    return hours * 3600 + minutes * 60 + seconds


def transcript_lines(vtt: str) -> list[tuple[int, str]]:
    """``(sekunda, tekst)`` jednej linii na wypowiedź; mówcy wypadają."""

    out: list[tuple[int, str]] = []
    for cue in teams_vtt.parse_vtt(vtt):
        text = " ".join(cue.text.split())
        if text:
            out.append((int(cue.start), text))
    return out


def render_transcript(lines: list[tuple[int, str]]) -> str:
    return "\n".join(f"[{stamp(second)}] {text}" for second, text in lines)


def parse_answer(
    raw: str, allowed: set[int]
) -> tuple[Optional[str], list[dict[str, Any]]]:
    """Odpowiedź modelu → podsumowanie i rozdziały; śmieci dają ``(None, [])``.

    Rozdział zostaje tylko z sekundą z transkryptu. Mniej niż dwa poprawne rozdziały
    = brak rozdziałów z AI (zostaje agenda), ale podsumowanie może zostać."""

    text = (raw or "").strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
    try:
        data = json.loads(text)
    except ValueError:
        return None, []
    if not isinstance(data, dict):
        return None, []
    summary = data.get("summary")
    clean_summary = (
        summary.strip()[:MAX_SUMMARY_CHARS]
        if isinstance(summary, str) and summary.strip()
        else None
    )
    seen: set[int] = set()
    rows: list[dict[str, Any]] = []
    for item in data.get("chapters") or []:
        if not isinstance(item, dict):
            continue
        second = _parse_stamp(item.get("start"))
        title = item.get("title")
        if (
            second is None
            or second not in allowed
            or second in seen
            or not isinstance(title, str)
            or not title.strip()
        ):
            continue
        seen.add(second)
        rows.append(
            {"title": " ".join(title.split())[:MAX_TITLE_CHARS], "start_second": second}
        )
    rows.sort(key=lambda row: row["start_second"])
    rows = rows[:MAX_CHAPTERS]
    if len(rows) < MIN_CHAPTERS:
        rows = []
    return clean_summary, rows


def _agenda(training: Training) -> str:
    items = [
        f"- {item.get('title', '')} ({int(item.get('minutes') or 0)} min)"
        for item in training.agenda
        if isinstance(item, dict) and item.get("title")
    ]
    return "\n".join(items) or "brak"


def _call_model(chain: list[str], system: str, prompt: str) -> str:
    """Jedno wywołanie modelu (w wątku). Osobna funkcja: testy ją podmieniają."""
    from app.services.claude_client import call_claude_text

    return call_claude_text(
        model=chain[0],
        fallback_models=chain[1:] or None,
        max_tokens=1_500,
        thinking={"type": "disabled"},
        system=system,
        messages=[{"role": "user", "content": prompt}],
    )


async def _status(db: AsyncSession, training_id: int, value: str) -> str:
    row = await db.get(TrainingTranscript, training_id)
    if row is not None:
        row.summary_status = value
        await db.commit()
    return value


async def summarize(db: AsyncSession, training_id: int) -> str:
    """``done`` | ``failed`` | ``skipped``. Nie rzuca: wynik modelu jest dodatkiem."""

    from app.services.ai_models import model_chain_for
    from app.services.ai_quota import ai_feature
    from app.services.llm_providers import api_key_configured

    training = await db.get(Training, training_id)
    row = await db.get(TrainingTranscript, training_id)
    if training is None or row is None or not row.vtt:
        return "skipped"
    lines = transcript_lines(row.vtt)
    transcript = render_transcript(lines)
    chain = list(model_chain_for(FEATURE))
    if (
        not lines
        or not api_key_configured(chain[0])
        or len(transcript) > MAX_TRANSCRIPT_CHARS
    ):
        return await _status(db, training_id, "skipped")
    # Kilka plików nagrania (Teams tnie co 4 h) = osobne osie czasu w jednym
    # transkrypcie, więc sekunda rozdziału byłaby niejednoznaczna: tylko podsumowanie.
    parts = await db.scalar(
        select(func.count())
        .select_from(TrainingFile)
        .where(
            TrainingFile.training_id == training_id, TrainingFile.kind == "recording"
        )
    )
    allowed = {second for second, _ in lines} if (parts or 0) <= 1 else set()
    prompt = TRAINING_TRANSCRIPT_SUMMARY.render(
        title=training.title,
        description=training.description or "",
        agenda=_agenda(training),
        transcript=transcript,
    )
    summary: Optional[str] = None
    chapters: list[dict[str, Any]] = []
    try:
        async with ai_feature(db, FEATURE):
            await db.commit()  # połączenie wraca do puli na czas modelu
            raw = await run_in_threadpool(
                _call_model,
                chain,
                TRAINING_TRANSCRIPT_SUMMARY.system_prompt or "",
                prompt,
            )
        summary, chapters = parse_answer(raw, allowed)
    except Exception as exc:  # noqa: BLE001 — AI to dodatek, nigdy bramka
        logger.warning("trainings_ai_summary: failed (%s)", type(exc).__name__)
        await db.rollback()
    row = await db.get(TrainingTranscript, training_id)
    if row is None:
        return "skipped"
    if summary is None and not chapters:
        row.summary_status = "failed"
        await db.commit()
        return "failed"
    row.summary = summary or ""
    row.ai_chapters = chapters
    row.summary_status = "done"
    await db.commit()
    return "done"
