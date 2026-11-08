"""„Lata z technologią” (08.11.2026): „Java · co najmniej 3 lata” w obu silnikach.

Lata pochodzą WYŁĄCZNIE z osi technologii z odczytu CV
(`candidate_skill_usage.months` — suma miesięcy stanowisk i projektów).
Osoba z technologią, ale bez lat, zostaje w grupie „bez danych o latach”
(`unknown_fields: ["skill_years"]`), chyba że braki są ukryte.

Część bez bazy sprawdza parser i reguły; część z bazą zadaje L
(`GET /api/candidates`) i S (`POST /api/search/candidates`) to samo pytanie
i wymaga tego samego zbioru osób (zasada z `test_search_engines_contract.py`).
"""

from __future__ import annotations

import uuid
from typing import Any, Optional

import pytest

from app.services import candidate_search_predicates as predicates

# ── Bez bazy ────────────────────────────────────────────────────────────────


def test_parser_czyta_technologie_i_lata():
    assert predicates.parse_skill_years(["Java:3", " C++ : 2 ", "ASP.NET:1"]) == [
        predicates.SkillYears("Java", 3),
        predicates.SkillYears("C++", 2),
        predicates.SkillYears("ASP.NET", 1),
    ]


def test_parser_ta_sama_technologia_dwa_razy_bierze_wyzszy_prog():
    assert predicates.parse_skill_years(["Java:2", "java:5", "JAVA:3"]) == [
        predicates.SkillYears("Java", 5)
    ]


def test_parser_pomija_puste_wiersze():
    assert predicates.parse_skill_years(["", "  ", None]) == []
    assert predicates.parse_skill_years(None) == []


@pytest.mark.parametrize(
    "value",
    ["Java", ":3", "Java:", "Java:trzy", "Java:0", "Java:31", "Java:-1", "x" * 121 + ":2"],
)
def test_parser_odrzuca_zly_wiersz(value):
    with pytest.raises(predicates.InvalidSkillYears):
        predicates.parse_skill_years([value])


def test_parser_najwyzej_piec_technologii():
    with pytest.raises(predicates.InvalidSkillYears):
        predicates.parse_skill_years([f"T{i}:1" for i in range(6)])


def test_los_osoby_bez_lat_zalezy_tylko_od_ukrycia():
    for version in (1, 2):
        for engine in ("list", "search"):
            sem = predicates.semantics_for(engine, version)
            assert sem.skill_years_unknown == "include"
            assert (
                predicates.semantics_for(
                    engine, version, hide_unknown_skill_years=True
                ).skill_years_unknown
                == "exclude"
            )
            assert (
                predicates.semantics_for(engine, version, True).skill_years_unknown
                == "exclude"
            )
    # Przełącznik innego filtru nie ukrywa braków lat.
    assert (
        predicates.semantics_for("list", 2, hide_unknown_rate=True).skill_years_unknown
        == "include"
    )


def test_brak_lat_przy_ktorymkolwiek_wierszu_to_brak_danych():
    known = {"skill": "Java", "years_min": 3, "months": 60, "source": "cv_roles"}
    missing = {"skill": "Kafka", "years_min": 2, "months": None, "source": None}
    assert predicates.skill_years_unknown_for([known]) is False
    assert predicates.skill_years_unknown_for([known, missing]) is True
    assert predicates.skill_years_unknown_for(None) is False


def test_unknown_fields_dopisuje_lata_na_koncu():
    class Row:
        city = location = country = None
        years_it_experience = None
        cv_extracted_data = None

    out = predicates.unknown_fields_for(
        Row(),
        location_active=True,
        country_active=False,
        experience_active=True,
        rate_active=False,
        skill_years_unknown=True,
    )
    assert out == ["location", "experience", "skill_years"]


def test_bez_filtru_lat_nie_ma_rangi_brakow():
    sem = predicates.semantics_for("list", 2)
    assert predicates.skill_years_unknown_rank([], sem) is None
    assert predicates.skill_years_clauses([], sem) == []
    hidden = predicates.semantics_for("list", 2, hide_unknown_skill_years=True)
    assert (
        predicates.skill_years_unknown_rank([predicates.SkillYears("Java", 3)], hidden)
        is None
    )


def test_grupa_ma_regule_brakow_danych():
    from app.services.structured_candidate_search import NULL_POLICY, NullPolicy

    assert NULL_POLICY["skill_years"].policy is NullPolicy.include


