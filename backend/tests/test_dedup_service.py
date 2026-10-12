"""Unit tests for dedup helpers (Phase 1)."""

from types import SimpleNamespace

import pytest
from sqlalchemy.dialects import postgresql

from app.services import dedup_service as dd


# ── _normalize_email ─────────────────────────────────────────────────────────


def test_email_lowercased_and_trimmed():
    assert dd._normalize_email("  JAN@mail.pl ") == "jan@mail.pl"


def test_email_none_returns_none():
    assert dd._normalize_email(None) is None


def test_email_empty_returns_none():
    assert dd._normalize_email("  ") is None


# ── _normalize_phone ─────────────────────────────────────────────────────────


def test_phone_digits_only_last_9():
    assert dd._normalize_phone("+48 500-100-200") == "500100200"


def test_phone_matches_same_number_different_formats():
    a = dd._normalize_phone("+48 500 100 200")
    b = dd._normalize_phone("0048-500.100.200")
    c = dd._normalize_phone("500100200")
    assert a == b == c == "500100200"


def test_phone_short_number_returned_as_is():
    assert dd._normalize_phone("1234") == "1234"


def test_phone_none_returns_none():
    assert dd._normalize_phone(None) is None


# ── _normalize_name ──────────────────────────────────────────────────────────


def test_name_lowercased_and_trimmed():
    assert dd._normalize_name("  Jan  ") == "jan"


def test_name_none_returns_none():
    assert dd._normalize_name(None) is None


# ── _linkedin_slug ───────────────────────────────────────────────────────────


def test_linkedin_slug_from_full_url():
    assert dd._linkedin_slug("https://linkedin.com/in/jan-kowalski/") == "jan-kowalski"


def test_linkedin_slug_preserves_trailing_slash_behavior():
    assert (
        dd._linkedin_slug("https://www.linkedin.com/in/jan-kowalski") == "jan-kowalski"
    )


def test_linkedin_slug_case_insensitive():
    assert dd._linkedin_slug("https://linkedin.com/in/Jan-Kowalski") == "jan-kowalski"


def test_linkedin_slug_empty_returns_none():
    assert dd._linkedin_slug(None) is None
    assert dd._linkedin_slug("  ") is None


@pytest.mark.parametrize(
    "value",
    [
        "linkedin.com",
        "https://www.linkedin.com",
        "LinkedIn",
        "LinkedIn Profile",
        "https://www.linkedin.com/in/",
        "?locale=en_US",
        "https://www.linkedin.com/company/acme",
        "Not provided",
        "jan-kowalski",
    ],
)
def test_linkedin_slug_rejects_values_that_are_not_a_profile_url(value):
    # 12.10.2026: ostatni kawałek po „/” z dowolnej wartości robił z 34 obcych
    # osób „podobnych kandydatów”, bo wszystkie miały w polu „linkedin.com”.
    assert dd._linkedin_slug(value) is None


def test_linkedin_slug_ignores_query_string_and_extra_path():
    assert (
        dd._linkedin_slug("https://www.linkedin.com/in/jan-kowalski?locale=en_US")
        == "jan-kowalski"
    )
    assert (
        dd._linkedin_slug(
            "https://www.linkedin.com/in/jan-kowalski/details/experience/"
        )
        == "jan-kowalski"
    )
    assert dd._linkedin_slug("pl.linkedin.com/in/Jan-Kowalski/") == "jan-kowalski"


# ── zapytania (bez bazy: atrapa łapie wysłane zapytanie) ─────────────────────


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
    return str(
        stmt.compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    ).lower()


async def test_find_candidate_by_email_uses_indexed_expression_and_light_columns():
    db = _FakeDb([_row(41, email="Jan@Example.com")])

    hits = await dd.find_candidate_by_email(db, "  JAN@example.com ")

    sql = _sql(db.statements[0])
    assert "lower(btrim(candidates.email)) = 'jan@example.com'" in sql
    # Pełny wiersz kandydata niesie tekst CV — do pytania „czy taki e-mail
    # jest” wystarczą cztery kolumny.
    assert "raw_cv_text" not in sql
    assert "order by candidates.id" in sql
    assert hits == [
        {
            "candidate_id": 41,
            "name": "Jan",
            "lastname": "Kowalski",
            "email": "Jan@Example.com",
            "match_score": 1.0,
            "match_reasons": ["email_exact"],
        }
    ]


async def test_find_candidate_by_email_blank_does_not_query():
    db = _FakeDb()

    assert await dd.find_candidate_by_email(db, "   ") == []
    assert await dd.find_candidate_by_email(db, None) == []
    assert db.statements == []


async def test_find_candidate_by_email_can_exclude_the_edited_candidate():
    db = _FakeDb()

    await dd.find_candidate_by_email(db, "jan@example.com", exclude_candidate_id=7)

    assert "candidates.id != 7" in _sql(db.statements[0])


async def test_duplicates_match_linkedin_by_slug_equality_only():
    db = _FakeDb()

    await dd.find_candidate_duplicates(
        db, linkedin="https://www.linkedin.com/in/jan-kowalski/"
    )

    sql = _sql(db.statements[0])
    assert "candidates.linkedin_slug = 'jan-kowalski'" in sql
    # Indeks na `linkedin_slug` jest częściowy (bez pustych) — warunek w zapytaniu
    # pozwala planerowi go użyć.
    assert "candidates.linkedin_slug != ''" in sql
    assert "like" not in sql
    assert "raw_cv_text" not in sql


async def test_duplicates_ignore_linkedin_that_is_not_a_profile_url():
    db = _FakeDb([_row(1, linkedin_slug="")])

    assert await dd.find_candidate_duplicates(db, linkedin="linkedin.com") == []
    assert db.statements == []


async def test_duplicates_linkedin_reason_comes_from_the_matched_column():
    db = _FakeDb(
        [
            _row(5, linkedin_slug="jan-kowalski"),
            _row(6, email="jan@example.com", linkedin_slug="ktos-inny"),
        ]
    )

    hits = await dd.find_candidate_duplicates(
        db,
        email="jan@example.com",
        linkedin="https://linkedin.com/in/Jan-Kowalski?trk=x",
    )

    assert [(h["candidate_id"], h["match_reasons"]) for h in hits] == [
        (6, ["email_exact"]),
        (5, ["linkedin_slug_match"]),
    ]


async def test_duplicates_break_score_ties_by_candidate_id():
    # Wtyczka LinkedIn bierze pierwszy wiersz — kolejność nie może zależeć od
    # tego, jak baza akurat zwróciła wiersze.
    db = _FakeDb(
        [_row(9, linkedin_slug="jan-kowalski"), _row(3, linkedin_slug="jan-kowalski")]
    )

    hits = await dd.find_candidate_duplicates(
        db, linkedin="https://linkedin.com/in/jan-kowalski"
    )

    assert [h["candidate_id"] for h in hits] == [3, 9]
