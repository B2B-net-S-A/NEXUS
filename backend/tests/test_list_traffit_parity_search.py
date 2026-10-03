"""Lista ``GET /api/candidates`` — wyszukiwanie jak w Traffit (22.09.2026).

Przez prawdziwy endpoint i Postgresa (regexy i ``to_tsquery`` muszą się
wykonać, nie tylko zbudować):

* słowa kluczowe v2 = CAŁE słowa (``java`` ≠ ``JavaScript``), gwiazdka, fraza;
  v1 (alerty zapisanych wyszukiwań) bez zmian;
* ``q_scope`` — CV / stanowisko / umiejętności / notatki;
* wycinki pod wynikiem po polach, z zakresami pogrubień;
* promień w km i województwo (``pl_places``);
* kontakt w okresie (notatki, rozmowy, aktywności z Traffita), także „przez kogo”;
* ``changed_after`` — skaner alertów widzi osobę, której doszła notatka.

Baza testowa jest wspólna, więc każde żądanie zawęża się własną frazą
``NONCE`` (``q`` dosłownie, w ``linkedin_current_company``), a asercje patrzą
na własne id.
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any

import pytest

NONCE = "zq" + "".join(chr(97 + int(c, 16)) for c in uuid.uuid4().hex[:10])
_IDS: dict[str, int] = {}


async def _seed() -> dict[str, int]:
    if _IDS:
        return _IDS
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate, CandidateStatus
    from app.models.note import Note, NoteType

    def person(key: str, **kw: Any) -> Candidate:
        return Candidate(
            name=key.capitalize(),
            lastname=f"Traffitowy{key}",
            email=f"{key}-{uuid.uuid4().hex[:10]}@example.com",
            status=CandidateStatus.active,
            linkedin_current_company=NONCE,
            **kw,
        )

    async with AsyncSessionLocal() as db:
        rows = {
            # Java w CV — całe słowo.
            "java": person(
                "java",
                raw_cv_text="Senior developer. Java 17, Spring Boot, Kafka.",
                experience=[{"role": "Java Developer", "company": "Bank"}],
                city="Kraków",
                country="PL",
            ),
            # Tylko JavaScript — nie może wpaść na „java”.
            "js": person(
                "js",
                raw_cv_text="Frontend: JavaScript, TypeScript, React.",
                experience=[{"role": "Frontend Developer"}],
                city="Wieliczka",
                country="PL",
            ),
            # Java wyłącznie w notatce.
            "note": person(
                "note",
                raw_cv_text="Tester manualny.",
                city="Gdynia",
                country="PL",
            ),
            # Bez lokalizacji.
            "nowhere": person("nowhere", raw_cv_text="Python developer"),
            # „Java/Spring” — parser tsvector trzyma to jako jeden token.
            "slash": person("slash", raw_cv_text="Stack: Java/Spring, Oracle."),
            # Zagraniczna nazwa równa polskiej miejscowości nie wpada w promień.
            "abroad": person(
                "abroad", raw_cv_text="Python developer", city="Kraków", country="DE"
            ),
        }
        db.add_all(rows.values())
        await db.flush()
        db.add(
            Note(
                candidate_id=rows["note"].id,
                content="Rozmowa: zna Javę? Tak — Java od 5 lat.",
            )
        )
        # Mail z Traffita — import promuje go do notatki typu „email”.
        db.add(
            Note(
                candidate_id=rows["js"].id,
                content="Odpisał na ofertę.",
                note_type=NoteType.email,
            )
        )
        await db.commit()
        for key, row in rows.items():
            _IDS[key] = row.id
    return _IDS


async def _list(client, headers, **params: Any) -> dict:
    status, body = await _list_raw(client, headers, **params)
    assert status == 200, body
    return body


async def _list_raw(client, headers, **params: Any) -> tuple[int, dict]:
    await _seed()
    # Zawężenie frazą w `q` (dosłownie), nie słowem kluczowym — zakres pola
    # (`q_scope`) dotyczy słów kluczowych i odciąłby własne rekordy.
    query: list[tuple[str, Any]] = [
        ("q", NONCE),
        ("text_mode", "literal"),
        ("page_size", 100),
    ]
    for key, value in params.items():
        if value is None:
            continue
        if isinstance(value, (list, tuple)):
            query.extend((key, v) for v in value)
        else:
            query.append((key, value))
    resp = await client.get("/api/candidates", params=query, headers=headers)
    return resp.status_code, resp.json()


async def _db_scalar(sql: str) -> Any:
    from sqlalchemy import text

    from app.core.database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        return (await db.execute(text(sql))).scalar_one()


def _keys(body: dict) -> set[str]:
    by_id = {v: k for k, v in _IDS.items()}
    return {by_id[item["id"]] for item in body["items"] if item["id"] in by_id}


# ── Całe słowa ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_v2_java_is_a_whole_word_and_v1_keeps_substring(
    app_client, app_auth_headers
):
    v2 = await _list(app_client, app_auth_headers, q_all="java", semantics_version=2)
    assert _keys(v2) == {"java", "note", "slash"}
    v1 = await _list(app_client, app_auth_headers, q_all="java")
    # v1: dotychczasowy prefiks/podłańcuch — JavaScript wpada (alerty).
    assert {"java", "js", "note"} <= _keys(v1)


@pytest.mark.asyncio
async def test_v2_wildcard_and_exclusion(app_client, app_auth_headers):
    body = await _list(app_client, app_auth_headers, q_all="java*", semantics_version=2)
    assert {"java", "js", "note"} <= _keys(body)
    body = await _list(
        app_client,
        app_auth_headers,
        q_all="*script",
        semantics_version=2,
    )
    assert _keys(body) == {"js"}
    body = await _list(
        app_client,
        app_auth_headers,
        q_all="developer",
        q_none="java",
        semantics_version=2,
    )
    assert "java" not in _keys(body)
    assert {"js", "nowhere", "abroad"} <= _keys(body)


@pytest.mark.asyncio
async def test_v2_phrase_and_special_characters(app_client, app_auth_headers):
    body = await _list(
        app_client, app_auth_headers, q_all="spring boot", semantics_version=2
    )
    assert _keys(body) == {"java"}
    body = await _list(
        app_client, app_auth_headers, q_all="react.", semantics_version=2
    )
    assert _keys(body) == {"js"}


# ── Zakres pola ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("scope", "expected"),
    [
        ("cv", {"java", "slash"}),
        ("title", {"java"}),
        ("notes", {"note"}),
        ("all", {"java", "note", "slash"}),
    ],
)
async def test_scope_limits_where_keywords_look(
    app_client, app_auth_headers, scope, expected
):
    body = await _list(
        app_client, app_auth_headers, q_all="java", q_scope=scope, semantics_version=2
    )
    assert _keys(body) == expected


@pytest.mark.asyncio
async def test_snippets_per_field_with_bold_ranges(app_client, app_auth_headers):
    body = await _list(
        app_client, app_auth_headers, q_all=["java", "kafka"], semantics_version=2
    )
    row = next(i for i in body["items"] if i["id"] == _IDS["java"])
    fields = {s["field"]: s for s in row["match_snippets"]}
    assert {"Treść CV", "Stanowisko"} <= set(fields)
    cv = fields["Treść CV"]
    bold = [cv["text"][s:e] for s, e in cv["highlights"]]
    assert bold == ["Java", "Kafka"]
    assert row["match_snippet"].startswith("Treść CV: ")


# ── Lokalizacja ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_radius_around_town(app_client, app_auth_headers):
    body = await _list(
        app_client,
        app_auth_headers,
        location="Krakow",
        location_radius_km=30,
        semantics_version=2,
        hide_unknown="true",
    )
    assert _keys(body) == {"java", "js"}  # Kraków + Wieliczka; DE odpada
    only_city = await _list(
        app_client,
        app_auth_headers,
        location="Kraków",
        semantics_version=2,
        hide_unknown="true",
    )
    assert "js" not in _keys(only_city)
    with_unknown = await _list(
        app_client,
        app_auth_headers,
        location="Krakow",
        location_radius_km=30,
        semantics_version=2,
    )
    assert "nowhere" in _keys(with_unknown)


@pytest.mark.asyncio
async def test_radius_center_from_single_city_of_a_saved_search(
    app_client, app_auth_headers
):
    """Zapis v3 niesie miasto w `location_cities` — to ono jest środkiem."""
    body = await _list(
        app_client,
        app_auth_headers,
        location_cities="Krakow",
        location_radius_km=30,
        semantics_version=2,
        hide_unknown="true",
    )
    assert _keys(body) == {"java", "js"}


@pytest.mark.asyncio
async def test_unknown_voivodeship_is_422(app_client, app_auth_headers):
    status, body = await _list_raw(
        app_client, app_auth_headers, voivodeship="atlantydzkie", semantics_version=2
    )
    assert status == 422
    assert "atlantydzkie" in body["detail"]


@pytest.mark.asyncio
async def test_unknown_town_with_radius_is_422(app_client, app_auth_headers):
    status, body = await _list_raw(
        app_client,
        app_auth_headers,
        location="Atlantyda",
        location_radius_km=10,
        semantics_version=2,
    )
    assert status == 422
    assert "Atlantyda" in body["detail"]


@pytest.mark.asyncio
async def test_voivodeship(app_client, app_auth_headers):
    body = await _list(
        app_client,
        app_auth_headers,
        voivodeship="pomorskie",
        semantics_version=2,
        hide_unknown="true",
    )
    assert _keys(body) == {"note"}


@pytest.mark.asyncio
async def test_places_suggest(app_client, app_auth_headers):
    resp = await app_client.get(
        "/api/candidates/places/suggest", params={"q": "krak"}, headers=app_auth_headers
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["items"][0]["name"] == "Kraków"
    assert "mazowieckie" in body["voivodeships"]


# ── Kontakt ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_contacted_in_period(app_client, app_auth_headers):
    # „Dziś” w czasie polskim według zegara BAZY — to on datuje notatki
    # (`server_default=now()`). `date.today()` (UTC na CI) myliło się między
    # 22:00 a 24:00 UTC, a zegar Pythona i zegar bazy to dwa różne zegary —
    # punkt odniesienia bierzemy z tego, który datuje wiersze.
    await _seed()
    today = await _db_scalar("SELECT (now() AT TIME ZONE 'Europe/Warsaw')::date")
    yes = await _list(
        app_client,
        app_auth_headers,
        contacted="yes",
        contacted_from=(today - timedelta(days=1)).isoformat(),
        contacted_to=today.isoformat(),
    )
    # Notatka (note) i mail z Traffita (js).
    assert _keys(yes) == {"note", "js"}
    no = await _list(app_client, app_auth_headers, contacted="no")
    assert {"java", "nowhere", "abroad", "slash"} <= _keys(no)
    assert not {"note", "js"} & _keys(no)
    old = await _list(
        app_client,
        app_auth_headers,
        contacted="yes",
        contacted_to=(today - timedelta(days=30)).isoformat(),
    )
    assert not _keys(old)


# ── Skaner alertów: nowa notatka ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_changed_after_sees_a_new_note(app_client, app_auth_headers):
    from app.core.database import AsyncSessionLocal
    from app.models.note import Note

    ids = await _seed()
    # Znacznik z zegara bazy, jak `updated_at`/`created_at`. Zegar Pythona
    # i zegar bazy mogą się rozjechać (23.09.2026: przypięty zegar Pythona) —
    # wiersze z seeda wyglądały wtedy na „zmienione po” znaczniku.
    mark = await _db_scalar("SELECT clock_timestamp()")
    body = await _list(app_client, app_auth_headers, changed_after=mark.isoformat())
    assert not _keys(body)
    async with AsyncSessionLocal() as db:
        db.add(Note(candidate_id=ids["nowhere"], content="Oddzwonić w piątek."))
        await db.commit()
    body = await _list(app_client, app_auth_headers, changed_after=mark.isoformat())
    assert _keys(body) == {"nowhere"}


# ── Ostatnia rozmowa i „prawdziwy kontakt” (03.10.2026) ─────────────────────


async def _seed_talks() -> tuple[str, dict[str, int]]:
    """Cztery osoby: po rozmowie, tylko z „nie odbiera”, tylko z wpisem automatu
    i tylko z nieodebranym telefonem (tak „nie odbiera” zapisuje praktykant)."""
    from app.core.database import AsyncSessionLocal
    from app.models.call import Call, CallStatus
    from app.models.candidate import Candidate, CandidateStatus
    from app.models.note import SYSTEM_NOTE_SOURCE, Note
    from app.models.user import User, UserRole

    nonce = f"Rozmowy{uuid.uuid4().hex[:10]}"
    async with AsyncSessionLocal() as db:
        author = User(
            email=f"talks-{uuid.uuid4().hex[:8]}@example.com",
            name="Ola Rozmowna",
            role=UserRole.recruiter,
            roles=[UserRole.recruiter.value],
            is_active=True,
        )
        people = {
            key: Candidate(
                name=key.capitalize(),
                lastname=f"Rozmowny{key}",
                email=f"{key}-{uuid.uuid4().hex[:10]}@example.com",
                status=CandidateStatus.active,
                linkedin_current_company=nonce,
            )
            for key in ("talked", "silent", "automat", "missed")
        }
        db.add_all([author, *people.values()])
        await db.flush()
        db.add_all(
            [
                Note(
                    candidate_id=people["talked"].id,
                    author_id=author.id,
                    content="Szuka projektu z Javą 21, nie chce samego utrzymania.",
                ),
                Note(candidate_id=people["talked"].id, content="nie odbiera"),
                Note(candidate_id=people["silent"].id, content="nie odbiera"),
                Note(
                    candidate_id=people["automat"].id,
                    content="Auto-match 71/100",
                    external_source=SYSTEM_NOTE_SOURCE,
                ),
                Call(
                    candidate_id=people["missed"].id,
                    user_id=author.id,
                    status=CallStatus.missed,
                    contact_outcome="no_answer",
                ),
            ]
        )
        await db.commit()
        return nonce, {key: row.id for key, row in people.items()}


async def _talk_list(client, headers, nonce: str, **params: Any) -> dict[int, dict]:
    resp = await client.get(
        "/api/candidates",
        params={"q": nonce, "text_mode": "literal", "page_size": 100, **params},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    return {item["id"]: item for item in resp.json()["items"]}


@pytest.mark.asyncio
async def test_last_talk_column_ignores_contact_attempts_and_automat(
    app_client, app_auth_headers
):
    nonce, ids = await _seed_talks()

    rows = await _talk_list(
        app_client, app_auth_headers, nonce, include_last_talk="true"
    )

    talked = rows[ids["talked"]]
    assert talked["last_talk_at"]
    assert talked["last_talk_by"] == "Ola Rozmowna"
    assert talked["last_talk_preview"].startswith("Szuka projektu z Javą 21")
    assert talked["contact_attempts"] == 1
    # „Nie odbiera” i wpis automatu nie są rozmową.
    for key, attempts in (("silent", 1), ("automat", 0), ("missed", 1)):
        row = rows[ids[key]]
        assert row["last_talk_at"] is None and row["last_talk_by"] is None
        assert row["contact_attempts"] == attempts

    # Bez flagi pola zostają puste (lista ich nie liczy).
    plain = await _talk_list(app_client, app_auth_headers, nonce)
    assert plain[ids["talked"]]["last_talk_at"] is None
    assert plain[ids["talked"]]["contact_attempts"] is None


@pytest.mark.asyncio
async def test_contact_filter_v2_counts_only_real_contact_and_v1_is_unchanged(
    app_client, app_auth_headers
):
    nonce, ids = await _seed_talks()

    yes_v2 = await _talk_list(
        app_client, app_auth_headers, nonce, contacted="yes", semantics_version=2
    )
    no_v2 = await _talk_list(
        app_client, app_auth_headers, nonce, contacted="no", semantics_version=2
    )
    assert set(yes_v2) == {ids["talked"]}
    # Nieodebrany telefon (tak zapisuje „nie odbiera” praktykant) też nie jest
    # kontaktem.
    assert set(no_v2) == {ids["silent"], ids["automat"], ids["missed"]}

    # v1 — na niej stoją alerty zapisanych wyszukiwań — liczy każdą notatkę.
    yes_v1 = await _talk_list(app_client, app_auth_headers, nonce, contacted="yes")
    assert set(yes_v1) == set(ids.values())


@pytest.mark.asyncio
async def test_quick_view_shows_the_last_talk_not_the_contact_attempt(
    app_client, app_auth_headers
):
    _, ids = await _seed_talks()

    talked = (
        await app_client.get(
            f"/api/candidates/{ids['talked']}/quick-view", headers=app_auth_headers
        )
    ).json()
    assert [note["content"][:14] for note in talked["recent_notes"]] == [
        "Szuka projektu"
    ]
    assert talked["contact_attempts"] == 1

    silent = (
        await app_client.get(
            f"/api/candidates/{ids['silent']}/quick-view", headers=app_auth_headers
        )
    ).json()
    assert silent["recent_notes"] == []
    assert silent["contact_attempts"] == 1
