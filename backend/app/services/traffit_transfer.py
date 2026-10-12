"""Przeniesienie otwartych rekrutacji z Traffita do NEXUSA — falami (11.10.2026).

Decyzje Artura 11.10.2026: zespół przechodzi z Traffita falami (klient po
kliencie), a „otwarta” rekrutacja to taka bez daty zamknięcia w Traffit
i z ruchem z Traffita w ostatnich 30 dniach. Pomiar tego dnia: 99,2% osób stoi
już w NEXUSIE na właściwym stanie — rekrutacje są po prostu zamknięte jako
archiwum (0377), więc nikt ich nie widzi jako swojej pracy.

Fala to dwa biegi tej samej reguły:

* **próba** (``dry_run=true``) — dla każdej rekrutacji fali pobiera z Traffita
  listę osób per stan, porównuje z wierszami NEXUSA (:mod:`traffit_transfer_plan`)
  i zapisuje raport: ile osób zgodnych, co zostanie poprawione, kto zejdzie
  z Tablicy, czego nie da się przenieść. Niczego nie zmienia;
* **wykonanie** (``dry_run=false``, wymaga próby z ostatnich 24 h dla tej samej
  fali) — każda rekrutacja we własnej transakcji: poprawki stanów, zdjęcie
  kart osób usuniętych w Traffit, „Prowadzona w NEXUSIE” i ponowne otwarcie.
  Od tej chwili import jej ruchów nie rusza (``skipped_managed``).

Czego ta wersja świadomie NIE robi:

* domyślnie nie przenosi rekrutacji, która ma bliźniaka założonego
  w NEXUSIE (ten sam klient, niemal ten sam tytuł) — raport ją wskazuje
  i pomija. ``include_twins`` (12.10.2026, migracja całego zespołu) otwiera
  kopię z Traffita z prowadzącym, DL-em i ręcznymi współpracownikami
  bliźniaka; rekrutacji NEXUSA nie rusza, więc request jest wtedy widoczny
  dwa razy, dopóki obu nie scali osobny krok;
* nie zakłada kandydatów — osoba z Traffita, której NEXUS nie zna, trafia do
  raportu z numerem osoby;
* nie rusza kart dodanych w NEXUSIE ani par, których ostatni ruch zrobiono
  w NEXUSIE.

Raport i paragon leżą w ``app_settings`` (liczby i ID, bez nazwisk; klucze nie
pasują do publicznego wzorca ``^\\d{4}_``).
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from difflib import SequenceMatcher
from typing import Any, NamedTuple, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.board_stage_badges import board_column_for
from app.services.traffit_transfer_plan import (
    JobPlan,
    StageRow,
    plan_job,
    roster_is_trustworthy,
)

logger = logging.getLogger(__name__)

DRY_RUN_KEY = "traffit_transfer_dry_run"
LOG_KEY = "traffit_transfer_log"
LOCK_KEY = "traffit_transfer"
ACTIVE_DAYS_DEFAULT = 30
#: Rekrutacja-worek (np. „projekty wewnętrzne”, 14,6 tys. zgłoszeń) nie jest
#: rekrutacją do przeniesienia.
MAX_PEOPLE = 3000
#: Bliźniak = rekrutacja założona w NEXUSIE u tego samego klienta o niemal tym
#: samym tytule.
TWIN_MIN_RATIO = 0.8
#: Od tego dnia rekrutacje zakłada się w NEXUSIE (decyzja z 24.09.2026).
NEXUS_START = date(2026, 9, 25)
DRY_RUN_MAX_AGE = timedelta(hours=24)
SAMPLE_IDS = 50

SKIP_LARGE = "too_many_people"
SKIP_TWIN = "twin_in_nexus"
SKIP_ROSTER = "roster_incomplete"
SKIP_TRAFFIT = "traffit_unavailable"

COUNT_KEYS = (
    "people",
    "matched",
    "promote",
    "insert",
    "remove",
    "nexus_on_top",
    "nexus_only",
    "unverified",
    "already_closed",
    "unknown_people",
)


@dataclass(frozen=True)
class Scope:
    """Fala: klient albo wskazane rekrutacje (id NEXUSA)."""

    client_id: Optional[int] = None
    job_ids: tuple[int, ...] = ()
    active_days: int = ACTIVE_DAYS_DEFAULT
    #: Przenieś także rekrutacje, które mają bliźniaka w NEXUSIE (12.10.2026).
    include_twins: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "client_id": self.client_id,
            "job_ids": sorted(self.job_ids),
            "active_days": self.active_days,
            "include_twins": self.include_twins,
        }

    def key(self) -> str:
        raw = json.dumps(self.as_dict(), sort_keys=True)
        return hashlib.sha256(raw.encode()).hexdigest()[:16]


@dataclass(frozen=True)
class WaveJob:
    job_id: int
    traffit_id: str
    client_id: Optional[int]
    title: str
    recruiter_id: Optional[int]
    delivery_lead_id: Optional[int]
    people: int


@dataclass(frozen=True)
class StageDef:
    stage_def_id: int
    name: Optional[str]
    legacy: str
    category: Optional[str]
    terminal_type: Optional[str]


class RosterUnavailable(RuntimeError):
    """Traffit nie oddał listy stanów rekrutacji."""


def _jobs_sql(scope: Scope) -> str:
    # Rekrutacja już przełączona ręcznie („Przełącz do NEXUSA”), ale nadal
    # zamknięta, wchodzi do fali tylko wtedy, gdy jest wskazana wprost —
    # 12.10.2026 trzy takie zostały w pół drogi (import ich nie rusza, a nikt
    # ich nie otworzył). Fala po kliencie ich nie bierze: zamknięcie
    # przełączonej rekrutacji bywa świadomą decyzją.
    not_switched = (
        "(NOT j.managed_in_nexus OR j.status = 'closed')"
        if scope.job_ids
        else "NOT j.managed_in_nexus"
    )
    clauses = [
        "j.external_source = 'traffit'",
        "j.external_id IS NOT NULL",
        "j.closed_at IS NULL",
        not_switched,
        # Kopia scalona z rekrutacją NEXUSA (`job_twin_merge.MERGE_ACTION`)
        # wygląda jak „przełączona, ale zamknięta”. Otwarcie jej dopisałoby
        # karty osobom, które przeszły do rekrutacji NEXUSA.
        """NOT EXISTS (
            SELECT 1 FROM activities merged
            WHERE merged.entity_type = 'job' AND merged.entity_id = j.id
              AND merged.action = 'traffit_twin_merged'
        )""",
        """EXISTS (
            SELECT 1 FROM candidate_stages cs
            WHERE cs.job_id = j.id AND cs.external_source = 'traffit'
              AND cs.moved_at >= now() - make_interval(days => :days)
        )""",
    ]
    if scope.client_id is not None:
        clauses.append("j.client_id = :client_id")
    if scope.job_ids:
        clauses.append("j.id = ANY(CAST(:job_ids AS integer[]))")
    return f"""
        SELECT j.id, j.external_id, j.client_id, j.title, j.recruiter_id,
               j.delivery_lead_id,
               (SELECT count(DISTINCT cs.candidate_id) FROM candidate_stages cs
                WHERE cs.job_id = j.id) AS people
        FROM jobs j
        WHERE {" AND ".join(clauses)}
        ORDER BY j.id
    """


_ROWS_SQL = """
SELECT cs.id, cs.candidate_id,
       CASE WHEN c.external_source = 'traffit' THEN c.external_id END AS emp,
       cs.external_source AS source,
       sd.external_id AS state_ext,
       cs.moved_at,
       CAST(cs.stage AS text) AS stage
