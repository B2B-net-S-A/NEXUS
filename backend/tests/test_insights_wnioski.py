"""Zakładka „Wnioski”: reguły spraw, decyzje i kto co widzi.

Pod ochroną:

1. „Tak” zamyka sprawę, „Nie teraz” chowa na 30 dni, „Nie” do dwukrotnego wzrostu liczby.
2. Najwyżej 5 otwartych spraw i próg minimalnej próby.
3. Opis z cechą chronioną nie staje się powodem, cytatem ani przykładem.
4. Reguły ocenia się na 100 dodanych, nie samym udziałem.
5. Dostęp: admin i Head of Recruitment; reszta dostaje 403, zła decyzja 422.
"""

from __future__ import annotations

import os
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, select, text

from app.api import insights_wnioski as api
from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_today
from app.core.security import hash_password
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.insight_decision import InsightDecision
from app.models.job import Job, JobStatus, RemotePolicy
from app.models.pipeline_template import PipelineTemplate, RejectionReason, TerminalType
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.models.user import User, UserRole
from app.services import insights_wnioski as service
from app.services.insight_decisions_schema import TABLE_DDL

BACKEND = Path(__file__).resolve().parent.parent

# Po każdym oknie z innych testów (te kończą się przed 2110): reguły liczą od `since`
# do końca danych. Fikstura niżej sprząta to okno, więc ponowny bieg na tej samej bazie
# widzi tylko własne wiersze.
_WINDOW_BASE = datetime(2200, 1, 1, tzinfo=timezone.utc)
_slot = 0


def _window() -> datetime:
    global _slot
    _slot += 1
    return _WINDOW_BASE + timedelta(days=30 * _slot)


@pytest.fixture(autouse=True)
async def _clean_window() -> None:
    if not os.environ.get("DATABASE_URL"):
        return
    async with AsyncSessionLocal() as db:
        await db.execute(
            delete(CandidateStage).where(CandidateStage.moved_at >= _WINDOW_BASE)
        )
        await db.commit()


def _latest(state: str, *, count: int = 10, return_on: date | None = None) -> Any:
    return SimpleNamespace(state=state, count_at_decision=count, return_on=return_on)


def _case(
    key: str = "konkret", *, count: int = 10, enough: bool = True
) -> dict[str, Any]:
    return {
        "key": key,
        "number": "1 na 3",
        "number_note": "odmowy klienta bez powodu",
        "count": count,
        "sample": 100,
        "enough": enough,
        "title": "Sprawa",
        "why": "Dlaczego",
        "if_yes": "Jeśli tak",
        "risk": "Ryzyko",
        "certainty": "Policzone",
        "evidence": [],
    }


TODAY = date(2026, 11, 5)


def test_new_case_is_open() -> None:
    assert service.is_case_open(10, None, TODAY)


def test_approved_case_never_returns() -> None:
    assert not service.is_case_open(10_000, _latest(service.STATE_APPROVED), TODAY)


@pytest.mark.parametrize(
    ("offset", "expected"),
    [(-1, True), (0, True), (1, False)],
)
def test_later_returns_on_the_return_date(offset: int, expected: bool) -> None:
    latest = _latest(service.STATE_LATER, return_on=TODAY + timedelta(days=offset))
    assert service.is_case_open(10, latest, TODAY) is expected


@pytest.mark.parametrize(
    ("count", "expected"),
    [(10, False), (19, False), (20, True), (21, True)],
)
def test_rejected_returns_when_the_number_doubles(count: int, expected: bool) -> None:
    latest = _latest(service.STATE_REJECTED, count=10)
    assert service.is_case_open(count, latest, TODAY) is expected


def test_rejected_at_zero_returns_on_first_occurrence_of_two() -> None:
    latest = _latest(service.STATE_REJECTED, count=0)
    assert not service.is_case_open(1, latest, TODAY)
    assert service.is_case_open(2, latest, TODAY)


def test_at_most_five_open_cases_in_rule_order() -> None:
    cases = [_case(f"k{index}") for index in range(7)]
    assert [case["key"] for case in service.open_cases(cases, {}, TODAY)] == [
        "k0",
        "k1",
        "k2",
        "k3",
        "k4",
    ]


def test_case_below_minimum_sample_is_not_open() -> None:
    assert service.open_cases([_case(enough=False)], {}, TODAY) == []


