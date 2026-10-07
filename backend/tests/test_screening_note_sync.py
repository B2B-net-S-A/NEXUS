"""Odpowiedzi z notatek do arkuszy screeningu (decyzje Artura 07.10.2026).

* ``map_note_answers`` — przypięcie odpowiedzi z karty do pytań Championa:
  po treści (≥ 0,5, przewaga ≥ 0,1, jeden do jednego), po numerze tylko przy
  komplecie i zgodnej numeracji; szara strefa i konflikty pomijane;
* ``is_sync_owned`` / ``plan_rows`` — automat poprawia tylko arkusz z samych
  odpowiedzi ``note_sync``, ludzkiego nie dotyka;
* ``sync_pair`` (z bazą): create → noop → update kopii → clear, arkusz
  człowieka zostaje, notatka sprzed bieżącej próby nie zasila arkusza, data
  i autor z notatki, bez ``Activity screening_answered``;
* zapis człowieka zamienia ``note_sync`` na ``note_import``;
* uzupełnienie historii: próba nic nie pisze, zapis jest idempotentny,
  zły ``expected`` = 409.

Dane fikcyjne.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.schemas.champion import ScreeningAnswers
from app.services import screening_note_backfill as backfill
from app.services import screening_note_sync as sync

QUESTIONS = {
    "q1": "Jak wygląda Twoje doświadczenie z Kubernetes w produkcji?",
    "q2": "Czy pracowałeś z Apache Kafka?",
    "q3": "Jaki jest Twój okres wypowiedzenia?",
}


def _item(number, question, answer):
    return {"number": number, "question": question, "answer": answer}


# ── map_note_answers ────────────────────────────────────────────────────────


def test_content_match_ignores_numbering_and_polish_letters():
    result = sync.map_note_answers(
        QUESTIONS,
        [
            _item(1, "Czy pracowales z Apache Kafka", "Tak, 3 lata."),
            _item(2, "Jaki jest twoj okres wypowiedzenia?", "Miesiąc."),
        ],
    )

    assert [(m.question_id, m.response, m.how) for m in result.matches] == [
        ("q2", "Tak, 3 lata.", "content"),
        ("q3", "Miesiąc.", "content"),
    ]
    assert result.by_content == 2 and result.by_number == 0


def test_number_maps_only_a_complete_consistent_list():
    items = [
        _item(1, "", "Dwa lata na EKS."),
        _item(2, "Czy pracowałeś z Apache Kafka?", "Tak."),
        _item(3, "", "Miesiąc."),
    ]

    result = sync.map_note_answers(QUESTIONS, items)

    assert [(m.question_id, m.how) for m in result.matches] == [
        ("q1", "number"),
        ("q2", "content"),
        ("q3", "number"),
    ]


def test_number_is_not_used_when_counts_differ():
    result = sync.map_note_answers(
        QUESTIONS, [_item(1, "", "Dwa lata."), _item(2, "", "Tak.")]
    )

    assert result.matches == ()
    assert result.skipped == {"no_text": 2}


def test_number_contradicting_a_content_match_disables_numbering():
    # Pozycja 1 to po treści pytanie q2 — numeracja notatki przeczy profilowi.
    items = [
        _item(1, "Czy pracowałeś z Apache Kafka?", "Tak."),
        _item(2, "", "Dwa lata."),
        _item(3, "", "Miesiąc."),
    ]

    result = sync.map_note_answers(QUESTIONS, items)

    assert [(m.question_id, m.how) for m in result.matches] == [("q2", "content")]
    assert result.skipped == {"no_text": 2}


def test_gray_zone_is_skipped_even_with_numbers():
    gray = "Kubernetes?"
    score = sync.match_score(gray, QUESTIONS["q1"])
    assert sync.GRAY_MIN <= score < sync.CONTENT_MIN, score

    result = sync.map_note_answers(
        QUESTIONS,
        [_item(1, gray, "Trochę."), _item(2, "", "Tak."), _item(3, "", "Miesiąc.")],
    )

    assert "q1" not in [m.question_id for m in result.matches]
    assert result.skipped.get("gray") == 1


def test_question_about_a_different_keyword_is_not_matched():
    # Wspólna reszta zdania: „AWS” i „Azure” mają podobieństwo 0,90.
    questions = {
        "q1": "Czy masz doświadczenie z Azure?",
        "q2": "Jaki jest Twój okres wypowiedzenia?",
    }
    assert sync.similarity("Czy masz doświadczenie z AWS?", questions["q1"]) > 0.8

    result = sync.map_note_answers(
        questions, [_item(1, "Czy masz doświadczenie z AWS?", "Nie")]
    )

    assert result.matches == ()
    assert result.skipped == {"different": 1}


def test_note_question_shortened_or_with_a_remark_still_matches():
    assert sync.match_score("Czy pracowałeś z Kafką", QUESTIONS["q2"]) >= (
        sync.CONTENT_MIN
    )
    assert (
        sync.match_score(
            "Czy pracowałeś z Apache Kafka? (min. 2 lata)", QUESTIONS["q2"]
        )
        >= sync.CONTENT_MIN
    )
    assert sync.match_score("Doświadczenie z Kubernetes", QUESTIONS["q1"]) >= (
        sync.CONTENT_MIN
    )


@pytest.mark.parametrize(
    ("champion", "note"),
    [
        ("Jaki poziom języka niemieckiego?", "Jaki poziom języka?"),
        ("Doświadczenie z AWS?", "Doświadczenie?"),
        ("Czy znasz Kafkę i RabbitMQ?", "Czy znasz Kafkę?"),
        ("Czy znasz Kafkę?", "Czy znasz Kafkę i RabbitMQ?"),
        ("Czy znasz Power BI?", "Czy znasz PowerShell?"),
        ("Czy znasz Terraform?", "Czy znasz Terragrunt?"),
        ("Czy znasz PostgreSQL?", "Czy znasz PostGIS?"),
        ("Doświadczenie z Microsoft?", "Doświadczenie z microservices?"),
        ("Czy znasz Selenium?", "Czy znasz Selenide?"),
    ],
)
def test_question_missing_a_specific_word_is_not_the_same_question(champion, note):
    # Przegląd #2059: wspólny początek słowa albo brak nazwy technologii /
    # języka w krótszym pytaniu przypinał odpowiedź do innego pytania.
    assert sync.match_score(note, champion) == 0.0
    result = sync.map_note_answers({"q1": champion}, [_item(1, note, "tak")])
    assert result.matches == ()


@pytest.mark.parametrize(
    ("left", "right", "same"),
    [
        ("kafka", "kafke", True),
        ("kubernetes", "kubernetesem", True),
        ("jezyka", "jezykiem", True),
        ("doswiadczenie", "doswiadczenia", True),
        ("terraform", "terragrunt", False),
        ("postgresql", "postgis", False),
        ("selenium", "selenide", False),
        ("powershell", "power", False),
    ],
)
def test_same_word_means_same_stem_with_an_inflection_ending(left, right, same):
    assert sync._same_word(left, right) is same


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        # Ostatnia odpowiedź karty połyka notatkę wewnętrzną — ucinamy.
        (
            "Certified Pega System Architect\nNOTATKA\nByła w procesie u innego klienta",
            "Certified Pega System Architect",
        ),
        ("Tak, 5 lat.\nRed flags brak", "Tak, 5 lat."),
        (
            "Tak, regularnie.\nNotatka dodatkowa\nAktualnie pracuje w X",
            "Tak, regularnie.",
        ),
        (
            "Pracuje z Kafką.\n@Anna Nowak notatka i motywacja w odpowiedzi",
            "Pracuje z Kafką.",
        ),
        (
            "Webpack, Gulp\n4. Czy korzystałeś z preprocesorów CSS?\nTAK",
            "Webpack, Gulp",
        ),
        (
            "Spore doświadczenie z bazami\n3. Jakie masz doświadczenie w tworzeniu aplikacji\nfrontendowych? Angular",
            "Spore doświadczenie z bazami",
        ),
        ("Monitoring w Grafanie\nczekam na cv i stawkę", "Monitoring w Grafanie"),
        (
            "Tabele w fundacji\n3. : Jak podchodzisz do UX\ndla formularzy?",
            "Tabele w fundacji",
        ),
        ("Diagramy ERD\np3 Z którymi technologiami pracowałeś", "Diagramy ERD"),
        # Wyliczenie w odpowiedzi zostaje.
        (
            "Bazy:\n3) relacyjne - postgres, oracle",
            "Bazy:\n3) relacyjne - postgres, oracle",
        ),
        # Kwota albo para stawek po ucięciu — odpowiedź nie trafia do klienta.
        ("Projekt w banku.\nkosztorys:\n138/90", "Projekt w banku."),
        ("Robił to w projekcie za 90 zł/h", ""),
        ("Stawka 140/110", ""),
        # Powtórzone pytanie w innym języku zamiast odpowiedzi.
        ("[PL] Jak wykorzystujesz narzędzia AI? Na co dzień Copilot", ""),
        # Zwykłe odpowiedzi bez zmian (także „dostępność” jako słowo).
        (
            "Dbam o dostępność (accessibility) i WCAG.",
            "Dbam o dostępność (accessibility) i WCAG.",
        ),
        ("Tak\n2 lata komercyjnie", "Tak\n2 lata komercyjnie"),
    ],
)
def test_client_safe_response_cuts_internal_sections(raw, expected):
    assert sync.client_safe_response(raw) == expected


def test_answer_with_only_internal_content_is_skipped():
    result = sync.map_note_answers(
        QUESTIONS,
        [_item(3, "Jaki jest Twój okres wypowiedzenia?", "Stawka 140/110")],
    )
    assert result.matches == ()
    assert result.skipped == {"internal": 1}


def test_questions_unlike_the_profile_are_not_mapped_by_number():
    # Profil zmieniony po notatce: trzy odpowiedzi na trzy INNE pytania.
    result = sync.map_note_answers(
        QUESTIONS,
        [
            _item(1, "Stawka?", "140"),
            _item(2, "Angielski?", "B2"),
            _item(3, "Dostępność?", "od zaraz"),
        ],
    )

    assert result.matches == ()
    assert result.skipped == {"different": 3}


def test_two_answers_claiming_one_question_are_both_dropped():
    result = sync.map_note_answers(
        QUESTIONS,
        [
            _item(1, "Czy pracowałeś z Apache Kafka?", "Tak."),
            _item(2, "Czy pracowałeś z Apache Kafką?", "Nie."),
        ],
    )

    assert result.matches == ()
    assert result.skipped == {"conflict": 2}


def test_empty_answers_are_skipped():
    result = sync.map_note_answers(
        QUESTIONS, [_item(1, "Czy pracowałeś z Apache Kafka?", "  ")]
    )

    assert result.matches == () and result.skipped == {"empty": 1}


def test_no_questions_or_no_items_maps_nothing():
    assert sync.map_note_answers({}, [_item(1, "x", "y")]).matches == ()
    assert sync.map_note_answers(QUESTIONS, []).matches == ()


# ── własność arkusza ────────────────────────────────────────────────────────


def _sync_sheet(**extra):
    return {
        "answers": [
            {"question_id": "q1", "response": "Tak.", "origin": "note_sync"},
        ],
        "overall_fit": "uncertain",
        **extra,
    }


def test_sheet_with_only_note_sync_answers_belongs_to_the_automat():
    assert sync.is_sync_owned(_sync_sheet())


@pytest.mark.parametrize(
    "sheet",
    [
        _sync_sheet(overall_fit="fit"),
        _sync_sheet(notes="Dobra komunikacja."),
        _sync_sheet(internal_note="pominięte"),
        _sync_sheet(
            experience_checks=[
                {"kind": "domains", "name": "Bankowość", "status": "confirmed"}
            ]
        ),
        {
            "answers": [
                {"question_id": "q1", "response": "Tak.", "origin": "note_sync"},
                {"question_id": "q2", "response": "Nie.", "origin": "manual"},
            ]
        },
        {
            "answers": [
                {
                    "question_id": "q1",
                    "response": "Tak.",
                    "origin": "note_sync",
                    "deal_breaker_hit": True,
                }
            ]
        },
        {
            "answers": [
                {"question_id": "q1", "response": "Tak.", "origin": "note_import"}
            ]
        },
        {"answers": []},
        None,
        {"answers": "zepsute"},
    ],
)
def test_any_human_trace_makes_the_sheet_human(sheet):
    assert not sync.is_sync_owned(sheet)


@pytest.mark.parametrize("sheet", [None, {}, {"answers": []}])
def test_blank_sheets(sheet):
    assert sync.is_blank(sheet)


def test_human_sheet_is_never_touched():
    human = {"answers": [{"question_id": "q1", "response": "Tak.", "origin": "manual"}]}
    desired = _sync_sheet()

    plan = sync.plan_rows([None, human], desired)

    assert (plan.action, plan.reason, plan.updates) == ("skip", "human_sheet", {})


def test_unreadable_sheet_is_not_touched():
    plan = sync.plan_rows([{"answers": "zepsute"}], _sync_sheet())

    assert (plan.action, plan.reason) == ("skip", "unreadable_sheet")


def test_plan_rows_create_update_clear_noop():
    desired = sync.build_sheet(
        QUESTIONS,
        [sync.AnswerMatch("q2", "Tak.", "content", 1.0)],
        note_at=datetime(2025, 3, 1, tzinfo=timezone.utc),
        author_id=7,
        previous=None,
    )

    created = sync.plan_rows([None, {"answers": []}], desired)
    assert created.action == "create" and set(created.updates) == {0}

    same = sync.plan_rows([desired, desired], desired)
    assert (same.action, same.updates) == ("noop", {})

    stale = _sync_sheet()
    updated = sync.plan_rows([None, stale], desired)
    assert updated.action == "update" and set(updated.updates) == {0, 1}

    cleared = sync.plan_rows([stale, None, stale], None, reason="no_answers")
    assert cleared.action == "clear" and cleared.updates == {0: None, 2: None}


def test_built_sheet_carries_note_date_author_and_question_text():
    at = datetime(2025, 3, 1, 9, 30, tzinfo=timezone.utc)

    sheet = ScreeningAnswers.model_validate(
        sync.build_sheet(
            QUESTIONS,
            [sync.AnswerMatch("q2", "Tak.", "content", 1.0)],
            note_at=at,
            author_id=7,
            previous=None,
        )
    )

    assert sheet.answered_at == at and sheet.answered_by == 7
    assert sheet.overall_fit == "uncertain"
    assert [(a.question_id, a.origin, a.question_text) for a in sheet.answers] == [
        ("q2", "note_sync", QUESTIONS["q2"])
    ]
    assert not sheet.answers[0].deal_breaker_hit


def test_human_save_turns_note_sync_into_note_import():
    sheet = ScreeningAnswers.model_validate(_sync_sheet())

    sync.humanize_origins(sheet)

    assert [a.origin for a in sheet.answers] == ["note_import"]


def test_sync_is_off_by_default():
    from app.core.config import Settings

    assert Settings.model_fields["SCREENING_NOTE_SYNC_ENABLED"].default is False


# ── z bazą (CI) ─────────────────────────────────────────────────────────────

NOTE_AT = datetime(2025, 3, 1, 9, 30, tzinfo=timezone.utc)


async def _world(*, attempt_started: datetime | None = None) -> dict:
    """Rekrutacja z trzema pytaniami, dwa wiersze etapu, notatka i karta."""
    from app.core.database import AsyncSessionLocal
    from app.core.security import hash_password
    from app.models.candidate import Candidate, CandidateStatus
    from app.models.client import Client
    from app.models.job import Job, JobStatus
    from app.models.note import Note, NoteType
    from app.models.recommendation_card import RecommendationCard
    from app.models.recruitment_pipeline import CandidateStage, PipelineStage
    from app.models.recruitment_process import ProcessStatus, RecruitmentProcess
    from app.models.user import User, UserRole

    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        author = User(
            email=f"note-sync-{tag}@example.com",
            password_hash=hash_password(f"T3st_{tag}!Sync"),
            name="Sync Recruiter",
            role=UserRole.recruiter,
            roles=["recruiter"],
            is_active=True,
        )
        cli = Client(name=f"NoteSyncClient-{tag}")
        cand = Candidate(
            name="Note",
            lastname=f"Sync-{tag}",
            email=f"note-sync-cand-{tag}@example.com",
            status=CandidateStatus("active"),
        )
        db.add_all([author, cli, cand])
        await db.flush()
        job = Job(
            title=f"Sync Rola {tag}",
            status=JobStatus.published,
            client_id=cli.id,
            champion_profile={
                "screening_questions": [
                    {"id": qid, "question": text} for qid, text in QUESTIONS.items()
                ]
            },
        )
        db.add(job)
        await db.flush()
        note = Note(
            content="P1: …",
            note_type=NoteType.general,
            candidate_id=cand.id,
            job_id=job.id,
            author_id=author.id,
            kind="card",
        )
        db.add(note)
        await db.flush()
        base = attempt_started or datetime(2025, 2, 1, tzinfo=timezone.utc)
        older = CandidateStage(
            candidate_id=cand.id,
            job_id=job.id,
            stage=PipelineStage.screening,
            moved_at=base + timedelta(days=1),
        )
        latest = CandidateStage(
            candidate_id=cand.id,
            job_id=job.id,
            stage=PipelineStage.verified,
            moved_at=base + timedelta(days=2),
        )
        db.add_all([older, latest])
        if attempt_started is not None:
            db.add(
                RecruitmentProcess(
                    candidate_id=cand.id,
                    job_id=job.id,
                    status=ProcessStatus.open,
                    attempt_no=2,
                    opened_at=attempt_started,
                )
            )
        db.add(
            RecommendationCard(
                candidate_id=cand.id,
                job_id=job.id,
                fields_notes={},
                fields_manual={},
                note_answers={
                    "items": [
                        _item(1, "", "Dwa lata na EKS."),
                        _item(2, "Czy pracowałeś z Apache Kafka?", "Tak, 3 lata."),
                        _item(3, "", "Miesiąc."),
                    ],
                    "note_id": note.id,
                    "at": NOTE_AT.isoformat(),
                },
            )
        )
        await db.commit()
        return {
            "candidate_id": cand.id,
            "job_id": job.id,
            "author_id": author.id,
            "author_email": author.email,
            "author_password": f"T3st_{tag}!Sync",
            "note_id": note.id,
            "older_id": older.id,
            "latest_id": latest.id,
        }


async def _sheets(world: dict) -> tuple:
    from app.core.database import AsyncSessionLocal
    from app.models.recruitment_pipeline import CandidateStage

    async with AsyncSessionLocal() as db:
        older = await db.get(CandidateStage, world["older_id"])
        latest = await db.get(CandidateStage, world["latest_id"])
        return older.screening_answers, latest.screening_answers


async def _set_sheet(stage_id: int, sheet) -> None:
    from app.core.database import AsyncSessionLocal
    from app.models.recruitment_pipeline import CandidateStage

    async with AsyncSessionLocal() as db:
        row = await db.get(CandidateStage, stage_id)
        row.screening_answers = sheet
        await db.commit()


async def _sync(world: dict) -> sync.PairPlan:
    from app.core.database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        plan = await sync.sync_pair(
            db, candidate_id=world["candidate_id"], job_id=world["job_id"]
        )
        await db.commit()
        return plan


async def _set_note_answers(world: dict, note_answers: dict) -> None:
    from app.core.database import AsyncSessionLocal
    from app.models.recommendation_card import RecommendationCard

    async with AsyncSessionLocal() as db:
        card = await db.scalar(
            select(RecommendationCard).where(
                RecommendationCard.candidate_id == world["candidate_id"],
                RecommendationCard.job_id == world["job_id"],
            )
        )
        card.note_answers = note_answers
        await db.commit()


async def _activities(world: dict, action: str) -> list:
    from app.core.database import AsyncSessionLocal
    from app.models.activity import Activity

    async with AsyncSessionLocal() as db:
        return list(
            (
                await db.scalars(
                    select(Activity).where(
                        Activity.entity_type == "candidate_stage",
                        Activity.entity_id.in_([world["older_id"], world["latest_id"]]),
                        Activity.action == action,
                    )
                )
            ).all()
        )


async def test_sync_creates_noops_updates_copies_and_clears(app_client: AsyncClient):
    world = await _world()

    created = await _sync(world)
    assert (created.action, created.stage_id) == ("create", world["latest_id"])
    older, latest = await _sheets(world)
    assert older is None
    sheet = ScreeningAnswers.model_validate(latest)
    assert [(a.question_id, a.origin) for a in sheet.answers] == [
        ("q1", "note_sync"),
        ("q2", "note_sync"),
        ("q3", "note_sync"),
    ]
    assert sheet.answered_by == world["author_id"]
    assert sheet.answered_at == NOTE_AT
    assert len(await _activities(world, sync.ACTIVITY_ACTION)) == 1
    # Statystyki zespołu liczą `screening_answered` — automat go nie pisze.
    assert await _activities(world, "screening_answered") == []

    assert (await _sync(world)).action == "noop"

    # Kopia arkusza automatu na starszym wierszu (ruch karty) idzie za zmianą.
    await _set_sheet(world["older_id"], latest)
    await _set_note_answers(
        world,
        {
            "items": [
                _item(2, "Czy pracowałeś z Apache Kafka?", "Nie, tylko RabbitMQ.")
            ],
            "note_id": world["note_id"],
            "at": NOTE_AT.isoformat(),
        },
    )
    updated = await _sync(world)
    assert updated.action == "update"
    older, latest = await _sheets(world)
    assert older == latest
    assert [a["response"] for a in latest["answers"]] == ["Nie, tylko RabbitMQ."]

    await _set_note_answers(world, {})
    cleared = await _sync(world)
    assert cleared.action == "clear"
    assert await _sheets(world) == (None, None)


async def test_sync_never_touches_a_human_sheet(app_client: AsyncClient):
    world = await _world()
    human = {
        "answers": [{"question_id": "q1", "response": "Rozmowa z rekruterem."}],
        "overall_fit": "fit",
    }
    await _set_sheet(world["older_id"], human)

    plan = await _sync(world)

    assert (plan.action, plan.reason) == ("skip", "human_sheet")
    older, latest = await _sheets(world)
    assert older == human and latest is None
    assert await _activities(world, sync.ACTIVITY_ACTION) == []


async def test_note_from_a_previous_attempt_does_not_fill_the_sheet(
    app_client: AsyncClient,
):
    world = await _world(attempt_started=NOTE_AT + timedelta(days=30))

    plan = await _sync(world)

    assert (plan.action, plan.reason) == ("noop", "previous_attempt")
    assert await _sheets(world) == (None, None)


async def test_human_save_takes_over_the_note_sheet(app_client: AsyncClient):
    world = await _world()
    await _sync(world)
    login = await app_client.post(
        "/api/auth/login",
        json={"email": world["author_email"], "password": world["author_password"]},
    )
    assert login.status_code == 200, login.text
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    _, latest = await _sheets(world)

    response = await app_client.post(
        f"/api/pipeline/stages/{world['latest_id']}/screening",
        json=latest,
        headers=headers,
    )

    assert response.status_code == 200, response.text
    _, saved = await _sheets(world)
    assert {a["origin"] for a in saved["answers"]} == {"note_import"}
    assert not sync.is_sync_owned(saved)
    # Teraz to arkusz człowieka — automat go nie poprawi.
    assert (await _sync(world)).reason == "human_sheet"


async def test_backfill_dry_run_writes_nothing_and_apply_is_idempotent(
    app_client: AsyncClient,
):
    from app.core.database import AsyncSessionLocal

    world = await _world()
    pair = {(world["candidate_id"], world["job_id"])}

    async with AsyncSessionLocal() as db:
        report = await backfill.plan(db, only_pairs=pair)
    assert report["to_change"] == 1 and report["actions"] == {"create": 1}
    assert report["answers"] == {"by_content": 1, "by_number": 2}
    assert report["samples"][0]["candidate_id"] == world["candidate_id"]
    assert await _sheets(world) == (None, None)

    async with AsyncSessionLocal() as db:
        applied = await backfill.apply(db, actor_user_id=None, only_pairs=pair)
    assert applied["counts"]["create"] == 1, applied
    _, latest = await _sheets(world)
    assert sync.is_sync_owned(latest)

    async with AsyncSessionLocal() as db:
        again = await backfill.apply(db, actor_user_id=None, only_pairs=pair)
    assert again["counts"]["create"] == 0 and again["counts"]["unchanged"] == 1


async def test_backfill_apply_requires_a_matching_expected(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
):
    from app.core.database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        await backfill._write_setting(
            db,
            backfill.DRY_RUN_KEY,
            {
                "dry_run": True,
                "to_change": 5,
                "finished_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        await db.commit()

    wrong = await app_client.post(
        "/api/admin/screening-note-backfill?dry_run=false&expected=4",
        headers=app_auth_headers,
    )
    missing = await app_client.post(
        "/api/admin/screening-note-backfill?dry_run=false",
        headers=app_auth_headers,
    )

    assert wrong.status_code == 409 and "5" in wrong.json()["detail"]
    assert missing.status_code == 409
    assert not backfill.is_running()


async def test_backfill_apply_requires_a_fresh_dry_run(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
):
    from app.core.database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        await backfill._write_setting(
            db,
            backfill.DRY_RUN_KEY,
            {
                "dry_run": True,
                "to_change": 5,
                "finished_at": (
                    datetime.now(timezone.utc) - timedelta(days=8)
                ).isoformat(),
            },
        )
        await db.commit()

    response = await app_client.post(
        "/api/admin/screening-note-backfill?dry_run=false&expected=5",
        headers=app_auth_headers,
    )

    assert response.status_code == 409
    assert "próbny" in response.json()["detail"]
