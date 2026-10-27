"""Sprawdzenie zrzutu zgody RODO pod CV (F37, 27.10.2026).

Przypadki odtwarzają złe zrzuty z pomiaru na produkcji (121 zrzutów, 11 złych)
na fikcyjnych osobach: prośba rekrutera zamiast odpowiedzi, inny numer ZOB,
zgoda innej osoby, plakat zamiast maila, ten sam plik u innego kandydata.
"""

from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.services import cv_consent_check as cc
from app.services import cv_qc as qc
from app.services.cv_finding_dismissals import NOT_DISMISSABLE
from app.services.cv_generator_b2b import consent_binding as binding

SUBJECT = cc.Subject(
    candidate_id=10,
    first_name="Mirosław",
    last_name="Kowalczyk",
    emails=("mirek.k@example.com",),
    client_name="PKO BP",
    expected_zob="3092",
    opened_on=date(2026, 10, 20),
)

CONSENT = (
    "Ja, Mirosław Kowalczyk, wyrażam zgodę na przetwarzanie przez PKO Bank Polski "
    "moich danych osobowych zawartych w dokumencie CV, przekazanym przez B2B.net S.A. "
    "w ramach zapytania ofertowego nr ZOB-3092."
)


def reading(**overrides):
    base = {
        "is_email": True,
        "sender_name": "Mirosław Kowalczyk",
        "sender_email": "mirek.k@example.com",
        "recipients": ["Anna Rekruterka"],
        "mail_date": "2026-10-21",
        "subject": "ZOB-3092 - zgoda na przetwarzanie danych osobowych",
        "consent_text": CONSENT,
    }
    return {**base, **overrides}


def codes(result, key="problems"):
    return [p["code"] for p in result[key]]


def test_matching_reply_passes_with_what_was_checked():
    result = cc.assess(reading(), SUBJECT)
    assert result["status"] == "ok"
    assert codes(result) == []
    assert codes(result, "passed") == ["sender", "name", "zob", "date"]
    assert result["reading"]["zob"] == ["ZOB-3092"]
    # Treść zgody nie ląduje w zapisanym wyniku — tylko nagłówek.
    assert "consent_text" not in result["reading"]


def test_recruiter_request_is_not_the_candidates_answer():
    """Przypadek 3456: nadawcą jest rekruterka, kandydat jest adresatem."""
    result = cc.assess(
        reading(
            sender_name="Anna Rekruterka",
            sender_email=None,
            recipients=["mirek.k@example.com"],
        ),
        SUBJECT,
    )
    assert result["status"] == "mismatch"
    assert codes(result) == ["recruiter_request"]


def test_consent_from_another_tender_is_flagged():
    """Przypadek 3331: ZOB-2584 w zgodzie, rekrutacja ZOB-2984."""
    subject = cc.Subject(**{**SUBJECT.__dict__, "expected_zob": "2984"})
    result = cc.assess(
        reading(consent_text=CONSENT.replace("3092", "2584"), subject=None), subject
    )
    assert codes(result) == ["wrong_zob"]
    assert "ZOB-2584" in result["problems"][0]["detail"]
    assert "ZOB-2984" in result["problems"][0]["detail"]


def test_consent_of_another_person_is_flagged():
    result = cc.assess(
        reading(consent_text=CONSENT.replace("Mirosław Kowalczyk", "Piotr Nowak")),
        SUBJECT,
    )
    assert codes(result) == ["wrong_person"]


def test_poster_instead_of_mail_stops_at_not_consent():
    result = cc.assess(
        reading(is_email=False, sender_name=None, consent_text=None), SUBJECT
    )
    assert codes(result) == ["not_consent"]


def test_mail_from_before_the_recruitment_opened():
    result = cc.assess(reading(mail_date="2026-09-01"), SUBJECT)
    assert codes(result) == ["old_date"]
    # Zapas trzech dni na rekrutację założoną po zapytaniu klienta.
    assert cc.assess(reading(mail_date="2026-10-18"), SUBJECT)["status"] == "ok"


