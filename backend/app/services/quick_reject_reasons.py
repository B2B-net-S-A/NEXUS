"""Odrzucenie jednym kliknięciem — najczęstsze powody osoby (decyzja Artura 23.11.2026).

Rekruter odrzuca średnio 19 osób dziennie (71% prosto z „Nowych”), a trzy
jego najczęstsze powody z 30 dni to średnio 57% jego odrzuceń. Panel osoby
pokazuje je pod rzędem akcji jako „Odrzuć: …”; klik odrzuca z tym powodem
i „Odrzucamy my”, jak „Potwierdź” w oknie.

Liczymy z ``candidate_stages``: wiersze ``rejected`` przesunięte przez tę
osobę w ostatnich 30 dniach kalendarza firmy, powód z ``rejection_reasons``
przełożony na klucz słownika (``close_reasons``). Odrzucenia „przez klienta”
nie wchodzą — skrót mówi za nas. Powody, których my nie wybieramy (powody
klienta i kandydata), oraz te z obowiązkowym opisem („Inne”, „Już po rozmowie
u tego hiring managera”) nigdy nie trafiają do skrótu. Gdy osoba ma mniej niż
trzy takie powody, lista dopełnia się najczęstszymi w zespole.

Zasady: ``docs/claude/rekrutacja-tablica/odrzucenie-jednym-kliknieciem.md``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta
from typing import Iterable, Optional
from zoneinfo import ZoneInfo

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scheduling import DEFAULT_TZ, business_today
from app.models.pipeline_template import RejectionReason
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.services import close_reasons

QUICK_REJECT_LIMIT = 3
QUICK_REJECT_WINDOW_DAYS = 30
# Opis obowiązkowy (``rejection_reason_labels.needs_description``) — klik bez
# opisu skończyłby się 422.
_NEEDS_DESCRIPTION = frozenset({close_reasons.OTHER.key, "hm_already_interviewed"})
# „Kto kończy” spoza „Odrzucamy my” — klient i kandydat mówią za siebie.
_NOT_US = ("client", "candidate")


@dataclass(frozen=True)
class QuickRejectReason:
    key: str
    count: int
    # ``mine`` — z odrzuceń tej osoby; ``team`` — dopełnienie z zespołu.
    source: str


def _key_by_template_name() -> dict[str, str]:
    """``rejection_reasons.name`` przy odrzuceniu → klucz słownika, tylko
    powody, które wybieramy my, bez obowiązkowego opisu."""
    out: dict[str, str] = {}
    for reason in close_reasons.CLOSE_REASONS:
        if (
            close_reasons.RECRUITER not in reason.who
            or reason.key in _NEEDS_DESCRIPTION
            or not reason.rejected
        ):
            continue
        out.setdefault(reason.rejected, reason.key)
    return out


QUICK_KEY_BY_TEMPLATE_NAME: dict[str, str] = _key_by_template_name()


def window_start(today=None) -> datetime:
    """Północ kalendarza firmy 30 dni temu (dziś wliczone)."""
    day = (today or business_today()) - timedelta(days=QUICK_REJECT_WINDOW_DAYS - 1)
    return datetime.combine(day, time.min, tzinfo=ZoneInfo(DEFAULT_TZ))


def _keyed(rows: Iterable[tuple[Optional[str], int]]) -> list[tuple[str, int]]:
    """Liczby po nazwie wiersza szablonu → po kluczu słownika, malejąco
    (remis: kolejność słownika, żeby wynik był stały)."""
    counts: dict[str, int] = {}
    for name, count in rows:
        key = QUICK_KEY_BY_TEMPLATE_NAME.get((name or "").strip())
        if key:
            counts[key] = counts.get(key, 0) + int(count)
    order = {reason.key: i for i, reason in enumerate(close_reasons.CLOSE_REASONS)}
    return sorted(counts.items(), key=lambda kv: (-kv[1], order.get(kv[0], 999)))


def pick_quick_reasons(
    mine: Iterable[tuple[Optional[str], int]],
    team: Iterable[tuple[Optional[str], int]],
    limit: int = QUICK_REJECT_LIMIT,
) -> list[QuickRejectReason]:
    """Najpierw najczęstsze powody osoby, potem dopełnienie z zespołu."""
    picked = [QuickRejectReason(key, count, "mine") for key, count in _keyed(mine)][
        :limit
    ]
    taken = {reason.key for reason in picked}
    for key, count in _keyed(team):
        if len(picked) >= limit:
            break
        if key not in taken:
            picked.append(QuickRejectReason(key, count, "team"))
            taken.add(key)
    return picked


async def _counts(
    db: AsyncSession, since: datetime, moved_by: Optional[int]
) -> list[tuple[Optional[str], int]]:
    query = (
        select(RejectionReason.name, func.count(CandidateStage.id))
        .join(RejectionReason, RejectionReason.id == CandidateStage.rejection_reason_id)
        .where(
            CandidateStage.stage == PipelineStage.rejected,
            CandidateStage.moved_at >= since,
            or_(
                CandidateStage.ended_by.is_(None),
                CandidateStage.ended_by.not_in(_NOT_US),
            ),
        )
        .group_by(RejectionReason.name)
    )
    if moved_by is not None:
        query = query.where(CandidateStage.moved_by == moved_by)
    return [(name, count) for name, count in (await db.execute(query)).all()]


async def quick_reject_reasons(
    db: AsyncSession, user_id: int
) -> list[QuickRejectReason]:
    since = window_start()
    mine = await _counts(db, since, user_id)
    picked = pick_quick_reasons(mine, [])
    if len(picked) >= QUICK_REJECT_LIMIT:
        return picked
    return pick_quick_reasons(mine, await _counts(db, since, None))
