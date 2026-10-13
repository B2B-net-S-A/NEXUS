"""Zaślepki numeru i pola z dwoma numerami w `dedup_service` (audyt 13.10.2026).

Numer „000 000 000” u dwóch różnych osób dawał „Ten sam telefon” i „Scal…”
w oknie dodawania, a `/check-duplicates` (okno scalania) zwracał każdą osobę
z zaślepką jako duplikat z wynikiem 1.0. Pole z dwoma numerami porównywało
tylko ostatni. Front (`add-candidates-identity.ts`) mówi to samo.
"""

from types import SimpleNamespace

import pytest
from sqlalchemy.dialects import postgresql

from app.services import dedup_service as dd
from app.services.cloudtalk_candidate import match_call_candidate


@pytest.mark.parametrize(
    "value",
    [
        "000 000 000",
        "+48 000 000 000",
        "000-000-000",
        "111 111 111",
        "999999999",
        "0048 555 555 555",
        "0000",
        "0",
    ],
)
def test_placeholder_is_not_a_phone(value):
    assert dd._normalize_phone(value) is None
    assert dd._phone_keys(value) == ()


def test_real_numbers_normalize_as_before():
    assert dd._normalize_phone("+48 500-100-200") == "500100200"
    assert dd._normalize_phone("000 000 101") == "000000101"
    assert dd._normalize_phone("1234") == "1234"
    assert dd._phone_keys("+48 500-100-200") == ("500100200",)
    assert dd._phone_keys("1234") == ("1234",)


def test_phone_keys_split_field_with_two_numbers():
    assert dd._phone_keys("601 204 118 / 502 333 444") == ("601204118", "502333444")
    assert dd._phone_keys("+48 601 204 118, 502-333-444") == ("601204118", "502333444")
    assert dd._phone_keys("601204118 lub 502333444") == ("601204118", "502333444")
    assert dd._phone_keys("000 000 000 / 601 204 118") == ("601204118",)
    assert dd._phone_keys("22 123 45 67 wew. 123") == ("221234567",)


def test_phone_keys_one_number_with_prefix_or_label():
    assert dd._phone_keys("(+48) 601 204 118") == ("601204118",)
    assert dd._phone_keys("tel. 601 204 118") == ("601204118",)


# ── find_candidate_duplicates (atrapa bazy łapie zapytanie) ──────────────────


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _FakeDb:
    def __init__(self, rows=()):
        self.rows = list(rows)
        self.statements = []

    async def execute(self, stmt):
        self.statements.append(stmt)
        return _FakeResult(self.rows)


def _row(candidate_id, **fields):
    base = {
        "id": candidate_id,
        "name": "Jan",
        "lastname": "Kowalski",
        "email": None,
        "phone": None,
        "linkedin_slug": None,
    }
    return SimpleNamespace(**{**base, **fields})


def _sql(stmt) -> str:
    # Dialekt podwaja „%” w literałach — porównujemy wzorce LIKE po odwróceniu.
    return (
        str(
            stmt.compile(
                dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
            )
        )
        .lower()
        .replace("%%", "%")
    )


async def test_placeholder_phone_does_not_query_duplicates():
    db = _FakeDb([_row(5, phone="000 000 000")])

    assert await dd.find_candidate_duplicates(db, phone="000 000 000") == []
    assert db.statements == []


async def test_stored_placeholder_is_not_phone_exact():
    # Wiersz przyszedł z innego powodu (e-mail) — zaślepka w nim to nie trafienie.
    db = _FakeDb([_row(5, email="jan@example.com", phone="000 000 000")])

    hits = await dd.find_candidate_duplicates(
        db, email="jan@example.com", phone="+48 000-000-000"
    )

    assert hits[0]["match_reasons"] == ["email_exact"]


async def test_first_number_of_stored_field_is_compared():
    db = _FakeDb([_row(7, phone="601-204-118 / 502 333 444")])

    hits = await dd.find_candidate_duplicates(db, phone="+48 601 204 118")

    assert [(h["candidate_id"], h["match_reasons"]) for h in hits] == [
        (7, ["phone_exact"])
    ]
    assert "'%601204118%'" in _sql(db.statements[0])


async def test_each_number_of_query_field_is_searched():
    db = _FakeDb([_row(8, phone="601 204 118")])

    hits = await dd.find_candidate_duplicates(db, phone="502 333 444 / 601 204 118")

    sql = _sql(db.statements[0])
    assert "'%502333444%'" in sql and "'%601204118%'" in sql
    assert [h["candidate_id"] for h in hits] == [8]


async def test_short_number_keeps_suffix_match():
    db = _FakeDb()

    await dd.find_candidate_duplicates(db, phone="1234")

    sql = _sql(db.statements[0])
    assert "'%1234'" in sql and "'%1234%'" not in sql


async def test_cloudtalk_call_from_placeholder_matches_nobody():
    class _NoDb:
        async def scalars(self, _stmt):  # pragma: no cover - nie może być wołane
            raise AssertionError("zaślepka nie pyta bazy")

    match = await match_call_candidate(_NoDb(), "000 000 000")

    assert match.last9 is None and match.candidate_ids == ()
