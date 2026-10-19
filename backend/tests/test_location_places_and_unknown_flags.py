"""D5 i D6 (19.10.2026) bez bazy: kilka miast z promieniami i braki danych
osobno dla stawki i miasta.

* ``parse_location_places`` — kształt ``Miasto[:km]``, limit 10, promień 1–300;
* ``location_places_clause`` — SUMA miast, promieni (kilka środków) i województw;
* ``Semantics`` — nowe przełączniki nigdy nie poszerzają wyniku, a bez nich
  v1/v2 i ``hide_unknown`` odpowiadają dokładnie jak dotąd;
* lista: licznik osób z danymi w tym samym oknie (``FILTER … OVER ()``),
  422 przed zbudowaniem filtrów, zapis wyszukiwania przenosi nowe pola.

Zachowanie na prawdziwej bazie: ``test_list_location_places_and_unknown.py``.
"""

from __future__ import annotations

import itertools
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy.dialects import postgresql

from app.services import candidate_search_predicates as predicates
from app.services import pl_places
from app.services import saved_search_payload as ssp


def _sql(clause) -> str:
    return str(clause.compile(dialect=postgresql.dialect()))


def _array_params(clause) -> list[str]:
    compiled = clause.compile(dialect=postgresql.dialect())
    out: list[str] = []
    for value in compiled.params.values():
        if isinstance(value, list):
            out.extend(value)
    return out


# ── Parser par miasto–promień ────────────────────────────────────────────────


def test_parse_pairs_and_plain_cities():
    places = predicates.parse_location_places(["Warszawa:30", "Łódź", " Kraków : 50 "])
    assert places == [
        predicates.LocationPlace("Warszawa", 30),
        predicates.LocationPlace("Łódź", None),
        predicates.LocationPlace("Kraków", 50),
    ]


def test_parse_skips_empty_and_duplicates_but_keeps_other_radius():
    places = predicates.parse_location_places(
        ["", "  ", "Łódź", "lodz", "Łódź:20", "Warszawa:"]
    )
    assert places == [
        predicates.LocationPlace("Łódź", None),
        predicates.LocationPlace("Łódź", 20),
        predicates.LocationPlace("Warszawa", None),
    ]


def test_parse_none_is_empty():
    assert predicates.parse_location_places(None) == []


def test_parse_rejects_more_than_ten_cities():
    values = [f"Miasto{i}" for i in range(11)]
    with pytest.raises(predicates.InvalidLocationPlaces, match="najwyżej 10"):
        predicates.parse_location_places(values)
    assert len(predicates.parse_location_places(values[:10])) == 10


@pytest.mark.parametrize("raw", ["Warszawa:0", "Warszawa:301"])
def test_parse_rejects_radius_out_of_range(raw):
    with pytest.raises(predicates.InvalidLocationPlaces, match="od 1 do 300"):
        predicates.parse_location_places([raw])


def test_parse_non_numeric_tail_is_part_of_the_name():
    assert predicates.parse_location_places(["Miasto:abc"]) == [
        predicates.LocationPlace("Miasto:abc", None)
    ]


# ── Suma lokalizacji ────────────────────────────────────────────────────────

V2 = predicates.semantics_for("list", 2)
V2_HIDE_LOCATION = predicates.semantics_for("list", 2, hide_unknown_location=True)


def test_union_of_two_radii_contains_both_surroundings():
    clause = predicates.location_places_clause(
        [
            predicates.LocationPlace("Warszawa", 30),
            predicates.LocationPlace("Kraków", 20),
        ],
        None,
        V2_HIDE_LOCATION,
    )
    keys = set(_array_params(clause))
    assert {"warszawa", "pruszkow", "krakow", "wieliczka"} <= keys
    # Jedno porównanie z jedną listą kluczy — nie część wspólna promieni.
    assert _sql(clause).count("= ANY") == 2