def test_decision_dates_per_state() -> None:
    assert service.decision_dates(service.STATE_LATER, TODAY) == (
        TODAY + timedelta(days=30),
        None,
    )
    assert service.decision_dates(service.STATE_APPROVED, TODAY) == (
        None,
        TODAY + timedelta(days=30),
    )
    assert service.decision_dates(service.STATE_REJECTED, TODAY) == (None, None)


def test_window_starts_at_rejection_reasons_launch_then_slides() -> None:
    assert service.counted_from_label(service.counted_from(TODAY)) == "12.10"
    assert service.counted_from_label(service.counted_from(date(2027, 3, 1))) == "01.12"


@pytest.mark.parametrize(
    ("before", "after", "expected"),
    [
        ((10, 1000), (5, 1000), "Pomogło"),
        ((10, 1000), (8, 1000), "Nie widać poprawy"),
        ((10, 1000), (11, 1000), "Nie widać poprawy"),
        ((0, 1000), (0, 1000), "Nie widać poprawy"),
        ((10, 199), (1, 1000), "Za mało danych"),
        ((10, 1000), (1, 199), "Za mało danych"),
    ],
)
def test_rule_verdict(
    before: tuple[int, int], after: tuple[int, int], expected: str
) -> None:
    assert service.rule_verdict(before, after) == expected


def test_takeaway_says_share_misleads_when_per_100_does_not_fall() -> None:
    """Liczby z testu danych 04.11: udział spada z 38% do 10%, na 100 dodanych nie."""
    takeaway = service.rules_takeaway(
        [
            {
                "metric": "„Za drogo”",
                "before": {"hits": 21, "added": 2220, "refused": 55, "per_100": 0.9},
                "after": {"hits": 11, "added": 1015, "refused": 107, "per_100": 1.1},
            }
        ]
    )
    assert takeaway is not None
    assert "38%" in takeaway and "10%" in takeaway
    assert "0,9 i 1,1" in takeaway
    assert "po 30 dniach" in takeaway


def test_no_case_copy_suggests_holding_cvs() -> None:
    """42511: po piątej odmowie 3 osoby poszły dalej, więc wniosek niczego nie wstrzymuje."""
    copy = " ".join(
        f"{item.title} {item.measure} {item.yes_label}"
        for item in service.CASE_COPY.values()
    ).lower()
    assert "wstrzym" not in copy
    assert "nie wysyłaj" not in copy


def test_cv_comparison_counts_points_missing_from_the_final_cv() -> None:
    kept = "Prowadził migrację systemu rozliczeń do chmury"
    edited = "Prowadził migracje systemu rozliczen do chmury."
    gone = "Nasz kandydat ma najlepsze doświadczenie w tej dziedzinie"
    payload = {
        "why_points": [kept, gone],
        "experience": [{"responsibilities": [edited, "za krótki"]}],
        "other": gone,
    }
    final_html = f"<ul><li>{kept}</li><li><b>Prowadził</b> migrację systemu rozliczeń do chmury</li></ul>"
    assert service.compare_cv_points(payload, final_html) == {
        "why": [1, 2],
        "duties": [0, 1],
    }


def test_cv_summary_names_only_client_with_enough_points() -> None:
    at = datetime(2026, 11, 1, tzinfo=timezone.utc)
    rows = [
        (
            "Duży",
            {
                "responsibilities": [
                    f"Obowiązek numer {index} w projekcie dużym" for index in range(120)
                ]
            },
            "",
            at,
        ),
        (
            "Mały",
            {"responsibilities": ["Obowiązek w projekcie małym i bardzo ważnym"]},
            "",
            at,
        ),
    ]
    summary = service.summarize_cv(rows, recent=at)
    assert summary["cvs"] == 2
    assert summary["outlier"] == ("Duży", 120, 120)


def test_cv_count_for_rejected_takes_only_recent_cvs() -> None:
    """Stare CV nie mogą same podnosić liczby, od której zależy powrót „Nie”."""
    point = {
        "why_points": ["Nasz kandydat ma najlepsze doświadczenie w tej dziedzinie"]
    }
    recent = datetime(2026, 11, 1, tzinfo=timezone.utc)
    summary = service.summarize_cv(
        [
            ("Klient", point, "", recent - timedelta(days=1)),
            ("Klient", point, "", recent),
        ],
        recent=recent,
    )
    assert summary["why"] == [2, 2]
    assert summary["why_recent"] == 1