FROM candidate_stages cs
JOIN candidates c ON c.id = cs.candidate_id
LEFT JOIN pipeline_stage_defs sd
       ON sd.id = cs.stage_def_id AND sd.external_source = 'traffit'
WHERE cs.job_id = :job_id
"""

_STAGE_DEFS_SQL = """
SELECT id, external_id, name, legacy_enum_value, category, terminal_type
FROM pipeline_stage_defs
WHERE external_source = 'traffit' AND external_id IS NOT NULL
ORDER BY id
"""

_TWINS_SQL = """
SELECT id, client_id, title
FROM jobs
WHERE external_source IS DISTINCT FROM 'traffit'
  AND status <> 'closed'
  AND created_at >= :since
  AND client_id = ANY(CAST(:client_ids AS integer[]))
"""


async def load_wave(db: AsyncSession, scope: Scope) -> list[WaveJob]:
    params: dict[str, Any] = {"days": int(scope.active_days)}
    if scope.client_id is not None:
        params["client_id"] = scope.client_id
    if scope.job_ids:
        params["job_ids"] = list(scope.job_ids)
    rows = await db.execute(text(_jobs_sql(scope)), params)
    return [
        WaveJob(
            int(r.id),
            str(r.external_id),
            r.client_id,
            r.title or "",
            r.recruiter_id,
            r.delivery_lead_id,
            int(r.people or 0),
        )
        for r in rows.all()
    ]


async def load_stage_defs(db: AsyncSession) -> dict[str, StageDef]:
    """Numer stanu Traffita → etap szablonu. Pierwszy wygrywa, jak w imporcie."""
    rows = await db.execute(text(_STAGE_DEFS_SQL))
    out: dict[str, StageDef] = {}
    for r in rows.all():
        out.setdefault(
            str(r.external_id),
            StageDef(
                int(r.id),
                r.name,
                r.legacy_enum_value or "screening",
                r.category,
                r.terminal_type,
            ),
        )
    return out


async def load_rows(db: AsyncSession, job_id: int) -> list[StageRow]:
    rows = await db.execute(text(_ROWS_SQL), {"job_id": job_id})
    return [
        StageRow(
            int(r.id),
            int(r.candidate_id),
            r.emp,
            r.source,
            r.state_ext,
            r.moved_at,
            r.stage,
        )
        for r in rows.all()
    ]


async def load_candidates_by_emp(db: AsyncSession, emps: list[str]) -> dict[str, int]:
    if not emps:
        return {}
    rows = await db.execute(
        text(
            "SELECT id, external_id FROM candidates "
            "WHERE external_source = 'traffit' "
            "AND external_id = ANY(CAST(:emps AS text[]))"
        ),
        {"emps": emps},
    )
    return {str(r.external_id): int(r.id) for r in rows.all()}


def _title_key(title: str) -> str:
    return " ".join(title.lower().split())


# Numer requestu klienta na końcu tytułu: „… (42961)”, „… (ZOB-3054)”.
_REQUEST_ID_RE = re.compile(r"\s*\(([^()]*\d[^()]*)\)\s*$")


def title_core(title: str) -> str:
    """Tytuł bez numeru requestu w nawiasie na końcu, małymi literami."""
    return _REQUEST_ID_RE.sub("", _title_key(title))


def request_id(title: str) -> Optional[str]:
    """Numer requestu z końca tytułu („42961”, „zob-3054”) albo ``None``."""
    found = _REQUEST_ID_RE.search(_title_key(title))
    return " ".join(found.group(1).split()) if found else None


class Twin(NamedTuple):
    job_id: int
    #: Pewne, że to ten sam request: ten sam tytuł i ten sam numer requestu,
    #: albo ten sam tytuł, gdy numeru nie ma jedna ze stron i dopasowanie jest
    #: jedyne. ``False`` = tylko podobny tytuł.
    exact: bool


def match_twin(title: str, candidates: list[tuple[int, str]]) -> Optional[Twin]:
    """Rekrutacja NEXUSA tego samego klienta dla tego samego requestu.

    Kolejność: ten sam tytuł i numer requestu → ten sam tytuł, gdy numeru nie
    ma jedna ze stron („MS Power Platform Expert” i „MS Power Platform Expert
    (42732)”) → najbardziej podobny tytuł powyżej progu. RÓŻNE numery to różne
    requesty, choćby tytuł był identyczny: „Programista Python (ZOB-2904)”
    nie jest bliźniakiem „Programista Python (ZOB-2947)” (12.10.2026 — taka
    para dostałaby cudzy zespół). Podobieństwo wystarcza, żeby rekrutację
    OSTROŻNIE pominąć, ale nie żeby przenieść na nią czyjś zespół.
    """
    core, number = title_core(title), request_id(title)
    same_core = [
        (job_id, other)
        for job_id, other in candidates
        if core and title_core(other) == core
    ]
    for job_id, other in same_core:
        if number and request_id(other) == number:
            return Twin(job_id, True)
    for job_id, other in same_core:
        if not number or not request_id(other):
            return Twin(job_id, True)
    key = _title_key(title)
    best: tuple[float, int] = (0.0, 0)
    for job_id, other in candidates:
        ratio = SequenceMatcher(None, key, _title_key(other)).ratio()
        if ratio > best[0]:
            best = (ratio, job_id)
    return Twin(best[1], False) if best[0] >= TWIN_MIN_RATIO else None


def assign_twins(
    wave: list[tuple[int, str]], candidates: list[tuple[int, str]]
) -> dict[int, Twin]:
    """Bliźniaki dla rekrutacji jednego klienta: ``job_id`` → :class:`Twin`.

    Jedna rekrutacja NEXUSA ma najwyżej jednego pewnego bliźniaka. Gdy pasuje
    do niej kilka rekrutacji z Traffita („Analityk Systemowy Senior” bez
    numeru i trzy kopie z różnymi numerami), pewna zostaje tylko ta z tym
    samym numerem requestu; bez niej żadna — nie zgadujemy, czyj to zespół.
    """
    titles = dict(candidates)
    out: dict[int, Twin] = {}
    for job_id, title in wave:
        twin = match_twin(title, candidates)
        if twin is not None:
            out[job_id] = twin
    wave_titles = dict(wave)
    by_twin: dict[int, list[int]] = {}
    for job_id, twin in out.items():
        if twin.exact:
            by_twin.setdefault(twin.job_id, []).append(job_id)
    for twin_id, job_ids in by_twin.items():
        if len(job_ids) < 2:
            continue
        number = request_id(titles.get(twin_id, ""))
        for job_id in job_ids:
            if not number or request_id(wave_titles[job_id]) != number:
                out[job_id] = Twin(twin_id, False)
    return out


def find_twin(title: str, candidates: list[tuple[int, str]]) -> Optional[int]:
    """Rekrutacja NEXUSA o niemal tym samym tytule (ten sam klient) albo ``None``."""
    twin = match_twin(title, candidates)
    return twin.job_id if twin is not None else None


async def load_twins(db: AsyncSession, jobs: list[WaveJob]) -> dict[int, Twin]:
    """``job_id`` rekrutacji z Traffita → jej bliźniak w NEXUSIE."""
    client_ids = sorted({j.client_id for j in jobs if j.client_id is not None})
    if not client_ids:
        return {}
    rows = await db.execute(
        text(_TWINS_SQL),
        {
            "since": datetime(
                NEXUS_START.year,
                NEXUS_START.month,
                NEXUS_START.day,
                tzinfo=timezone.utc,
            ),
            "client_ids": client_ids,
        },
    )
    by_client: dict[int, list[tuple[int, str]]] = {}
    for r in rows.all():
        by_client.setdefault(int(r.client_id), []).append((int(r.id), r.title or ""))
    wave_by_client: dict[int, list[tuple[int, str]]] = {}
    for job in jobs:
        if job.client_id is not None:
            wave_by_client.setdefault(int(job.client_id), []).append(
                (job.job_id, job.title)
            )
    out: dict[int, Twin] = {}
    for client_id, wave in wave_by_client.items():
        out.update(assign_twins(wave, by_client.get(client_id, [])))
    return out


async def fetch_roster(
    traffit: Any, traffit_id: str
) -> tuple[dict[str, str], Optional[int]]:
    """``(osoba → stan, liczba osób w rekrutacji)`` prosto z Traffita.

    Historii ruchów nie da się zawęzić do rekrutacji (filtr jest ignorowany),
    ale lista osób NA STANIE jest dostępna wprost i to ona jest źródłem prawdy.
    """
    resp = await traffit._get_raw(  # noqa: SLF001
        f"/recruitments/{traffit_id}/states", page=1, page_size=100
    )
    if resp.status_code != 200:
        raise RosterUnavailable(f"states HTTP {resp.status_code}")
    states = resp.json()
    if not isinstance(states, list):
        raise RosterUnavailable("states: nie lista")
    people: dict[str, str] = {}
    for state in states:
        state_id = state.get("id") if isinstance(state, dict) else None
        if state_id is None:
            continue
        async for _page, items in traffit.get_pages(
            f"/recruitments/{traffit_id}/states/{state_id}/employees", page_size=100
        ):
            for item in items:
                emp = item.get("id") if isinstance(item, dict) else None
                if emp is not None:
                    people[str(emp)] = str(state_id)
    try:
        total: Optional[int] = await traffit.total_count(
            f"/recruitments/{traffit_id}/employees"
        )
    except RuntimeError:
        total = None
    return people, total


def columns_after(people: dict[str, str], defs: dict[str, StageDef]) -> dict[str, int]:
    """Ile osób stanie w której kolumnie Tablicy (``unknown`` = stan spoza szablonu)."""
    counts: Counter[str] = Counter()
    for state in people.values():
        stage_def = defs.get(state)
        if stage_def is None:
            counts["unknown"] += 1
            continue
        counts[
            board_column_for(
                stage_def.name,
                stage_def.legacy,
                category=stage_def.category,
                terminal_type=stage_def.terminal_type,
            )
        ] += 1
    return dict(counts)


def plan_counts(plan: JobPlan) -> dict[str, int]:
    return {
        "people": plan.people_in_traffit,
        "matched": plan.matched,
        "promote": len(plan.promotes),
        "insert": len(plan.inserts),
        "remove": len(plan.removes),
        "nexus_on_top": plan.nexus_on_top,
        "nexus_only": plan.nexus_only,
        "unverified": plan.unverified,
        "already_closed": plan.already_closed,
        "unknown_people": len(plan.unknown_people),
    }


async def _read_setting(db: AsyncSession, key: str) -> Optional[dict[str, Any]]:
    row = await db.execute(
        text("SELECT value FROM app_settings WHERE key = :k"), {"k": key}
    )
    value = row.scalar_one_or_none()
    return value if isinstance(value, dict) else None


async def _write_setting(db: AsyncSession, key: str, value: dict[str, Any]) -> None:
    await db.execute(
        text(
            """
            INSERT INTO app_settings (key, value, updated_at)
            VALUES (:k, CAST(:v AS jsonb), now())
            ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now()
            """
        ),
        {"k": key, "v": json.dumps(value, default=str)},
    )


# ── Jedna rekrutacja ─────────────────────────────────────────────────────────

#: Notatka przy karcie osoby zdjętej z rekrutacji w Traffit.
REMOVED_NOTE = "Zdjęty z rekrutacji w Traffit — przeniesienie do NEXUSA."
TRANSFER_REASON = "traffit_transfer"


def _ext_id(kind: str, traffit_id: str, emp: str) -> str:
    """Klucz idempotencji wiersza dopisanego przy przeniesieniu.

    Wiersze z importu niosą numer wpisu historii Traffita; te nie mają
    odpowiednika w historii (stan odczytany z listy osób), więc dostają własny
    prefiks. Ponowny bieg trafia w ten sam wiersz zamiast dokładać kolejny.
    """
    return f"transfer:{kind}:{traffit_id}:{emp}"


def _blocker_codes(job: Any) -> list[str]:
    """Braki z bramki „Otwórz ponownie” — do raportu, przeniesienie ich nie wymusza."""
    from app.services.job_readiness import job_handoff_blocker_items

    try:
        return [
            item["code"] for item in job_handoff_blocker_items(job, include_open=True)
        ]
    except Exception:  # noqa: BLE001 — raport braków nie może wywrócić przeniesienia
        logger.warning("Traffit transfer: readiness check failed for job %s", job.id)
        return ["readiness_unknown"]


async def _apply_plan(
    db: AsyncSession,
    importer: Any,
    job: WaveJob,
    plan: JobPlan,
    defs: dict[str, StageDef],
    fallback: Any,
    now: datetime,
) -> dict[str, Any]:
    """Zapisz poprawki jednej rekrutacji. Bez commitu. Zwraca ID do paragonu."""
    from app.services.recruitment_process_commands import (
        note_external_stage_row,
        promote_external_stage_row,
        sync_external_observed_processes,
    )

    receipt: dict[str, Any] = {"promoted": [], "inserted": [], "withdrawn": []}
    pairs: list[tuple[int, int]] = []

    for promote in plan.promotes:
        if await promote_external_stage_row(
            db, stage_id=promote.row_id, job_id=job.job_id, moved_at=promote.moved_at
        ):
            receipt["promoted"].append(promote.row_id)
            pairs.append((promote.candidate_id, job.job_id))

    for insert in plan.inserts:
        stage_def = defs.get(insert.state_ext)
        if stage_def is None:
            # Stan spoza szablonów NEXUSA — nie zgadujemy etapu.
            continue
        payload = {
            "external_id": _ext_id("state", job.traffit_id, insert.emp),
            "candidate_id": insert.candidate_id,
            "job_id": job.job_id,
            "stage_def_id": stage_def.stage_def_id,
            "stage_legacy_enum": stage_def.legacy,
            "moved_at": now,
            "moved_by": None,
            "contact_source_created_at": None,
        }
        reason_id = fallback.resolve(
            stage_def.legacy, job.job_id, stage_def.stage_def_id
        )
        if stage_def.legacy == "withdrawn" and reason_id is None:
            continue
        await importer._upsert_stage_row(payload, reason_id)  # noqa: SLF001
        receipt["inserted"].append(insert.candidate_id)
        pairs.append((insert.candidate_id, job.job_id))

    for remove in plan.removes:
        reason_id = fallback.resolve("withdrawn", job.job_id, None)
        if reason_id is None:
            # Bez powodu wiersz padłby na ograniczeniu 0068 — karta zostaje.
            continue
        ext_id = _ext_id("removed", job.traffit_id, f"c{remove.candidate_id}")
        payload = {
            "external_id": ext_id,
            "candidate_id": remove.candidate_id,
            "job_id": job.job_id,
            # Etap bez wskazania szablonu: Tablica dobiera „Wycofany” rekrutacji
            # po kodzie etapu, jak dla każdego wiersza bez etapu szablonu.
            "stage_def_id": None,
            "stage_legacy_enum": "withdrawn",
            "moved_at": now,
            "moved_by": None,
            "contact_source_created_at": None,
        }
        await importer._upsert_stage_row(payload, reason_id)  # noqa: SLF001
        await note_external_stage_row(
            db, external_id=ext_id, rejection_note=REMOVED_NOTE
        )
        receipt["withdrawn"].append(remove.candidate_id)
        pairs.append((remove.candidate_id, job.job_id))

    if pairs:
        await sync_external_observed_processes(db, pairs=pairs)
    return receipt


async def _adopt_twin_team(
    db: AsyncSession, job_row: Any, twin_job_id: int, actor_id: int
) -> dict[str, Any]:
    """Zespół z rekrutacji założonej w NEXUSIE przechodzi na kopię z Traffita.

    Ten sam request bywa w NEXUSIE dwa razy: Delivery Lead założył go tutaj
    (wskazał prowadzącego, siebie, dopisał współpracowników), a kandydaci są
    w kopii z Traffita, w której „prowadzącym” jest pierwsza osoba z listy
    Traffita. Otwierana kopia dostaje więc prowadzącego (aktywnego), DL-a
    i ręcznie dopisanych współpracowników z rekrutacji NEXUSA — inaczej nie
    trafiłaby do „moich rekrutacji” ludzi, którzy nad nią pracują. Rekrutacja
    NEXUSA zostaje nietknięta; scalenie obu to osobny krok. Bez commitu.
    """
    from app.models.job import Job
    from app.models.user import User

    twin = await db.get(Job, twin_job_id)
    if twin is None:
        return {}
    adopted: dict[str, Any] = {}
    if twin.recruiter_id is not None and twin.recruiter_id != job_row.recruiter_id:
        owner = await db.get(User, twin.recruiter_id)
        if owner is not None and owner.is_active:
            job_row.recruiter_id = owner.id
            adopted["recruiter_from_twin"] = owner.id
    if (
        twin.delivery_lead_id is not None
        and twin.delivery_lead_id != job_row.delivery_lead_id
    ):
        job_row.delivery_lead_id = twin.delivery_lead_id
        job_row.delivery_lead_auto_filled = False
        adopted["delivery_lead_from_twin"] = twin.delivery_lead_id
    copied = await db.execute(
        text(
            """
            INSERT INTO job_collaborators (job_id, user_id, added_by, source)
            SELECT :job_id, jc.user_id, :actor, jc.source
            FROM job_collaborators jc
            WHERE jc.job_id = :twin_id
              AND jc.source = 'manual'
              AND NOT jc.removed_from_auto_cc
              AND jc.removed_at IS NULL
            ON CONFLICT (job_id, user_id) DO NOTHING
            """
        ),
        {"job_id": job_row.id, "twin_id": twin_job_id, "actor": actor_id},
    )
    adopted["collaborators_from_twin"] = int(copied.rowcount or 0)
    return adopted


async def _settle_owner(db: AsyncSession, job_row: Any) -> dict[str, Any]:
    """Prowadzący z Traffita bez roli rekrutera nie zostaje rekruterem requestu.

    W Traffit „osobą odpowiedzialną” za rekrutację jest zwykle Delivery Lead,
    a import wpisuje ją do ``jobs.recruiter_id``. Dopóki rekrutacja była
    archiwum, nic z tego nie wynikało; po otwarciu prowadzący jest przy
    requeście z urzędu jako „Rekruter” (wiersz ``owner`` automatu przydziału)
    — 12.10.2026 pierwsza fala pokazała w „Obłożeniu” trzech Delivery Leadów
    z 10–18 requestami. Aktywna osoba bez roli pracy przy requestach
    (``job_team.WORK_ROLES``) trafia więc na miejsce Delivery Leada, jeśli
    jest puste albo wypełnił je automat, a rekrutacja zostaje bez rekrutera
    — nikogo nowego nie przypisujemy, o rekruterze decyduje człowiek.
    Bez commitu.
    """
    from app.models.user import User, UserRole
    from app.services.job_team import WORK_ROLES

    if job_row.recruiter_id is None:
        return {}
    owner = await db.get(User, job_row.recruiter_id)
    if owner is None or not owner.is_active or owner.has_any_role(*WORK_ROLES):
        return {}
    settled: dict[str, Any] = {"owner_without_recruiter_role": owner.id}
    # DL-a wpisanego przez automat (główny DL klienta) zastępujemy: u klienta
    # z kilkoma Delivery Leadami rekrutację prowadzi ten z Traffita, a automat
    # wpisywał wszystkim jednego — 35 rekrutacji jednego DL-a dostało innego.
    # DL-a wpisanego przez człowieka nie ruszamy.
    lead_slot_free = job_row.delivery_lead_id is None or bool(
        job_row.delivery_lead_auto_filled
    )
    if owner.has_any_role(UserRole.delivery_lead) and lead_slot_free:
        if job_row.delivery_lead_id != owner.id:
            settled["owner_moved_to_delivery_lead"] = True
        job_row.delivery_lead_id = owner.id
        job_row.delivery_lead_auto_filled = False
    job_row.recruiter_id = None
    return settled


_TRANSFERRED_WITH_OWNER_SQL = """
SELECT j.id
FROM jobs j
JOIN users u ON u.id = j.recruiter_id
WHERE j.external_source = 'traffit'
  AND j.managed_in_nexus
  AND j.status = 'published'
  AND u.is_active
  AND EXISTS (SELECT 1 FROM activities a
              WHERE a.entity_type = 'job' AND a.entity_id = j.id
                AND a.action = 'traffit_transfer')