def test_union_mixes_text_city_radius_and_voivodeship_with_or():
    clause = predicates.location_places_clause(
        [predicates.LocationPlace("Łódź"), predicates.LocationPlace("Warszawa", 10)],
        ["pomorskie"],
        V2_HIDE_LOCATION,
    )
    sql = _sql(clause)
    keys = set(_array_params(clause))
    assert "gdynia" in keys and "warszawa" in keys  # promień i województwo w sumie
    assert " OR " in sql
    # Bez promienia Łódź to dopasowanie tekstu, jak w `location_cities`.
    assert "lodz" not in keys


def test_union_keeps_people_without_city_unless_hidden():
    places = [predicates.LocationPlace("Warszawa", 30)]
    with_unknown = _sql(predicates.location_places_clause(places, None, V2))
    hidden = _sql(predicates.location_places_clause(places, None, V2_HIDE_LOCATION))
    assert "candidates.city IS NULL AND candidates.location IS NULL" in with_unknown
    assert "IS NULL AND candidates.location IS NULL" not in hidden


def test_union_v1_drops_people_without_city():
    v1 = predicates.semantics_for("list", None)
    sql = _sql(
        predicates.location_places_clause([predicates.LocationPlace("Łódź")], None, v1)
    )
    assert "candidates.city IS NULL AND candidates.location IS NULL" not in sql


def test_union_unknown_town_with_radius_is_unknown_place():
    with pytest.raises(predicates.UnknownPlace, match="Atlantyda"):
        predicates.location_places_clause(
            [predicates.LocationPlace("Atlantyda", 10)], None, V2
        )
    # Bez promienia nieznana nazwa to zwykłe dopasowanie tekstu.
    assert (
        predicates.location_places_clause(
            [predicates.LocationPlace("Atlantyda")], None, V2
        )
        is not None
    )


def test_union_unknown_voivodeship_is_unknown_place():
    with pytest.raises(predicates.UnknownPlace, match="atlantydzkie"):
        predicates.location_places_clause([], ["atlantydzkie"], V2)


def test_union_without_anything_is_none():
    assert predicates.location_places_clause([], [], V2) is None


# ── „16 km od Warszawy” ─────────────────────────────────────────────────────


def test_place_distance_nearest_center_in_radius():
    places = [
        predicates.LocationPlace("Kraków", 50),
        predicates.LocationPlace("Warszawa", 30),
    ]
    got = predicates.place_distance(SimpleNamespace(city="Pruszków"), places)
    assert got is not None
    assert got["place"] == "Pruszków" and got["center"] == "Warszawa"
    assert 10 <= got["km"] <= 25


def test_place_distance_uses_location_when_city_missing():
    got = predicates.place_distance(
        SimpleNamespace(city=None, location="Pruszków, mazowieckie"),
        [predicates.LocationPlace("Warszawa", 30)],
    )
    assert got is not None and got["center"] == "Warszawa"


@pytest.mark.parametrize(
    "candidate",
    [
        SimpleNamespace(city="Warszawa"),  # w samym środku
        SimpleNamespace(city="Gdynia"),  # poza promieniem
        SimpleNamespace(city="Atlantyda"),  # spoza spisu
        SimpleNamespace(city=None, location=None),
    ],
)
def test_place_distance_none(candidate):
    assert (
        predicates.place_distance(candidate, [predicates.LocationPlace("Warszawa", 30)])
        is None
    )


def test_place_distance_without_radius_is_none():
    assert (
        predicates.place_distance(
            SimpleNamespace(city="Pruszków"), [predicates.LocationPlace("Warszawa")]
        )
        is None
    )


def test_distance_km_is_symmetric():
    a, b = pl_places.resolve("Warszawa"), pl_places.resolve("Łódź")
    assert a is not None and b is not None
    assert 110 <= pl_places.distance_km(a, b) <= 135
    assert pl_places.distance_km(a, b) == pl_places.distance_km(b, a)


