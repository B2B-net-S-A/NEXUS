"""Umowa przedwstępna przy osobie — reguła stanów, plakietki i sweepera (bez bazy).

Decyzje Artura 21.10.2026: prośba przy osobie (DL / HoR / rekruter), każda
forma podpisu, brak podpisu nie blokuje ruchu — plakietka robi się czerwona,
gdy osoba minęła etap, przed którym umowa miała być podpisana.
"""

from __future__ import annotations

import importlib.util
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from app.models.pre_contract import PreContractRequest
from app.services import pre_contract_schema as schema
from app.services import pre_contracts as svc
from app.tasks.pre_contract_sweeper import due_action

TODAY = date(2026, 10, 21)  # środa
NOW = datetime(2026, 10, 21, 10, 0, tzinfo=timezone.utc)
BACKEND = Path(__file__).resolve().parents[1]


def _req(**kw) -> PreContractRequest:
    base = dict(
        id=1,
        candidate_id=10,
        job_id=20,
        needed_before="cv_sent",
        needed_by=None,
        document_id=None,
        issued_at=None,
        sent_at=None,
        candidate_signed_at=None,
        company_signed_at=None,
        valid_until=None,
        b2b_deadline=None,
        closed_at=None,
        close_reason=None,
        last_reminder_at=None,
    )
    base.update(kw)
    return PreContractRequest(**base)


def _signed(**kw) -> PreContractRequest:
    return _req(
        document_id=5,
        sent_at=NOW - timedelta(days=5),
        candidate_signed_at=NOW - timedelta(days=4),
        company_signed_at=NOW - timedelta(days=3),
        **kw,
    )


# ── Stan ─────────────────────────────────────────────────────────────────────


def test_state_follows_the_steps() -> None:
    assert svc.state_of(_req()) == "requested"
    assert svc.state_of(_req(document_id=5)) == "issued"
    assert svc.state_of(_req(document_id=5, sent_at=NOW)) == "sent"
    assert (
        svc.state_of(_req(document_id=5, sent_at=NOW, candidate_signed_at=NOW))
        == "candidate_signed"
    )
    assert svc.state_of(_signed()) == "signed"
    assert svc.state_of(_req(closed_at=NOW, close_reason="expired")) == "expired"


def test_signed_needs_both_signatures() -> None:
    assert svc.is_signed(_signed())
    assert not svc.is_signed(_req(candidate_signed_at=NOW))


# ── Plakietka ────────────────────────────────────────────────────────────────


def test_requested_before_cv_is_orange_until_cv_goes_out() -> None:
    b = svc.badge(_req(), column="verified", today=TODAY)
    assert b.tone == "missing"
    assert b.label == "Przedwstępna przed wysłaniem CV — nie wystawiona"


def test_missing_contract_after_cv_sent_is_red() -> None:
    b = svc.badge(_req(), column="cv_sent", today=TODAY)
    assert b.tone == "late"
    assert "miała być podpisana przed wysłaniem CV" in b.detail


def test_client_interview_requirement_is_not_late_in_cv_sent() -> None:
    req = _req(needed_before="client_interview")
    assert svc.badge(req, column="cv_sent", today=TODAY).tone == "missing"
    assert svc.badge(req, column="client_interview", today=TODAY).tone == "late"


def test_date_requirement_turns_late_after_the_date() -> None:
    req = _req(needed_before="date", needed_by=TODAY - timedelta(days=1))
    b = svc.badge(req, column="new", today=TODAY)
    assert b.tone == "late"
    assert "do 20.10" in b.label


def test_sent_counts_waiting_days() -> None:
    req = _req(document_id=5, sent_at=NOW - timedelta(days=2))
    b = svc.badge(req, column="verified", today=TODAY)
    assert b.tone == "wait"
    assert b.label == "Przedwstępna wysłana · czeka 2 dni"


def test_candidate_signed_waits_for_company() -> None:
    req = _req(document_id=5, sent_at=NOW, candidate_signed_at=NOW)
    b = svc.badge(req, column="verified", today=TODAY)
    assert (b.tone, b.label) == ("signer", "Przedwstępna: czeka na podpis firmy")


def test_signed_shows_valid_until_then_expiring() -> None:
    ok = svc.badge(
        _signed(valid_until=date(2026, 12, 14)), column="cv_sent", today=TODAY
    )
    assert (ok.tone, ok.label) == ("ok", "Przedwstępna do 14.12")
    soon = svc.badge(
        _signed(valid_until=TODAY + timedelta(days=3)), column="cv_sent", today=TODAY
    )
    assert (soon.tone, soon.label) == ("late", "Przedwstępna wygasa za 3 dni")


def test_b2b_deadline_wins_over_validity() -> None:
    req = _signed(valid_until=date(2026, 12, 14), b2b_deadline=date(2026, 10, 26))
    b = svc.badge(req, column="contract", today=TODAY, business_days_left=3)
    assert b.tone == "late"
    assert b.label == "Umowa B2B: zostało 3 dni roboczych"


def test_closed_request_is_grey() -> None:
    b = svc.badge(
        _req(closed_at=NOW, close_reason="candidate_withdrew"), column=None, today=TODAY
    )
    assert b.tone == "closed"
    assert b.label == "Przedwstępna: kandydat zrezygnował"


