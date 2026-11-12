"""Rodzaj ``question`` (G-B): „Zapytaj bota” o jedną firmę z karty.

Do bota idą nazwa i domena firmy (``firms``) oraz jedno pole ``request``:
``question``, bo bez treści pytania bot nie wie, czego szukać. Pytanie przed
wysyłką przechodzi filtr danych osobowych (``personal_data_reason``): komputery
bota stoją w USA, więc adres e-mail, telefon, PESEL ani numer konta nie mogą tam
wyjść. Kto pytał (``requested_by_user_id``), zostaje w NEXUSIE.

Odpowiedź to najwyżej 6 linii po 400 znaków; linia bez linku to wniosek bota
i ekran tak ją podpisuje. Wynik trafia do ``sales_bot_results`` (jeden na bieg)
i nie ma akcji przyjęcia: karta tylko go pokazuje.

Reguły: ``docs/claude/sprzedaz/sygnaly-grok-bot.md`` („Zapytaj bota”).
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.sales import SalesSignalRun
from app.services.sales import signals
from app.services.sales.bot_tasks.base import (
    BotTask,
    RequiredText,
    SourceUrl,
    TaskContext,
    result_fingerprint,
    save_results,
)

KIND = "question"
MIN_QUESTION = 5
MAX_QUESTION = 300
MAX_LINES = 6
MAX_LINE = 400

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_IBAN = re.compile(r"\b[A-Z]{2}\d{2}(?:[ ]?\d){10,30}\b", re.IGNORECASE)
_PESEL = re.compile(r"(?<!\d)\d{11}(?!\d)")
#: Ciąg cyfr z separatorami telefonu (spacja, kreska, nawiasy, plus).
_DIGIT_RUN = re.compile(r"\+?\(?\d[\d\s\-()]*\d")
#: Daty nie są numerem telefonu: „2026-10-01”, „1.10.2026”, „01/10/2026”.
_DATE = re.compile(r"\b\d{4}-\d{1,2}-\d{1,2}\b|\b\d{1,2}[./]\d{1,2}[./]\d{2,4}\b")
MIN_PHONE_DIGITS = 7


def personal_data_reason(text: str) -> Optional[str]:
    """Powód odmowy po polsku, gdy pytanie wygląda na dane osobowe; inaczej ``None``."""

    if _EMAIL.search(text):
        return "Pytanie nie może zawierać adresu e-mail: do bota nie wysyłamy danych osobowych."
    if _IBAN.search(text):
        return "Pytanie nie może zawierać numeru konta: do bota nie wysyłamy danych osobowych."
    if _PESEL.search(text):
        return "Pytanie nie może zawierać numeru PESEL: do bota nie wysyłamy danych osobowych."
    without_dates = _DATE.sub(" ", text)
    for run in _DIGIT_RUN.finditer(without_dates):
        if sum(ch.isdigit() for ch in run.group()) >= MIN_PHONE_DIGITS:
            return (
                "Pytanie nie może zawierać numeru telefonu ani innego długiego numeru "
                "(7 i więcej cyfr): do bota nie wysyłamy danych osobowych."
            )
    return None


def clean_question(value: str) -> str:
    """Pytanie po czyszczeniu; zły rozmiar albo dane osobowe to ``ValueError`` po polsku."""

    text = signals._clean(value or "")
    if len(text) < MIN_QUESTION:
        raise ValueError(f"Pytanie musi mieć co najmniej {MIN_QUESTION} znaków.")
    if len(text) > MAX_QUESTION:
        raise ValueError(f"Pytanie może mieć najwyżej {MAX_QUESTION} znaków.")
    reason = personal_data_reason(text)
    if reason:
        raise ValueError(reason)
    return text


class QuestionRequest(BaseModel):
    """Jedyne pole zlecenia: treść pytania (bot musi wiedzieć, czego szukać)."""

    model_config = ConfigDict(extra="forbid")

    question: str

    @field_validator("question")
    @classmethod
    def _question(cls, value: str) -> str:
        return clean_question(value)


class AnswerLine(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: RequiredText = Field(min_length=1, max_length=MAX_LINE)
    url: Optional[SourceUrl] = Field(default=None, max_length=1000)
    published: Optional[date] = None


class QuestionReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answer: list[AnswerLine] = Field(default_factory=list, max_length=MAX_LINES)


def _task_text(run: SalesSignalRun, ctx: TaskContext) -> str:
    return (
        "Odpowiedz na pytanie handlowca z pola request.question o firmę z listy "
        "firms (jedna firma). Szukaj w otwartych źródłach: strona firmy, komunikaty "
        "prasowe, prasa branżowa, rejestry publiczne. Odpowiedź to najwyżej "
        f"{MAX_LINES} krótkich linii po {MAX_LINE} znaków. Każdy fakt podaj z adresem "
        "źródła (url) i datą publikacji. Linia bez url to Twój wniosek: pisz ją tylko "
        "wtedy, gdy wynika z faktów wyżej. Nie podawaj danych kontaktowych osób. "
        "Gdy nie znajdziesz odpowiedzi, odeślij pustą listę answer."
    )


def _report_format() -> dict[str, Any]:
    return {
        "answer": [
            {"text": "...", "url": "https://...", "published": "RRRR-MM-DD"},
            {"text": "Wniosek: ..."},
        ]
    }


async def _ingest(
    db: AsyncSession, run: SalesSignalRun, report: Any, now: datetime
) -> dict[str, Any]:
    ids = [int(ref) for ref in run.company_ids]
    rows = await signals._companies(db, ids[:1])
    company_id = next(iter(rows), None)
    lines = [
        {
            "text": line.text,
            "url": line.url,
            "published": line.published.isoformat() if line.published else None,
        }
        for line in report.answer
    ]
    payload = {
        "question": (run.request or {}).get("question"),
        "answer": lines,
        "asked_by_user_id": run.requested_by_user_id,
    }
    new = await save_results(
        db,
        run,
        [
            {
                "company_id": company_id,
                "payload": payload,
                "fingerprint": result_fingerprint(KIND, run.id),
            }
        ],
        now,
    )
    return {
        "answer_lines": len(lines),
        "with_source": sum(1 for line in lines if line["url"]),
        "results_new": new,
    }


QUESTION = BotTask(
    kind=KIND,
    task_text=_task_text,
    report_format=_report_format,
    report_model=QuestionReport,
    ingest=_ingest,
    request_model=QuestionRequest,
)
