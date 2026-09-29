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
    from app.models.note import Note

    def person(name: str, lastname: str, email: str | None = None) -> Candidate:
        # Krótkie imię i brak e-maila: tożsamość (imię + nazwisko + e-mail)
        # jest krótka, więc podobieństwo trigramowe nazwisk wyraźnie
        # przekracza próg 0,2 — tak jak na produkcji.
        return Candidate(
            name=name,
            lastname=lastname,
            email=email,
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
        # „Nowak” vs „Nowakowski”: dokładne nazwisko i nazwisko z tym samym
        # początkiem; słowo w e-mailu i w notatce innej osoby.
        extra = {
            "wit": person("Jo", f"Wita{Y}"),
            "wit_longer": person("Jo", f"Wita{Y}kowski"),
            "wit_email": person("Ala", "Inna", email=f"wita{Y}@example.com"),
            "wit_note": person("Ola", "Inna"),
        }
        for row in extra.values():
            db.add(row)
        await db.flush()
        db.add(
            Note(
                candidate_id=extra["wit_note"].id,
                content=f"Polecił ją Wita{Y} z poprzedniego projektu.",
            )
        )
        rows.update(extra)
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


@pytest.mark.parametrize(
    "token",
    [
        "warszawski",
        "Śląski",
        "mazowiecka",
        "pomorski",
        "małopolski",
        "wielkopolska",
        "podlaski",
        "lubelski",
        "łódzki",
        "krakowska",
        "gdański",
        "poznański",
        "wrocławski",
    ],
)
def test_przymiotnik_regionu_to_nie_nazwisko(token: str) -> None:
    """Region/miasto bez trafienia dokładnego idzie po znaczeniu, nie jako
    „podobne nazwiska”."""
    assert not p.looks_like_surname(token)


def test_dokladny_filtr_to_samodzielny_semi_join() -> None:
    """Warunek dokładny nie może być ``OR`` z gałęziami frazy: ``OR`` na
    najwyższym poziomie z ``IN (UNION …)`` wyłącza semi-join i skanuje całą
    tabelę kandydatów. Ma być jedno ``IN (SELECT …)`` zawężone trigramem."""
    from sqlalchemy.dialects import postgresql

    clause = p.literal_text_clause("Jan Kowalski", person_match="exact")
    sql = str(clause.compile(dialect=postgresql.dialect()))
    assert sql.startswith("candidates.id IN (SELECT candidates.id"), sql
    assert "FROM candidates" in sql
    assert sql.count("search_doc_unaccented ILIKE") == 2
    for forbidden in ("UNION", "notes", "email", "raw_cv_text", " % "):
        assert forbidden not in sql, f"{forbidden!r} w warunku dokładnym: {sql}"
    # jedyne OR-y są w środku podzapytania (imię / nazwisko), nie na górze
    head = sql.split("(SELECT", 1)[0]
    assert " OR " not in head


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
    assert "UNION" not in compiled, "przy trafieniu dokładnym nie ma gałęzi frazy"


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
async def test_tylko_dokladne_nazwisko_bez_prefiksu_emaila_i_notatek(
    app_client, app_auth_headers
):
    """Decyzja 29.09.2026: „Nowak” pokazuje wyłącznie Nowaków — bez
    „Nowakowskiego” i bez osób, u których to słowo stoi w e-mailu lub notatce."""
    q = f"Wita{Y}"
    body = await _list_raw(app_client, app_auth_headers, q=q, text_mode="auto")
    assert _keys([i["id"] for i in body["items"]]) == ["wit"]
    assert body["text_match"] == "exact"

    data = await _search_raw(app_client, app_auth_headers, q=q, text_mode="auto")
    assert _keys([i["id"] for i in data["items"]]) == ["wit"]


@pytest.mark.asyncio
async def test_doslownie_bez_text_mode_nadal_szuka_frazy(app_client, app_auth_headers):
    """Bez ``text_mode`` (alerty zapisanych wyszukiwań) fraza nadal trafia
    w dłuższe nazwisko, e-mail i notatkę — dotychczasowe zachowanie."""
    q = f"Wita{Y}"
    body = await _list_raw(app_client, app_auth_headers, q=q)
    found = set(_keys([i["id"] for i in body["items"]]))
    assert {"wit", "wit_longer", "wit_email", "wit_note"} <= found


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