# ── Semantyka: nowe przełączniki nigdy nie poszerzają wyniku ───────────────


@pytest.mark.parametrize(
    "engine,version,hide",
    list(itertools.product(["list", "search"], [None, 1, 2], [None, False, True])),
)
def test_without_new_flags_nothing_changes(engine, version, hide):
    base = predicates.Semantics(
        version=2 if version == 2 else 1, engine=engine, hide_unknown=hide
    )
    for flags in ({}, {"hide_unknown_rate": False, "hide_unknown_location": False}):
        sem = predicates.semantics_for(engine, version, hide, **flags)
        assert sem.unknown == base.unknown
        assert sem.rate_unknown == base.rate_unknown
        assert sem.location_unknown == base.unknown


@pytest.mark.parametrize(
    "engine,version,hide",
    list(itertools.product(["list", "search"], [None, 2], [None, False, True])),
)
def test_new_flags_only_hide_their_own_field(engine, version, hide):
    rate = predicates.semantics_for(engine, version, hide, hide_unknown_rate=True)
    assert rate.rate_unknown == "exclude"
    assert rate.location_unknown == rate.unknown  # miasto i staż bez zmian
    location = predicates.semantics_for(
        engine, version, hide, hide_unknown_location=True
    )
    assert location.location_unknown == "exclude"
    assert location.unknown == predicates.semantics_for(engine, version, hide).unknown
    assert (
        location.rate_unknown
        == predicates.semantics_for(engine, version, hide).rate_unknown
    )


def test_rate_clause_hides_missing_rate_with_narrow_flag():
    from decimal import Decimal

    open_sql = _sql(predicates.hourly_rate_clause(None, Decimal(55), V2))
    hidden_sql = _sql(
        predicates.hourly_rate_clause(
            None,
            Decimal(55),
            predicates.semantics_for("list", 2, hide_unknown_rate=True),
        )
    )
    # Ukryte braki = dokładnie warunek listy v1 (sama znana i pasująca stawka).
    v1_sql = _sql(
        predicates.hourly_rate_clause(
            None, Decimal(55), predicates.semantics_for("list", None)
        )
    )
    assert hidden_sql == v1_sql
    assert open_sql != hidden_sql and len(open_sql) > len(hidden_sql)


def test_location_clause_hides_missing_city_with_narrow_flag():
    shown = _sql(predicates.location_clauses(["Kraków"], None, V2)[0])
    hidden = _sql(predicates.location_clauses(["Kraków"], None, V2_HIDE_LOCATION)[0])
    assert "candidates.city IS NULL AND candidates.location IS NULL" in shown
    assert "candidates.city IS NULL AND candidates.location IS NULL" not in hidden


def test_geo_clause_hides_missing_city_with_narrow_flag():
    kw = {"center": "Kraków", "radius_km": 20, "voivodeships": None}
    shown = _sql(predicates.geo_clause(sem=V2, **kw))
    hidden = _sql(predicates.geo_clause(sem=V2_HIDE_LOCATION, **kw))
    # Osoba bez miasta = dodatkowe `coalesce(city, '') = ''` w sumie.
    assert shown.count("coalesce(candidates.city") == (
        hidden.count("coalesce(candidates.city") + 1
    )


# ── Lista: walidacja, licznik z danymi, pary z pojedynczych pól ─────────────


def test_list_rejects_bad_places_before_building_filters():
    from app.api.candidates import _reject_invalid_location_places

    _reject_invalid_location_places(None)
    _reject_invalid_location_places(["Warszawa:30"])
    with pytest.raises(HTTPException) as exc:
        _reject_invalid_location_places(["Warszawa:999"])
    assert exc.value.status_code == 422
    assert "Warszawa" in exc.value.detail


def test_export_body_validates_places():
    from app.api.candidates import CandidateFilterSpec

    with pytest.raises(ValidationError):
        CandidateFilterSpec(location_places=[f"M{i}" for i in range(11)])
    assert CandidateFilterSpec(location_places=["Łódź", "Warszawa:30"])