def _reason_row(
    client_id: int | None, client: str, is_other: bool, k: str, total: int
) -> Any:
    return SimpleNamespace(
        client_id=client_id, client=client, is_other=is_other, k=k, total=total
    )


def test_reasons_read_descriptions_without_losing_todays_view() -> None:
    built = service.build_reasons(
        [
            _reason_row(1, "Alfa", False, "Stawka", 10),
            _reason_row(1, "Alfa", True, "Stawka", 5),
            _reason_row(1, "Alfa", True, "Nieodczytane", 5),
            _reason_row(1, "Alfa", True, "KlientWybral", 30),
            _reason_row(2, "Beta", False, "Umiejetnosci", 5),
        ]
    )
    by_key = {row["key"]: row for row in built["why_out"]}
    assert built["total"] == 55
    assert by_key["rate"] == {
        "key": "rate",
        "reason": "Stawka",
        "today": 10,
        "after": 15,
    }
    assert by_key["unread"]["today"] == 40
    assert by_key["unread"]["after"] == 5
    assert by_key["client_silent"]["today"] == 0
    # Bez dolnej granicy próby klient nie trafia do tabeli.
    assert [row["client"] for row in built["heatmap"]] == ["Alfa"]
    assert sum(row["today"] for row in built["why_out"]) == sum(
        row["after"] for row in built["why_out"]
    )


def test_every_read_kind_has_a_bucket() -> None:
    kinds = {kind for bucket in service.WHY_OUT_BUCKETS for kind in bucket.kinds}
    read = {
        "Umiejetnosci", "Stawka", "Zatrudniony", "Tryb", "Rezygnacja", "BrakKontaktu", "Reszta",
        "BezOpisu", "KonfliktKlient", "KlientWybral", "KlientBezKonkretu", "FormaUmowy",
        "ZaWysokiPoziom", "Porzadki", "Nieodczytane",
    }  # fmt: skip
    assert read == kinds
    for kind in read:
        assert f"'{kind}'" in service._READ_CASE


def test_schema_has_one_source_and_a_mirror() -> None:
    entrypoint = (BACKEND / "entrypoint.sh").read_text(encoding="utf-8")
    assert "from app.services import insight_decisions_schema" in entrypoint
    assert "*_INSIGHT_DECISIONS_TABLE_DDL," in entrypoint
    # Bez numeru w ścieżce: pas migracji przepina numer, gdy inny PR wejdzie pierwszy.
    migration = next(
        (BACKEND / "alembic/versions").glob("*_insight_decisions.py")
    ).read_text(encoding="utf-8")
    assert "from app.services.insight_decisions_schema import TABLE_DDL" in migration


def test_model_columns_match_the_ddl() -> None:
    columns = {
        line.split()[0]
        for line in TABLE_DDL[0].splitlines()[1:]
        if line.split()[0] != ")"
    }
    assert columns == set(InsightDecision.__table__.columns.keys())


def test_deep_health_probes_the_table() -> None:
    main = (BACKEND / "app/main.py").read_text(encoding="utf-8")
    assert '("insight_decisions", InsightDecision)' in main


async def _rejection_setup(db) -> tuple[int, int, int]:
    tag = uuid.uuid4().hex[:6]
    client = Client(name=f"Wnioski-{tag}")
    template = PipelineTemplate(name=f"Wnioski {tag}")
    db.add_all([client, template])
    await db.flush()
    other = RejectionReason(
        template_id=template.id, name="Inne", category=TerminalType.rejected
    )
    db.add(other)
    await db.flush()
    return client.id, template.id, other.id


async def _job(db, client_id: int, title: str) -> int:
    job = Job(
        title=f"{uuid.uuid4().hex[:6]} {title}",
        location="Warszawa",
        status=JobStatus.published,
        remote_policy=RemotePolicy.hybrid,
        client_id=client_id,
    )
    db.add(job)
    await db.flush()
    return job.id


async def _refusal(db, job_id: int, reason_id: int, at: datetime, note: str) -> int:
    candidate = Candidate(
        name="Ola",
        lastname=f"Wnioski-{uuid.uuid4().hex[:6]}",
        email=f"wnioski-{uuid.uuid4().hex[:10]}@example.com",
    )
    db.add(candidate)
    await db.flush()
    db.add(
        CandidateStage(
            candidate_id=candidate.id,
            job_id=job_id,
            stage=PipelineStage.rejected,
            moved_at=at,
            rejection_reason_id=reason_id,
            ended_by="client",
            notes=note,
        )
    )
    await db.flush()
    return candidate.id


