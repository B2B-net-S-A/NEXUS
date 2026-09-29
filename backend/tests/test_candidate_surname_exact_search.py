"""Nazwisko w górnym polu listy: najpierw dokładnie, podobne tylko bez trafienia.

Zgłoszenie 09.2026: „Składanowski” (v2, ``text_mode=auto``) zwracało też
Stefanowskiego, Baranowskiego, Bazanowskiego i SKŁADOWSKIEGO — gałąź
literówek (trigramy, próg 0,2) łapała każde „-anowski”. Decyzja Artura:
„tylko dokładne”. Podobne nazwiska wyłącznie wtedy, gdy nikogo o tym
nazwisku nie ma — i odpowiedź to mówi (``text_match: "similar"``).

v1 i żądania BEZ ``text_mode`` (alerty zapisanych wyszukiwań) zostają przy
dotychczasowym dopasowaniu — pilnuje tego ostatni test.

Baza testowa jest wspólna i nie jest czyszczona: nazwiska niosą losowy
wtręt, a każde żądanie jest zawężone do własnych wierszy (``q_all=[CO]``,
fraza w ``linkedin_current_company``).
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from app.services import candidate_search_predicates as p


def _letters(n: int) -> str:
    return "".join(chr(97 + int(c, 16)) for c in uuid.uuid4().hex[:n])


# Same litery a–p: przechodzą przez detekcję „to osoba” i przez FTS.
X = _letters(8)
Y = _letters(8)
CO = "zq" + _letters(10)

_IDS: dict[str, int] = {}


async def _seed() -> dict[str, int]:
    if _IDS:
        return _IDS
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate, CandidateStatus

    def person(name: str, lastname: str) -> Candidate:
        # Krótkie imię i brak e-maila: tożsamość (imię + nazwisko + e-mail)
        # jest krótka, więc podobieństwo trigramowe nazwisk wyraźnie
        # przekracza próg 0,2 — tak jak na produkcji.
        return Candidate(
            name=name,
            lastname=lastname,
            email=None,
            status=CandidateStatus.active,
            linkedin_current_company=CO,
        )

    async with AsyncSessionLocal() as db:
        rows = {
            "sklad": person("Jo", f"Składa{X}owski"),
            "baran": person("Jo", f"Bara{X}owski"),
            "stefan": person("Jo", f"Stefa{X}owski"),
        }
        for row in rows.values():
            db.add(row)
        await db.flush()
        # Kolejność: dokładne nazwisko STARSZE, dłuższa odmiana NOWSZA.
        older = person("Jo", f"Wita{Y}owski")
        db.add(older)
        await db.flush()
        newer = person("Jo", f"Wita{Y}owskiego")
        db.add(newer)
        await db.flush()
        rows["wit"] = older
        rows["wit_newer"] = newer
        await db.commit()
        for key, row in rows.items():
            _IDS[key] = row.id
    return _IDS


def _keys(found: list[int]) -> list[str]:
    reverse = {v: k for k, v in _IDS.items()}
    return [reverse[i] for i in found if i in reverse]


async def _list_raw(client, headers, **params: Any) -> dict:
    await _seed()
    query: list[tuple[str, Any]] = [
        ("q_all", CO),
        ("page_size", 100),
        ("semantics_version", 2),
    ]
    query.extend((k, v) for k, v in params.items() if v is not None)
    resp = await client.get("/api/candidates", params=query, headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _search_raw(client, headers, **body: Any) -> dict:
    await _seed()
    payload = {
        "q_all": [CO],
        "page": 1,
        "page_size": 200,
        "semantics_version": 2,
        "search_mode": "boolean",
        **body,
    }
    resp = await client.post("/api/search/candidates", json=payload, headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


# ── Czysta reguła (bez bazy) ────────────────────────────────────────────────


@pytest.mark.parametrize(
    "token", ["Składanowski", "kowalczykowska", "Nowicki", "Dąbrowicz", "Stańczyk"]
)
def test_koncowka_nazwiska_rozpoznana(token: str) -> None:
    assert p.looks_like_surname(token)


@pytest.mark.parametrize(
    "token", ["księgowa", "angielski", "Niemiecki", "java", "Nowak", "UIAZ2026ski"]
)
def test_opis_i_jezyk_to_nie_nazwisko(token: str) -> None:
    assert not p.looks_like_surname(token)


@pytest.mark.asyncio
async def test_regula_dziala_tylko_w_v2_z_auto(monkeypatch) -> None:
    async def _never(*args, **kwargs):  # pragma: no cover - nie może zostać zawołane
        raise AssertionError("poza v2 + auto nie pytamy bazy o osobę")

    monkeypatch.setattr(p, "person_name_exists", _never)
    v1 = p.semantics_for("list", None, None)
    v2 = p.semantics_for("list", 2, None)
    assert await p.person_text_match(None, "Składanowski", v1, "auto") is None
    assert await p.person_text_match(None, "Składanowski", v2, None) is None
    assert await p.person_text_match(None, "Składanowski", v2, "literal") is None
    # Tekst, który nie wygląda na osobę, też nie pyta bazy.
    assert await p.person_text_match(None, "senior java developer", v2, "auto") is None


@pytest.mark.asyncio
async def test_dokladne_nazwisko_wylacza_literowki(monkeypatch) -> None:
    async def _exists(db, tokens):
        return True

    monkeypatch.setattr(p, "person_name_exists", _exists)
    v2 = p.semantics_for("list", 2, None)
    assert await p.person_text_match(None, "Składanowski", v2, "auto") == "exact"
    compiled = str(p.literal_text_clause("Składanowski", person_match="exact"))
    assert " % " not in compiled, "gałąź literówek nie może zostać przy trafieniu"


# ── Oba silniki na prawdziwej bazie ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_nazwisko_zwraca_tylko_te_osobe(app_client, app_auth_headers):
    q = f"Składa{X}owski"
    body = await _list_raw(app_client, app_auth_headers, q=q, text_mode="auto")
    assert _keys([i["id"] for i in body["items"]]) == ["sklad"]
    assert body["text_match"] == "exact"

    data = await _search_raw(app_client, app_auth_headers, q=q, text_mode="auto")
    assert _keys([i["id"] for i in data["items"]]) == ["sklad"]
    assert data["meta"]["text_match"] == "exact"


@pytest.mark.asyncio
async def test_nazwisko_bez_polskich_znakow(app_client, app_auth_headers):
    q = f"Sklada{X}owski"
    body = await _list_raw(app_client, app_auth_headers, q=q, text_mode="auto")
    assert _keys([i["id"] for i in body["items"]]) == ["sklad"]
    assert body["text_match"] == "exact"


@pytest.mark.parametrize("q", [f"Jo Składa{X}owski", f"Sklada{X}owski Jo"])
@pytest.mark.asyncio
async def test_imie_i_nazwisko_w_dowolnej_kolejnosci(app_client, app_auth_headers, q):
    body = await _list_raw(app_client, app_auth_headers, q=q, text_mode="auto")
    assert _keys([i["id"] for i in body["items"]]) == ["sklad"]
    assert body["text_match"] == "exact"


@pytest.mark.asyncio
async def test_brak_nazwiska_pokazuje_podobne_z_flaga(app_client, app_auth_headers):
    q = f"Kowalczy{X}owski"
    body = await _list_raw(app_client, app_auth_headers, q=q, text_mode="auto")
    found = set(_keys([i["id"] for i in body["items"]]))
    assert {"sklad", "baran", "stefan"} <= found
    assert body["text_match"] == "similar"
    assert body["text_mode_applied"] == "literal"

    data = await _search_raw(app_client, app_auth_headers, q=q, text_mode="auto")
    assert set(_keys([i["id"] for i in data["items"]])) == found
    assert data["meta"]["text_match"] == "similar"


@pytest.mark.asyncio
async def test_dokladna_osoba_pierwsza_niezaleznie_od_sortowania(
    app_client, app_auth_headers
):
    q = f"Wita{Y}owski"
    body = await _list_raw(app_client, app_auth_headers, q=q, text_mode="auto")
    # Nowsza „…owskiego” trafia prefiksem, ale dokładne nazwisko jest pierwsze
    # mimo domyślnego sortowania od najnowszych.
    assert _keys([i["id"] for i in body["items"]]) == ["wit", "wit_newer"]


@pytest.mark.asyncio
async def test_bez_text_mode_zostaje_dotychczasowe_dopasowanie(
    app_client, app_auth_headers
):
    """Alerty zapisanych wyszukiwań nie wysyłają ``text_mode`` — wynik bez zmian
    (gałąź literówek zostaje) i bez flagi."""
    q = f"Składa{X}owski"
    body = await _list_raw(app_client, app_auth_headers, q=q)
    found = set(_keys([i["id"] for i in body["items"]]))
    assert {"sklad", "baran", "stefan"} <= found
    assert body.get("text_match") is None