def test_missing_header_and_missing_tender_number():
    result = cc.assess(
        reading(
            sender_name=None,
            sender_email=None,
            subject=None,
            consent_text=CONSENT.replace(" nr ZOB-3092", ""),
        ),
        SUBJECT,
    )
    assert codes(result) == ["no_sender", "no_zob"]


def test_other_client_named_in_the_consent():
    result = cc.assess(
        reading(consent_text=CONSENT.replace("PKO Bank Polski", "mBank")), SUBJECT
    )
    assert codes(result) == ["other_client"]


def test_names_match_without_diacritics_case_or_full_first_name():
    upper = CONSENT.replace("Mirosław Kowalczyk", "MIROSŁAW KOWALCZYK")
    assert cc.assess(reading(consent_text=upper), SUBJECT)["status"] == "ok"
    # Skrzynka podpisana zdrobnieniem i bez polskich znaków, adres inny niż w bazie.
    nick = reading(sender_name="Mirek Kowalczyk", sender_email="mk@example.org")
    assert cc.assess(nick, SUBJECT)["status"] == "ok"
    # Skrzynka podpisana samym imieniem — nazwisko jest w treści zgody.
    first_only = reading(sender_name="Mirosław", sender_email="x@example.org")
    assert cc.assess(first_only, SUBJECT)["status"] == "ok"


def test_short_reply_quoting_the_request_counts_as_consent():
    quoted = (
        "Potwierdzam. czw., 8 paź 2026 o 10:23 Anna Rekruterka napisał(a): "
        "Dzień dobry, " + CONSENT
    )
    assert cc.assess(reading(consent_text=quoted), SUBJECT)["status"] == "ok"


def test_without_a_known_candidate_only_the_document_is_checked():
    subject = cc.Subject(**{**SUBJECT.__dict__, "first_name": "", "last_name": ""})
    result = cc.assess(reading(sender_name="Ktoś Inny", sender_email=None), subject)
    assert result["status"] == "ok"
    assert "sender" not in codes(result, "passed")


def test_model_failure_is_unavailable_but_a_reused_file_still_counts():
    assert cc.assess(None, SUBJECT)["status"] == "unavailable"
    reused = cc.assess(None, SUBJECT, duplicate=True)
    assert reused["status"] == "mismatch"
    assert codes(reused) == ["duplicate"]


def test_parse_reply_keeps_only_known_fields_and_rejects_garbage():
    assert cc.parse_reply("nie wiem") is None
    assert cc.parse_reply("[1, 2]") is None
    parsed = cc.parse_reply(
        'Oto wynik: {"is_email": true, "sender_name": " Jan  K ", '
        '"recipients": ["a@b.pl", 5, null], "mail_date": "21.10.2026", '
        '"consent_text": "Ja, Jan K, wyrażam zgodę", "extra": "x"}'
    )
    assert parsed["sender_name"] == "Jan K"
    assert parsed["recipients"] == ["a@b.pl", "5"]
    assert parsed["mail_date"] is None
    assert "extra" not in parsed


def test_zob_and_name_are_read_by_code_from_the_transcribed_text():
    assert cc.zob_numbers("nr ZOB-3092, a temat ZOB 03092 i zob_12") == ["3092", "12"]
    assert cc.consent_name("Ja, **Jan Kowalski**, wyrażam zgodę") == "Jan Kowalski"
    assert cc.consent_name("Wyrażam zgodę") is None


def test_override_reason_is_required_to_save_a_mismatch():
    assert cc.clean_override_reason("   ") is None
    with pytest.raises(ValueError):
        cc.clean_override_reason("ok")
    reason = cc.clean_override_reason("kandydat  potwierdził telefonicznie")
    assert reason == "kandydat potwierdził telefonicznie"
    saved = cc.with_override({"status": "mismatch"}, reason, 7)
    assert saved["override"]["reason"] == reason
    assert saved["override"]["by"] == 7


def test_receipt_carries_the_signed_check_into_the_binding():
    context = binding.subject(candidate_id=1, stage_id=2, client_id=3)
    check = {"status": "ok", "problems": [], "passed": []}
    token = binding.issue("cv/x.png", 7, context, check)
    assert binding.verify(token, 7, context)["binding"]["check"] == check
    plain = binding.issue("cv/x.png", 7, context)
    assert "check" not in binding.verify(plain, 7, context)["binding"]


