"""Udział CV wysłanych do klienta, które przyszły z karty AI (22.11.2026).

Cel Artura: osoby, które proponuje AI w porcji dnia, mają być osobami, które
wysyłamy klientom. Do 22.11.2026 udział liczyło ręczne zapytanie; teraz to
kafelek w Insights → Zespół (zasady:
``docs/claude/finanse-insights/cv-do-klienta-z-karty-ai.md``).

* **Mianownik** — pierwsze wejście pary (rekrutacja, kandydat) w ``cv_sent``
  (``min(moved_at)`` z ``candidate_stages``), w tygodniu kalendarzowym firmy
  (Europe/Warsaw, pon–niedz). Druga wysyłka tej samej pary nie jest nowym CV.
* **Licznik** — z tych wysyłek te, w których najnowszy proces pary otwarty nie
  później niż wysyłka (``opened_at <= t``, ``ORDER BY opened_at DESC LIMIT 1``)
  ma ``entry_source = 'system'``, czyli kartę od porcji dnia albo silnika.
  Proces otwarty po wysyłce (ponowna próba) nie przypisuje jej wstecz.

Bez ``JOIN jobs`` i bez filtra klienta (cała firma), tak jak ręczne zapytanie:
skasowana rekrutacja nie zaniża historii (zasada 2 z ``insights_recruitment``).
"""

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scheduling import business_date, local_day_start_utc
from app.schemas.insights_ai_card import AiCardCvShare, AiCardCvWeek

# Cel Artura z 22.11.2026: każda osoba wysłana klientowi przyszła z karty AI.
# Stała, nie ustawienie — procent pokazujemy zawsze wobec pełnego pokrycia.
TARGET_PCT = 100
# Bieżący tydzień i 4 poprzednie.
WEEKS_SHOWN = 5
AI_CARD_ENTRY_SOURCE = "system"


@dataclass(frozen=True)
class CvSend:
    sent_at: datetime
    # ``entry_source`` najnowszego procesu pary otwartego nie później niż wysyłka.
    entry_source: Optional[str]


def _monday(day: date) -> date:
    return day - timedelta(days=day.weekday())


def window_start(today: date) -> date:
    return _monday(today) - timedelta(weeks=WEEKS_SHOWN - 1)


def _pct(part: int, whole: int) -> Optional[float]:
    return round(100 * part / whole, 1) if whole else None


def summarize_ai_card_cv_share(sends: list[CvSend], today: date) -> AiCardCvShare:
    """Tygodnie od najstarszego do bieżącego; tydzień bez wysyłek ma ``None``."""

    current = _monday(today)
    starts = [window_start(today) + timedelta(weeks=i) for i in range(WEEKS_SHOWN)]
    sent: dict[date, int] = dict.fromkeys(starts, 0)
    from_card: dict[date, int] = dict.fromkeys(starts, 0)
    for send in sends:
        week = _monday(business_date(send.sent_at))
        if week not in sent or business_date(send.sent_at) > today:
            continue
        sent[week] += 1
        if send.entry_source == AI_CARD_ENTRY_SOURCE:
            from_card[week] += 1
    return AiCardCvShare(
        window_from=starts[0],
        window_to=today,
        target_pct=TARGET_PCT,
        weeks=[
            AiCardCvWeek(
                week_start=start,
                week_end=start + timedelta(days=6),
                cv_sent=sent[start],
                from_ai_card=from_card[start],
                share_pct=_pct(from_card[start], sent[start]),
                in_progress=start == current,
            )
            for start in starts
        ],
    )


async def _load_cv_sends(db: AsyncSession, since: date, until: date) -> list[CvSend]:
    rows = (
        await db.execute(
            text(
                """
                WITH first_cv AS (
                  SELECT cs.job_id, cs.candidate_id, min(cs.moved_at) AS sent_at
                  FROM candidate_stages cs
                  WHERE cs.stage::text = 'cv_sent'
                  GROUP BY cs.job_id, cs.candidate_id
                  HAVING min(cs.moved_at) >= :since AND min(cs.moved_at) < :until
                )
                SELECT f.sent_at,
                       (
                         SELECT rp.entry_source
                         FROM recruitment_processes rp
                         WHERE rp.job_id = f.job_id
                           AND rp.candidate_id = f.candidate_id
                           AND rp.opened_at <= f.sent_at
                         ORDER BY rp.opened_at DESC
                         LIMIT 1
                       ) AS entry_source
                FROM first_cv f
                """
            ),
            {
                "since": local_day_start_utc(since),
                "until": local_day_start_utc(until + timedelta(days=1)),
            },
        )
    ).all()
    return [CvSend(sent_at=row.sent_at, entry_source=row.entry_source) for row in rows]


async def compute_ai_card_cv_share(db: AsyncSession, today: date) -> AiCardCvShare:
    sends = await _load_cv_sends(db, window_start(today), today)
    return summarize_ai_card_cv_share(sends, today)
