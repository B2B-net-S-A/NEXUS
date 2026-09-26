"""Dopasowanie maila do kandydata — zakres i koszt (runda 6 audytu).

- M365-3: reguła „imię i nazwisko w temacie” ładowała CAŁĄ tabelę kandydatów
  przy każdym niedopasowanym mailu; teraz zawężenie jest w SQL (słowa tematu,
  kontakt < 90 dni), z limitem i bez przypinania przy kilku trafieniach.
- M365-4: adres właściciela skrzynki i domeny firmy nie wskazują kandydata
  (strict), a domena firmy, klienta i darmowa nie idzie do smart_domain.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.dialects import postgresql

from app.core.config import settings
from app.models.m365 import EmailMatchMethod
from app.services.m365 import matcher


def _sql(stmt) -> str:
    return str(
        stmt.compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )


def _rows_db(rows):
    captured = []

    async def _execute(stmt):
        captured.append(stmt)
        return SimpleNamespace(
            all=lambda: rows,
            scalars=lambda: SimpleNamespace(
                first=lambda: rows[0] if rows else None, all=lambda: rows
            ),
        )

    return SimpleNamespace(execute=AsyncMock(side_effect=_execute)), captured


@pytest.fixture(autouse=True)
def _company_domain(monkeypatch):
    monkeypatch.setattr(settings, "SSO_ALLOWED_DOMAINS", "b2bnetwork.pl")


# ── M365-3: smart_name ───────────────────────────────────────────────────────


async def test_smart_name_narrows_in_sql_with_limit_and_contact_window() -> None:
    db, captured = _rows_db([SimpleNamespace(id=7, name="Łukasz", lastname="Żółw")])

    found = await matcher._find_candidate_by_subject_name(db, "CV — Łukasz Żółw, Java")

    assert found == 7
    sql = _sql(captured[0])
    assert "translate" in sql and "LIMIT 20" in sql
    assert "'zolw'" in sql and "'lukasz'" in sql
    assert "last_contacted_at" in sql and "emails" in sql
    # Tylko kolumny potrzebne do porównania, nie pełne obiekty kandydatów.
    assert "candidates.raw_cv_text" not in sql


async def test_smart_name_two_people_is_no_match() -> None:
    db, _ = _rows_db(
        [
            SimpleNamespace(id=7, name="Jan", lastname="Kowalski"),
            SimpleNamespace(id=9, name="Jan", lastname="Kowalski"),
        ]
    )
    assert await matcher._find_candidate_by_subject_name(db, "CV Jan Kowalski") is None


async def test_smart_name_without_tokens_skips_query() -> None:
    db, captured = _rows_db([])
    assert await matcher._find_candidate_by_subject_name(db, "RE: 12") is None
    assert captured == []


# ── M365-4: strict i smart_domain ────────────────────────────────────────────


async def test_strict_ignores_owner_and_company_addresses() -> None:
    db, captured = _rows_db([SimpleNamespace(id=1)])
    found = await matcher._find_candidate_by_email(
        db,
        ["Marta@b2bnetwork.pl", "kolega@b2bnetwork.pl"],
        owner_address="marta@b2bnetwork.pl",
    )
    assert found is None
    assert captured == []


async def test_strict_still_matches_external_address() -> None:
    db, captured = _rows_db([SimpleNamespace(id=5)])
    found = await matcher._find_candidate_by_email(
        db,
        ["marta@b2bnetwork.pl", "Kandydat@Firma.pl"],
        owner_address="marta@b2bnetwork.pl",
    )
    assert found.id == 5
    sql = _sql(captured[0])
    assert "'kandydat@firma.pl'" in sql and "marta@" not in sql


async def test_strict_with_two_candidates_prefers_the_sender() -> None:
    """Runda 7 (X1-3): nie najniższy `id`, tylko nadawca."""
    rows = [
        SimpleNamespace(id=1, email="b@firma.pl"),
        SimpleNamespace(id=2, email="a@firma.pl"),
    ]
    db, _ = _rows_db(rows)
    found = await matcher._find_candidate_by_email(
        db,
        ["A@firma.pl", "b@firma.pl"],
        owner_address="marta@b2bnetwork.pl",
        sender_address="A@firma.pl",
    )
    assert found.id == 2


async def test_strict_with_two_recipient_candidates_is_ambiguous() -> None:
    """Runda 7 (X1-3): zbiorczy mail do dwóch kandydatów — żadnego „strict”."""
    rows = [
        SimpleNamespace(id=1, email="b@firma.pl"),
        SimpleNamespace(id=2, email="a@firma.pl"),
    ]
    db, captured = _rows_db(rows)
    found = await matcher._find_candidate_by_email(
        db,
        ["marta@b2bnetwork.pl", "b@firma.pl", "a@firma.pl"],
        owner_address="marta@b2bnetwork.pl",
        sender_address="marta@b2bnetwork.pl",
    )
    assert found is None
    # Pytamy o więcej niż jeden wiersz — inaczej niejednoznaczności nie widać.
    assert f"LIMIT {matcher._STRICT_ROW_LIMIT}" in _sql(captured[0])


def _msg(from_address: str, **kw) -> matcher.IncomingMessage:
    return matcher.IncomingMessage(
        from_address=from_address,
        to_addresses=[],
        cc_addresses=[],
        subject=kw.get("subject"),
        conversation_id="conv-1",
        owner_address="marta@b2bnetwork.pl",
    )


@pytest.mark.parametrize(
    ("sender", "client_domain", "expected"),
    [
        ("hm@klient.pl", True, None),  # domena klienta
        ("kolega@b2bnetwork.pl", False, None),  # domena firmy
        ("ktos@gmail.com", False, None),  # darmowa
        ("jan@mala-firma.pl", False, 3),  # jedyny kandydat w domenie
    ],
)
async def test_smart_domain_exclusions(
    monkeypatch, sender, client_domain, expected
) -> None:
    monkeypatch.setattr(
        matcher, "_find_candidate_by_email", AsyncMock(return_value=None)
    )
    monkeypatch.setattr(
        matcher, "_find_candidate_by_conversation", AsyncMock(return_value=None)
    )
    monkeypatch.setattr(
        matcher, "_is_client_domain", AsyncMock(return_value=client_domain)
    )
    by_domain = AsyncMock(return_value=[SimpleNamespace(id=3)])
    monkeypatch.setattr(matcher, "_find_candidates_by_domain", by_domain)

    result = await matcher.match(SimpleNamespace(), _msg(sender))

    assert result.candidate_id == expected
    if expected is None:
        assert result.method == EmailMatchMethod.unmatched.value
        by_domain.assert_not_awaited()


async def test_client_domain_checks_contacts_and_website() -> None:
    db = SimpleNamespace(scalar=AsyncMock(side_effect=[False, True]))
    assert await matcher._is_client_domain(db, "klient.pl") is True
    contacts_sql = _sql(db.scalar.await_args_list[0].args[0])
    site_sql = _sql(db.scalar.await_args_list[1].args[0])
    assert "contacts" in contacts_sql and "@klient.pl'" in contacts_sql
    assert "clients.website" in site_sql
