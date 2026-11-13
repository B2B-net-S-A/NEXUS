"""Po szkoleniu: nagranie, transkrypt i obecność same wracają z Teams (0696).

Do 13.11.2026 TCM szukał nagrania w OneDrive organizatora, pobierał do 2 GB
i wgrywał je w NEXUSIE, a obecność eksportował z Teams jako CSV. Teraz pętla
``trainings_teams`` co kilka minut bierze szkolenia z ``recording_status='waiting'``
po końcu spotkania i:

1. kopiuje każde nagranie (Teams tnie je co 4 h albo 1,5 GB) do magazynu szkoleń
   (SharePoint albo dysk) strumieniem — kopia nie wygasa po 120 dniach jak plik
   w OneDrive skrzynki szkolenia@,
2. zapisuje transkrypt VTT (wyszukiwanie w bibliotece),
3. zastępuje obecność raportem z Graph (to samo dopasowanie co CSV),
4. daje TCM dzwonek „Nagranie do zatwierdzenia”.

Nagranie wchodzi jako przyjęte i „dla uczestników”, ale ludzie zobaczą je dopiero
po decyzji TCM (udostępnienie zapisanym albo publikacja). Nagrania nie wgrał
człowiek, więc zasada „publikuje ktoś inny niż wgrywający” spełnia się sama.

Przypomnienia dla zapisanych pracowników idą tą samą pętlą i nie wymagają Teams.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.scheduling import business_today
from app.models.training import Training, TrainingFile, TrainingTranscript
from app.services.trainings import attendance, core, signals, storage, teams

logger = logging.getLogger(__name__)

RETRY = timedelta(minutes=15)
BATCH = 5
REMINDER_HOUR = 9


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def _claim(db: AsyncSession, now: datetime) -> list[int]:
    """Szkolenia do sprawdzenia; dzierżawa 15 min zamiast trzymania blokady przez Graph."""

    rows = (
        await db.scalars(
            select(Training)
            .where(
                Training.recording_status == "waiting",
                Training.recording_next_at.is_not(None),
                Training.recording_next_at <= now,
                Training.teams_meeting_id.is_not(None),
            )
            .order_by(Training.recording_next_at)
            .limit(BATCH)
            .with_for_update(skip_locked=True)
        )
    ).all()
    for training in rows:
        training.recording_next_at = now + RETRY
    await db.commit()
    return [t.id for t in rows]


async def _import_recordings(
    db: AsyncSession, training: Training, user_id: str, now: datetime
) -> int:
    from app.services.m365 import teams_training_graph as tgraph  # noqa: PLC0415

    refs = await tgraph.list_recordings(user_id, training.teams_meeting_id or "")
    if not refs:
        return 0
    day = (training.session_date or business_today()).isoformat()
    added: list[TrainingFile] = []
    try:
        for index, ref in enumerate(refs, start=1):
            suffix = f"_cz{index}" if len(refs) > 1 else ""
            name = f"Nagranie_{day}{suffix}.mp4"
            stored = await storage.save(
                db,
                training_id=training.id,
                training_title=training.title,
                session_year=(training.session_date or business_today()).year,
                file_name=name,
                content_type="video/mp4",
                source=tgraph.stream_recording(
                    user_id, training.teams_meeting_id or "", ref.id
                ),
            )
            added.append(
                await core.add_file(
                    db,
                    training,
                    kind="recording",
                    stored=stored,
                    file_name=name,
                    now=now,
                )
            )
    except Exception:
        # Część plików bez reszty dałaby nagranie bez końcówki: sprzątamy i ponawiamy.
        for item in added:
            try:
                await storage.remove(item)
            except Exception:  # noqa: BLE001
                logger.warning("trainings_recordings: cleanup failed file=%s", item.id)
            await db.delete(item)
        await db.flush()
        raise
    return len(added)


async def _import_transcript(
    db: AsyncSession, training: Training, user_id: str
) -> bool:
    from app.services.m365 import teams_prep_graph as graph  # noqa: PLC0415

    refs = await graph.list_transcripts(user_id, training.teams_meeting_id or "")
    if not refs:
        return False
    parts = [
        await graph.transcript_vtt(user_id, training.teams_meeting_id or "", ref.id)
        for ref in refs
    ]
    row = await db.get(TrainingTranscript, training.id)
    if row is None:
        row = TrainingTranscript(training_id=training.id)
        db.add(row)
    row.vtt = "\n\n".join(part for part in parts if part)
    row.fetched_at = _utcnow()
    await db.flush()
    return True


async def _import_attendance(db: AsyncSession, training: Training, user_id: str) -> int:
    from app.services.m365 import teams_training_graph as tgraph  # noqa: PLC0415

    report = await tgraph.attendance(user_id, training.teams_meeting_id or "")
    if report is None:
        return 0
    rows = await attendance.match(
        db,
        [
            attendance.AttendanceRow(
                name=item.name, email=item.email, minutes=round(item.seconds / 60)
            )
            for item in report
        ],
    )
    await attendance.replace_rows(db, training.id, rows)
    return len(rows)


async def process(db: AsyncSession, training_id: int, *, now: datetime) -> str:
    """Jedno szkolenie: ``imported`` | ``waiting`` | ``none`` | ``failed``."""

    from app.services.m365 import teams_prep_graph as graph  # noqa: PLC0415

    training = await db.get(Training, training_id)
    if training is None or training.recording_status != "waiting":
        return "skip"
    slot = teams.window(training)
    ended = slot[1] if slot else now
    try:
        user_id = await graph.resolve_user_id(teams.organizer())
        if not user_id:
            raise RuntimeError("organizer not found")
        files = await _import_recordings(db, training, user_id, now)
        if files == 0:
            give_up = ended + timedelta(
                hours=settings.TRAININGS_RECORDING_GIVE_UP_HOURS
            )
            training.recording_status = "none" if now >= give_up else "waiting"
            await db.commit()
            return training.recording_status
        # Transkrypt i obecność to dodatki: ich brak nie zatrzymuje nagrania.
        for step in (_import_transcript, _import_attendance):
            try:
                await step(db, training, user_id)
            except Exception:  # noqa: BLE001
                logger.warning(
                    "trainings_recordings: %s failed training=%s",
                    step.__name__,
                    training.id,
                )
        training.recording_status = "imported"
        training.recording_next_at = None
        await signals.recording_ready(db, training)
        await db.commit()
        return "imported"
    except Exception as exc:  # noqa: BLE001
        await db.rollback()
        logger.warning(
            "trainings_recordings: training=%s failed %s",
            training_id,
            type(exc).__name__,
        )
        training = await db.get(Training, training_id)
        if training is not None and now >= ended + timedelta(
            hours=settings.TRAININGS_RECORDING_GIVE_UP_HOURS
        ):
            training.recording_status = "failed"
            await db.commit()
            return "failed"
        return "waiting"


async def fetch_due(
    db: AsyncSession, *, now: Optional[datetime] = None
) -> dict[str, Any]:
    if not teams.ready():
        return {"status": "disabled"}
    now = now or _utcnow()
    counts: dict[str, int] = {}
    for training_id in await _claim(db, now):
        outcome = await process(db, training_id, now=now)
        counts[outcome] = counts.get(outcome, 0) + 1
    return counts


async def send_reminders(
    db: AsyncSession, *, now: Optional[datetime] = None
) -> dict[str, int]:
    """Dzwonek dla zapisanych pracowników: dzień wcześniej od 9:00 i 15 minut przed."""

    now = now or _utcnow()
    today = business_today()
    trainings = (
        await db.scalars(
            select(Training).where(
                Training.status == "signed",
                Training.session_date.is_not(None),
                Training.session_date >= today,
                Training.session_date <= today + timedelta(days=1),
            )
        )
    ).all()
    sent = {"day": 0, "soon": 0}
    for training in trainings:
        slot = teams.window(training)
        if slot is None:
            continue
        start, _ = slot
        local = now.astimezone(start.tzinfo)
        if (
            training.reminder_day_at is None
            and training.session_date == today + timedelta(days=1)
            and local.hour >= REMINDER_HOUR
        ):
            await signals.reminder(db, training, soon=False, join_url=training.join_url)
            training.reminder_day_at = now
            sent["day"] += 1
        if (
            training.reminder_soon_at is None
            and start - timedelta(minutes=15) <= now < start
        ):
            await signals.reminder(db, training, soon=True, join_url=training.join_url)
            training.reminder_soon_at = now
            sent["soon"] += 1
    await db.commit()
    return sent


async def run_once(db: AsyncSession) -> dict[str, Any]:
    reminders = await send_reminders(db)
    recordings = await fetch_due(db)
    return {"reminders": reminders, "recordings": recordings}