PROTECTED_NOTE = "Klient: osoba jest w ciąży, nie zatrudni"


@pytest.mark.asyncio
async def test_protected_description_never_becomes_reason_or_quote() -> None:
    since = _window()
    at = since + timedelta(days=1)
    async with AsyncSessionLocal() as db:
        client_id, _, reason_id = await _rejection_setup(db)
        protected_job = await _job(db, client_id, "Chroniona")
        for index in range(6):
            await _refusal(
                db,
                protected_job,
                reason_id,
                at + timedelta(hours=index),
                PROTECTED_NOTE,
            )
        repeat_job = await _job(db, client_id, "Powtarza się (42511)")
        for index in range(5):
            await _refusal(
                db,
                repeat_job,
                reason_id,
                at + timedelta(hours=index),
                "Z CPro: Profile not matching.",
            )
        await db.commit()

        case = await service._case_refusals(db, since)
        rows = (await db.execute(text(service._REASONS_SQL), {"since": since})).all()

    rendered = " ".join(
        [case["why"], case["if_yes"], case["risk"]]
        + [f"{row['label']} {row['value']}" for row in case["evidence"]]
    ).lower()
    assert "ciąż" not in rendered
    assert "profile not matching" in rendered
    assert "42511" in rendered
    # Tekstu chronionego nie ma też w liczniku „Powtarza się”.
    assert "dotyczy to 1 " in case["if_yes"]
    kinds = {(row.k, int(row.total)) for row in rows}
    assert ("Nieodczytane", 6) in kinds
    assert ("KlientBezKonkretu", 5) in kinds


@pytest.mark.parametrize(
    "note",
    [
        "Za stary na ten projekt",
        "Problem ze zdrowiem",
        "Narodowość nie ta",
        "Too old for this team",
        "Jest na L4, stawka za wysoka",
        "Macierzyński do marca, b2b",
        "CIĄŻA, stawka za wysoka",
        "Kraj objęty konfliktem, nie pasuje",
        "Kandydatka chora, nie pasuje",
        "Maternity leave, not a fit",
        "Russian speaker, not a match",
        "Białoruś, profile not matching",
        "Wschodni akcent, nie pasuje",
        "Ma 58 lat, za wysoka stawka",
    ],
)
@pytest.mark.asyncio
async def test_protected_words_outrank_every_other_reading(note: str) -> None:
    since = _window()
    async with AsyncSessionLocal() as db:
        client_id, _, reason_id = await _rejection_setup(db)
        job_id = await _job(db, client_id, "Słowa")
        await _refusal(db, job_id, reason_id, since + timedelta(days=1), note)
        await db.commit()
        rows = (await db.execute(text(service._REASONS_SQL), {"since": since})).all()
    assert [(row.k, int(row.total)) for row in rows] == [("Nieodczytane", 1)]


@pytest.mark.parametrize(
    ("reason", "kind"),
    [
        ("not_looking_for_work", "Rezygnacja"),
        ("client_conflict", "KonfliktKlient"),
        ("contract_form", "FormaUmowy"),
        ("no_contact", "BrakKontaktu"),
        ("client_no_reason", "KlientBezKonkretu"),
        ("client_chose_other", "KlientWybral"),
    ],
)
@pytest.mark.asyncio
async def test_reasons_from_the_rejection_window_land_in_their_groups(
    reason: str, kind: str
) -> None:
    """Powody z okna odrzucenia (#3040) to już wybór człowieka, nie „Pozostałe”."""
    since = _window()
    async with AsyncSessionLocal() as db:
        client_id, template_id, _ = await _rejection_setup(db)
        picked = RejectionReason(
            template_id=template_id, name=reason, category=TerminalType.rejected
        )
        db.add(picked)
        await db.flush()
        job_id = await _job(db, client_id, "Powód z okna")
        await _refusal(db, job_id, picked.id, since + timedelta(days=1), "")
        await db.commit()
        rows = (await db.execute(text(service._REASONS_SQL), {"since": since})).all()
    assert [(row.k, row.is_other) for row in rows] == [(kind, False)]