def test_business_days_skip_weekend_and_holidays() -> None:
    # 21.10 (śr) → 26.10 (pn): czw, pt, pn = 3 dni robocze.
    assert svc.business_days_until(TODAY, date(2026, 10, 26)) == 3
    # 30.10 (pt) → 2.11 (pn): 1.11 to niedziela, 2.11 roboczy.
    assert svc.business_days_until(date(2026, 10, 30), date(2026, 11, 2)) == 1
    assert svc.business_days_until(TODAY, TODAY) == 0


# ── Sweeper ──────────────────────────────────────────────────────────────────


def test_sweeper_expires_signed_contract_after_validity() -> None:
    req = _signed(valid_until=TODAY - timedelta(days=1))
    assert due_action(req, today=TODAY, now=NOW) == "expire"


def test_sweeper_warns_once_before_expiry() -> None:
    req = _signed(valid_until=TODAY + timedelta(days=2))
    assert due_action(req, today=TODAY, now=NOW) == "expiring"
    req.last_reminder_at = NOW - timedelta(days=1)
    # Przypomnienie wyszło już w oknie 3 dni — drugiego nie ma.
    assert due_action(req, today=TODAY, now=NOW) is None


def test_sweeper_reminds_assignee_when_candidate_is_silent() -> None:
    req = _req(document_id=5, sent_at=NOW - timedelta(days=3, minutes=1))
    assert due_action(req, today=TODAY, now=NOW) == "reminder_waiting"
    req.last_reminder_at = NOW - timedelta(hours=2)
    assert due_action(req, today=TODAY, now=NOW) is None


def test_sweeper_warns_about_b2b_deadline() -> None:
    req = _signed(valid_until=date(2026, 12, 14), b2b_deadline=date(2026, 10, 22))
    assert due_action(req, today=TODAY, now=NOW) == "b2b_deadline"


def test_sweeper_ignores_closed_requests() -> None:
    req = _signed(
        valid_until=TODAY - timedelta(days=5), closed_at=NOW, close_reason="fulfilled"
    )
    assert due_action(req, today=TODAY, now=NOW) is None


# ── Lustro DDL ───────────────────────────────────────────────────────────────


def test_entrypoint_mirrors_every_statement_after_b2b_documents() -> None:
    entrypoint = (BACKEND / "entrypoint.sh").read_text(encoding="utf-8")
    documents = entrypoint.index("*_B2B_DOCUMENTS_DDL,")
    for statement in schema.ALL_DDL:
        assert statement in entrypoint, statement
        assert entrypoint.index(statement) > documents, statement
    assert schema.ENUM_DDL in entrypoint


def test_migration_uses_the_shared_ddl() -> None:
    path = BACKEND / "alembic" / "versions" / "0505_pre_contract_requests.py"
    spec = importlib.util.spec_from_file_location("m0504", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    assert module.revision == "0505_pre_contract_requests"
    text = path.read_text(encoding="utf-8")
    assert "schema.ALL_DDL" in text and "schema.ENUM_DDL" in text


def test_model_check_constraints_match_ddl() -> None:
    from app.models.pre_contract import CLOSE_REASONS, NEEDED_BEFORE, SIGNATURE_FORMS

    for value in (*NEEDED_BEFORE, *SIGNATURE_FORMS, *CLOSE_REASONS):
        assert f"'{value}'" in schema.REQUESTS_DDL, value


# ── Okno „Przesuń dalej” ─────────────────────────────────────────────────────


def _requirements(to_column: str, **facts):
    from app.services.move_requirements import PairFacts, build_requirements

    return build_requirements(PairFacts(from_column="verified", **facts), to_column)


def test_move_to_cv_sent_warns_about_unsigned_pre_contract_without_blocking() -> None:
    result = _requirements(
        "cv_sent",
        pre_contract_column="cv_sent",
        pre_contract_detail="DL poprosił(a) o nią przed wysłaniem CV.",
    )
    [item] = [i for i in result["items"] if i["key"] == "pre_contract"]
    assert item["status"] == "missing" and item["blocking"] is False
    assert item["action"]["kind"] == "open_pre_contract"


def test_no_warning_before_the_needed_column_or_when_signed() -> None:
    early = _requirements("cv_qc", pre_contract_column="cv_sent")
    assert not [i for i in early["items"] if i["key"] == "pre_contract"]
    signed = _requirements(
        "cv_sent", pre_contract_column="cv_sent", pre_contract_signed=True
    )
    assert not [i for i in signed["items"] if i["key"] == "pre_contract"]


def test_cez_template_binds_five_business_days() -> None:
    assert svc.b2b_term_days("preliminary_cez") == 5
    assert svc.b2b_term_days(None) is None


def test_sweeper_does_not_repeat_b2b_deadline_after_it_passed() -> None:
    req = _signed(
        valid_until=TODAY + timedelta(days=30),
        b2b_deadline=TODAY - timedelta(days=5),
        last_reminder_at=NOW - timedelta(days=1),
    )
    assert due_action(req, today=TODAY, now=NOW) is None


def test_pre_contract_bell_cannot_be_muted_and_has_a_group() -> None:
    from app.models.notification import NotificationType
    from app.services.notification_categories import (
        CATEGORY_BY_TYPE,
        NotificationCategory,
    )

    assert (
        CATEGORY_BY_TYPE[NotificationType.pre_contract] is NotificationCategory.mentions
    )