# ── Z bazą: L i S na tej samej populacji ────────────────────────────────────

NONCE = "zq" + "".join(chr(97 + int(c, 16)) for c in uuid.uuid4().hex[:10])
_IDS: dict[str, int] = {}

# Rodzina aliasów jak na produkcji: oś trzyma `canonical_of(nazwa)` z chwili
# odczytu, profil — to, co przyszło z CV.
_ALIASES = {
    "mssql": "microsoft sql server",
    "ms sql": "microsoft sql server",
    "microsoft sql server": "microsoft sql server",
}


async def _seed() -> dict[str, int]:
    if _IDS:
        return _IDS
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate, CandidateStatus
    from app.models.candidate_skill_usage import CandidateSkillUsage

    def person(key: str, **kw: Any) -> Candidate:
        return Candidate(
            name=key.capitalize(),
            lastname=f"Lata{key}",
            status=CandidateStatus.active,
            email=f"{key}-{uuid.uuid4().hex[:10]}@example.com",
            linkedin_current_company=NONCE,
            **kw,
        )

    rows = {
        "a": person("a", skills=["Java"]),  # 5 lat z dat stanowisk
        "b": person("b", skills=["Java"]),  # 2 lata — za mało
        "c": person("c", skills=["Java"]),  # Java bez osi
        "d": person("d", skills=[{"name": "Java"}]),  # oś bez długości okresu
        "e": person("e", skills=["Python"]),  # Java tylko na osi (4 lata)
        "f": person("f", skills=["Python"]),  # bez Javy
        "g": person("g", skills=["MSSQL"]),  # alias, dwa wiersze osi
        "h": person("h", skills=["Java", "Kafka"]),  # Java 5 lat, Kafka bez lat
    }
    usage = [
        ("a", "java", 60),
        ("b", "java", 24),
        ("d", "java", None),
        ("e", "java", 48),
        ("g", "microsoft sql server", 40),
        ("g", "mssql", 10),
        ("h", "java", 60),
    ]
    async with AsyncSessionLocal() as db:
        db.add_all(rows.values())
        await db.flush()
        for key, skill, months in usage:
            db.add(
                CandidateSkillUsage(
                    candidate_id=rows[key].id,
                    skill_canonical=skill,
                    skill_raw=skill,
                    months=months,
                    contexts=[],
                    provenance="cv",
                )
            )
        await db.commit()
        for key, row in rows.items():
            _IDS[key] = row.id
    return _IDS


@pytest.fixture
def aliases():
    from app.services.scoring_service import ALIAS_MAP, set_alias_map

    saved = dict(ALIAS_MAP)
    set_alias_map(_ALIASES)
    try:
        yield
    finally:
        set_alias_map(saved)


def _key_of(item_id: int) -> Optional[str]:
    return {v: k for k, v in _IDS.items()}.get(item_id)