@pytest.mark.asyncio
async def test_rejected_case_compares_last_30_days_not_the_whole_window() -> None:
    """Przy stałym tempie liczba od początku rośnie sama, a ta z 30 dni nie."""
    since = _window()
    async with AsyncSessionLocal() as db:
        client_id, _, reason_id = await _rejection_setup(db)
        job_id = await _job(db, client_id, "Tempo")
        for days in (1, 2, 3, 4):
            await _refusal(db, job_id, reason_id, since + timedelta(days=days), "")
        await _refusal(db, job_id, reason_id, since + timedelta(days=40), "")
        await db.commit()
        client = (
            await db.execute(select(Client.name).where(Client.id == client_id))
        ).scalar_one()
        rows = (
            await db.execute(
                text(service._REFUSAL_TOTALS_SQL),
                {
                    "since": since,
                    "silent": service._SILENT_KINDS,
                    "recent": since + timedelta(days=30),
                },
            )
        ).all()
    row = next(item for item in rows if item.client == client)
    assert (int(row.silent), int(row.recent_silent)) == (5, 1)


@pytest.mark.asyncio
async def test_people_list_matches_the_number_and_carries_no_description() -> None:
    since = _window()
    at = since + timedelta(days=1)
    async with AsyncSessionLocal() as db:
        client_id, _, reason_id = await _rejection_setup(db)
        job_id = await _job(db, client_id, "Osoby")
        expected = {
            await _refusal(db, job_id, reason_id, at, "za wysoka stawka"),
            await _refusal(
                db, job_id, reason_id, at, "oczekiwania finansowe za wysokie"
            ),
        }
        await _refusal(db, job_id, reason_id, at, "nie odbiera telefonu")
        await db.commit()

        original = service.counted_from
        service.counted_from = lambda _today: since  # type: ignore[assignment]
        try:
            after = await service.compute_reason_people(
                db,
                today=TODAY,
                bucket="rate",
                basis="after",
                client_id=client_id,
                limit=40,
                offset=0,
            )
            today_view = await service.compute_reason_people(
                db,
                today=TODAY,
                bucket="unread",
                basis="today",
                client_id=client_id,
                limit=40,
                offset=0,
            )
            nobody = await service.compute_reason_people(
                db,
                today=TODAY,
                bucket="rate",
                basis="today",
                client_id=client_id,
                limit=40,
                offset=0,
            )
        finally:
            service.counted_from = original  # type: ignore[assignment]

    assert after["total"] == 2
    assert {row["candidate_id"] for row in after["rows"]} == expected
    assert today_view["total"] == 3
    assert nobody == {"total": 0, "rows": []}
    assert all("stawka" not in str(row).lower() for row in after["rows"])


@pytest.mark.asyncio
async def test_full_read_paths_run_against_the_real_schema() -> None:
    """SQL widzi prawdziwy schemat: literówka w kolumnie to 500 przy pierwszym wejściu."""
    today = business_today()
    async with AsyncSessionLocal() as db:
        await db.execute(delete(InsightDecision))
        await db.commit()
        cases = await service.compute_cases(db, today)
        reasons = await service.compute_reasons(db, today)
        collected = await service.compute_collected(db, today)
        history = await service.compute_history(db, today)
    assert [case["key"] for case in cases["cases"]] == list(service.CASE_KEYS)
    assert len(cases["watching"]) == 3
    assert {row["key"] for row in reasons["why_out"]} == {
        b.key for b in service.WHY_OUT_BUCKETS
    }
    assert len(collected["rows"]) == 12
    assert {row["status"] for row in collected["rows"]} == set(collected["statuses"])
    assert {row["key"] for row in history["approved"]} == {"zatrudnieni", "inne"}
    assert len(history["rules"]) == 3


@pytest.mark.asyncio
async def test_history_measures_each_approved_decision_after_review_date() -> None:
    decided = datetime.now(timezone.utc)
    review = date(2026, 12, 1)
    async with AsyncSessionLocal() as db:
        await db.execute(delete(InsightDecision))
        for key in ("konkret", "cv", "kciuki"):
            db.add(
                InsightDecision(
                    insight_key=key,
                    state=service.STATE_APPROVED,
                    decided_at=decided,
                    count_at_decision=60,
                    number_at_decision="1 na 3",
                    review_on=review,
                )
            )
        await db.commit()
        before = await service.compute_history(db, review - timedelta(days=1))
        after = await service.compute_history(db, date(2027, 1, 1))
    assert all(row["measure_now"] is None for row in before["approved"])
    assert all(row["verdict"] is None or row["verdict"] for row in before["rules"])
    measured = {row["key"]: row["measure_now"] for row in after["approved"]}
    assert measured["konkret"] is not None
    assert measured["cv"] is not None
    assert measured["kciuki"] is None
    assert measured["inne"] is not None
    assert measured["zatrudnieni"].endswith("kart")
    assert all(row["verdict"] for row in after["rules"])


