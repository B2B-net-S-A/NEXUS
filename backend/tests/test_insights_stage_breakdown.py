"""GET /api/insights/recruitment/stage-breakdown — „Lejek po etapach”.

Tablica ma 6 kolumn, a statystyki muszą dalej liczyć każdy etap i odznakę:
etap szablonu bez własnego kodu („Umowa wysłana” = kod `new` + nazwa) ma
swój wiersz, „Zatrudnieni” zgadzają się z regułą D2 (widok kamieni, bez
wykluczonych placementów), a „kto zakończył” czyta `ended_by`, a przy jego
braku typ końca (odrzucenie = my, wycofanie = kandydat).

Baza testowa jest wspólna, więc liczby serwisu są zawężone do własnych
rekrutacji (`job_ids`), a okno leży w roku, którego nie używa nikt inny.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.job import Job, JobStatus, RemotePolicy
from app.models.pipeline_template import (
    PipelineStageDef,
    PipelineTemplate,
    RejectionReason,
    StageCategoryEnum,
    TerminalType,
)
from app.models.placement_exclusion import PlacementExclusion
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.models.recruitment_process import ProcessStatus, RecruitmentProcess
from app.models.user import User, UserRole
from app.services import board_stage_badges as badges
from app.services.insights_stage_breakdown import (
    KEY_COLUMN,
    ROWS,
    compute_stage_breakdown,
    reason_label,
    stage_key,
    summarize_closed_by,
)

FIXTURE = (
    Path(__file__).resolve().parents[2]
    / "frontend/src/lib/__fixtures__/board-stage-cases.json"
)
CASES = json.loads(FIXTURE.read_text(encoding="utf-8"))["cases"]

_YEAR = 1987
WINDOW_START = datetime(_YEAR, 3, 1, tzinfo=timezone.utc)
WINDOW_END = datetime(_YEAR, 4, 1, tzinfo=timezone.utc)


def _at(month: int, day: int) -> datetime:
    return datetime(_YEAR, month, day, 12, 0, tzinfo=timezone.utc)


# ── Reguła klucza = reguła kolumn Tablicy ────────────────────────────────────


@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
def test_stage_key_lands_in_the_same_board_column(case: dict) -> None:
    key = stage_key(case["name"], case["stage"], category=case["category"])
    expected = badges.board_column_for(
        case["name"], case["stage"], category=case["category"]
    )
    assert KEY_COLUMN[key] == expected


def test_every_badge_named_in_the_fixture_has_its_own_row() -> None:
    row_keys = {row.key for row in ROWS}
    name_badges = {
        badges.stage_badge_kind(c["name"])
        for c in CASES
        if badges.stage_badge_kind(c["name"]) is not None
    }
    assert name_badges <= row_keys


def test_contract_sent_is_a_row_although_its_code_is_new() -> None:
    assert stage_key("Umowa wysłana", "new", category="external") == "contract_sent"
    assert stage_key("Lista rezerwowa", "new") == "__reserve"
    assert (
        stage_key("Wycofany", "new", category="terminal", terminal_type="withdrawn")
        == "__closed"
    )


def _reason(label: str, count: int, kind: str = "reason", details=None) -> dict:
    return {"label": label, "count": count, "kind": kind, "details": details or []}


def test_single_free_text_goes_to_other_and_sums_match() -> None:
    groups = [
        {"who": "client", "reason_name": None, "reason_note": "Brak EN", "count": 2},
        {
            "who": "client",
            "reason_name": None,
            "reason_note": "Jan był miły",
            "count": 1,
        },
        {"who": "client", "reason_name": None, "reason_note": "brak en", "count": 1},
        {"who": "recruiter", "reason_name": "Po CV", "count": 1, "reason_note": None},
    ]
    result = summarize_closed_by(groups)
    by_key = {g["key"]: g for g in result}
    assert [g["key"] for g in result] == [
        "candidate",
        "recruiter",
        "delivery_lead",
        "client",
    ]
    assert by_key["client"]["count"] == 4
    # Wielkość liter nie rozdziela powodu; jednorazowy wpis idzie do „Inne”.
    assert by_key["client"]["top_reasons"] == [
        _reason("Brak EN", 3),
        _reason("Inne", 1, "other", ["Jan był miły"]),
    ]
    assert by_key["recruiter"]["top_reasons"] == [_reason("Po CV", 1)]
    assert by_key["delivery_lead"] == {
        "key": "delivery_lead",
        "label": "Odrzucony przez DL",
        "count": 0,
        "top_reasons": [],
    }
    for group in result:
        assert sum(r["count"] for r in group["top_reasons"]) == group["count"]


def test_catalog_codes_get_polish_labels_and_legacy_means_no_reason() -> None:
    groups = [
        {"who": "candidate", "reason_name": "legacy_unknown", "count": 6},
        {"who": "candidate", "reason_name": "counter_offer", "count": 3},
        {"who": "candidate", "reason_name": "lost_interest", "count": 2},
        # Zaślepka importu z notatką z Traffita — liczy się notatka.
        {
            "who": "candidate",
            "reason_name": "legacy_unknown",
            "reason_note": "Rezygnacja przez Kandydata",
            "count": 2,
        },
        {"who": "recruiter", "reason_name": None, "reason_note": None, "count": 4},
        # Katalogowe „Inne (rejected)” idzie do zbiorczego „Inne”.
        {"who": "recruiter", "reason_name": "Inne (rejected)", "count": 2},
    ]
    by_key = {g["key"]: g for g in summarize_closed_by(groups)}
    assert by_key["candidate"]["top_reasons"] == [
        _reason("Kontroferta od obecnego pracodawcy", 3),
        _reason("Rezygnacja przez Kandydata", 2),
        _reason("Stracił zainteresowanie", 2),
        _reason("Bez podanego powodu", 6, "none"),
    ]
    assert by_key["recruiter"]["top_reasons"] == [
        _reason("Inne", 2, "other", ["Inne (z listy powodów) (2)"]),
        _reason("Bez podanego powodu", 4, "none"),
    ]
    labels = {r["label"] for g in by_key.values() for r in g["top_reasons"]}
    assert not labels & {"legacy_unknown", "counter_offer", "lost_interest"}


@pytest.mark.parametrize(
    ("code", "label"),
    [
        ("accepted_other_offer", "Przyjął inną ofertę"),
        ("counter_offer", "Kontroferta od obecnego pracodawcy"),
        ("personal_reasons", "Powody osobiste"),
        ("lost_interest", "Stracił zainteresowanie"),
        ("salary_mismatch", "Rozbieżność oczekiwań finansowych"),
        ("process_too_long", "Za długi proces"),
        ("Inne (rejected)", "Inne"),
        ("legacy_unknown", None),
        ("  ", None),
        ("Za wysoka stawka", "Za wysoka stawka"),
    ],
)
def test_reason_label(code: str, label: str | None) -> None:
    assert reason_label(code) == label


def test_reasons_beyond_the_top_three_fold_into_other() -> None:
    groups = [
        {"who": "client", "reason_name": f"Powód {i}", "count": 10 - i}
        for i in range(5)
    ] + [{"who": "client", "reason_name": None, "reason_note": "Jednorazowy"}]
    groups[-1]["count"] = 1
    by_key = {g["key"]: g for g in summarize_closed_by(groups)}
    reasons = by_key["client"]["top_reasons"]
    assert [r["label"] for r in reasons] == ["Powód 0", "Powód 1", "Powód 2", "Inne"]
    assert reasons[-1] == _reason(
        "Inne", 7 + 6 + 1, "other", ["Powód 3 (7)", "Powód 4 (6)", "Jednorazowy"]
    )
    assert sum(r["count"] for r in reasons) == by_key["client"]["count"]


# ── Liczby z prawdziwej bazy ─────────────────────────────────────────────────


async def _seed_world() -> dict[str, Any]:
    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        cli = Client(name=f"StageBreakdown-{tag}")
        tpl = PipelineTemplate(name=f"Etapy {tag}")
        db.add_all([cli, tpl])
        await db.flush()
        dz = PipelineStageDef(
            template_id=tpl.id,
            name="Przepuszczony przez DZ",
            order=1,
            category=StageCategoryEnum.internal,
        )
        sent = PipelineStageDef(
            template_id=tpl.id,
            name="Umowa wysłana",
            order=2,
            category=StageCategoryEnum.external,
        )
        reason = RejectionReason(
            template_id=tpl.id,
            name=f"Za wysoka stawka {tag}",
            category=TerminalType.rejected,
        )
        # DB wymaga powodu przy wycofaniu (ck_candidate_stages_withdrawn_requires_reason).
        gone = RejectionReason(
            template_id=tpl.id,
            name=f"Inna oferta {tag}",
            category=TerminalType.withdrawn,
        )
        job_a = Job(
            title=f"Etapy A {tag}",
            location="Warszawa",
            status=JobStatus.published,
            remote_policy=RemotePolicy.hybrid,
            client_id=cli.id,
        )
        job_b = Job(
            title=f"Etapy B {tag}",
            location="Warszawa",
            status=JobStatus.closed,
            remote_policy=RemotePolicy.hybrid,
            client_id=cli.id,
        )
        legacy = RejectionReason(
            template_id=tpl.id,
            name="legacy_unknown",
            category=TerminalType.withdrawn,
        )
        db.add_all([dz, sent, reason, gone, legacy, job_a, job_b])
        await db.flush()

        cands = []
        for i in range(14):
            c = Candidate(
                name=f"Etap{i}",
                lastname=f"Test-{tag}",
                email=f"stage-bd-{tag}-{i}@example.com",
            )
            db.add(c)
            cands.append(c)
        await db.flush()
        c = [x.id for x in cands]

        def row(cand: int, job: int, stage: PipelineStage, when: datetime, **kw):
            db.add(
                CandidateStage(
                    candidate_id=cand, job_id=job, stage=stage, moved_at=when, **kw
                )
            )

        a, b = job_a.id, job_b.id
        # c0: przez weryfikację, DZ, wysyłkę CV do „Umowa wysłana” (kod `new`).
        row(c[0], a, PipelineStage.new, _at(3, 2))
        row(c[0], a, PipelineStage.verified, _at(3, 3))
        row(c[0], a, PipelineStage.interview, _at(3, 4), stage_def_id=dz.id)
        row(c[0], a, PipelineStage.cv_sent, _at(3, 5))
        row(c[0], a, PipelineStage.new, _at(3, 6), stage_def_id=sent.id)
        # c1: dodany w lutym (poza oknem), zweryfikowany w marcu.
        row(c[1], a, PipelineStage.new, _at(2, 1))
        row(c[1], a, PipelineStage.verified, _at(3, 10))
        # c2: odrzucony bez `ended_by` → „odrzucony przez nas”, powód z katalogu.
        row(c[2], a, PipelineStage.new, _at(3, 2))
        row(c[2], a, PipelineStage.rejected, _at(3, 8), rejection_reason_id=reason.id)
        # c3: wycofany bez `ended_by` → „zrezygnował”.
        row(c[3], a, PipelineStage.new, _at(3, 2))
        row(c[3], a, PipelineStage.withdrawn, _at(3, 9), rejection_reason_id=gone.id)
        # c4, c5: odrzuceni przez klienta z tym samym opisem.
        for idx in (4, 5):
            row(c[idx], a, PipelineStage.new, _at(3, 2))
            row(
                c[idx],
                a,
                PipelineStage.rejected,
                _at(3, 11),
                ended_by="client",
                rejection_note="Brak angielskiego",
            )
        # c6: zatrudniony, potem onboarding.
        row(c[6], a, PipelineStage.hired, _at(3, 20))
        row(c[6], a, PipelineStage.onboarding, _at(3, 21))
        # c7: przepięty z innej rekrutacji.
        row(c[7], a, PipelineStage.new, _at(3, 15))
        db.add(
            RecruitmentProcess(
                candidate_id=c[7],
                job_id=a,
                client_id=cli.id,
                status=ProcessStatus.open,
                entry_source="reassign",
                opened_at=_at(3, 15),
            )
        )
        # c8: rekrutacja zamknięta — liczy się do „Doszło”, nie do „Teraz”.
        row(c[8], b, PipelineStage.new, _at(3, 2))
        row(c[8], b, PipelineStage.cv_sent, _at(3, 4))
        # c9: zatrudnienie wykluczone (masowa rejestracja) — poza D2.
        row(c[9], a, PipelineStage.hired, _at(3, 22))
        db.add(
            PlacementExclusion(candidate_id=c[9], job_id=a, reason="admin_bulk_no_cv")
        )
        # c10: wszystko przed oknem — nie może wpaść nigdzie w „Doszło”.
        row(c[10], a, PipelineStage.new, _at(1, 5))
        row(c[10], a, PipelineStage.cv_sent, _at(1, 6))
        # c11: odrzucenie bez `ended_by`, ale powód z Traffita mówi, że to
        # kandydat odrzucił ofertę → „zrezygnował”, nie „odrzucony przez nas”.
        row(
            c[11],
            a,
            PipelineStage.rejected,
            _at(3, 12),
            rejection_note="Odrzucenie oferty przez Kandydata",
        )
        # c12: wycofanie z zaślepką importu bez notatki → „Bez podanego powodu”.
        row(
            c[12], a, PipelineStage.withdrawn, _at(3, 12), rejection_reason_id=legacy.id
        )
        # c13: klient, jednorazowy wpis ręczny → „Inne”.
        row(
            c[13],
            a,
            PipelineStage.rejected,
            _at(3, 12),
            ended_by="client",
            rejection_note="Za daleko do biura",
        )
        await db.commit()
        return {"job_a": a, "job_b": b, "reason": reason.name, "gone": gone.name}


@pytest.mark.asyncio
async def test_breakdown_counts_every_stage_and_badge() -> None:
    world = await _seed_world()
    async with AsyncSessionLocal() as db:
        result = await compute_stage_breakdown(
            db,
            start=WINDOW_START,
            end=WINDOW_END,
            job_ids=[world["job_a"], world["job_b"]],
        )

    rows = {r["key"]: r for r in result["rows"]}
    assert [r["key"] for r in result["rows"]] == [row.key for row in ROWS]
    reached = {k: r["reached"] for k, r in rows.items()}
    assert reached == {
        # c0, c2–c9, c11–c13 — c1 i c10 zaczęli przed oknem.
        "added": 12,
        "reassign": 1,
        "verified": 2,
        "dz": 1,
        "cpro": 0,
        "cv_sent": 2,
        "prep": 0,
        "client_interview": 0,
        "after_interview": 0,
        "acceptance": 0,
        "contract_sent": 1,
        "contract_signed": 0,
        # D2: c6; wykluczone zatrudnienie c9 się nie liczy.
        "hired": 1,
        "onboarding": 1,
    }

    now = {k: r["now"] for k, r in rows.items()}
    # c9 stoi na „hired” (kolumna Zatrudniony), c10 na „CV wysłane”.
    assert now["added"] == 1  # c7
    assert now["reassign"] == 1
    assert now["verified"] == 1  # c1
    assert now["contract_sent"] == 1  # c0
    assert now["onboarding"] == 1  # c6
    assert now["hired"] == 1  # c9
    assert now["cv_sent"] == 1  # c10; c8 jest w rekrutacji zamkniętej
    assert now["dz"] == 0

    assert rows["added"]["column"] == "new" and rows["added"]["is_main"] is True
    assert rows["contract_sent"]["column_label"] == "Umowa"

    closed = {g["key"]: g for g in result["closed_by"]}
    assert closed["recruiter"]["count"] == 1
    assert closed["recruiter"]["top_reasons"] == [_reason(world["reason"], 1)]
    assert closed["candidate"]["count"] == 3  # c3, c11, c12
    assert closed["candidate"]["top_reasons"] == [
        _reason(world["gone"], 1),
        _reason("Inne", 1, "other", ["Odrzucenie oferty przez Kandydata"]),
        _reason("Bez podanego powodu", 1, "none"),
    ]
    assert closed["client"]["count"] == 3
    assert closed["client"]["top_reasons"] == [
        _reason("Brak angielskiego", 2),
        _reason("Inne", 1, "other", ["Za daleko do biura"]),
    ]
    assert closed["delivery_lead"]["count"] == 0
    assert set(result["definitions"]) == {"reached", "now"}


# ── API ──────────────────────────────────────────────────────────────────────


async def _login(client: AsyncClient, role: UserRole) -> dict[str, str]:
    unique = uuid.uuid4().hex[:8]
    email = f"stage-bd-{role.value}-{unique}@example.com"
    password = f"T3st_{unique}!Etapy"
    async with AsyncSessionLocal() as db:
        db.add(
            User(
                email=email,
                name=f"Etapy {unique}",
                password_hash=hash_password(password),
                role=role,
                is_active=True,
            )
        )
        await db.commit()
    resp = await client.post(
        "/api/auth/login", json={"email": email, "password": password}
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


@pytest_asyncio.fixture
async def fx_client() -> AsyncClient:
    from app.core.rate_limit import limiter as _limiter
    from app.main import app

    _limiter.enabled = False
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=True),
        base_url="http://testserver",
    ) as c:
        yield c


@pytest.mark.asyncio
async def test_endpoint_requires_login(fx_client: AsyncClient) -> None:
    resp = await fx_client.get("/api/insights/recruitment/stage-breakdown")
    assert resp.status_code in (401, 403)


@pytest.mark.asyncio
async def test_endpoint_returns_rows_for_a_recruiter(fx_client: AsyncClient) -> None:
    headers = await _login(fx_client, UserRole.recruiter)
    resp = await fx_client.get(
        "/api/insights/recruitment/stage-breakdown",
        headers=headers,
        params={
            "period": "custom",
            "date_from": f"{_YEAR}-03-01",
            "date_to": f"{_YEAR}-03-31",
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["period"]["start"].startswith(f"{_YEAR}-03-01")
    assert [r["key"] for r in body["rows"]] == [row.key for row in ROWS]
    assert [g["key"] for g in body["closed_by"]] == [
        "candidate",
        "recruiter",
        "delivery_lead",
        "client",
    ]


@pytest.mark.asyncio
async def test_endpoint_rejects_a_bad_period(fx_client: AsyncClient) -> None:
    headers = await _login(fx_client, UserRole.admin)
    resp = await fx_client.get(
        "/api/insights/recruitment/stage-breakdown",
        headers=headers,
        params={"period": "custom", "date_from": f"{_YEAR}-03-01"},
    )
    assert resp.status_code == 422
