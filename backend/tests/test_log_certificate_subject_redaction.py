"""Podmiot certyfikatu podpisu (imię, nazwisko, PESEL) nie trafia do logów.

22.11.2026: pyHanko przy podpisie wystawcy spoza listy zaufanych UE (podpis
osobisty z e-dowodu) loguje na WARNING „Failed to build path for Common Name:
…; Serial Number: PNOPL-<PESEL>; Given Name: …; Surname: …” razem
z tracebackiem, którego komunikat powtarza ten podmiot. ``redact_sensitive``
maskował e-maile i sekrety, ale nie pola podmiotu, więc dane kontraktora szły
na stdout → Loki przy każdym takim pliku: strona podpisu, „Oznacz jako
podpisaną” (data podpisu z pliku), umowa szkoleniowa. Sentry dostaje
z breadcrumbs tylko kategorię i poziom (``scrub_event``), więc tu chodzi
o stdout. Dane w teście są fikcyjne.
"""

from __future__ import annotations

import io
import json
import logging
from datetime import datetime, timezone

import pytest

from app.core.logging_config import (
    RedactingFilter,
    RedactingJsonFormatter,
    redact_sensitive,
)

NAME = "JAN TESTOWY"
PESEL = "00000000001"
SUBJECT = (
    f"Common Name: {NAME}; Serial Number: PNOPL-{PESEL}; "
    "Given Name: JAN, ADAM; Surname: TESTOWY; Country: PL"
)


def _leaks(text: str) -> list[str]:
    return [part for part in ("TESTOWY", PESEL, "ADAM") if part in text]


def test_pyhanko_path_message_keeps_shape_but_hides_the_person():
    redacted = redact_sensitive(f"Failed to build path for {SUBJECT}")
    assert _leaks(redacted) == []
    assert redacted.startswith("Failed to build path for Common Name: [redacted]")
    assert "Country: PL" in redacted


def test_path_building_error_in_traceback_is_redacted():
    message = (
        f'Unable to build a validation path for the certificate "{SUBJECT}" - '
        'no issuer matching "Common Name: Testowe Root CA, Serial Number: 2019, '
        'Country: PL" was found'
    )
    assert _leaks(redact_sensitive(message)) == []


@pytest.mark.parametrize(
    "text",
    [
        f"signer CN={NAME},serialNumber=PNOPL-{PESEL}",
        f"dowód IDCPL-ABC{PESEL} paszport PASPL-EA{PESEL}",
    ],
)
def test_etsi_person_identifiers_are_redacted_in_any_format(text):
    assert PESEL not in redact_sensitive(text)


def test_redaction_is_idempotent():
    once = redact_sensitive(f"Failed to build path for {SUBJECT}")
    assert redact_sensitive(once) == once


def test_ordinary_lines_stay_readable():
    line = "Encountered disallowed algorithm during CMS validation; Country: PL"
    assert redact_sensitive(line) == line


@pytest.mark.skipif(
    RedactingJsonFormatter.__bases__[0] is logging.Formatter,
    reason="python-json-logger niedostępny — produkcyjny formatter nie istnieje",
)
@pytest.mark.asyncio
async def test_real_pyhanko_warning_reaches_stdout_without_the_person():
    """Prawdziwy log pyHanko z walidatora NEXUSA, przez produkcyjny handler."""
    from cryptography import x509
    from cryptography.x509.oid import NameOID
    from pyhanko.sign.validation.qualified.tsp import TSPRegistry

    from app.services.b2b_esign import qualified
    from tests._signed_pdf import blank_pdf, sign, signer_from_ca_outside_the_eu_list

    signer = signer_from_ca_outside_the_eu_list(
        NAME,
        [
            x509.NameAttribute(NameOID.SERIAL_NUMBER, f"PNOPL-{PESEL}"),
            x509.NameAttribute(NameOID.GIVEN_NAME, "JAN, ADAM"),
            x509.NameAttribute(NameOID.SURNAME, "TESTOWY"),
        ],
    )
    data = await sign(
        blank_pdf(),
        NAME,
        datetime(2026, 11, 3, tzinfo=timezone.utc),
        field="Podpis1",
        signer=signer,
    )

    raw: list[str] = []

    class _Raw(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            raw.append(record.getMessage())

    out = io.StringIO()
    production = logging.StreamHandler(out)
    production.setFormatter(
        RedactingJsonFormatter(
            "%(asctime)s %(levelname)s %(name)s %(message)s",
            rename_fields={"asctime": "timestamp", "levelname": "level"},
        )
    )
    production.addFilter(RedactingFilter())
    pyhanko_logger = logging.getLogger("pyhanko")
    # Kolejność ma znaczenie: ``RedactingFilter`` przepisuje ``record.msg``,
    # więc surowa kopia (dowód, że pyHanko w ogóle zalogował podmiot) jest pierwsza.
    pyhanko_logger.addHandler(raw_handler := _Raw())
    pyhanko_logger.addHandler(production)
    try:
        validator = qualified.QualifiedValidator()
        validator._registry = TSPRegistry()  # lista bez wystawcy podpisu, bez sieci
        report = await validator.validate(data)
    finally:
        pyhanko_logger.removeHandler(raw_handler)
        pyhanko_logger.removeHandler(production)

    assert report.signature_results[0]["untrusted_issuer"] is True
    assert any("TESTOWY" in message for message in raw), raw
    emitted = out.getvalue()
    records = [json.loads(line) for line in emitted.splitlines()]
    assert any("Failed to build path" in r["message"] for r in records), emitted
    assert _leaks(emitted) == [], emitted