async def _list_raw(client, headers, **params: Any) -> dict:
    await _seed()
    query: list[tuple[str, Any]] = [
        ("q_all", NONCE),
        ("page_size", 100),
        ("sort", "newest"),
    ]
    params = {"semantics_version": 2, **params}
    for key, value in params.items():
        if value is None:
            continue
        if isinstance(value, (list, tuple)):
            query.extend((key, v) for v in value)
        else:
            query.append((key, value))
    resp = await client.get("/api/candidates", params=query, headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _search_raw(client, headers, **body: Any) -> dict:
    await _seed()
    payload = {
        "q_all": [NONCE],
        "page": 1,
        "page_size": 200,
        "semantics_version": 2,
        **body,
    }
    resp = await client.post("/api/search/candidates", json=payload, headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _rows(data: dict) -> dict[str, dict]:
    return {
        key: item
        for item in data["items"]
        if (key := _key_of(item["id"])) is not None
    }


async def _both(client, headers, expected: set[str], **flt: Any) -> tuple[dict, dict]:
    lst = _rows(await _list_raw(client, headers, **flt))
    srch = _rows(await _search_raw(client, headers, **flt))
    assert set(lst) == set(srch), (
        f"silniki się rozjechały: L={sorted(lst)} S={sorted(srch)} ({flt})"
    )
    assert set(lst) == expected, f"oba zgodne, ale zwracają {sorted(lst)}"
    return lst, srch


@pytest.mark.asyncio
async def test_java_trzy_lata_te_same_osoby_w_obu(app_client, app_auth_headers):
    # a, h: 5 lat; e: 4 lata z osi bez Javy w profilu; c, d: Java bez lat.
    # b: 2 lata (za mało); f: bez Javy; g: inna technologia.
    lst, srch = await _both(
        app_client,
        app_auth_headers,
        {"a", "c", "d", "e", "h"},
        skill_years=["Java:3"],
    )
    for rows in (lst, srch):
        assert rows["a"]["unknown_fields"] == []
        assert rows["e"]["unknown_fields"] == []
        assert rows["c"]["unknown_fields"] == ["skill_years"]
        assert rows["d"]["unknown_fields"] == ["skill_years"]
        assert rows["a"]["skill_years"] == [
            {"skill": "Java", "years_min": 3, "months": 60, "source": "cv_roles"}
        ]
        assert rows["c"]["skill_years"] == [
            {"skill": "Java", "years_min": 3, "months": None, "source": None}
        ]


@pytest.mark.asyncio
async def test_ukrycie_brakow_zostawia_same_lata_z_cv(app_client, app_auth_headers):
    await _both(
        app_client,
        app_auth_headers,
        {"a", "e", "h"},
        skill_years=["Java:3"],
        hide_unknown_skill_years=True,
    )
    await _both(
        app_client,
        app_auth_headers,
        {"a", "e", "h"},
        skill_years=["Java:3"],
        hide_unknown=True,
    )


@pytest.mark.asyncio
async def test_lista_liczy_spelniajacych_i_stawia_braki_na_koncu(
    app_client, app_auth_headers
):
    data = await _list_raw(app_client, app_auth_headers, skill_years=["Java:3"])
    order = [k for item in data["items"] if (k := _key_of(item["id"]))]
    assert data["known_match_count"] == 3
    assert set(order[:3]) == {"a", "e", "h"}
    assert set(order[3:]) == {"c", "d"}


@pytest.mark.asyncio
async def test_kazdy_wiersz_musi_byc_spelniony(app_client, app_auth_headers):
    # Java ≥ 3 ORAZ Kafka ≥ 2: tylko h ma obie technologie; Kafka bez lat.
    lst, srch = await _both(
        app_client,
        app_auth_headers,
        {"h"},
        skill_years=["Java:3", "Kafka:2"],
    )
    for rows in (lst, srch):
        assert rows["h"]["unknown_fields"] == ["skill_years"]
        assert [e["months"] for e in rows["h"]["skill_years"]] == [60, None]


@pytest.mark.asyncio
async def test_prog_wyzszy_niz_lata_wycina(app_client, app_auth_headers):
    # 5 lat: a i h mają dokładnie 60 miesięcy, e 48 — odpada.
    await _both(
        app_client,
        app_auth_headers,
        {"a", "c", "d", "h"},
        skill_years=["Java:5"],
        hide_unknown_skill_years=False,
    )


@pytest.mark.asyncio
async def test_alias_i_kilka_wierszy_osi_bierze_najdluzszy(
    app_client, app_auth_headers, aliases
):
    # „MS SQL” z profilu i dwa wiersze osi tej samej rodziny (40 i 10 mies.).
    lst, srch = await _both(
        app_client, app_auth_headers, {"g"}, skill_years=["ms sql:3"]
    )
    for rows in (lst, srch):
        assert rows["g"]["skill_years"][0]["months"] == 40
    await _both(
        app_client,
        app_auth_headers,
        set(),
        skill_years=["ms sql:4"],
        hide_unknown_skill_years=True,
    )


@pytest.mark.asyncio
async def test_lista_v1_tez_rozumie_filtr(app_client, app_auth_headers):
    data = await _list_raw(
        app_client, app_auth_headers, skill_years=["Java:3"], semantics_version=None
    )
    assert {k for item in data["items"] if (k := _key_of(item["id"]))} == {
        "a",
        "c",
        "d",
        "e",
        "h",
    }


@pytest.mark.asyncio
async def test_zly_wiersz_to_422_w_obu(app_client, app_auth_headers):
    await _seed()
    resp = await app_client.get(
        "/api/candidates",
        params=[("skill_years", "Java:0")],
        headers=app_auth_headers,
    )
    assert resp.status_code == 422
    assert "od 1 do 30 lat" in resp.text
    resp = await app_client.post(
        "/api/search/candidates",
        json={"skill_years": ["Java"], "semantics_version": 2},
        headers=app_auth_headers,
    )
    assert resp.status_code == 422
    assert "technologia:lata" in resp.text