async def test_duplicate_lookup_skips_unknown_candidate_and_stops_at_first_hit():
    db = SimpleNamespace(scalar=AsyncMock(side_effect=[None, 55]))
    assert await cc.used_for_other_candidate(db, b"img", None) is False
    db.scalar.assert_not_awaited()
    assert await cc.used_for_other_candidate(db, b"img", 10) is True
    assert db.scalar.await_count == 2


async def test_check_screenshot_survives_a_model_failure(monkeypatch):
    def boom(*_args):
        raise RuntimeError("provider down")

    monkeypatch.setattr(cc, "_call_model", boom)
    db = SimpleNamespace(scalar=AsyncMock(return_value=None))

    class _Feature:
        async def __aenter__(self):
            return None

        async def __aexit__(self, *exc):
            return False

    monkeypatch.setattr("app.services.ai_quota.ai_feature", lambda *a, **k: _Feature())
    result = await cc.check_screenshot(
        db, image=b"img", mime="image/png", subject=SUBJECT, user_id=7
    )
    assert result["status"] == "unavailable"


def _qc_data(consent, record):
    return qc.QcInput(
        must=[],
        nice=[],
        blocks=[],
        has_cv=True,
        bold_known=True,
        original_text="",
        experience=None,
        consent=consent,
        consent_check=record,
    )


def test_qc_shows_an_overridden_mismatch_to_the_delivery_lead():
    record = cc.with_override(
        cc.assess(
            reading(
                sender_name="Anna Rekruterka",
                sender_email=None,
                recipients=["mirek.k@example.com"],
            ),
            SUBJECT,
        ),
        "kandydat potwierdził telefonicznie",
        7,
    )
    check = qc._consent_matches_check(_qc_data("ok", record))
    assert check["status"] == "fail"
    assert check["severity"] == "warning"
    (item,) = check["items"]
    assert "prośba o zgodę" in item["detail"]
    assert "„kandydat potwierdził telefonicznie”" in item["detail"]
    assert item["fix"] == "replace_consent"
    # DL przyjmuje zrzut przez „To OK” — uwaga musi dać się pominąć.
    assert "consent_matches" not in NOT_DISMISSABLE
    assert "consent_matches" in qc.WARNING_KEYS


def test_qc_consent_states_without_a_mismatch():
    ok = cc.assess(reading(), SUBJECT)
    assert qc._consent_matches_check(_qc_data("ok", ok))["status"] == "pass"
    down = cc.assess(None, SUBJECT)
    assert qc._consent_matches_check(_qc_data("ok", down))["status"] == "manual"
    # Zrzut sprzed sprawdzania i brak zrzutu: bez uwagi.
    assert qc._consent_matches_check(_qc_data("ok", None))["status"] == "skip"
    assert qc._consent_matches_check(_qc_data("missing", ok))["status"] == "skip"


def test_cases_found_by_the_measurement_on_121_screenshots():
    """Poprawki po pomiarze 27.10 (przypadki 3371, 2708, 2972, 2745)."""
    glued = reading(consent_text=CONSENT.replace("nr ZOB-3092", "nrZOB-3092"))
    assert cc.assess(glued, SUBJECT)["status"] == "ok"
    # Literówka w nazwisku: adres nadawcy zgadza się z bazą.
    typo = reading(consent_text=CONSENT.replace("Kowalczyk", "Kowalczak"))
    assert cc.assess(typo, SUBJECT)["status"] == "ok"
    assert codes(
        cc.assess(reading(consent_text=CONSENT.replace("Kowalczyk", "Nowak")), SUBJECT)
    ) == ["wrong_person"]
    # Mail do kandydata, „nadawca” wzięty z treści zgody — to nadal prośba.
    to_candidate = reading(sender_email=None, recipients=["mirek.k@example.com"])
    assert codes(cc.assess(to_candidate, SUBJECT)) == ["recruiter_request"]
    # Sama treść zgody bez nagłówka maila.
    bare = reading(is_email=False, sender_name=None, sender_email=None, recipients=[])
    assert codes(cc.assess(bare, SUBJECT)) == ["no_sender"]