ORDER BY j.id
"""


async def repair_transferred_owners(
    db: AsyncSession, *, actor_user_id: Optional[int], dry_run: bool
) -> dict[str, Any]:
    """Zastosuj :func:`_settle_owner` do rekrutacji przeniesionych wcześniej.

    Pierwsza fala (12.10.2026) otworzyła rekrutacje z Delivery Leadem jako
    prowadzącym. Ten przebieg zdejmuje go z miejsca rekrutera i zwalnia jego
    przypisanie „Rekruter” tą samą funkcją co zmiana prowadzącego w oknie
    edycji. Idempotentny: po naprawie rekrutacja nie ma prowadzącego, więc
    kolejny bieg jej nie widzi.
    """
    from sqlalchemy import select

    from app.models.activity import Activity
    from app.models.job import Job
    from app.models.user import User
    from app.services import job_lifecycle
    from app.services.job_team import WORK_ROLES
    from app.services.recruitment_allocation import allocation_lock

    job_ids = [int(r[0]) for r in (await db.execute(text(_TRANSFERRED_WITH_OWNER_SQL)))]
    await db.rollback()
    repaired: list[int] = []
    moved_to_lead = 0
    for job_id in job_ids:
        if dry_run:
            job_row = await db.get(Job, job_id)
            owner = await db.get(User, job_row.recruiter_id) if job_row else None
            if owner is not None and not owner.has_any_role(*WORK_ROLES):
                repaired.append(job_id)
            continue
        if actor_user_id is None:
            break
        await allocation_lock(db)
        job_row = (
            await db.execute(
                select(Job)
                .where(Job.id == job_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        ).scalar_one()
        previous = job_row.recruiter_id
        settled = await _settle_owner(db, job_row)
        if not settled:
            await db.rollback()
            continue
        await job_lifecycle._api()._sync_work_assignments_with_owner(  # noqa: SLF001
            db,
            job=job_row,
            previous_owner_id=previous,
            owner=None,
            actor_id=actor_user_id,
        )
        db.add(
            Activity(
                entity_type="job",
                entity_id=job_id,
                action="traffit_transfer_owner_settled",
                user_id=actor_user_id,
                details=settled,
            )
        )
        await db.commit()
        repaired.append(job_id)
        moved_to_lead += int(bool(settled.get("owner_moved_to_delivery_lead")))
    await db.rollback()
    return {
        "owners_settled": len(repaired),
        "owners_moved_to_delivery_lead": moved_to_lead,
        "owners_settled_job_ids": repaired[:200],
    }


def _job_report(
    job: WaveJob, plan: Optional[JobPlan], *, status: str, **extra: Any
) -> dict[str, Any]:
    report: dict[str, Any] = {
        "job_id": job.job_id,
        "traffit_id": job.traffit_id,
        "client_id": job.client_id,
        "status": status,
        "missing_delivery_lead": job.delivery_lead_id is None,
        "missing_recruiter": job.recruiter_id is None,
    }
    if plan is not None:
        report.update(plan_counts(plan))
        report["unknown_people_ids"] = plan.unknown_people[:SAMPLE_IDS]
    report.update(extra)
    return report


async def process_job(
    db: AsyncSession,
    traffit: Any,
    importer: Any,
    job: WaveJob,
    *,
    defs: dict[str, StageDef],
    twin_job_id: Optional[int],
    fallback: Any,
    actor_user_id: Optional[int],
    dry_run: bool,
    include_twins: bool = False,
    twin_exact: bool = False,
) -> dict[str, Any]:
    """Próba albo przeniesienie jednej rekrutacji — własna transakcja."""
    from fastapi import HTTPException
    from sqlalchemy import select

    from app.models.activity import Activity
    from app.models.job import Job, JobStatus
    from app.models.user import User
    from app.services import job_lifecycle
    from app.services.recruitment_allocation import allocation_lock
    from app.services.traffit.importer import safe_db_error

    if job.people > MAX_PEOPLE:
        return _job_report(job, None, status="skipped", skip_reason=SKIP_LARGE)
    if twin_job_id is not None and not include_twins:
        return _job_report(
            job, None, status="skipped", skip_reason=SKIP_TWIN, twin_job_id=twin_job_id
        )
    twin: dict[str, Any] = (
        {"twin_job_id": twin_job_id, "twin_exact": twin_exact}
        if twin_job_id is not None
        else {}
    )

    # Połączenie wraca do puli na czas zapytań do Traffita.
    await db.rollback()
    try:
        people, total = await fetch_roster(traffit, job.traffit_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "Traffit transfer: roster for recruitment %s failed: %s",
            job.traffit_id,
            type(exc).__name__,
        )
        return _job_report(job, None, status="skipped", skip_reason=SKIP_TRAFFIT)
    if not roster_is_trustworthy(people, total):
        return _job_report(
            job,
            None,
            status="skipped",
            skip_reason=SKIP_ROSTER,
            roster_people=len(people),
            roster_total=total,
        )

    try:
        if not dry_run:
            await allocation_lock(db)
        rows = await load_rows(db, job.job_id)
        with_card = {r.emp for r in rows if r.emp}
        emp_map = await load_candidates_by_emp(
            db, sorted(emp for emp in people if emp not in with_card)
        )
        plan = plan_job(people, rows, emp_map)
        columns = columns_after(people, defs)
        job_row = (
            await db.execute(select(Job).where(Job.id == job.job_id))
        ).scalar_one()
        blockers = _blocker_codes(job_row)
        if dry_run:
            await db.rollback()
            return _job_report(
                job, plan, status="ready", columns=columns, blockers=blockers, **twin
            )

        actor = await db.get(User, actor_user_id) if actor_user_id else None
        if actor is None:
            await db.rollback()
            return _job_report(job, plan, status="failed", error="brak wykonawcy")
        now = datetime.now(timezone.utc)
        # Poprawki etapów PRZED blokadą rekrutacji: synchronizacja procesów
        # blokuje kandydatów, potem rekrutację — ta sama kolejność co ruch
        # karty, więc równoległy ruch nie zakleszczy się z przeniesieniem.
        receipt = await _apply_plan(db, importer, job, plan, defs, fallback, now)
        job_row = (
            await db.execute(
                select(Job)
                .where(Job.id == job.job_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        ).scalar_one()
        if job_row.external_source != "traffit" or job_row.status != JobStatus.closed:
            # Ktoś otworzył ją w międzyczasie — poprawki cofamy.
            await db.rollback()
            return _job_report(job, plan, status="skipped", skip_reason="changed")
        if twin_job_id is not None and twin_exact:
            # PRZED otwarciem: przypisanie i dzwonek idą do prowadzącego,
            # którego Delivery Lead wskazał w NEXUSIE. Tylko przy pewnym
            # bliźniaku — podobny tytuł nie wystarcza, żeby zmienić komuś
            # prowadzącego (decyzja Artura 12.10.2026: przypisane osoby
            # mają się nie zmieniać).
            twin.update(await _adopt_twin_team(db, job_row, twin_job_id, actor.id))
        twin.update(await _settle_owner(db, job_row))
        effects = job_lifecycle.PostCommit()
        # Te same funkcje co „Otwórz ponownie”: flaga „Prowadzona w NEXUSIE”,
        # status, „Szukamy”, przypisanie prowadzącego. Bramki braków NIE
        # sprawdzamy — rekrutacja jest już w pracy, braki niesie raport.
        await job_lifecycle.publish_core(
            db, job_row, actor, effects, reason=TRANSFER_REASON
        )
        await job_lifecycle.reopen_keep_team_core(db, job_row, actor, effects)
        db.add(
            Activity(
                entity_type="job",
                entity_id=job.job_id,
                action="traffit_transfer",
                user_id=actor.id,
                details={**plan_counts(plan), "traffit_id": job.traffit_id, **twin},
            )
        )
        await db.commit()
    except HTTPException as exc:
        await db.rollback()
        detail = exc.detail
        if isinstance(detail, dict):
            detail = detail.get("code") or detail.get("message") or "odmowa"
        return _job_report(job, None, status="failed", error=str(detail)[:200])
    except Exception as exc:  # noqa: BLE001
        await db.rollback()
        logger.error(
            "Traffit transfer: job %s failed: %s", job.job_id, safe_db_error(exc)
        )
        return _job_report(job, None, status="failed", error=type(exc).__name__)

    await job_lifecycle.run_post_commit(effects)
    return _job_report(
        job,
        plan,
        status="transferred",
        columns=columns,
        blockers=blockers,
        **receipt,
        **twin,
    )


# ── Bieg fali ────────────────────────────────────────────────────────────────


def _totals(jobs: list[dict[str, Any]]) -> dict[str, Any]:
    counts: Counter[str] = Counter()
    statuses: Counter[str] = Counter()
    columns: Counter[str] = Counter()
    for job in jobs:
        statuses[job["status"]] += 1
        for key in COUNT_KEYS:
            counts[key] += int(job.get(key) or 0)
        for column, value in (job.get("columns") or {}).items():
            columns[column] += int(value)
    return {
        "jobs": len(jobs),
        "by_status": dict(statuses),
        **{key: int(counts[key]) for key in COUNT_KEYS},
        "columns": dict(columns),
    }


async def process(
    db: AsyncSession,
    traffit: Any,
    scope: Scope,
    *,
    dry_run: bool,
    actor_user_id: Optional[int],
    actor_label: str,
) -> dict[str, Any]:
    """Jeden bieg fali. Zwraca raport (zapis raportu: :func:`finish_run`)."""
    from app.services.traffit.importer import TraffitImporter

    jobs = await load_wave(db, scope)
    defs = await load_stage_defs(db)
    twins = await load_twins(db, jobs)
    importer = TraffitImporter(traffit, db, dry_run=dry_run)
    # Próba nie dosiewa powodu `legacy_unknown` (importer w dry_run nie pisze).
    fallback = await importer._build_withdrawn_fallback_reason_map()  # noqa: SLF001
    await db.commit()

    owners = await repair_transferred_owners(
        db, actor_user_id=actor_user_id, dry_run=dry_run
    )

    reports: list[dict[str, Any]] = []
    for job in jobs:
        twin = twins.get(job.job_id)
        reports.append(
            await process_job(
                db,
                traffit,
                importer,
                job,
                defs=defs,
                twin_job_id=twin.job_id if twin else None,
                twin_exact=bool(twin and twin.exact),
                fallback=fallback,
                actor_user_id=actor_user_id,
                dry_run=dry_run,
                include_twins=scope.include_twins,
            )
        )

    if not dry_run:
        from app.services.job_delivery_lead_fill import fill_missing_job_delivery_leads

        client_ids = {j.client_id for j in jobs if j.client_id is not None}
        try:
            await fill_missing_job_delivery_leads(db, client_ids)
            await db.commit()
        except Exception:  # noqa: BLE001 — DL-a dopełni też start aplikacji
            await db.rollback()
            logger.warning("Traffit transfer: delivery lead fill failed")

    return {
        "dry_run": dry_run,
        "scope": scope.as_dict(),
        "scope_key": scope.key(),
        "actor": actor_label,
        "totals": _totals(reports),
        "owners": owners,
        "jobs": reports,
    }


async def finish_run(
    db: AsyncSession, report: dict[str, Any], *, started: datetime
) -> None:
    """Próba → ``DRY_RUN_KEY`` (ostatnia); wykonanie → dopisek do ``LOG_KEY``."""
    report = {
        **report,
        "started_at": started.isoformat(),
        "finished_at": datetime.now(timezone.utc).isoformat(),
    }
    if report["dry_run"]:
        await _write_setting(db, DRY_RUN_KEY, report)
    else:
        log = await _read_setting(db, LOG_KEY) or {}
        runs = list(log.get("runs") or [])
        runs.append(report)
        await _write_setting(db, LOG_KEY, {"runs": runs})
    await db.commit()


# ── Przebieg w tle ───────────────────────────────────────────────────────────

_running: dict[str, bool] = {"transfer": False}


def is_running() -> bool:
    return _running["transfer"]


async def fresh_dry_run_exists(db: AsyncSession, scope: Scope) -> bool:
    """Czy jest próba TEJ fali z ostatnich 24 godzin."""
    report = await _read_setting(db, DRY_RUN_KEY)
    if not report or report.get("scope_key") != scope.key():
        return False
    try:
        finished = datetime.fromisoformat(str(report.get("finished_at")))
    except ValueError:
        return False
    return datetime.now(timezone.utc) - finished <= DRY_RUN_MAX_AGE


async def run_transfer(
    *,
    scope: Scope,
    dry_run_mode: bool,
    actor_user_id: Optional[int],
    actor_label: str,
) -> None:
    """Bieg w tle (spawn z endpointu) pod blokadą syncu Traffita."""
    from app.core.database import AsyncSessionLocal
    from app.services.traffit.client import TraffitClient, TraffitConfig
    from app.tasks.traffit_sync import traffit_exclusive_lock

    if _running["transfer"]:
        return
    _running["transfer"] = True
    started = datetime.now(timezone.utc)
    try:
        lock = traffit_exclusive_lock()
        if lock.locked():
            logger.warning("Traffit transfer skipped: sync running")
            return
        async with lock:
            config = TraffitConfig.from_env()
            async with TraffitClient(config) as traffit:
                async with AsyncSessionLocal() as db:
                    report = await process(
                        db,
                        traffit,
                        scope,
                        dry_run=dry_run_mode,
                        actor_user_id=actor_user_id,
                        actor_label=actor_label,
                    )
                    await finish_run(db, report, started=started)
                    logger.info(
                        "Traffit transfer done (dry_run=%s): %s",
                        dry_run_mode,
                        json.dumps(report["totals"]),
                    )
    finally:
        _running["transfer"] = False


async def read_status(db: AsyncSession) -> dict[str, Any]:
    log = await _read_setting(db, LOG_KEY) or {}
    runs = list(log.get("runs") or [])
    return {
        "running": is_running(),
        "dry_run": await _read_setting(db, DRY_RUN_KEY),
        "runs": len(runs),
        "last_run": runs[-1] if runs else None,
    }


def spawn_running_guard() -> Optional[str]:
    """Powód odmowy startu (409) albo ``None``."""
    from app.services import traffit_file_dates_repair, traffit_notes_repair
    from app.tasks.traffit_sync import sync_is_running

    if sync_is_running():
        return "Trwa synchronizacja z Traffitem — spróbuj po jej zakończeniu."
    if traffit_notes_repair.is_running() or traffit_file_dates_repair.is_running():
        return "Trwa naprawa danych z Traffita — spróbuj po jej zakończeniu."
    if is_running():
        return "Przeniesienie rekrutacji z Traffita już trwa."
    return None


__all__ = [
    "ACTIVE_DAYS_DEFAULT",
    "DRY_RUN_KEY",
    "LOG_KEY",
    "Scope",
    "WaveJob",
    "Twin",
    "assign_twins",
    "find_twin",
    "request_id",
    "match_twin",
    "title_core",
    "finish_run",
    "fresh_dry_run_exists",
    "process",
    "process_job",
    "repair_transferred_owners",
    "read_status",
    "run_transfer",
    "spawn_running_guard",
]
