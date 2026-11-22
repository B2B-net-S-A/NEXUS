"""„Znamy tę osobę” — punkty kolejki w „Nowych” (decyzja Artura z 02.11.2026).

Makiety i pomiar: https://claude.ai/artifact/8x6AxqnTihmecy2uw3Dhoh. Wagi dobrane
na 178 wysłanych z 01–22.10, sprawdzone z flagami produkcji na 146 wysłanych od
23.10 (bez osób dopisanych do bazy tuż przed dodaniem): w top 20 z 32% do 38%,
w top 40 z 49% do 62%, rekrutacje z trafieniem w top 20 z 45% do 62%. Mocniejsze
„musi mieć” ani punkty za umiejętności nic tu nie dokładały.

Punkty zmieniają WYŁĄCZNIE kolejność kandydatów do „Nowych” i kart w kolumnie;
procent dopasowania zostaje (ta sama zasada co ``known_people_signal``). Zapis
w ``app_settings``, domyślne działają bez wiersza.

Bez punktów zostaje tylko osoba jawnie odrzucona przez tego klienta
(``ended_by = 'client'``). Pusty ``ended_by`` po wysyłce CV to nie odrzucenie: pod
ten warunek wpadało 33 z 82 wysłanych ze zweryfikacją u tego klienta i top 40
spadało z 62% do 53% (pomiar bez flag).

Osoby bez procesu (``without_process``) dostają co 5. miejsce w kolejce, decyzja
Artura z 03.11.2026; zasady w ``docs/claude/rekrutacja-tablica/kolejka-w-nowych.md``.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Mapping, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.rejection_reason_labels import CLIENT_NOT_A_VERDICT

from app.models.app_setting import AppSetting
from app.services.known_people_signal import POSITIVE_STAGES

SETTING_KEY = "queue_known_points"
RECENT_NOTE_DAYS = 30
OLDER_NOTE_DAYS = 90
MAX_POINTS = 15
# Wysłany do klienta w innej rekrutacji w ostatnim roku (Z1, 20.11.2026):
# wśród kart od systemu 12,2% do klienta wobec 7,9% wszystkich. Stała, nie
# suwak panelu: skala jak „u klienta” (6) i świeża notatka (8).
SENT_POINTS = 8


@dataclass(frozen=True)
class KnownPoints:
    client: int = 6
    note_recent: int = 8
    note_older: int = 2

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class KnownFacts:
    points: int
    client_points: int
    note_points: int
    verified_at_client: int
    last_note_days: Optional[int]
    sent_elsewhere: int = 0
    sent_points: int = 0

    def as_dict(self) -> dict:
        return asdict(self)


def validation_error(points: KnownPoints) -> Optional[str]:
    if any(not 0 <= value <= MAX_POINTS for value in asdict(points).values()):
        return f"Punkty muszą być w zakresie 0–{MAX_POINTS}."
    return None


async def read_points(db: AsyncSession) -> KnownPoints:
    row = await db.get(AppSetting, SETTING_KEY)
    if row is None or not isinstance(row.value, dict):
        return KnownPoints()
    defaults = asdict(KnownPoints())
    try:
        return KnownPoints(
            **{key: int(row.value.get(key, defaults[key])) for key in defaults}
        )
    except (TypeError, ValueError):
        return KnownPoints()


async def save_points(db: AsyncSession, points: KnownPoints, *, actor_id: int) -> None:
    row = await db.get(AppSetting, SETTING_KEY)
    if row is None:
        db.add(AppSetting(key=SETTING_KEY, value=points.as_dict(), updated_by=actor_id))
    else:
        row.value = points.as_dict()
        row.updated_by = actor_id


def points_for(
    weights: KnownPoints, verified_at_client: int, last_note_days: Optional[int]
) -> tuple[int, int]:
    """Punkty za klienta i za notatkę."""
    client = weights.client if verified_at_client > 0 else 0
    if last_note_days is not None and last_note_days <= RECENT_NOTE_DAYS:
        return client, weights.note_recent
    if last_note_days is not None and last_note_days <= OLDER_NOTE_DAYS:
        return client, weights.note_older
    return client, 0


async def _rejected_by_client(
    db: AsyncSession, client_ids: list[int], candidate_ids: list[int]
) -> set[tuple[int, int, int]]:
    """Najnowszy wiersz pary z innej rekrutacji klienta to jawne odrzucenie przez niego.

    ``{(kandydat, rekrutacja, klient)}`` — wołający odrzuca wiersze swojej
    rekrutacji (``DISTINCT ON`` liczy się per para, więc wynik jest ten sam,
    co z ``job_id <> :job`` w zapytaniu)."""
    if not client_ids or not candidate_ids:
        return set()
    rows = await db.execute(
        text(
            """
            WITH last AS (
              SELECT DISTINCT ON (cs.candidate_id, cs.job_id)
                     cs.candidate_id, cs.job_id, j.client_id,
                     cs.stage::text AS stage, cs.ended_by,
                     rr.name AS reason
              FROM candidate_stages cs
              JOIN jobs j ON j.id = cs.job_id
              LEFT JOIN rejection_reasons rr ON rr.id = cs.rejection_reason_id
              WHERE j.client_id = ANY(:clients)
                AND cs.candidate_id = ANY(:ids)
              ORDER BY cs.candidate_id, cs.job_id, cs.moved_at DESC, cs.id DESC
            )
            SELECT candidate_id, job_id, client_id FROM last
            WHERE stage = 'rejected' AND ended_by = 'client'
              AND COALESCE(reason, '') <> ALL(CAST(:not_verdict AS text[]))
            """
        ),
        {
            "clients": client_ids,
            "ids": candidate_ids,
            "not_verdict": list(CLIENT_NOT_A_VERDICT),
        },
    )
    return {(int(cid), int(jid), int(client)) for cid, jid, client in rows.all()}


async def facts_for(
    db: AsyncSession,
    *,
    job_id: int,
    client_id: Optional[int],
    candidate_ids: list[int],
    now: datetime,
) -> dict[int, KnownFacts]:
    """Fakty i punkty osób ze znanym śladem; reszty nie ma w wyniku."""
    return (
        await facts_for_jobs(db, boards={job_id: (client_id, candidate_ids)}, now=now)
    )[job_id]


async def facts_for_jobs(
    db: AsyncSession,
    *,
    boards: Mapping[int, tuple[Optional[int], list[int]]],
    now: datetime,
) -> dict[int, dict[int, KnownFacts]]:
    """``facts_for`` dla wielu Tablic naraz: ``{rekrutacja: (klient, kandydaci)}``.

    Te same zapytania co dla jednej rekrutacji (``my-next-steps`` składa do 25
    Tablic), wiersze rozdzielone w Pythonie per Tablica."""
    out: dict[int, dict[int, KnownFacts]] = {job_id: {} for job_id in boards}
    all_ids = sorted({cid for _, ids in boards.values() for cid in ids})
    if not all_ids:
        return out
    weights = await read_points(db)
    client_ids = sorted(
        {client for client, ids in boards.values() if client is not None and ids}
    )
    # (kandydat, klient) → rekrutacje klienta z pozytywnym etapem osoby.
    verified_jobs: dict[tuple[int, int], set[int]] = {}
    if client_ids:
        rows = await db.execute(
            text(
                """
                SELECT DISTINCT cs.candidate_id, j.client_id, cs.job_id
                FROM candidate_stages cs
                JOIN jobs j ON j.id = cs.job_id
                WHERE j.client_id = ANY(:clients)
                  AND cs.candidate_id = ANY(:ids)
                  AND cs.stage::text = ANY(:stages)
                """
            ),
            {
                "clients": client_ids,
                "ids": all_ids,
                "stages": list(POSITIVE_STAGES),
            },
        )
        for cid, client, jid in rows.all():
            verified_jobs.setdefault((int(cid), int(client)), set()).add(int(jid))
    rows = await db.execute(
        text(
            """
            SELECT candidate_id, MAX(created_at)
            FROM notes
            WHERE candidate_id = ANY(:ids) AND source_deleted_at IS NULL
            GROUP BY 1
            """
        ),
        {"ids": all_ids},
    )
    note_days = {int(cid): (now - at).days for cid, at in rows.all() if at is not None}
    rejected_rows = await _rejected_by_client(db, client_ids, all_ids)
    # Wysyłki do klienta w ostatnim roku: (kandydat) → rekrutacje (20.11.2026).
    from datetime import timedelta

    from app.services import sent_before

    sent_rows = await db.execute(
        text(
            """
            SELECT DISTINCT candidate_id, job_id FROM candidate_stages
            WHERE candidate_id = ANY(:ids) AND stage::text = 'cv_sent'
              AND moved_at >= :since
            """
        ),
        {"ids": all_ids, "since": now - timedelta(days=sent_before.DAYS)},
    )
    sent_jobs: dict[int, set[int]] = {}
    for cid, jid in sent_rows.all():
        sent_jobs.setdefault(int(cid), set()).add(int(jid))
    for job_id, (client_id, candidate_ids) in boards.items():
        rejected = (
            {
                cid
                for cid, jid, client in rejected_rows
                if client == client_id and jid != job_id
            }
            if client_id is not None
            else set()
        )
        facts: dict[int, KnownFacts] = {}
        for candidate_id in candidate_ids:
            if candidate_id in rejected:
                continue
            client_jobs = (
                len(verified_jobs.get((candidate_id, client_id), set()) - {job_id})
                if client_id is not None
                else 0
            )
            last_note = note_days.get(candidate_id)
            client, note = points_for(weights, client_jobs, last_note)
            sent_count = len(sent_jobs.get(candidate_id, set()) - {job_id})
            sent = SENT_POINTS if sent_count > 0 else 0
            if client + note + sent > 0:
                facts[candidate_id] = KnownFacts(
                    client + note + sent,
                    client,
                    note,
                    client_jobs,
                    last_note,
                    sent_count,
                    sent,
                )
        out[job_id] = facts
    return out


async def without_process(
    db: AsyncSession, *, job_id: int, candidate_ids: list[int]
) -> set[int]:
    """Osoby bez żadnego wiersza etapu w innej rekrutacji."""
    return (await without_process_for_jobs(db, boards={job_id: candidate_ids}))[job_id]


async def without_process_for_jobs(
    db: AsyncSession, *, boards: Mapping[int, list[int]]
) -> dict[int, set[int]]:
    """``without_process`` dla wielu Tablic jednym zapytaniem.

    Najmniejsza i największa rekrutacja osoby wystarczą: dwie różne znaczą
    proces poza każdą Tablicą, jedna — proces poza wszystkimi oprócz niej."""
    out: dict[int, set[int]] = {job_id: set() for job_id in boards}
    all_ids = sorted({cid for ids in boards.values() for cid in ids})
    if not all_ids:
        return out
    rows = await db.execute(
        text(
            """
            SELECT candidate_id, MIN(job_id), MAX(job_id) FROM candidate_stages
            WHERE candidate_id = ANY(:ids) AND job_id IS NOT NULL
            GROUP BY 1
            """
        ),
        {"ids": all_ids},
    )
    spans = {int(cid): (int(low), int(high)) for cid, low, high in rows.all()}
    for job_id, candidate_ids in boards.items():
        out[job_id] = {
            cid
            for cid in candidate_ids
            if cid not in spans or spans[cid] == (job_id, job_id)
        }
    return out
