"""Błąd zapisu kandydata nie wynosi adresu e-mail do logu (audyt 25.09.2026).

`repr(IntegrityError)` niesie `DETAIL: Key (email)=(…) already exists` —
adres kandydata trafiał do logu kontenera i do `error_samples` fazy
(`/sync/status`). `safe_db_error` zostawia klasę i nazwę ograniczenia.
"""

from __future__ import annotations

from sqlalchemy.exc import IntegrityError

from app.services.traffit.importer import _ERROR_REF_RE, safe_db_error


class _UniqueViolation(Exception):
    constraint_name = "ix_candidates_email"


def test_integrity_error_description_has_constraint_but_no_email() -> None:
    orig = _UniqueViolation(
        'duplicate key value violates unique constraint "ix_candidates_email"\n'
        "DETAIL:  Key (email)=(jan.kowalski@example.com) already exists."
    )
    err = IntegrityError("INSERT INTO candidates …", {}, orig)

    text = safe_db_error(err)

    assert "jan.kowalski@example.com" not in text
    assert "ix_candidates_email" in text
    assert text.startswith("IntegrityError(")
    # Komunikat nadal przypina błąd do wiersza (kwarantanna).
    msg = f"upsert candidate ext=48895: {text}"
    match = _ERROR_REF_RE.search(msg)
    assert match is not None
    assert (match.group(1), match.group(2)) == ("candidate", "48895")


def test_non_database_error_keeps_repr() -> None:
    assert safe_db_error(ValueError("x")) == "ValueError('x')"