def test_single_location_and_cities_join_the_union():
    from app.api.candidates import CandidateFilterSpec, _list_location_places

    spec = CandidateFilterSpec(
        location_places=["Łódź"],
        location="Warszawa",
        location_radius_km=30,
        location_cities=["Gdańsk"],
    )
    assert _list_location_places(spec) == [
        predicates.LocationPlace("Łódź"),
        predicates.LocationPlace("Warszawa", 30),
        predicates.LocationPlace("Gdańsk"),
    ]


def test_radius_places_for_row_distance():
    from app.api.candidates import CandidateFilterSpec, _radius_places

    assert _radius_places(CandidateFilterSpec()) == []
    assert _radius_places(CandidateFilterSpec(location="Warszawa")) == []
    assert _radius_places(
        CandidateFilterSpec(location="Warszawa", location_radius_km=20)
    ) == [predicates.LocationPlace("Warszawa", 20)]
    assert _radius_places(
        CandidateFilterSpec(location_places=["Łódź", "Kraków:50"])
    ) == [predicates.LocationPlace("Kraków", 50)]


@pytest.mark.parametrize(
    "spec,active",
    [
        ({}, False),
        ({"semantics_version": 2}, False),
        ({"semantics_version": 2, "max_rate": 55}, True),
        ({"semantics_version": 2, "location_places": ["Łódź"]}, True),
        # v1 wycina braki — nie ma czego rozdzielać.
        ({"max_rate": 55}, False),
        # Globalne „ukryj” — w wyniku same trafienia.
        ({"semantics_version": 2, "max_rate": 55, "hide_unknown": True}, False),
        # Ukryte braki stawki — sama stawka nie zostawia braków.
        ({"semantics_version": 2, "max_rate": 55, "hide_unknown_rate": True}, False),
        (
            {
                "semantics_version": 2,
                "max_rate": 55,
                "location": "Łódź",
                "hide_unknown_rate": True,
            },
            True,
        ),
        (
            {
                "semantics_version": 2,
                "location": "Łódź",
                "hide_unknown_location": True,
            },
            False,
        ),
    ],
)
def test_known_count_only_when_unknowns_can_be_in_result(spec, active):
    from sqlalchemy import select

    from app.api.candidates import CandidateFilterSpec, _with_window_counts
    from app.models.candidate import Candidate

    sql = _sql(_with_window_counts(select(Candidate.id), CandidateFilterSpec(**spec)))
    assert "count(*) OVER ()" in sql
    assert ("FILTER (WHERE" in sql) is active
    assert ("known_count" in sql) is active


def test_unknown_rank_counts_location_places_as_location_filter():
    from app.api.candidates import CandidateFilterSpec, _unknown_rank_expr

    rank = _unknown_rank_expr(
        CandidateFilterSpec(semantics_version=2, location_places=["Warszawa:30"])
    )
    assert rank is not None
    assert "candidates.city IS NULL" in _sql(rank)


# ── Zapisane wyszukiwania: nowe pola w obie strony ─────────────────────────


def test_saved_search_round_trips_new_list_fields():
    api = {
        "semantics_version": 2,
        "max_rate": 55,
        "hide_unknown_rate": True,
        "hide_unknown_location": True,
        "location_places": ["Warszawa:30", "Łódź"],
        "voivodeship": ["pomorskie"],
    }
    unified = ssp.list_api_to_unified(api)
    assert unified["list_only"]["location_places"] == ["Warszawa:30", "Łódź"]
    assert unified["list_only"]["hide_unknown_rate"] is True
    params = ssp.unified_to_list_params(unified)
    for key in (
        "hide_unknown_rate",
        "hide_unknown_location",
        "location_places",
        "voivodeship",
    ):
        assert params[key] == api[key]
    assert ssp.list_engine_gaps(unified) == []
