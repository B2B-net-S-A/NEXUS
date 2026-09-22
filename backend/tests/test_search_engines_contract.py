"""Kontrakt: DWA silniki wyszukiwania kandydatów, JEDNA semantyka filtrów.

* **L** = ``GET /api/candidates`` (lista, ⌘K, alerty zapisanych wyszukiwań),
* **S** = ``POST /api/search/candidates`` (wyszukiwarka + ręczne szukanie
  w rekrutacji).

Dla każdej decyzji właściciela produktu (09.2026, tabela w
``app/services/candidate_search_predicates.py``) ten plik zadaje OBU silnikom
równoważne żądanie i wymaga TEGO SAMEGO zbioru identyfikatorów.

Populacja jest wspólna dla całego pliku i zakładana raz: 13 kandydatów
skrojonych tak, żeby każda pozycja tabeli decyzji miała co najmniej jedną osobę
po każdej stronie granicy. Baza testowa jest współdzielona i NIE jest
czyszczona, więc każde żądanie jest zawężone do własnych wierszy
(``q_all=[NONCE]`` — fraza siedzi w ``linkedin_current_company``), a asercje
patrzą wyłącznie na własne id.

Wyszukiwanie wektorowe nie jest tu dotykane: żądania do S idą w trybie
``boolean``, a jedyny test trybu ``hybrid`` podstawia pulę retrievalu tak samo
jak ``test_hybrid_search_sort_and_soft_rank``.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any, Optional

import pytest

# Same litery (a–p): fraza przechodzi zarówno jako token FTS, jak i jako
# „nazwisko" w detekcji trybu tekstu.
NONCE = "zq" + "".join(chr(97 + int(c, 16)) for c in uuid.uuid4().hex[:10])
_PHONE_TAIL = f"{uuid.uuid4().int % 10**9:09d}"

_IDS: dict[str, int] = {}
_CC: dict[str, int] = {}


async def _seed() -> dict[str, int]:
    if _IDS:
        return _IDS
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import AvailabilityStatus, Candidate, CandidateStatus
    from app.models.competence_category import (
        CandidateCompetenceCategory,
        CompetenceCategory,
    )

    def person(key: str, **kw: Any) -> Candidate:
        kw.setdefault("name", key.capitalize())
        kw.setdefault("lastname", f"Testowy{key}")
        kw.setdefault("status", CandidateStatus.active)
        return Candidate(
            email=f"{key}-{uuid.uuid4().hex[:10]}@example.com",
            linkedin_current_company=NONCE,
            **kw,
        )

    async with AsyncSessionLocal() as db:
        cats = []
        for i in range(2):
            cat = CompetenceCategory(
                slug=f"ct-{NONCE[:20]}-{i}",
                name_pl=f"Kontrakt {i}",
                name_en=f"Contract {i}",
                description="test",
                keywords=[],
            )
            db.add(cat)
            cats.append(cat)
        await db.flush()
        _CC["one"], _CC["two"] = cats[0].id, cats[1].id

        rows = {
            # pełny profil: wszystko podane wprost
            "a": person(
                "a",
                skills=["Python", "React"],
                tags=["java"],
                location="Warszawa",
                city="Warszawa",
                country="PL",
                expected_rate_hourly=Decimal("100"),
                expected_rate_currency="PLN",
                years_it_experience=6,
                competence_category_id=cats[0].id,
                open_to_side_projects=True,
                availability_status=AvailabilityStatus.actively_looking,
            ),
            # doświadczenie TYLKO z koszyka Traffita, brak stawki, CC poboczna
            "b": person(
                "b",
                skills=["Python"],
                tags=["javascript"],
                location="Kraków",
                country="PL",
                cv_extracted_data={"traffit_experience": "2-5"},
                competence_category_id=cats[1].id,
                open_to_sales_support=True,
                availability_status=AvailabilityStatus.open_to_offers,
            ),
            # kształt słownikowy umiejętności, „%" w lokalizacji, koszyk „5+"
            "c": person(
                "c",
                skills=[{"name": "Java", "level": "senior"}],
                tags=["vip"],
                location="100% remote",
                country="DE",
                expected_rate_hourly=Decimal("200"),
                expected_rate_currency="PLN",
                cv_extracted_data={"traffit_experience": "5+"},
            ),
            # BRAK danych: umiejętności, lokalizacji, doświadczenia; stawka
            # w walucie, której nie porównujemy; CC wyłącznie przez legacy FK
            "d": person(
                "d",
                tags=["vip-2024"],
                expected_rate_hourly=Decimal("150"),
                expected_rate_currency="EUR",
                competence_category_id=cats[0].id,
                open_to_expert_consult=True,
                open_to_side_projects=True,
            ),
            # podłańcuchy, które NIE są umiejętnością „Go"
            "e": person(
                "e",
                skills=["Django", "MongoDB"],
                location="Gdansk A_B",
                country="PL",
                years_it_experience=1,
                expected_rate_hourly=Decimal("60"),
            ),
            "f": person(
                "f",
                skills=["Go", "Python"],
                location="Gdansk AXB",
                country="PL",
                years_it_experience=12,
            ),
            # „100" + cokolwiek — trafia tylko przy NIEescapowanym „%"
            "g": person(
                "g",
                skills=["React", "Vue"],
                location="Aleja 1000-lecia",
                status=CandidateStatus.passive,
                availability_status=AvailabilityStatus.not_looking,
            ),
            # osoba do szukania po nazwisku / e-mailu / telefonie
            "h": person(
                "h",
                name="Łucja",
                lastname=f"Żółć{NONCE}",
                phone=f"+48 {_PHONE_TAIL[:3]} {_PHONE_TAIL[3:6]} {_PHONE_TAIL[6:]}",
                skills=["Kotlin"],
            ),
            # sobowtór: nazwisko osoby „h" pada w cudzym podsumowaniu
            "i": person(
                "i",
                ai_summary=f"Polecony przez: Łucja Żółć{NONCE}.",
                skills=["Kotlin", "Java"],
            ),
            # umiejętności podwójnie zakodowane (string JSON w JSONB)
            "j": person("j", skills='["Go", "Rust"]', tags=["Java"]),
            # wielkość liter i alias zapisu
            "k": person("k", skills=["python", "REACT"], tags=["VIP"]),
            "l": person(
                "l",
                status=CandidateStatus.blacklisted,
                skills=["Python"],
                availability_status=AvailabilityStatus.actively_looking,
            ),
            # tylko miasto, bez pola `location`
            "m": person("m", city="Warszawa", country="pl", skills=["Rust"]),
        }
        db.add_all(rows.values())
        await db.flush()
        db.add(
            CandidateCompetenceCategory(
                candidate_id=rows["b"].id,
                competence_category_id=cats[0].id,
                is_primary=False,
            )
        )
        await db.commit()
        for key, row in rows.items():
            _IDS[key] = row.id
    return _IDS


def _keys(ids: dict[str, int], found: set[int]) -> set[str]:
    reverse = {v: k for k, v in ids.items()}
    return {reverse[i] for i in found if i in reverse}


async def _list(client, headers, **params: Any) -> set[str]:
    ids = await _seed()
    query: list[tuple[str, Any]] = [("q_all", NONCE), ("page_size", 100)]
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
    return _keys(ids, {item["id"] for item in resp.json()["items"]})


async def _search_raw(client, headers, **body: Any) -> dict:
    await _seed()
    payload = {
        "q_all": [NONCE],
        "page": 1,
        "page_size": 200,
        "semantics_version": 2,
        **body,
    }
    payload = {k: v for k, v in payload.items() if v is not None}
    resp = await client.post("/api/search/candidates", json=payload, headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _search(client, headers, **body: Any) -> set[str]:
    data = await _search_raw(client, headers, **body)
    return _keys(_IDS, {item["id"] for item in data["items"]})


async def _both(
    client,
    headers,
    *,
    lst: dict[str, Any],
    srch: dict[str, Any],
    expected: Optional[set[str]] = None,
) -> set[str]:
    from_list = await _list(client, headers, **lst)
    from_search = await _search(client, headers, **srch)
    assert from_list == from_search, (
        f"silniki się rozjechały: L={sorted(from_list)} S={sorted(from_search)} "
        f"(L: {lst} | S: {srch})"
    )
    if expected is not None:
        assert from_list == expected, f"oba zgodne, ale zwracają {sorted(from_list)}"
    return from_list


ALL = set("abcdefghijklm")


# ── Populacja ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_bez_filtrow_oba_silniki_widza_cala_populacje(
    app_client, app_auth_headers
):
    await _both(app_client, app_auth_headers, lst={}, srch={}, expected=ALL)


# ── Umiejętności: trzy kubełki ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_musi_miec_jest_filtrem_twardym_w_obu(app_client, app_auth_headers):
    # „python": a, b, f, k (wielkość liter), l. Brak danych (d) NIE przechodzi.
    await _both(
        app_client,
        app_auth_headers,
        lst={"skills_required": ["Python"]},
        srch={"skills_required": ["Python"]},
        expected={"a", "b", "f", "k", "l"},
    )


@pytest.mark.asyncio
async def test_musi_miec_dwie_umiejetnosci_to_koniunkcja(app_client, app_auth_headers):
    await _both(
        app_client,
        app_auth_headers,
        lst={"skills_required": ["Python", "React"]},
        srch={"skills_required": ["Python", "React"]},
        expected={"a", "k"},
    )


@pytest.mark.asyncio
async def test_grupa_ktorakolwiek_i_skladnia_pipe(app_client, app_auth_headers):
    # Java LUB Go; „Django"/„MongoDB" to nie Go. „a" ma TAG „java" — tagi są
    # częścią przeszukiwanego zrzutu umiejętności (tak było na liście od zawsze).
    expected = {"a", "c", "f", "i", "j"}
    await _both(
        app_client,
        app_auth_headers,
        lst={"skills_required_any_groups": ["java|go"]},
        srch={"skills_required_any_groups": [["java", "go"]]},
        expected=expected,
    )
    # `|` wewnątrz „Musi mieć" znaczy to samo — w obu silnikach.
    await _both(
        app_client,
        app_auth_headers,
        lst={"skills_required": ["java|go"]},
        srch={"skills_required": ["java|go"]},
        expected=expected,
    )


@pytest.mark.asyncio
async def test_wyklucz_jest_twarde_i_rozumie_pipe(app_client, app_auth_headers):
    expected = ALL - {"a", "c", "f", "i", "j"}
    await _both(
        app_client,
        app_auth_headers,
        lst={"skills_excluded": ["go|java"]},
        srch={"skills_excluded": ["go|java"]},
        expected=expected,
    )
    # pole legacy `skills_none` ze składnią `|` — dotąd rozumiała ją tylko lista
    await _both(
        app_client,
        app_auth_headers,
        lst={"skills_none": ["go|java"]},
        srch={"skills_none": ["go|java"]},
        expected=expected,
    )


@pytest.mark.asyncio
async def test_mile_widziane_nie_tnie_w_zadnym_silniku(app_client, app_auth_headers):
    await _both(
        app_client,
        app_auth_headers,
        lst={"skills_preferred": ["Python"]},
        srch={"skills_preferred": ["Python"]},
        expected=ALL,
    )


@pytest.mark.asyncio
async def test_mile_widziane_podbija_ranking_wyszukiwarki(app_client, app_auth_headers):
    data = await _search_raw(
        app_client, app_auth_headers, skills_preferred=["Python"], sort="name"
    )
    own = [i["id"] for i in data["items"] if i["id"] in set(_IDS.values())]
    matchers = {_IDS[k] for k in ("a", "b", "f", "k", "l")}
    head, tail = own[: len(matchers)], own[len(matchers) :]
    assert set(head) == matchers, "osoby z umiejętnością muszą stać PRZED resztą"
    assert not (set(tail) & matchers)


@pytest.mark.asyncio
async def test_legacy_znaczenie_pol_umiejetnosci_zostaje(app_client, app_auth_headers):
    """Zapisane wyszukiwania nie mogą zmienić wyniku: lista tnie, wyszukiwarka
    tylko szereguje. To jest ŚWIADOMIE różne zachowanie tych samych nazw pól —
    zgodne są dopiero pola jawne."""
    assert await _list(app_client, app_auth_headers, skills=["Python"]) == {
        "a",
        "b",
        "f",
        "k",
        "l",
    }
    assert await _list(
        app_client,
        app_auth_headers,
        skills=["Java", "Go"],
        skill_combine="or",
    ) == {"a", "c", "f", "i", "j"}
    assert await _list(app_client, app_auth_headers, skills_any=["java|go"]) == {
        "a",
        "c",
        "f",
        "i",
        "j",
    }
    assert await _search(app_client, app_auth_headers, skills_must=["Python"]) == ALL
    assert await _search(app_client, app_auth_headers, skills_any=["Java"]) == ALL


# ── Tekst q ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_nazwisko_bez_polskich_znakow_trafia_w_obu(app_client, app_auth_headers):
    q = f"zolc{NONCE}"
    await _both(
        app_client,
        app_auth_headers,
        lst={"q": q},
        srch={"q": q},
        expected={"h", "i"},
    )


@pytest.mark.asyncio
async def test_telefon_w_innym_zapisie_trafia_w_obu(app_client, app_auth_headers):
    q = f"{_PHONE_TAIL[:3]}-{_PHONE_TAIL[3:6]}-{_PHONE_TAIL[6:]}"
    await _both(
        app_client,
        app_auth_headers,
        lst={"q": q},
        srch={"q": q},
        expected={"h"},
    )


@pytest.mark.asyncio
async def test_tryb_tekstu_jest_raportowany(app_client, app_auth_headers):
    data = await _search_raw(app_client, app_auth_headers, q=f"zolc{NONCE}")
    assert data["meta"]["text_mode_applied"] == "literal"
    assert data["meta"]["interpretation"]["kind"] == "name"

    await _seed()
    resp = await app_client.get(
        "/api/candidates",
        params=[("q", f"zolc{NONCE}"), ("q_all", NONCE)],
        headers=app_auth_headers,
    )
    body = resp.json()
    assert body["text_mode_applied"] == "literal"
    assert body["interpretation"]["kind"] == "name"


@pytest.mark.asyncio
async def test_opis_w_trybie_auto_idzie_sciezka_semantyczna(
    app_client, app_auth_headers, monkeypatch
):
    from app.services import hybrid_search
    from app.services.hybrid_search import HybridResult

    ids = await _seed()
    seen: dict[str, Any] = {}

    async def _fake(db, query, **kwargs):
        seen["query"] = query
        return HybridResult(pairs=[(ids["a"], 1.0), (ids["f"], 0.9)])

    monkeypatch.setattr(hybrid_search, "hybrid_candidates", _fake)
    data = await _search_raw(
        app_client,
        app_auth_headers,
        q="senior python developer fintech",
        search_mode="hybrid",
    )
    assert seen["query"] == "senior python developer fintech"
    assert data["meta"]["text_mode_applied"] == "semantic"
    assert data["meta"]["interpretation"]["kind"] == "text"
    assert [i["id"] for i in data["items"]] == [ids["a"], ids["f"]]


@pytest.mark.asyncio
async def test_jawne_literal_wylacza_semantyke(
    app_client, app_auth_headers, monkeypatch
):
    from app.services import hybrid_search

    async def _boom(*args, **kwargs):  # pragma: no cover - nie może zostać zawołane
        raise AssertionError("tryb literal nie może wołać retrievalu wektorowego")

    monkeypatch.setattr(hybrid_search, "hybrid_candidates", _boom)
    found = await _search(
        app_client,
        app_auth_headers,
        q="kotlin",
        search_mode="hybrid",
        text_mode="literal",
    )
    assert found == await _list(app_client, app_auth_headers, q="kotlin")
    assert found == {"h", "i"}


# ── „Otwarty na": LUB ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_otwarty_na_laczy_alternatywa(app_client, app_auth_headers):
    await _both(
        app_client,
        app_auth_headers,
        lst={"open_to": ["side_projects", "sales_support"]},
        srch={"open_to": ["side_projects", "sales_support"]},
        expected={"a", "b", "d"},
    )
    # pola legacy wyszukiwarki (dwa `true`) znaczą to samo
    assert await _search(
        app_client,
        app_auth_headers,
        open_to_side_projects=True,
        open_to_sales_support=True,
    ) == {"a", "b", "d"}


# ── Kategoria kompetencji: główna LUB poboczna ──────────────────────────────


@pytest.mark.asyncio
async def test_kategoria_obejmuje_poboczna(app_client, app_auth_headers):
    await _seed()
    await _both(
        app_client,
        app_auth_headers,
        lst={"competence_category_id": [_CC["one"]]},
        srch={"competence_category_ids": [_CC["one"]]},
        expected={"a", "b", "d"},
    )


# ── Stawka: brak stawki przechodzi ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_stawka_brak_danych_przechodzi(app_client, app_auth_headers):
    # 90–160 PLN/h: a (100) pasuje; c (200) i e (60) odpadają; d (EUR) i wszyscy
    # bez stawki zostają.
    await _both(
        app_client,
        app_auth_headers,
        lst={"min_rate": 90, "max_rate": 160},
        srch={"rate_hourly_min": 90, "rate_hourly_max": 160},
        expected=ALL - {"c", "e"},
    )


# ── Doświadczenie: jedna reguła z zapasem Traffita ──────────────────────────


@pytest.mark.asyncio
async def test_doswiadczenie_czyta_koszyk_traffita(app_client, app_auth_headers):
    # 3–8 lat, bez osób bez sygnału: a (6), b („2-5"), c („5+").
    await _both(
        app_client,
        app_auth_headers,
        lst={"min_experience": 3, "max_experience": 8, "hide_unknown": True},
        srch={
            "experience_years_min": 3,
            "experience_years_max": 8,
            "hide_unknown": True,
        },
        expected={"a", "b", "c"},
    )
    # …a z osobami bez sygnału: dochodzą wszyscy bez liczby i bez koszyka.
    await _both(
        app_client,
        app_auth_headers,
        lst={"min_experience": 3, "max_experience": 8},
        srch={"experience_years_min": 3, "experience_years_max": 8},
        expected=ALL - {"e", "f"},
    )


# ── Tagi: cały tag ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_tag_to_caly_tag_nie_podlancuch(app_client, app_auth_headers):
    await _both(
        app_client,
        app_auth_headers,
        lst={"tags": ["java"]},
        srch={"tags": ["java"]},
        expected={"a", "j"},  # nie „javascript"; wielkość liter bez znaczenia
    )
    await _both(
        app_client,
        app_auth_headers,
        lst={"tags": ["vip"]},
        srch={"tags": ["vip"]},
        expected={"c", "k"},  # nie „vip-2024"
    )


# ── Lokalizacja: znaki wieloznaczne dosłownie, kraj w obu ───────────────────


@pytest.mark.asyncio
async def test_lokalizacja_traktuje_wieloznaczniki_doslownie(
    app_client, app_auth_headers
):
    await _both(
        app_client,
        app_auth_headers,
        lst={"location": "A_B", "hide_unknown": True},
        srch={"location_cities": ["A_B"], "hide_unknown": True},
        expected={"e"},
    )
    await _both(
        app_client,
        app_auth_headers,
        lst={"location": "100%", "hide_unknown": True},
        srch={"location_cities": ["100%"], "hide_unknown": True},
        expected={"c"},
    )


@pytest.mark.asyncio
async def test_lokalizacja_czyta_miasto_i_polskie_znaki(app_client, app_auth_headers):
    await _both(
        app_client,
        app_auth_headers,
        lst={"location": "warszawa", "hide_unknown": True},
        srch={"location_cities": ["warszawa"], "hide_unknown": True},
        expected={"a", "m"},
    )
    await _both(
        app_client,
        app_auth_headers,
        lst={"location": "Krakow", "hide_unknown": True},
        srch={"location_cities": ["Krakow"], "hide_unknown": True},
        expected={"b"},
    )


@pytest.mark.asyncio
async def test_kraj_jest_dostepny_w_obu(app_client, app_auth_headers):
    await _both(
        app_client,
        app_auth_headers,
        lst={"country": ["pl"], "hide_unknown": True},
        srch={"location_countries": ["pl"], "hide_unknown": True},
        expected={"a", "b", "e", "f", "m"},
    )


@pytest.mark.asyncio
async def test_brak_danych_zostaje_i_jest_oznaczony(app_client, app_auth_headers):
    """Decyzja 09.2026: w semantyce v2 osoba BEZ lokalizacji / stażu / stawki
    ZOSTAJE w wynikach obu silników i jest oznaczona w `unknown_fields`;
    `hide_unknown` ją ukrywa."""
    with_location = {"a", "m"}
    nowhere = {"d", "h", "i", "j", "k", "l"}
    await _both(
        app_client,
        app_auth_headers,
        lst={"location": "warszawa"},
        srch={"location_cities": ["warszawa"]},
        expected=with_location | nowhere,
    )

    ids = await _seed()
    filters_l = [
        ("q_all", NONCE),
        ("page_size", 100),
        ("semantics_version", 2),
        ("location", "warszawa"),
        ("min_experience", 3),
        ("min_rate", 50),
    ]
    resp = await app_client.get(
        "/api/candidates", params=filters_l, headers=app_auth_headers
    )
    from_list = {
        i["id"]: i["unknown_fields"]
        for i in resp.json()["items"]
        if i["id"] in set(ids.values())
    }
    data = await _search_raw(
        app_client,
        app_auth_headers,
        location_cities=["warszawa"],
        experience_years_min=3,
        rate_hourly_min=50,
    )
    from_search = {
        i["id"]: i["unknown_fields"]
        for i in data["items"]
        if i["id"] in set(ids.values())
    }
    assert from_list == from_search
    assert from_list[ids["a"]] == []
    assert from_list[ids["m"]] == ["experience", "rate"]
    assert from_list[ids["d"]] == ["location", "experience", "rate"]  # EUR = nieznana


@pytest.mark.asyncio
@pytest.mark.parametrize("sort", ["newest", "oldest", "name"])
async def test_lista_stawia_potwierdzone_przed_brakiem_danych(
    app_client, app_auth_headers, sort
):
    """Test manualny 22.09.2026: przy filtrze miasta osoby bez żadnego miasta
    (przepuszczone z plakietką „brak lokalizacji") zajmowały górę listy.
    Potwierdzone dopasowanie idzie pierwsze w KAŻDYM sortowaniu; nikt nie
    znika z wyniku."""
    ids = await _seed()
    ours = set(ids.values())
    resp = await app_client.get(
        "/api/candidates",
        params=[
            ("q_all", NONCE),
            ("page_size", 100),
            ("semantics_version", 2),
            ("location", "warszawa"),
            ("sort", sort),
        ],
        headers=app_auth_headers,
    )
    assert resp.status_code == 200, resp.text
    order = [i for i in resp.json()["items"] if i["id"] in ours]
    flags = [bool(i["unknown_fields"]) for i in order]
    assert flags == sorted(flags), f"brak danych przed dopasowaniem: {flags}"
    assert {ids[k] for k in ("a", "m")} <= {
        i["id"] for i in order if not i["unknown_fields"]
    }


@pytest.mark.asyncio
async def test_hide_unknown_ukrywa_takze_brak_stawki(app_client, app_auth_headers):
    await _both(
        app_client,
        app_auth_headers,
        lst={"min_rate": 90, "max_rate": 160, "hide_unknown": True},
        srch={"rate_hourly_min": 90, "rate_hourly_max": 160, "hide_unknown": True},
        expected={"a"},
    )


@pytest.mark.asyncio
async def test_v1_kazdy_silnik_zostaje_przy_swoim(app_client, app_auth_headers):
    """Bez `semantics_version` NIC się nie zmienia — także rozjazdy. Pełny dowód
    „przed = po" jest w `test_saved_search_legacy_replay.py`; tu przypinamy, że
    przełącznikiem jest WYŁĄCZNIE wersja semantyki."""
    v1 = {"semantics_version": None}
    # lista v1: sama kolumna `location`, brak danych odpada
    assert await _list(app_client, app_auth_headers, location="warszawa", **v1) == {"a"}
    # wyszukiwarka v1: brak danych zostaje
    assert await _search(
        app_client, app_auth_headers, location_cities=["warszawa"], **v1
    ) == {"a", "m", "d", "h", "i", "j", "k", "l"}
    # lista v1: brak stawki odpada; wyszukiwarka v1: zostaje
    assert await _list(
        app_client, app_auth_headers, min_rate=90, max_rate=160, **v1
    ) == {"a"}
    assert await _search(
        app_client, app_auth_headers, rate_hourly_min=90, rate_hourly_max=160, **v1
    ) == ALL - {"c", "e"}
    # wyszukiwarka v1: tag podłańcuchem, kategoria tylko główna, „Otwarty na" = I
    assert await _search(app_client, app_auth_headers, tags=["java"], **v1) == {
        "a",
        "b",
        "j",
    }
    await _seed()
    assert await _search(
        app_client, app_auth_headers, competence_category_ids=[_CC["one"]], **v1
    ) == {"a", "d"}
    assert await _search(
        app_client,
        app_auth_headers,
        open_to_side_projects=True,
        open_to_expert_consult=True,
        **v1,
    ) == {"d"}
    # wyszukiwarka v1: `q` wyglądające na osobę NIE przełącza się samo
    data = await _search_raw(app_client, app_auth_headers, q=f"zolc{NONCE}", **v1)
    assert data["meta"]["text_mode_applied"] == "keywords"
    # …chyba że `text_mode` przyszedł jawnie
    data = await _search_raw(
        app_client, app_auth_headers, q=f"zolc{NONCE}", text_mode="auto", **v1
    )
    assert data["meta"]["text_mode_applied"] == "literal"


@pytest.mark.asyncio
async def test_pojedyncze_slowo_jest_osoba_tylko_gdy_istnieje_w_bazie(
    app_client, app_auth_headers, monkeypatch
):
    from app.services import hybrid_search
    from app.services.hybrid_search import HybridResult

    ids = await _seed()
    data = await _search_raw(app_client, app_auth_headers, q=f"zolc{NONCE}")
    assert data["meta"]["interpretation"]["rule"] == "single_word_person_exists"
    assert data["meta"]["text_mode_applied"] == "literal"

    async def _fake(db, query, **kwargs):
        return HybridResult(pairs=[(ids["b"], 1.0)])

    monkeypatch.setattr(hybrid_search, "hybrid_candidates", _fake)
    word = f"ksiegowa{NONCE[:6]}"  # same litery, nikt się tak nie nazywa
    data = await _search_raw(app_client, app_auth_headers, q=word, search_mode="hybrid")
    assert data["meta"]["interpretation"]["rule"] == "single_word_no_person"
    assert data["meta"]["text_mode_applied"] == "semantic"
    assert [i["id"] for i in data["items"]] == [ids["b"]]


# ── Grupy q_all / q_any / q_none: jeden parser ──────────────────────────────


@pytest.mark.asyncio
async def test_grupy_boolowskie_maja_jeden_parser(app_client, app_auth_headers):
    await _both(
        app_client,
        app_auth_headers,
        lst={"q_any_group": ["kotlin|rust"], "q_none": ["java"]},
        srch={"q_any_groups": [["kotlin", "rust"]], "q_none": ["java"]},
        expected={"h", "m"},  # i oraz j mają też „java"
    )
    # napis z `|` w żądaniu wyszukiwarki = ta sama grupa
    await _both(
        app_client,
        app_auth_headers,
        lst={"q_any_group": ["kotlin|rust"]},
        srch={"q_any_groups": [["kotlin|rust"]]},
        expected={"h", "i", "j", "m"},
    )


# ── Status i dostępność: zgodne dziś, przypięte na przyszłość ───────────────


@pytest.mark.asyncio
async def test_status_i_dostepnosc_sa_zgodne(app_client, app_auth_headers):
    await _both(
        app_client,
        app_auth_headers,
        lst={"status": ["passive", "blacklisted"]},
        srch={"status": ["passive", "blacklisted"]},
        expected={"g", "l"},
    )
    await _both(
        app_client,
        app_auth_headers,
        lst={"availability": ["actively_looking", "open_to_offers"]},
        srch={"availability_status": ["actively_looking", "open_to_offers"]},
        expected={"a", "b", "l"},
    )
    await _both(
        app_client,
        app_auth_headers,
        lst={"status": ["active"], "availability": ["actively_looking"]},
        srch={"status": ["active"], "availability_status": ["actively_looking"]},
        expected={"a"},
    )


# ── Diagnostyka zna twarde kubełki ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_diagnostyka_wskazuje_kubelek_musi_miec(app_client, app_auth_headers):
    await _seed()
    resp = await app_client.post(
        "/api/search/candidates/diagnostics",
        json={"q_all": [NONCE], "skills_required": ["cobol-ktorego-nikt-nie-ma"]},
        headers=app_auth_headers,
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["first_zeroing_stage"] == "skills_required"
    stage = next(s for s in data["stages"] if s["key"] == "skills_required")
    assert stage["count"] == 0 and "Musi mieć" in stage["label"]


@pytest.mark.asyncio
async def test_czlon_nazwiska_dwuczlonowego_liczy_sie_jako_osoba(app_client):
    """„Kowalska" → „Nowak-Kowalska": jedno słowo jest osobą także wtedy, gdy
    jest jednym członem nazwiska z myślnikiem (bez polskich znaków, bez
    wielkości liter). Fragment członu już nie."""
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate, CandidateStatus
    from app.services import candidate_search_predicates as predicates

    part = "Żół" + NONCE[:8]
    async with AsyncSessionLocal() as db:
        db.add(
            Candidate(
                name="Ewa",
                lastname=f"Nowak-{part}",
                email=f"hyphen-{uuid.uuid4().hex[:10]}@example.com",
                status=CandidateStatus.active,
            )
        )
        await db.commit()
        folded = "zol" + NONCE[:8]
        predicates._person_token_cache.clear()
        assert await predicates.person_token_exists(db, folded) is True
        assert await predicates.person_token_exists(db, folded.upper()) is True
        assert await predicates.person_token_exists(db, folded[:-2]) is False
        found = await predicates.interpret_text(db, folded)
        assert found.rule == "single_word_person_exists" and found.mode == "literal"
