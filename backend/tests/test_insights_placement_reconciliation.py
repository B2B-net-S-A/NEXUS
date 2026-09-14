"""Uzgodnienie placementów: raport ma TŁUMACZYĆ rozjazd, nie go usuwać.

Cała wartość tego endpointu siedzi w wierszach, które są w jednej rodzinie
atrybucji i nie ma ich w drugiej. Test zasila obie rodziny tak, żeby powstały
wszystkie trzy kubełki, i sprawdza, że raport je rozróżnia.

Rok fixture'ów (2036, okno czerwiec–lipiec): baza testowa jest wspólna dla
przebiegu i nie jest czyszczona, więc rok zajęty przez sąsiada wraca jako
„regresja" w kodzie, którego nikt nie ruszał. `test_kanban_offer_response`
i `test_hiring_manager_feedback` też stoją na 2036 (kwiecień/maj) — okna się
nie nakładają, a testy wielu prób asertują RÓŻNICE, nie wartości bezwzględne.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.job import Job
from app.models.recruitment_pipeline import (
    CandidateStage,
    PipelineStage,
    VerificationStatus,
)
from app.models.recruitment_priority import PriorityOriginKind
from app.models.recruitment_process import ProcessStatus, RecruitmentProcess
from app.models.user import User, UserRole

T0 = datetime(2036, 6, 1, 9, 0, tzinfo=timezone.utc)
# Osobne okno (lipiec 2036) dla testów wielu prób — totale raportu są liczone
# z CAŁEGO okna, więc placementy z pozostałych testów nie mogą się do nich
# dosumować.
T_ATTEMPTS = datetime(2036, 7, 1, 9, 0, tzinfo=timezone.utc)


async def _seed_placement(db, *, kpi_eligible: bool, tag: str):
    """Jedna para (kandydat, oferta) doprowadzona do `hired`.

    ``kpi_eligible=False`` to jedyna dźwignia, jakiej potrzebuję: widok
    ``analytics_first_milestones`` nie ma ŻADNYCH filtrów, więc złapie ten
    placement zawsze, a ``VERIFIER_ANCHORED_CTE`` wymaga
    ``kpi_eligible IS TRUE`` — czyli ta sama para wypada z drugiej rodziny.
    Dokładnie ten mechanizm produkuje rozjazd na produkcji.
    """
    u = f"{tag}-{uuid.uuid4().hex[:8]}"
    mover = User(
        email=f"recon-{u}@example.com",
        password_hash=hash_password("x"),
        name=f"Mover {u}",
        role=UserRole.recruiter,
        is_active=True,
    )
    client = Client(name=f"Recon Client {u}")
    db.add_all([mover, client])
    await db.flush()

    job = Job(title=f"Recon Job {u}", client_id=client.id)
    cand = Candidate(name="Rekon", lastname=f"CIL-{u}")
    db.add_all([job, cand])
    await db.flush()

    db.add_all(
        [
            CandidateStage(
                candidate_id=cand.id,
                job_id=job.id,
                stage=PipelineStage.verified,
                moved_at=T0 + timedelta(days=1),
                moved_by=mover.id,
                verification_status=VerificationStatus.active,
            ),
            CandidateStage(
                candidate_id=cand.id,
                job_id=job.id,
                stage=PipelineStage.hired,
                moved_at=T0 + timedelta(days=4),
                moved_by=mover.id,
            ),
        ]
    )
    db.add(
        RecruitmentProcess(
            candidate_id=cand.id,
            job_id=job.id,
            client_id=client.id,
            attempt_no=1,
            status=ProcessStatus.open,
            origin_kind=PriorityOriginKind.assigned,
            opened_at=T0,
            kpi_eligible=kpi_eligible,
            credit_user_id=mover.id,
        )
    )
    await db.commit()
    return {"candidate_id": cand.id, "job_id": job.id, "mover_id": mover.id}


async def _seed_two_attempts(db, *, tag: str):
    """Jedna para (kandydat, oferta) z DWIEMA sklasyfikowanymi próbami.

    Każda próba ma własny proces (`attempt_no` 1 i 2), własną kotwicę
    `verified` i własne `hired` wewnątrz okna procesu, więc `credited`
    (UNION ALL po `process_id`) niesie dla tej pary DWA wiersze `hired`.
    Widok `analytics_first_milestones` ma dla niej dokładnie JEDEN wiersz.
    To jest kształt, który do 09.2026 mnożył wiersze raportu.
    """
    u = f"{tag}-{uuid.uuid4().hex[:8]}"
    mover = User(
        email=f"recon-{u}@example.com",
        password_hash=hash_password("x"),
        name=f"Mover {u}",
        role=UserRole.recruiter,
        is_active=True,
    )
    client = Client(name=f"Recon Client {u}")
    db.add_all([mover, client])
    await db.flush()

    job = Job(title=f"Recon Job {u}", client_id=client.id)
    cand = Candidate(name="Rekon", lastname=f"CIL-{u}")
    db.add_all([job, cand])
    await db.flush()

    t_attempt2 = T_ATTEMPTS + timedelta(days=10)
    db.add_all(
        [
            CandidateStage(
                candidate_id=cand.id,
                job_id=job.id,
                stage=PipelineStage.verified,
                moved_at=T_ATTEMPTS + timedelta(days=1),
                moved_by=mover.id,
                verification_status=VerificationStatus.active,
            ),
            CandidateStage(
                candidate_id=cand.id,
                job_id=job.id,
                stage=PipelineStage.hired,
                moved_at=T_ATTEMPTS + timedelta(days=4),
                moved_by=mover.id,
            ),
            CandidateStage(
                candidate_id=cand.id,
                job_id=job.id,
                stage=PipelineStage.verified,
                moved_at=t_attempt2 + timedelta(days=1),
                moved_by=mover.id,
                verification_status=VerificationStatus.active,
            ),
            CandidateStage(
                candidate_id=cand.id,
                job_id=job.id,
                stage=PipelineStage.hired,
                moved_at=t_attempt2 + timedelta(days=4),
                moved_by=mover.id,
            ),
        ]
    )
    # Najwyżej jeden OTWARTY proces pary (`ux_process_one_open`): pierwsza
    # próba jest zamknięta, druga otwarta. CTE wyklucza wyłącznie `voided`.
    for attempt_no, opened_at, proc_status in (
        (1, T_ATTEMPTS, ProcessStatus.closed),
        (2, t_attempt2, ProcessStatus.open),
    ):
        db.add(
            RecruitmentProcess(
                candidate_id=cand.id,
                job_id=job.id,
                client_id=client.id,
                attempt_no=attempt_no,
                status=proc_status,
                origin_kind=PriorityOriginKind.assigned,
                opened_at=opened_at,
                kpi_eligible=True,
                credit_user_id=mover.id,
            )
        )
    await db.commit()
    return {
        "candidate_id": cand.id,
        "job_id": job.id,
        "first_hired_at": T_ATTEMPTS + timedelta(days=4),
    }


async def _report(
    app_client,
    headers,
    *,
    date_from: str = "2036-06-01",
    date_to: str = "2036-06-30",
) -> dict:
    r = await app_client.get(
        "/api/insights/reconciliation/placements",
        params={
            "period": "custom",
            "date_from": date_from,
            "date_to": date_to,
        },
        headers=headers,
    )
    assert r.status_code == 200, r.text
    return r.json()


@pytest.mark.asyncio
async def test_report_separates_the_three_buckets(app_client, app_auth_headers):
    """Placement w obu rodzinach i placement tylko w widoku — rozróżnione.

    To jest cały sens tego endpointu. Gdyby raport pokazywał wyłącznie część
    wspólną (INNER JOIN), nie odpowiadałby na jedyne pytanie, które ludzie
    zadają: KTÓRYCH placementów brakuje po drugiej stronie.
    """
    async with AsyncSessionLocal() as db:
        both = await _seed_placement(db, kpi_eligible=True, tag="both")
        only_view = await _seed_placement(db, kpi_eligible=False, tag="viewonly")

    body = await _report(app_client, app_auth_headers)
    by_pair = {(i["candidate_id"], i["job_id"]): i for i in body["items"]}

    row_both = by_pair[(both["candidate_id"], both["job_id"])]
    assert row_both["in_first_hired"] is True
    assert row_both["in_verifier_anchored"] is True

    row_view = by_pair[(only_view["candidate_id"], only_view["job_id"])]
    assert row_view["in_first_hired"] is True
    assert row_view["in_verifier_anchored"] is False, (
        "kpi_eligible=False musi wypadać z rodziny verifier-anchored — "
        "jeśli nie wypada, raport nie pokazuje rozjazdu, tylko go ukrywa"
    )


@pytest.mark.asyncio
async def test_totals_add_up_to_the_row_list(app_client, app_auth_headers):
    """Nagłówek musi zgadzać się z sumą własnych wierszy.

    To jest dokładnie ten defekt, który raport ma tłumaczyć u innych:
    `/api/reports/recruitment` podaje 317 w nagłówku i 332 w wierszach tej
    samej odpowiedzi. Narzędzie do uzgadniania nie może mieć tej wady samo.
    """
    async with AsyncSessionLocal() as db:
        await _seed_placement(db, kpi_eligible=True, tag="sum-a")
        await _seed_placement(db, kpi_eligible=False, tag="sum-b")

    body = await _report(app_client, app_auth_headers)
    t = body["totals"]

    assert t["first_hired"] == t["in_both"] + t["only_first_hired"]
    assert t["verifier_anchored"] == t["in_both"] + t["only_verifier_anchored"]
    assert (
        len(body["items"])
        == t["in_both"] + t["only_first_hired"] + t["only_verifier_anchored"]
    )


@pytest.mark.asyncio
async def test_definition_codes_are_the_shared_constants(app_client, app_auth_headers):
    """Kody muszą być TYMI SAMYMI stringami co na ekranach liczących.

    Własny wariant (`..._by_mover`) dałby maszynowo „inna reguła" tam, gdzie
    reguła jest identyczna — czyli odwrotność tego, do czego to pole służy.
    """
    from app.services.metric_definitions import (
        FIRST_HIRED_PER_CANDIDATE_JOB,
        VERIFIER_ANCHORED_MILESTONES,
    )

    body = await _report(app_client, app_auth_headers)
    assert body["definitions"]["first_hired"] == FIRST_HIRED_PER_CANDIDATE_JOB
    assert body["definitions"]["verifier_anchored"] == VERIFIER_ANCHORED_MILESTONES


async def _viewer_headers() -> dict[str, str]:
    """Read-only `user` — widzi /insights (D7), ale nie dane kandydatów."""
    from app.core.security import create_access_token

    async with AsyncSessionLocal() as db:
        viewer = User(
            email=f"recon-viewer-{uuid.uuid4().hex[:8]}@example.com",
            password_hash=hash_password("x"),
            name="Recon Viewer",
            role=UserRole.user,
            roles=["user"],
            is_active=True,
            profile_completed=True,
        )
        db.add(viewer)
        await db.commit()
        await db.refresh(viewer)
        token = create_access_token(viewer.id, UserRole.user.value, roles=["user"])
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_viewer_without_candidate_access_gets_no_candidate_names(
    app_client, app_auth_headers
):
    """Nazwiska kandydatów to PII — rola `user` jest od nich odcięta.

    Raport nadal uzgadnia wiersze (``candidate_id`` zostaje), ale nie niesie
    imion i nazwisk, a flaga mówi, że to redakcja, nie brak danych.
    """
    async with AsyncSessionLocal() as db:
        seeded = await _seed_placement(db, kpi_eligible=True, tag="pii")

    body = await _report(app_client, await _viewer_headers())
    assert body["candidate_names_redacted"] is True
    row = next(
        i
        for i in body["items"]
        if (i["candidate_id"], i["job_id"])
        == (seeded["candidate_id"], seeded["job_id"])
    )
    assert row["candidate_name"] is None
    assert all(i["candidate_name"] is None for i in body["items"])

    # Rola z dostępem do kandydatów widzi ten sam wiersz z nazwiskiem.
    admin_body = await _report(app_client, app_auth_headers)
    assert admin_body["candidate_names_redacted"] is False
    admin_row = next(
        i
        for i in admin_body["items"]
        if (i["candidate_id"], i["job_id"])
        == (seeded["candidate_id"], seeded["job_id"])
    )
    assert admin_row["candidate_name"].startswith("Rekon CIL-pii-")


@pytest.mark.asyncio
async def test_rejects_a_broken_period_instead_of_guessing(
    app_client, app_auth_headers
):
    r = await app_client.get(
        "/api/insights/reconciliation/placements",
        params={"period": "custom"},  # custom bez dat
        headers=app_auth_headers,
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_repeated_attempt_is_one_row_with_attempt_count(
    app_client, app_auth_headers
):
    """Para z dwiema próbami = JEDEN wiersz raportu, nie dwa.

    `credited` niesie po wierszu `hired` na każdy proces pary, a widok ma
    jeden. Do 09.2026 złączenie mnożyło wiersz widoku przez każdą próbę,
    więc nagłówek `first_hired` twierdził, że pierwszych zatrudnień było
    tyle, ile prób. Liczba prób nie ginie — jedzie w `attempts`.
    """
    window = {"date_from": "2036-07-01", "date_to": "2036-07-31"}
    # Totale liczą CAŁE okno, a baza testowa nie jest czyszczona między
    # biegami — dlatego sprawdzamy PRZYROST po zasianiu, nie wartość bezwzględną.
    before = (await _report(app_client, app_auth_headers, **window))["totals"]

    async with AsyncSessionLocal() as db:
        pair = await _seed_two_attempts(db, tag="attempts")

    body = await _report(app_client, app_auth_headers, **window)
    rows = [
        i
        for i in body["items"]
        if (i["candidate_id"], i["job_id"]) == (pair["candidate_id"], pair["job_id"])
    ]
    assert len(rows) == 1, f"para z 2 próbami dała {len(rows)} wiersze"
    row = rows[0]
    assert row["in_first_hired"] is True
    assert row["in_verifier_anchored"] is True
    assert row["verifier_anchored"]["attempts"] == 2
    # Wiersz niesie NAJWCZEŚNIEJSZĄ próbę — tę samą datę, którą ma widok.
    assert row["verifier_anchored"]["reached_at"] == row["first_hired"]["reached_at"]

    t = body["totals"]
    delta = {key: t[key] - before[key] for key in t}
    assert delta["first_hired"] == 1, delta
    assert delta["verifier_anchored"] == 1, delta
    assert delta["in_both"] == 1, delta
    assert delta["only_first_hired"] == 0, delta
    assert delta["only_verifier_anchored"] == 0, delta
    # Surowe wiersze `credited` — liczba, którą sumują kafle — zostają widoczne.
    assert delta["verifier_anchored_attempts"] == 2, delta


@pytest.mark.asyncio
async def test_totals_come_from_the_whole_window_not_the_row_list(
    app_client, app_auth_headers, monkeypatch
):
    """Nagłówek liczy okno, nie obciętą listę.

    Sufit listy zbity do 1: druga para w tym samym oknie nie mieści się na
    liście, ale totale nadal ją liczą, a `truncated` mówi, że lista jest
    niepełna. Nagłówek liczony z listy mówiłby o raporcie, nie o oknie.
    """
    from app.api import insights_reconciliation as mod

    async with AsyncSessionLocal() as db:
        await _seed_two_attempts(db, tag="cap-a")
        await _seed_two_attempts(db, tag="cap-b")

    monkeypatch.setattr(mod, "_MAX_ROWS", 1)
    body = await _report(
        app_client,
        app_auth_headers,
        date_from="2036-07-01",
        date_to="2036-07-31",
    )
    assert len(body["items"]) == 1
    assert body["truncated"] is True
    t = body["totals"]
    assert t["first_hired"] >= 2
    assert t["verifier_anchored"] >= 2
    assert t["first_hired"] == t["in_both"] + t["only_first_hired"]
    assert t["verifier_anchored"] == t["in_both"] + t["only_verifier_anchored"]


def test_join_keys_tolerate_null_job_id():
    """Klucz `job_id` złączenia rodzin jest odporny na NULL po obu stronach.

    `NULL = NULL` nie łączy, więc para bez oferty rozpadałaby się na wiersz
    „tylko widok" i wiersz „tylko CTE". Dziś `candidate_stages.job_id` jest
    NOT NULL, więc takiej pary nie da się zasiać — test pilnuje kształtu
    złączenia, bo dane nie mogą. (`IS NOT DISTINCT FROM` odpada: Postgres nie
    zrobi po nim FULL JOIN.)
    """
    from app.api.insights_reconciliation import _FAMILIES_CTE

    assert "COALESCE(va.job_id, 0) = COALESCE(fh.job_id, 0)" in _FAMILIES_CTE
    assert "va.job_id       = fh.job_id" not in _FAMILIES_CTE