async def _login(client: AsyncClient, *roles: UserRole) -> dict[str, str]:
    unique = uuid.uuid4().hex[:8]
    email = f"wnioski-{roles[0].value}-{unique}@example.com"
    password = f"T3st_{unique}!Wns"
    async with AsyncSessionLocal() as db:
        db.add(
            User(
                email=email,
                name=f"Wnioski {unique}",
                password_hash=hash_password(password),
                role=roles[0],
                is_active=True,
                profile_completed=True,
            )
        )
        await db.commit()
    resp = await client.post(
        "/api/auth/login", json={"email": email, "password": password}
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


@pytest.fixture
def fake_cases(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Reguły podstawione, żeby test decyzji nie zależał od cache i danych innych testów."""
    computed: dict[str, Any] = {
        "computed_at": "2026-11-05T10:00:00+00:00",
        "counted_from": "2026-10-11T22:00:00+00:00",
        "counted_from_label": "12.10",
        "cases": [
            _case("konkret", count=60),
            _case("cv", count=232),
            _case("kciuki", count=213),
        ],
        "watching": [],
    }

    async def _cached(_db: Any) -> dict[str, Any]:
        return computed

    monkeypatch.setattr(api, "_cached_cases", _cached)
    return computed


@pytest.fixture
async def no_decisions() -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(delete(InsightDecision))
        await db.commit()


@pytest.mark.parametrize(
    "role",
    [
        UserRole.delivery_lead,
        UserRole.recruiter,
        UserRole.finance,
        UserRole.board,
        UserRole.automation,
    ],
)
@pytest.mark.asyncio
async def test_other_roles_get_403_on_every_route(
    app_client: AsyncClient, role: UserRole
) -> None:
    headers = await _login(app_client, role)
    for path in (
        "/api/insights/wnioski",
        "/api/insights/wnioski/history",
        "/api/insights/wnioski/reasons",
        "/api/insights/wnioski/collected",
        "/api/insights/wnioski/reasons/people?bucket=rate",
    ):
        resp = await app_client.get(path, headers=headers)
        assert resp.status_code == 403, (path, resp.text)
    resp = await app_client.post(
        "/api/insights/wnioski/konkret/decision",
        json={"state": "approved"},
        headers=headers,
    )
    assert resp.status_code == 403, resp.text


@pytest.mark.asyncio
async def test_unauthenticated_is_refused(app_client: AsyncClient) -> None:
    resp = await app_client.get("/api/insights/wnioski")
    assert resp.status_code == 401


@pytest.mark.parametrize(
    "body", [{"state": "maybe"}, {"state": None}, {}, {"state": "approved "}]
)
@pytest.mark.asyncio
async def test_bad_decision_is_422(
    app_client: AsyncClient, fake_cases: dict[str, Any], body: dict[str, Any]
) -> None:
    headers = await _login(app_client, UserRole.admin)
    resp = await app_client.post(
        "/api/insights/wnioski/konkret/decision", json=body, headers=headers
    )
    assert resp.status_code == 422, resp.text


@pytest.mark.asyncio
async def test_bad_people_filter_is_422(app_client: AsyncClient) -> None:
    headers = await _login(app_client, UserRole.admin)
    resp = await app_client.get(
        "/api/insights/wnioski/reasons/people?bucket=x%27%20OR%201=1", headers=headers
    )
    assert resp.status_code == 422, resp.text


@pytest.mark.asyncio
async def test_unknown_case_is_404(
    app_client: AsyncClient, fake_cases: dict[str, Any]
) -> None:
    headers = await _login(app_client, UserRole.admin)
    resp = await app_client.post(
        "/api/insights/wnioski/nieistnieje/decision",
        json={"state": "approved"},
        headers=headers,
    )
    assert resp.status_code == 404, resp.text


@pytest.mark.asyncio
async def test_hor_cannot_decide_a_case_owned_by_admin(
    app_client: AsyncClient, fake_cases: dict[str, Any], no_decisions: None
) -> None:
    hor = await _login(app_client, UserRole.head_of_recruitment)
    admin = await _login(app_client, UserRole.admin)
    refused = await app_client.post(
        "/api/insights/wnioski/kciuki/decision", json={"state": "approved"}, headers=hor
    )
    assert refused.status_code == 403, refused.text
    accepted = await app_client.post(
        "/api/insights/wnioski/kciuki/decision",
        json={"state": "approved"},
        headers=admin,
    )
    assert accepted.status_code == 200, accepted.text


@pytest.mark.asyncio
async def test_decisions_hide_and_return_cases(
    app_client: AsyncClient, fake_cases: dict[str, Any], no_decisions: None
) -> None:
    hor = await _login(app_client, UserRole.head_of_recruitment)
    today = business_today()

    listed = (await app_client.get("/api/insights/wnioski", headers=hor)).json()
    assert listed["open_count"] == 3
    assert [case["key"] for case in listed["cases"]] == ["konkret", "cv", "kciuki"]
    assert listed["cases"][0]["owner"] == "Head of Recruitment"

    approved = await app_client.post(
        "/api/insights/wnioski/konkret/decision",
        json={"state": "approved"},
        headers=hor,
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["review_on"] == (today + timedelta(days=30)).isoformat()

    again = await app_client.post(
        "/api/insights/wnioski/konkret/decision",
        json={"state": "rejected"},
        headers=hor,
    )
    assert again.status_code == 409, again.text

    rejected = await app_client.post(
        "/api/insights/wnioski/cv/decision", json={"state": "rejected"}, headers=hor
    )
    assert rejected.status_code == 200, rejected.text
    listed = (await app_client.get("/api/insights/wnioski", headers=hor)).json()
    assert [case["key"] for case in listed["cases"]] == ["kciuki"]

    # „Nie” wraca dopiero przy dwukrotnym wzroście liczby z chwili decyzji.
    fake_cases["cases"][1] = _case("cv", count=463)
    listed = (await app_client.get("/api/insights/wnioski", headers=hor)).json()
    assert "cv" not in [case["key"] for case in listed["cases"]]
    fake_cases["cases"][1] = _case("cv", count=464)
    listed = (await app_client.get("/api/insights/wnioski", headers=hor)).json()
    assert "cv" in [case["key"] for case in listed["cases"]]

    async with AsyncSessionLocal() as db:
        rows = (
            (
                await db.execute(
                    select(InsightDecision).where(
                        InsightDecision.insight_key == "konkret"
                    )
                )
            )
            .scalars()
            .all()
        )
    assert len(rows) == 1
    assert rows[0].state == "approved"
    assert rows[0].count_at_decision == 60
    assert rows[0].number_at_decision == "1 na 3"
    assert rows[0].decided_by_id is not None


@pytest.mark.asyncio
async def test_later_comes_back_after_30_days(
    app_client: AsyncClient, fake_cases: dict[str, Any], no_decisions: None
) -> None:
    hor = await _login(app_client, UserRole.head_of_recruitment)
    today = business_today()
    resp = await app_client.post(
        "/api/insights/wnioski/cv/decision", json={"state": "later"}, headers=hor
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["return_on"] == (today + timedelta(days=30)).isoformat()
    listed = (await app_client.get("/api/insights/wnioski", headers=hor)).json()
    assert "cv" not in [case["key"] for case in listed["cases"]]

    async with AsyncSessionLocal() as db:
        latest = await service.latest_decisions(db)
    assert service.is_case_open(232, latest["cv"], today + timedelta(days=30))

    history = (
        await app_client.get("/api/insights/wnioski/history", headers=hor)
    ).json()
    assert [row["key"] for row in history["deferred"]] == ["cv"]
    assert {"zatrudnieni", "inne"} <= {row["key"] for row in history["approved"]}


@pytest.mark.asyncio
async def test_closed_rule_case_cannot_be_decided(
    app_client: AsyncClient, fake_cases: dict[str, Any], no_decisions: None
) -> None:
    fake_cases["cases"][1] = _case("cv", enough=False)
    hor = await _login(app_client, UserRole.head_of_recruitment)
    resp = await app_client.post(
        "/api/insights/wnioski/cv/decision", json={"state": "approved"}, headers=hor
    )
    assert resp.status_code == 409, resp.text
