"""Dowód równoważności dla optymalizacji pełnych skanów `candidate_stages`.

Trzy miejsca w kodzie robiły dokładnie to samo: `SELECT` całej tabeli
`candidate_stages` bez `WHERE` i bez `LIMIT` (~158k ciężkich wierszy: `notes`
Text + `scorecard_answers`/`screening_answers` JSONB), a potem dedupe pętlą
w Pythonie do "najnowszy etap per (kandydat, oferta)":

* `services/notification_triggers.py::_latest_stage_per_pair` — wołane z 6
  triggerów, z czego 2 bez żadnej bramki, co 5 min z loopa,
* `api/pipeline.py::pipeline_overview` — endpoint managera,
* `tasks/slack_sla_alerts.py::_compute_breaches` — co 30 min.

Wszystkie trzy przeszły na `DISTINCT ON (candidate_id, job_id)` / widok
`analytics_current_pipeline` (indeks `ix_analytics_cs_cand_job_moved`).

Ten plik NIE testuje "czy jest szybciej" — testuje, że **wynik się nie zmienił**.
Wzorzec: oracle = dosłowna kopia starego algorytmu, uruchamiana na tej samej
bazie co nowa implementacja. Porównanie na całej zawartości bazy, nie tylko na
zaseedowanych wierszach — więc test broni się też na współdzielonej instancji.

Zaseedowane przypadki brzegowe:

* para z JEDNYM etapem,
* para z KILKOMA etapami (wygrywa najnowszy `moved_at`),
* para z REMISEM `moved_at` (wygrywa większe `id` — zgodnie z indeksem
  `... moved_at DESC, id DESC`); to jedyne miejsce, gdzie stary kod był
  niedeterministyczny, więc oracle sprawdzamy tu wprost przeciw kontraktowi,
* para w etapie terminalnym (`hired`) — wypada z agregatów "aktywnych",
* pary "przeterminowane" (>5 dni) zasilające `aging_alerts`,
* wiersz z `moved_by IS NULL` → kubełek 0 ("Nieprzypisany") w `workload`.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from httpx import AsyncClient
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.recruitment_pipeline import CandidateStage, PipelineStage

OVERVIEW = "/api/pipeline/overview"

_TERMINAL = (PipelineStage.hired, PipelineStage.rejected, PipelineStage.withdrawn)


# ── oracle: dosłowna kopia starego algorytmu ────────────────────────────────


async def _oracle_latest_per_pair(db) -> dict[tuple[int, int], CandidateStage]:
    """Stary `_latest_stage_per_pair` / `_compute_breaches` — pełny skan + Python."""
    rows = await db.execute(
        select(CandidateStage).order_by(
            CandidateStage.candidate_id,
            CandidateStage.job_id,
            CandidateStage.moved_at.desc(),
            # Stary kod NIE miał tego tie-breaka — przy remisie `moved_at`
            # wygrywał losowy wiersz. Kontrakt (indeks + widok) mówi `id DESC`,
            # więc oracle jawnie go domyka: to jedyna różnica względem starego
            # kodu i jest ona zamierzonym doprecyzowaniem, nie zmianą wyniku.
            CandidateStage.id.desc(),
        )
    )
    latest: dict[tuple[int, int], CandidateStage] = {}
    for stage in rows.scalars().all():
        key = (stage.candidate_id, stage.job_id)
        if key not in latest:
            latest[key] = stage
    return latest


def _days_in_stage(moved_at: datetime) -> int:
    """Kopia `api/pipeline.py::_days_in_stage`."""
    now = datetime.now(timezone.utc)
    if moved_at.tzinfo is None:
        moved_at = moved_at.replace(tzinfo=timezone.utc)
    return max(0, (now - moved_at).days)


def _oracle_overview(latest: dict[tuple[int, int], CandidateStage]) -> dict:
    """Stary `pipeline_overview` — agregaty liczone pętlą w Pythonie."""
    entries = list(latest.values())

    jobs_data: dict[int, dict] = {}
    for entry in entries:
        bucket = jobs_data.setdefault(entry.job_id, {"stages": {}, "total": 0})
        val = entry.stage.value
        bucket["stages"][val] = bucket["stages"].get(val, 0) + 1
        bucket["total"] += 1

    aging = [
        {
            "candidate_id": e.candidate_id,
            "job_id": e.job_id,
            "stage": e.stage.value,
            "days": _days_in_stage(e.moved_at),
        }
        for e in entries
        if _days_in_stage(e.moved_at) > 5 and e.stage not in _TERMINAL
    ]
    aging.sort(key=lambda x: -x["days"])

    recruiter_load: dict[int, int] = {}
    for entry in entries:
        if entry.stage not in _TERMINAL:
            rid = entry.moved_by or 0
            recruiter_load[rid] = recruiter_load.get(rid, 0) + 1

    return {
        "jobs": jobs_data,
        "aging": aging[:20],
        "workload": recruiter_load,
    }


# ── seed ────────────────────────────────────────────────────────────────────


async def _seed_user(name: str) -> int:
    from app.core.security import hash_password
    from app.models.user import User, UserRole

    async with AsyncSessionLocal() as db:
        u = User(
            email=f"scan-eq-{uuid.uuid4().hex[:8]}@example.com",
            password_hash=hash_password("T3st_scan_eq!Pass"),
            name=name,
            role=UserRole.recruiter,
            roles=["recruiter"],
            is_active=True,
        )
        db.add(u)
        await db.commit()
        await db.refresh(u)
        return u.id


async def _seed_job() -> int:
    from app.models.client import Client
    from app.models.job import Job, JobStatus

    async with AsyncSessionLocal() as db:
        cli = Client(name=f"ScanEqClient-{uuid.uuid4().hex[:6]}")
        db.add(cli)
        await db.commit()
        await db.refresh(cli)
        job = Job(
            title=f"ScanEq-Job-{uuid.uuid4().hex[:6]}",
            status=JobStatus.published,
            client_id=cli.id,
        )
        db.add(job)
        await db.commit()
        await db.refresh(job)
        return job.id


async def _seed_candidate() -> int:
    from app.models.candidate import Candidate, CandidateStatus

    async with AsyncSessionLocal() as db:
        c = Candidate(
            name="ScanEq",
            lastname=f"Cand-{uuid.uuid4().hex[:6]}",
            email=f"scan-eq-cand-{uuid.uuid4().hex[:8]}@example.com",
            status=CandidateStatus.active,
        )
        db.add(c)
        await db.commit()
        await db.refresh(c)
        return c.id


async def _seed_stage(
    candidate_id: int,
    job_id: int,
    stage: PipelineStage,
    moved_at: datetime,
    moved_by: int | None = None,
) -> int:
    async with AsyncSessionLocal() as db:
        row = CandidateStage(
            candidate_id=candidate_id,
            job_id=job_id,
            stage=stage,
            moved_at=moved_at,
            moved_by=moved_by,
            # Ciężkie kolumny, których nowa ścieżka celowo NIE pobiera —
            # wypełnione, żeby test faktycznie chodził po tym samym kształcie
            # danych co produkcja.
            notes="x" * 512,
            scorecard_answers={"answers": [{"q": "a"} for _ in range(20)]},
            screening_answers={"answers": [{"q": "b"} for _ in range(20)]},
        )
        db.add(row)
        await db.commit()
        await db.refresh(row)
        return row.id


async def _seed_fixtures() -> dict:
    now = datetime.now(timezone.utc)
    recruiter = await _seed_user("ScanEq Recruiter")
    job_a = await _seed_job()
    job_b = await _seed_job()
    c_single = await _seed_candidate()
    c_multi = await _seed_candidate()
    c_tie = await _seed_candidate()
    c_terminal = await _seed_candidate()

    ids: dict[str, int] = {}

    # 1. Para z jednym etapem, świeża (nie trafia do aging).
    await _seed_stage(c_single, job_a, PipelineStage.screening, now, recruiter)

    # 2. Para z trzema etapami — wygrywa najnowszy `moved_at`, mimo że
    #    wstawiony jako pierwszy (czyli NIE "największe id wygrywa zawsze").
    ids["multi_winner"] = await _seed_stage(
        c_multi, job_a, PipelineStage.cv_sent, now - timedelta(days=7), recruiter
    )
    await _seed_stage(
        c_multi, job_a, PipelineStage.new, now - timedelta(days=30), recruiter
    )
    await _seed_stage(
        c_multi, job_a, PipelineStage.prep_call, now - timedelta(days=20), recruiter
    )

    # 3. Remis `moved_at` → wygrywa większe `id`.
    tie_at = now - timedelta(days=9)
    await _seed_stage(c_tie, job_b, PipelineStage.interview, tie_at, recruiter)
    ids["tie_winner"] = await _seed_stage(
        c_tie, job_b, PipelineStage.client_interview, tie_at, None
    )

    # 4. Para terminalna — wypada z `workload` i `aging_alerts`.
    await _seed_stage(
        c_terminal, job_b, PipelineStage.screening, now - timedelta(days=40), recruiter
    )
    ids["terminal_winner"] = await _seed_stage(
        c_terminal, job_b, PipelineStage.hired, now - timedelta(days=12), recruiter
    )

    ids.update(
        {
            "recruiter": recruiter,
            "job_a": job_a,
            "job_b": job_b,
            "c_single": c_single,
            "c_multi": c_multi,
            "c_tie": c_tie,
            "c_terminal": c_terminal,
        }
    )
    return ids


# ── licznik zapytań ─────────────────────────────────────────────────────────


class _PipelineScanCounter:
    """Liczy zapytania czytające `candidate_stages` BEZ klauzuli `WHERE`.

    Dokładnie taki kształt miał stary pełny skan. Licznik jest twardą bramką
    regresji: jeśli ktoś doda kolejne `_latest_stage_per_pair` do triggera
    zamiast przekazać gotową mapę, liczba wróci powyżej 1 i test się wywali.
    """

    def __init__(self) -> None:
        self.statements: list[str] = []

    def __call__(self, conn, cursor, statement, params, context, executemany):
        flat = " ".join(statement.split()).lower()
        if "from candidate_stages" in flat and " where " not in flat:
            self.statements.append(flat)

    def __enter__(self) -> _PipelineScanCounter:
        from sqlalchemy import event

        from app.core.database import engine

        self._target = engine.sync_engine
        event.listen(self._target, "before_cursor_execute", self)
        return self

    def __exit__(self, *exc) -> None:
        from sqlalchemy import event

        event.remove(self._target, "before_cursor_execute", self)


# ── testy ───────────────────────────────────────────────────────────────────


async def test_run_all_triggers_scans_candidate_stages_once():
    """Cały tick triggerów = JEDEN skan `candidate_stages`, nie sześć.

    Przed zmianą 6 z 8 triggerów wołało własne `_latest_stage_per_pair`, a dwa
    z nich (`dl_stage_stale_6h`, `stage_stuck_7d`) nie miały żadnej bramki —
    skan był pierwszą instrukcją funkcji. Loop chodzi co 5 min w dni robocze,
    więc było to ≥24 pełne skany 158k wierszy na godzinę przy zerowym ruchu.
    """
    from zoneinfo import ZoneInfo

    from app.services import notification_triggers as nt

    await _seed_fixtures()
    # Wtorek 21:00 Warsaw — poza oknami KPI/EOBD, więc mierzymy ścieżkę
    # "nic się nie dzieje", czyli dokładnie ten przypadek, który marnował I/O.
    now = datetime(2026, 4, 21, 21, 0, tzinfo=ZoneInfo("Europe/Warsaw"))

    async with AsyncSessionLocal() as db:
        with _PipelineScanCounter() as counter:
            await nt.run_all_triggers(db, now)

    assert len(counter.statements) == 1, (
        f"oczekiwano 1 pełnego skanu candidate_stages, było "
        f"{len(counter.statements)}: {counter.statements}"
    )
    # I to nie jest już hydratacja całego wiersza — tylko pięć kolumn + DISTINCT ON.
    only = counter.statements[0]
    assert "distinct on" in only
    assert "notes" not in only
    assert "scorecard_answers" not in only
    assert "screening_answers" not in only


async def test_latest_stage_per_pair_matches_full_scan_oracle():
    """Nowy `DISTINCT ON` zwraca DOKŁADNIE ten sam zestaw co pełny skan."""
    from app.services import notification_triggers as nt

    ids = await _seed_fixtures()

    async with AsyncSessionLocal() as db:
        oracle = await _oracle_latest_per_pair(db)
        actual = await nt._latest_stage_per_pair(db)

    assert set(actual.keys()) == set(oracle.keys())
    for key, expected in oracle.items():
        got = actual[key]
        assert got.id == expected.id, f"inny wiersz wygrał dla pary {key}"
        assert got.stage == expected.stage
        assert got.candidate_id == expected.candidate_id
        assert got.job_id == expected.job_id
        assert got.moved_at == expected.moved_at

    # Przypadki brzegowe wprost, żeby zielony test nie oznaczał "obie
    # implementacje są tak samo zepsute".
    assert actual[(ids["c_multi"], ids["job_a"])].id == ids["multi_winner"]
    assert actual[(ids["c_multi"], ids["job_a"])].stage == PipelineStage.cv_sent
    assert actual[(ids["c_tie"], ids["job_b"])].id == ids["tie_winner"]
    assert actual[(ids["c_terminal"], ids["job_b"])].stage == PipelineStage.hired


async def test_latest_stage_per_pair_accepts_precomputed_map():
    """`run_all_triggers` liczy mapę raz i przekazuje ją w dół — bez zapytania."""
    from app.services import notification_triggers as nt

    sentinel: nt.LatestStageMap = {
        (1, 2): nt.LatestStage(
            id=99,
            candidate_id=1,
            job_id=2,
            stage=PipelineStage.new,
            moved_at=datetime.now(timezone.utc),
        )
    }
    # `db=None` — gdyby funkcja mimo podanej mapy poszła do bazy, wywali się
    # na AttributeError. To jest właśnie asercja "zero dodatkowych skanów".
    assert await nt._latest_stage_per_pair(None, sentinel) is sentinel


async def test_pipeline_overview_matches_full_scan_oracle(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
):
    """Agregaty `/pipeline/overview` z SQL == agregaty ze starej pętli."""
    ids = await _seed_fixtures()

    async with AsyncSessionLocal() as db:
        expected = _oracle_overview(await _oracle_latest_per_pair(db))

    resp = await app_client.get(OVERVIEW, headers=app_auth_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()

    # 1. Per-job: te same kubełki etapów i te same sumy.
    got_jobs = {
        j["job_id"]: {"stages": j["stages"], "total": j["total"]} for j in body["jobs"]
    }
    assert got_jobs == expected["jobs"]

    # 2. Aging alerts: ta sama lista top-20 (kandydat, oferta, etap, dni).
    got_aging = [
        (a["candidate_id"], a["job_id"], a["stage"], a["days"])
        for a in body["aging_alerts"]
    ]
    exp_aging = [
        (a["candidate_id"], a["job_id"], a["stage"], a["days"])
        for a in expected["aging"]
    ]
    assert got_aging == exp_aging

    # 3. Workload: te same liczby per rekruter (w tym kubełek 0).
    got_workload = {w["recruiter_id"]: w["active_candidates"] for w in body["workload"]}
    assert got_workload == expected["workload"]
    # Malejąco po liczbie — kontrakt sortowania utrzymany.
    counts = [w["active_candidates"] for w in body["workload"]]
    assert counts == sorted(counts, reverse=True)

    # 4. Kształt odpowiedzi bez zmian.
    assert set(body.keys()) == {
        "jobs",
        "bottlenecks",
        "aging_alerts",
        "opportunities",
        "workload",
        "stage_labels",
    }
    assert len(body["aging_alerts"]) <= 20

    # 5. Przypadki brzegowe wprost.
    job_b = got_jobs[ids["job_b"]]
    assert job_b["stages"].get("hired") == 1, "para terminalna musi być w kubełkach"
    assert (
        ids["c_terminal"],
        ids["job_b"],
        "hired",
    ) not in [(a[0], a[1], a[2]) for a in got_aging], "terminal nie może starzeć"
    # `moved_by IS NULL` (zwycięzca remisu) → kubełek 0.
    assert got_workload.get(0, 0) >= 1


async def test_match_stats_uses_one_bulk_call_per_job_without_cache_writes(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
):
    """Kolumna dopasowań: 1 wywołanie na OFERTĘ, nie na parę kandydat × oferta.

    Dawniej `for cand in items: rank_jobs_for_candidate(cand, open_jobs)` —
    page_size × 50 ofert sekwencyjnych `score_candidate_job`, każdy z własnymi
    round-tripami. Test pilnuje transpozycji pętli ORAZ tego, że ta ścieżka
    NIGDY nie zapisuje do cache match-score: nie ma similarity_map z Qdranta,
    więc świeże wyniki mają neutralną semantykę i utrwalone zaniżyłyby
    `/api/recommendations` (M3-CACHE-01).
    """
    import app.api.candidates as candidates_api

    await _seed_fixtures()

    calls: list[dict] = []
    original = candidates_api.bulk_get_or_compute

    async def _spy(job, candidates, db, **kwargs):
        calls.append(
            {
                "job_id": job.id,
                "candidate_ids": [c.id for c in candidates],
                "allow_cache_write": kwargs.get("allow_cache_write"),
            }
        )
        return await original(job, candidates, db, **kwargs)

    candidates_api.bulk_get_or_compute = _spy
    try:
        resp = await app_client.get(
            "/api/candidates?include_match_stats=true&page_size=3",
            headers=app_auth_headers,
        )
    finally:
        candidates_api.bulk_get_or_compute = original

    assert resp.status_code == 200, resp.text
    items = resp.json()["items"]
    assert items, "potrzebny co najmniej jeden kandydat na stronie"
    assert calls, "match-stats nie policzone — brak opublikowanych ofert?"

    # Jedno wywołanie per oferta — żadna oferta nie powtarza się.
    job_ids = [c["job_id"] for c in calls]
    assert len(job_ids) == len(set(job_ids)), (
        f"oferta punktowana wielokrotnie: {job_ids}"
    )

    page_ids = [i["id"] for i in items]
    for call in calls:
        # Każde wywołanie dostaje CAŁĄ stronę kandydatów, nie pojedynczego.
        assert call["candidate_ids"] == page_ids
        assert call["allow_cache_write"] is False, (
            "ta ścieżka nie może utrwalać wyników z neutralną semantyką"
        )

    # Kontrakt odpowiedzi bez zmian.
    for item in items:
        stats = item.get("match_stats")
        if stats is not None:
            assert set(stats.keys()) >= {"open_count", "total_open", "top_score"}


async def test_slack_sla_breaches_match_full_scan_oracle():
    """`_compute_breaches` po prefiltrze == wynik dawnego pełnego skanu."""
    from app.models.pipeline_template import PipelineStageDef
    from app.tasks.slack_sla_alerts import _compute_breaches

    await _seed_fixtures()

    async with AsyncSessionLocal() as db:
        latest = await _oracle_latest_per_pair(db)
        stage_def_ids = {s.stage_def_id for s in latest.values() if s.stage_def_id}
        defs: dict[int, PipelineStageDef] = {}
        if stage_def_ids:
            rows = await db.execute(
                select(PipelineStageDef).where(PipelineStageDef.id.in_(stage_def_ids))
            )
            defs = {sd.id: sd for sd in rows.scalars().all()}

        now = datetime.now(timezone.utc)
        expected_ids: set[int] = set()
        for s in latest.values():
            sd = defs.get(s.stage_def_id or 0)
            if not sd or not sd.sla_max_days or sd.is_terminal:
                continue
            moved = s.moved_at
            if moved.tzinfo is None:
                moved = moved.replace(tzinfo=timezone.utc)
            if (now - moved).days > sd.sla_max_days:
                expected_ids.add(s.id)

        breaches = await _compute_breaches(db)

    assert {b["candidate_stage_id"] for b in breaches} == expected_ids
