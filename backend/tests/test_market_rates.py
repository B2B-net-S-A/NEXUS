"""Stawki rynku do raportu kompetencji (``services/market_rates.py``).

Część bez bazy: rola z CV, lata i przedziały, miasta, kolejność poszerzania.
Część z bazą: każdy test w jednej transakcji, która najpierw zdejmuje stawki
wszystkim istniejącym kandydatom (populacja to cała baza), dokłada fikcyjne osoby
i na końcu się cofa. Stawki i dane są syntetyczne.
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import text

from app.core.scheduling import local_now
from app.services import market_rates as mr
from app.services.competence_report_schema import MIN_GROUP

# ── Bez bazy ────────────────────────────────────────────────────────────────


def _usage(*pairs):
    return [SimpleNamespace(skill_canonical=name, months=months) for name, months in pairs]


def test_rola_to_technologia_z_najwieksza_liczba_miesiecy():
    rows = _usage(("java", 96), ("python", 30), ("spring boot", 120))
    assert mr.resolve_role({"current_position": "Senior Developer"}, rows) == "java"
    assert mr.resolve_role({}, _usage(("java 17", 12), ("golang", 40))) == "go"


def test_rola_przyjmuje_slowniki_i_wiersze_bez_miesiecy():
    rows = [{"skill_canonical": "c#", "months": None}, {"skill_canonical": "php", "months": 5}]
    assert mr.resolve_role(None, rows) == "php"
    assert mr.resolve_role(None, [{"skill_canonical": "c#", "months": None}]) == "dotnet"


def test_stanowisko_spoza_programowania_wygrywa_z_technologia():
    rows = _usage(("java", 120))
    assert mr.resolve_role({"current_position": "QA Engineer"}, rows) == "tester"
    assert mr.resolve_role({"current_position": "Tester automatyzujący"}, rows) == "tester"
    assert mr.resolve_role({"current_position": "DevOps Engineer"}, rows) == "devops"
    assert mr.resolve_role({"current_position": "Analityk biznesowy"}, rows) == "business_analyst"
    assert mr.resolve_role({"current_position": "IT Project Manager"}, rows) == "project_manager"
    assert mr.resolve_role({"current_position": "Big Data Engineer"}, rows) == "data_engineer"


def test_kierownik_testow_nie_jest_testerem():
    rows = _usage(("java", 60))
    assert mr.resolve_role({"current_position": "Test Manager"}, rows) == "java"
    # „latest” nie zawiera słowa „test”
    assert mr.resolve_role({"current_position": "Developer of latest tools"}, rows) == "java"


def test_bez_znanej_technologii_i_roli_brak_roli():
    assert mr.resolve_role({"current_position": "Księgowa"}, _usage(("excel", 100))) is None
    assert mr.resolve_role(None, []) is None


@pytest.mark.parametrize(
    "years,bucket",
    [(None, None), (-1, None), (0, "<3"), (2, "<3"), (3, "3–5"), (4, "3–5"),
     (5, "5–8"), (7, "5–8"), (8, "8+"), (25, "8+")],
)
def test_przedzialy_lat(years, bucket):
    assert mr.years_bucket(years) == bucket


def test_lata_w_roli():
    rows = _usage(("java", 100), ("jira", 150), ("python", None))
    assert mr.role_years("java", rows) == 8
    assert mr.role_years("python", rows) is None
    assert mr.role_years("tester", rows) == 12  # najdłuższa umiejętność
    assert mr.role_years("tester", _usage(("jira", None))) is None


def test_miasta_polska_i_angielska_pisownia():
    assert mr.normalize_city(" krakow ") == "Kraków"
    assert mr.normalize_city("Warsaw") == "Warszawa"
    assert mr.normalize_city("Lodz") == "Łódź"
    assert mr.normalize_city("Rzeszów") == "Rzeszów"
    assert mr.normalize_city("  ") is None


def test_kolejnosc_poszerzania():
    assert mr._steps("8+", "Kraków") == [("8+", "Kraków"), ("8+", None), ("5+", None), (None, None)]
    assert mr._steps("<3", None) == [("<3", None), ("<5", None), (None, None)]
    assert mr._steps(None, "Gdańsk") == [(None, "Gdańsk"), (None, None)]
    assert mr._steps(None, None) == [(None, None)]


def test_zaokraglenie_polowek_w_gore():
    assert mr._round(114.5) == 115
    assert mr._round(107.25) == 107


# ── Z bazą ──────────────────────────────────────────────────────────────────


@pytest.fixture
async def db():
    import app.models  # noqa: F401  (zarejestruj wszystkie mappery)
    from app.core.database import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        await session.execute(
            text("update candidates set rate_latest_hourly = null where rate_latest_hourly is not null")
        )
        try:
            yield session
        finally:
            await session.rollback()


async def _people(
    db,
    n: int,
    *,
    rate: float = 100,
    skills: tuple[tuple[str, int | None], ...] = (("java", 120),),
    city: str | None = None,
    position: str | None = None,
    rate_age_days: int = 30,
    status=None,
    **extra,
) -> None:
    from app.models.candidate import Candidate, CandidateStatus
    from app.models.candidate_skill_usage import CandidateSkillUsage

    people = [
        Candidate(
            name="Test",
            lastname=f"Rynek{i}",
            email=f"rynek-{uuid.uuid4().hex[:12]}@example.com",
            status=status or CandidateStatus.active,
            city=city,
            cv_extracted_data={"current_position": position} if position else {},
            rate_latest_hourly=rate,
            rate_latest_at=local_now() - timedelta(days=rate_age_days),
            **extra,
        )
        for i in range(n)
    ]
    db.add_all(people)
    await db.flush()
    db.add_all(
        CandidateSkillUsage(
            candidate_id=person.id,
            skill_canonical=name,
            skill_raw=name,
            months=months,
            contexts=[],
            provenance="cv",
        )
        for person in people
        for name, months in skills
    )
    await db.flush()


async def test_grupa_29_to_za_malo_30_wystarcza(db):
    await _people(db, MIN_GROUP - 1, city="Kraków")
    assert await mr.market_rate_for(db, role="java", years=10, city="Krakow") is None

    await _people(db, 1, city="krakow")
    rate = await mr.market_rate_for(db, role="java", years=10, city="Krakow")
    assert rate is not None and rate.n == MIN_GROUP
    assert rate.group.model_dump() == {
        "role_label": "Java", "years_bucket": "8+", "city": "Kraków", "widened": False,
    }
    assert (rate.p25, rate.median, rate.p75) == (100, 100, 100)


async def test_percentyle_z_bazy(db):
    for i in range(MIN_GROUP):
        await _people(db, 1, rate=100 + i)
    rate = await mr.market_rate_for(db, role="java", years=None, city=None)
    # 100…129: p25 = 107,25, mediana = 114,5, p75 = 121,75
    assert (rate.p25, rate.median, rate.p75, rate.n) == (107, 115, 122, MIN_GROUP)
    assert rate.group.widened is False and rate.group.years_bucket is None


async def test_poszerzanie_najpierw_bez_miasta(db):
    await _people(db, 10, city="Kraków")
    await _people(db, 25, city="Gdańsk")
    rate = await mr.market_rate_for(db, role="java", years=9, city="Kraków")
    assert (rate.group.years_bucket, rate.group.city, rate.group.widened, rate.n) == ("8+", None, True, 35)


async def test_poszerzanie_potem_sasiednie_lata(db):
    await _people(db, 10, city="Kraków")
    await _people(db, 25, skills=(("java", 72),))  # 6 lat
    await _people(db, 40, skills=(("java", 24),))  # 2 lata, poza „5+”
    rate = await mr.market_rate_for(db, role="java", years=9, city="Kraków")
    assert (rate.group.years_bucket, rate.group.city, rate.group.widened, rate.n) == ("5+", None, True, 35)


async def test_poszerzanie_na_koniec_sama_rola(db):
    await _people(db, 10, city="Kraków")
    await _people(db, 25, skills=(("java", 24),))
    await _people(db, 5, skills=(("java", None),))  # bez lat liczy się tylko w samej roli
    rate = await mr.market_rate_for(db, role="java", years=9, city="Kraków")
    assert (rate.group.years_bucket, rate.group.city, rate.group.widened, rate.n) == (None, None, True, 40)


async def test_brak_wyniku_gdy_nawet_sama_rola_ponizej_progu(db):
    await _people(db, MIN_GROUP - 1)
    await _people(db, 50, skills=(("python", 120),))
    assert await mr.market_rate_for(db, role="java", years=None, city=None) is None


async def test_stare_stawki_nie_licza_sie(db):
    await _people(db, MIN_GROUP - 1)
    await _people(db, 5, rate_age_days=400)
    assert await mr.market_rate_for(db, role="java", years=None, city=None) is None


async def test_stawki_poza_60_400_nie_licza_sie(db):
    await _people(db, MIN_GROUP - 2)
    for rate in (59, 401, 1200):
        await _people(db, 1, rate=rate)
    assert await mr.market_rate_for(db, role="java", years=None, city=None) is None

    await _people(db, 1, rate=60)
    await _people(db, 1, rate=400)
    rate = await mr.market_rate_for(db, role="java", years=None, city=None)
    assert rate.n == MIN_GROUP


async def test_czarna_lista_i_usunieci_nie_licza_sie(db):
    from app.models.candidate import CandidateStatus

    await _people(db, MIN_GROUP - 1)
    await _people(db, 1, status=CandidateStatus.blacklisted)
    await _people(db, 1, blacklisted_at=local_now())
    await _people(db, 1, external_deleted_at=local_now())
    assert await mr.market_rate_for(db, role="java", years=None, city=None) is None


async def test_tester_z_java_w_cv_liczy_sie_jako_tester(db):
    await _people(db, MIN_GROUP, position="QA Engineer")
    assert await mr.market_rate_for(db, role="java", years=None, city=None) is None
    rate = await mr.market_rate_for(db, role="tester", years=10, city=None)
    assert (rate.group.role_label, rate.group.years_bucket, rate.n) == ("Tester", "8+", MIN_GROUP)


async def test_premia_tylko_gdy_obie_strony_maja_30(db):
    await _people(db, 30, rate=130, skills=(("java", 120), ("spring boot", 60)))
    await _people(db, 30, rate=110, skills=(("java", 120), ("docker", 30)))
    await _people(db, 29, rate=150, skills=(("java", 120), ("kafka", 30)))
    rate = await mr.market_rate_for(db, role="java", years=10, city=None)
    assert rate.n == 89

    premiums = await mr.tech_premiums(
        db, role="java", group=rate.group, skills=["Spring Boot", "docker", "kafka", "java", "rust"]
    )
    # docker ma premię ujemną, kafka 29 osób z, java i rust < 30 po jednej ze stron
    assert [(p.name, p.premium) for p in premiums] == [("Spring Boot", 20)]


async def test_premia_liczona_w_tej_samej_grupie(db):
    await _people(db, 30, rate=130, city="Gdańsk", skills=(("java", 120), ("spring boot", 60)))
    await _people(db, 30, rate=110, city="Gdańsk")
    await _people(db, 30, rate=200, skills=(("java", 120), ("spring boot", 60)))
    rate = await mr.market_rate_for(db, role="java", years=10, city="Gdansk")
    assert rate.group.city == "Gdańsk" and rate.n == 60
    premiums = await mr.tech_premiums(db, role="java", group=rate.group, skills=["spring boot"])
    assert [(p.name, p.premium) for p in premiums] == [("spring boot", 20)]
    assert await mr.tech_premiums(db, role="java", group=rate.group, skills=[]) == []
