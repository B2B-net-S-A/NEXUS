"""Silnik raportu kompetencji (``services/competence_report_engine.py``).

Część bez bazy: lejek narastająco, pomijane kroki, „co otworzy więcej” tylko
z zyskiem, projekty spełniające i chybione o jeden warunek z polskim powodem.
Część z bazą: każdy test w jednej transakcji, która zamyka wszystkie otwarte
rekrutacje, dokłada fikcyjnego klienta, rekrutacje i kandydata, a na końcu się
cofa. Stawki rynku podmienione (liczy je ``test_market_rates.py``). Dane syntetyczne.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import text

from app.services import competence_report_engine as engine
from app.services import market_rates
from app.services.competence_report_engine import JobFacts, Terms
from app.services.competence_report_schema import (
    MarketGroup,
    MarketRate,
    ReportConditions,
    ReportSnapshot,
    TechPremium,
)

# ── Bez bazy ────────────────────────────────────────────────────────────────


def _job(job_id, *, days=None, city=None, budget=None, remote=False, must=("java",)):
    tokens = frozenset({city.lower()}) if city else frozenset()
    return JobFacts(
        job_id=job_id,
        days=days,
        needs_office=bool(days),
        remote=remote,
        office_tokens=tokens,
        city=city,
        budget=budget,
        must=tuple(must),
        skills=tuple(m.capitalize() for m in must),
    )


def _terms(**kw) -> Terms:
    base = dict(
        rate=150, office_max=2, remote_only=False, cities=("Kraków",), remote_ok=True
    )
    return Terms(**{**base, **kw})


JOBS = [
    _job(1, days=2, city="Kraków", budget=160),  # spełnia
    _job(2, days=3, city="Kraków", budget=160),  # dni
    _job(3, days=2, city="Warszawa", budget=170),  # miasto
    _job(4, remote=True, budget=140),  # budżet
    _job(5, remote=True),  # nieznany budżet nie przechodzi kroku budżetu
    _job(6, days=3, city="Warszawa", budget=100),  # trzy warunki
]


def test_lejek_narastajaco_w_kolejnosci_warunkow():
    steps = engine.funnel(JOBS, _terms(), role="java")
    assert [(s.key, s.label, s.count) for s in steps] == [
        ("tech", "Otwarte projekty z Javą", 6),
        ("office_days", "Biuro do 2 dni", 4),
        ("location", "Kraków albo zdalnie", 3),
        ("budget", "Od 150 zł/h", 1),
    ]


def test_budzet_rowny_stawce_przechodzi():
    assert engine._fails(_job(9, budget=150), _terms()) == []
    assert engine._fails(_job(9, budget=149.99), _terms()) == ["budget"]


def test_nieznany_budzet_nie_przechodzi_kroku_od_stawki():
    assert engine._fails(_job(9, remote=True), _terms()) == ["budget"]
    steps = engine.funnel([_job(9, remote=True)], _terms(), role="java")
    assert steps[-1].key == "budget" and steps[-1].count == 0


def test_tylko_zdalnie_bez_kroku_dni_w_biurze():
    t = _terms(remote_only=True, office_max=0, cities=())
    steps = engine.funnel(JOBS, t, role="java")
    assert [s.key for s in steps] == ["tech", "location", "budget"]
    assert steps[1].label == "Zdalnie"
    assert steps[1].count == 2  # zdalne 4 i 5
    assert steps[2].count == 0  # 4 za nisko, 5 bez budżetu


def test_krok_bez_mozliwosci_filtrowania_pominiety():
    t = _terms(office_max=5, cities=())
    assert [s.key for s in engine.funnel(JOBS, t, role="java")] == ["tech", "budget"]
    t = _terms(office_max=None, cities=("Kraków", "Gdańsk"))
    steps = engine.funnel(JOBS, t, role="java")
    assert [s.key for s in steps] == ["tech", "location", "budget"]
    assert steps[1].label == "Kraków, Gdańsk albo zdalnie"


def test_warunki_z_formularza():
    t = engine.terms_from(
        ReportConditions(
            rate=150, modes=("remote",), office_days_max=None, office_cities=("krakow",)
        )
    )
    assert t.remote_only and t.cities == ("Kraków",)
    t = engine.terms_from(
        ReportConditions(rate=150, modes=("hybrid",), office_days_max=0)
    )
    assert t.remote_only
    t = engine.terms_from(
        ReportConditions(rate=150, modes=("onsite",), office_days_max=3)
    )
    assert not t.remote_only and not t.remote_ok


def test_dzwignie_tylko_z_zyskiem_i_po_polsku():
    levers = engine.levers(
        JOBS, _terms(), role="java", median=140, profile_city="Kraków"
    )
    assert {(lv.key, lv.label, lv.gain) for lv in levers} == {
        ("office_days_plus1", "3 dni w biurze zamiast 2", 1),
        ("extra_city", "Warszawa jako dodatkowe miasto", 1),
        ("rate_to_median", "Stawka od 140 zł/h", 1),
    }
    extra = next(lv for lv in levers if lv.key == "extra_city")
    assert extra.hint == "tu jest najwięcej projektów z Javą poza Twoimi miastami"
    # mediana 145: rekrutacja 4 (140 zł/h) dalej odpada → zysk 0, dźwigni nie ma
    levers = engine.levers(JOBS, _terms(), role="java", median=145, profile_city=None)
    assert "rate_to_median" not in {lv.key for lv in levers}
    # stawka poniżej mediany: nie proponujemy podwyżki ani obniżki
    levers = engine.levers(
        JOBS, _terms(rate=120), role="java", median=140, profile_city=None
    )
    assert "rate_to_median" not in {lv.key for lv in levers}


def test_dzwignie_najwyzej_trzy_od_najwiekszego_zysku():
    jobs = [_job(i, days=3, city="Kraków", budget=200) for i in range(10, 15)]
    jobs += [_job(i, days=1, city="Gdańsk", budget=200) for i in range(20, 22)]
    levers = engine.levers(jobs, _terms(), role="java", median=140, profile_city=None)
    assert [(lv.key, lv.gain) for lv in levers] == [
        ("office_days_plus1", 5),
        ("extra_city", 2),
    ]


def test_tylko_zdalnie_dzwignia_hybrydy_z_miastem_profilu():
    jobs = JOBS + [_job(7, days=1, city="Kraków", budget=200)]
    t = _terms(remote_only=True, office_max=None, cities=())
    levers = engine.levers(jobs, t, role="java", median=None, profile_city="Kraków")
    assert [(lv.key, lv.label, lv.gain) for lv in levers] == [
        ("remote_to_hybrid", "Hybrydowo, 1 dzień w biurze", 1)
    ]
    assert engine.levers(jobs, t, role="java", median=None, profile_city=None) == ()


def test_projekty_najpierw_spelniajace_potem_chybione_o_jeden():
    picked = engine.pick_jobs(JOBS, _terms())
    # Bez budżetu (5) nie spełnia; chybione: znany budżet przed nieznanym, wyższy pierwszy.
    assert [(j.job_id, reason) for j, reason in picked] == [
        (1, None),
        (3, "poza Twoimi miastami"),
        (2, "o 1 dzień w biurze za dużo"),
    ]


def test_projekt_bez_budzetu_tylko_jako_chybiony_do_ustalenia():
    picked = engine.pick_jobs([JOBS[0], JOBS[4]], _terms())
    assert [(j.job_id, reason) for j, reason in picked] == [
        (1, None),
        (5, "budżet do ustalenia z rekruterem"),
    ]
    three = [_job(i, remote=True, budget=150 + i) for i in range(10, 13)]
    picked = engine.pick_jobs([*three, JOBS[4]], _terms())
    assert [(j.job_id, r) for j, r in picked] == [(12, None), (11, None), (10, None)]
    assert all(j.budget is not None and j.budget >= 150 for j, r in picked if r is None)


def test_powody_chybienia():
    jobs = [JOBS[1], JOBS[2], JOBS[3], _job(8, days=4, city="Kraków", budget=300)]
    reasons = {j.job_id: r for j, r in engine.pick_jobs(jobs, _terms())}
    assert reasons == {
        8: "o 2 dni w biurze za dużo",
        3: "poza Twoimi miastami",
        2: "o 1 dzień w biurze za dużo",
    }
    assert (
        engine._miss_reason("budget", JOBS[3], _terms())
        == "budżet poniżej Twojej stawki"
    )
    remote = _terms(remote_only=True, office_max=None, cities=())
    assert engine._miss_reason("location", JOBS[0], remote) == "wymaga pracy w biurze"


def test_miejsce_projektu():
    assert engine.place_of(_job(1, days=2, city="Kraków")) == "Kraków, 2 dni w biurze"
    assert engine.place_of(_job(1, days=1)) == "1 dzień w biurze"
    assert engine.place_of(_job(1, remote=True)) == "zdalnie"
    assert engine.place_of(_job(1)) is None
    # Polityka nieznana, ale miasto znane: samo miasto.
    assert engine.place_of(_job(1, city="Gdańsk")) == "Gdańsk"


def test_miasto_tylko_ze_znanych():
    assert (
        market_rates.known_city("Biurowiec Kometa, ul. Fikcyjna 1, 30-001 Kraków")
        == "Kraków"
    )
    assert market_rates.known_city("Warsaw / hybrid") == "Warszawa"
    assert market_rates.known_city("Kampus Orion") is None
    assert market_rates.known_city(None) is None


def test_umiejetnosci_tylko_krotkie_nazwy():
    assert engine.skill_shown("Spring Boot")
    assert not engine.skill_shown("Znajomość systemu Orion w zespole Kometa")
    assert not engine.skill_shown("Kometa", ["Kometa"])


def test_tytul_ogolny_z_roli_poziomu_i_technologii():
    assert (
        engine.generic_title("java", None, ["Java 17", "Kafka"])
        == "Java Developer · Kafka"
    )
    assert (
        engine.generic_title("java", "senior", ["Java"])
        == "Senior Java Developer · backend"
    )
    assert (
        engine.generic_title("tester", None, []) == "Tester manualny · projekt testowy"
    )
    assert (
        engine.generic_title("tester", None, ["Selenium", "SQL"])
        == "Tester automatyzujący · Selenium"
    )


def test_brakujaca_technologia_bez_glownej_i_bez_posiadanych():
    jobs = [
        _job(1, must=("java", "kubernetes", "kafka")),
        _job(2, must=("java 17", "kubernetes")),
        _job(3, must=("java", "kafka", "sql")),
        _job(4, must=("java", "kubernetes")),
    ]
    assert engine.missing_tech(jobs, have={"kafka"}, role="java") == (
        "Kubernetes",
        3,
        4,
    )
    assert (
        engine.missing_tech(jobs, have={"kafka", "kubernetes", "sql"}, role="java")
        is None
    )
    assert engine.missing_tech([], have=set(), role="java") is None


def test_procent_wzgledem_mediany_zaokraglony():
    assert engine._pct(150, 140) == 7
    assert engine._pct(135, 140) == -4
    assert engine._pct(140, 140) == 0


# ── Z bazą ──────────────────────────────────────────────────────────────────

CLIENT = "Zetafirma Testowa"
MARKET = MarketRate(
    group=MarketGroup(role_label="Java", years_bucket="8+", city="Kraków"),
    p25=130,
    median=140,
    p75=169,
    n=40,
)


@pytest.fixture
async def db():
    import app.models  # noqa: F401  (zarejestruj wszystkie mappery)
    from app.core.database import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        await session.execute(text("update jobs set is_open = false where is_open"))
        try:
            yield session
        finally:
            await session.rollback()


@pytest.fixture
def market(monkeypatch):
    calls: list[list[str]] = []

    async def fake_rate(db, *, role, years, city):
        return MARKET

    async def fake_premiums(db, *, role, group, skills):
        calls.append(list(skills))
        if list(skills) == ["Kubernetes"]:
            return [TechPremium(name="Kubernetes", premium=10)]
        return [
            TechPremium(name="gcp", premium=15),
            TechPremium(name="kafka", premium=5),
        ]

    monkeypatch.setattr(market_rates, "market_rate_for", fake_rate)
    monkeypatch.setattr(market_rates, "tech_premiums", fake_premiums)
    return calls


async def _client(db):
    from app.models.client import Client

    client = Client(name=CLIENT)
    db.add(client)
    await db.flush()
    return client


async def _open_job(db, client, title, **kw):
    from app.models.job import Job

    job = Job(title=title, client_id=client.id, is_open=kw.pop("is_open", True), **kw)
    db.add(job)
    await db.flush()
    return job


async def _candidate(
    db,
    *,
    skills=(("java", "Java", 100), ("gcp", "GCP", 36)),
    position=None,
    city="Kraków",
):
    from app.models.candidate import Candidate
    from app.models.candidate_skill_usage import CandidateSkillUsage

    candidate = Candidate(
        name="Testowa",
        lastname="Osoba",
        email=f"silnik-{uuid.uuid4().hex[:12]}@example.com",
        city=city,
        cv_extracted_data={"current_position": position} if position else {},
        cv_parsed_at=datetime.now(timezone.utc),
    )
    db.add(candidate)
    await db.flush()
    for canonical, raw, months in skills:
        db.add(
            CandidateSkillUsage(
                candidate_id=candidate.id,
                skill_canonical=canonical,
                skill_raw=raw,
                months=months,
            )
        )
    await db.flush()
    return candidate


async def _report(db, candidate, *, owner_id=None, **conditions):
    from app.models.competence_report import CompetenceReport

    cond = dict(
        rate=150,
        current_rate=135,
        modes=("hybrid", "remote"),
        office_days_max=2,
        office_cities=("Kraków",),
    )
    cond.update(conditions)
    now = datetime.now(timezone.utc)
    report = CompetenceReport(
        candidate_id=candidate.id,
        email=candidate.email,
        conditions=ReportConditions(**cond).model_dump(mode="json"),
        owner_user_id=owner_id,
        created_at=now,
        send_due_at=now + timedelta(hours=23),
    )
    db.add(report)
    await db.flush()
    return report


async def _owner(db):
    from app.models.user import User, UserRole

    user = User(
        email=f"opiekun-{uuid.uuid4().hex[:8]}@example.com",
        password_hash="not-a-real-hash",
        name="Opiekun Testowy",
        role=UserRole.recruiter,
    )
    db.add(user)
    await db.flush()
    return user


async def _jobs(db):
    from app.models.job import RemotePolicy

    client = await _client(db)
    must = ["Java", "Spring Boot", "Kubernetes"]
    await _open_job(
        db,
        client,
        f"{CLIENT} - Java Developer",
        must_skills=must,
        onsite_days_per_week=2,
        location="Kraków",
        rate_budget_hourly=Decimal("163.40"),
        remote_policy=RemotePolicy.hybrid,
    )
    await _open_job(
        db,
        client,
        f"Java Developer dla {CLIENT}",
        must_skills=["Java", "Kafka"],
        remote_policy=RemotePolicy.remote,
        rate_budget_hourly=Decimal("150"),
    )
    await _open_job(
        db,
        client,
        "Starszy programista Java",
        must_skills=must,
        onsite_days_per_week=3,
        location="Kraków",
        rate_budget_hourly=Decimal("200"),
    )
    await _open_job(
        db,
        client,
        "Programista Java (budżet niski)",
        must_skills=["Java"],
        remote_policy=RemotePolicy.remote,
        rate_budget_hourly=Decimal("120"),
    )
    await _open_job(
        db,
        client,
        "Python Developer",
        must_skills=["Python"],
        remote_policy=RemotePolicy.remote,
    )
    await _open_job(db, client, "Java zamknięta", must_skills=["Java"], is_open=False)


async def test_pelny_raport_z_warunkow_formularza(db, market):
    await _jobs(db)
    owner = await _owner(db)
    candidate = await _candidate(db)
    report = await _report(db, candidate, owner_id=owner.id)

    snap = await engine.build_snapshot(db, report)

    assert snap.variant == "full"
    assert snap.profile.role_label == "Java" and snap.profile.years == 8
    assert snap.profile.city == "Kraków"
    assert snap.rate_position.expected_vs_median_pct == 7
    assert snap.rate_position.current_vs_median_pct == -4
    assert [(s.key, s.count) for s in snap.funnel] == [
        ("tech", 4),
        ("office_days", 3),
        ("location", 3),
        ("budget", 2),
    ]
    assert snap.strongest_tech == TechPremium(name="GCP", premium=15, months=36)
    assert snap.missing_tech.name == "Kubernetes"
    assert (
        snap.missing_tech.jobs,
        snap.missing_tech.of,
        snap.missing_tech.premium,
    ) == (2, 4, 10)
    # zapytanie o premie bez głównej technologii
    assert market[0] == ["gcp"]
    assert snap.owner.name == "Opiekun Testowy"
    meets = [j for j in snap.jobs if j.meets]
    assert [j.budget_max for j in meets] == [160, 150]
    assert meets[0].place == "Kraków, 2 dni w biurze"
    assert meets[0].skills == ("Java", "Spring Boot", "Kubernetes")
    assert meets[1].place == "zdalnie"
    near = [j for j in snap.jobs if not j.meets]
    assert [(j.budget_max, j.miss_reason) for j in near] == [
        (200, "o 1 dzień w biurze za dużo")
    ]
    # stawka do mediany (140) nie wpuszcza rekrutacji za 120 zł/h → zysk 0, bez dźwigni
    assert [(lv.key, lv.gain) for lv in snap.levers] == [("office_days_plus1", 1)]
    ReportSnapshot.model_validate(snap.model_dump(mode="json"))


async def test_w_snapshocie_nigdy_nazwy_klienta(db, market):
    await _jobs(db)
    candidate = await _candidate(db)
    report = await _report(db, candidate)

    snap = await engine.build_snapshot(db, report)

    dumped = json.dumps(snap.model_dump(mode="json"), ensure_ascii=False)
    assert CLIENT.lower() not in dumped.lower()
    assert "Zetafirma" not in dumped
    titles = {j.title for j in snap.jobs}
    assert titles == {"Java Developer · Spring Boot", "Java Developer · Kafka"}


async def test_tytul_wewnetrzny_rekrutacji_nigdy_w_raporcie(db, market):
    """Wewnętrzny tytuł, zespół, program i biuro z rekrutacji nie trafiają do maila."""
    from app.models.job import RemotePolicy
    from app.services.competence_report_email import ReportLinks, render_report_email

    client = await _client(db)
    await _open_job(
        db,
        client,
        "Zespół Kometa / program Orion — Java (wewn.)",
        must_skills=["Java", "Kafka", "Znajomość systemu Orion w zespole Kometa"],
        onsite_days_per_week=2,
        location="Biurowiec Kometa, ul. Fikcyjna 1, Kraków",
        rate_budget_hourly=Decimal("180"),
        remote_policy=RemotePolicy.hybrid,
    )
    candidate = await _candidate(db)
    report = await _report(db, candidate)

    snap = await engine.build_snapshot(db, report)

    [job] = snap.jobs
    assert job.title == "Java Developer · Kafka"
    assert job.skills == ("Java", "Kafka")
    assert job.place == "Kraków, 2 dni w biurze"
    assert job.meets and job.budget_max == 180
    mail = render_report_email(
        snap,
        first_name="Testowa",
        links=ReportLinks(
            edit_conditions_url="https://example.com/r",
            unsubscribe_url="https://example.com/u",
            one_click_unsubscribe_url=None,
        ),
    )
    dumped = json.dumps(snap.model_dump(mode="json"), ensure_ascii=False)
    for secret in ("Kometa", "Orion", "Fikcyjna", "wewn"):
        assert secret not in dumped
        assert secret not in mail.html and secret not in mail.text


async def test_cv_spoza_it_daje_raport_limited(db, market):
    await _jobs(db)
    candidate = await _candidate(
        db, skills=(("excel", "Excel", 100),), position="Księgowa"
    )
    report = await _report(db, candidate)

    snap = await engine.build_snapshot(db, report)

    assert snap.variant == "limited"
    assert snap.profile.role_label == "Księgowa"
    assert snap.market is None and snap.rate_position is None
    assert snap.funnel == () and snap.jobs == ()


async def test_brak_stawek_rynku_zostawia_lejek(db, monkeypatch):
    async def no_rate(db, *, role, years, city):
        return None

    monkeypatch.setattr(market_rates, "market_rate_for", no_rate)
    await _jobs(db)
    candidate = await _candidate(db)
    report = await _report(db, candidate)

    snap = await engine.build_snapshot(db, report)

    assert snap.variant == "limited"
    assert snap.market is None and snap.strongest_tech is None
    assert snap.funnel[0].count == 4 and snap.jobs
    assert "rate_to_median" not in {lv.key for lv in snap.levers}


async def test_limited_po_20_h_bez_rynku(db, market):
    await _jobs(db)
    candidate = await _candidate(db)
    report = await _report(db, candidate)

    snap = await engine.build_snapshot(db, report, limited=True)

    assert snap.variant == "limited" and snap.market is None


async def test_przeliczenie_po_zmianie_warunkow_zapisuje_snapshot(db, market):
    await _jobs(db)
    candidate = await _candidate(db)
    report = await _report(db, candidate)
    report.conditions = ReportConditions(rate=150, modes=("remote",)).model_dump(
        mode="json"
    )

    snap = await engine.rebuild_snapshot(db, report)

    assert report.snapshot == snap.model_dump(mode="json")
    assert [s.key for s in snap.funnel] == ["tech", "location", "budget"]


# ── Przegląd 26.11.2026 ─────────────────────────────────────────────────────


async def test_technologia_z_nazwa_klienta_nie_trafia_do_raportu(db, market):
    """Brakująca technologia „Allegro Pay” niesie nazwę klienta — nie pokazujemy jej."""
    from app.models.client import Client
    from app.models.job import RemotePolicy
    from app.services.competence_report_email import ReportLinks, render_report_email

    client = Client(name="Allegro")
    db.add(client)
    await db.flush()
    for budget in (160, 170, 180):
        await _open_job(
            db,
            client,
            "Programista Java",
            must_skills=["Java", "Allegro Pay"],
            remote_policy=RemotePolicy.remote,
            rate_budget_hourly=Decimal(budget),
        )
    candidate = await _candidate(db)
    report = await _report(db, candidate)

    snap = await engine.build_snapshot(db, report)

    assert len(snap.jobs) == 3 and snap.missing_tech is None
    mail = render_report_email(
        snap,
        first_name="Testowa",
        links=ReportLinks(
            edit_conditions_url="https://example.com/r",
            unsubscribe_url="https://example.com/u",
            one_click_unsubscribe_url=None,
        ),
    )
    dumped = json.dumps(snap.model_dump(mode="json"), ensure_ascii=False)
    assert "allegro" not in dumped.lower()
    assert "allegro" not in mail.html.lower() and "allegro" not in mail.text.lower()


async def test_rola_java_bez_rekrutacji_na_testera_analityka_pm_devops(db, market):
    """Java w wymaganiach rekrutacji na testera nie robi z niej projektu dla Javy."""
    from app.models.job import RemotePolicy

    await _jobs(db)
    client = await _client(db)
    for title in (
        "Test Automation Engineer",
        "Analityk biznesowy",
        "Project Manager",
        "DevOps Engineer",
    ):
        await _open_job(
            db,
            client,
            title,
            must_skills=["Java", "Selenium"],
            remote_policy=RemotePolicy.remote,
            rate_budget_hourly=Decimal("200"),
        )
    await _open_job(
        db,
        client,
        "Inżynier jakości",
        working_title="QA Engineer (Java)",
        must_skills=["Java"],
        remote_policy=RemotePolicy.remote,
        rate_budget_hourly=Decimal("200"),
    )
    candidate = await _candidate(db)
    report = await _report(db, candidate)

    snap = await engine.build_snapshot(db, report)

    assert snap.funnel[0].count == 4, "tylko cztery rekrutacje programistyczne z _jobs"
    assert all("Tester" not in j.title for j in snap.jobs)
    assert snap.missing_tech.name != "Selenium"
