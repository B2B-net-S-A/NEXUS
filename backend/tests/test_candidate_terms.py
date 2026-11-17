"""Warunki od kandydata: kto dostaje link, przeliczenie stawki, treść maila."""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.services import candidate_terms as t

NOW = datetime(2026, 11, 17, 10, 0, tzinfo=timezone.utc)
FULL = t.TermsSnapshot(
    rate=Decimal("120"),
    modes=("hybrid",),
    onsite_days=2,
    office_cities=("Warszawa",),
    notice_period=1,
)


def _elig(**kw):
    base = dict(
        email="kandydat@example.com",
        snapshot=t.TermsSnapshot(),
        applied_at=NOW - timedelta(hours=2),
        now=NOW,
        last_link_sent_at=None,
        opted_out=False,
        blacklisted=False,
        works_here=False,
    )
    base.update(kw)
    return t.eligibility(**base)


def test_empty_profile_gets_link_with_all_fields_missing():
    e = _elig()
    assert e.action == t.LINK
    assert e.missing == ("rate", "work_mode", "start")


def test_complete_profile_gets_thanks_only():
    assert _elig(snapshot=FULL) == t.Eligibility(t.THANKS, "complete")


@pytest.mark.parametrize(
    "snapshot,missing",
    [
        (t.TermsSnapshot(rate=Decimal(1), modes=("remote",), notice_period=0), ()),
        (
            t.TermsSnapshot(rate=Decimal(1), modes=("hybrid",), notice_period=0),
            ("office",),
        ),
        (
            t.TermsSnapshot(
                rate=Decimal(1), modes=("hybrid",), onsite_days=2, notice_period=0
            ),
            ("office",),
        ),
        (
            t.TermsSnapshot(
                rate=Decimal(1),
                modes=("onsite",),
                office_cities=("Gdańsk",),
                availability_date=date(2026, 12, 1),
            ),
            (),
        ),
    ],
)
def test_office_counts_only_when_office_is_possible(snapshot, missing):
    assert t.missing_fields(snapshot) == missing


@pytest.mark.parametrize(
    "kw,action,reason",
    [
        (dict(email=None), t.NONE, "no_email"),
        (dict(email="bez-malpy"), t.NONE, "no_email"),
        (dict(blacklisted=True), t.NONE, "blacklisted"),
        (dict(works_here=True), t.NONE, "works_here"),
        (dict(applied_at=NOW - timedelta(days=4)), t.NONE, "stale_application"),
        (dict(opted_out=True), t.THANKS, "opted_out"),
        (dict(last_link_sent_at=NOW - timedelta(days=29)), t.THANKS, "recent_request"),
    ],
)
def test_refusal_paths(kw, action, reason):
    e = _elig(**kw)
    assert (e.action, e.reason) == (action, reason)


def test_link_again_after_30_days():
    assert _elig(last_link_sent_at=NOW - timedelta(days=30)).action == t.LINK


def test_application_exactly_three_days_old_still_counts():
    assert _elig(applied_at=NOW - timedelta(days=3)).action == t.LINK


@pytest.mark.parametrize(
    "hour,minute,ok",
    [(7, 59, False), (8, 0, True), (19, 59, True), (20, 0, False), (23, 0, False)],
)
def test_send_window(hour, minute, ok):
    assert t.in_send_window(datetime(2026, 11, 17, hour, minute)) is ok


def test_monthly_rate_is_divided_by_168():
    assert t.hourly_rate(Decimal("20160"), "month") == Decimal("120.00")
    assert t.hourly_rate(Decimal("95.5"), "hour") == Decimal("95.50")
    with pytest.raises(ValueError):
        t.hourly_rate(Decimal("1"), "day")


def test_unit_warning():
    assert t.rate_unit_warning(Decimal("25000"), "hour") == "looks_monthly"
    assert t.rate_unit_warning(Decimal("150"), "month") == "looks_hourly"
    assert t.rate_unit_warning(Decimal("120"), "hour") is None


def test_token_is_hashed_and_unique():
    raw, digest = t.new_token()
    assert len(raw) >= 32 and digest == t.token_hash(raw) and raw not in digest
    assert t.new_token()[0] != raw


def _mail(**kw):
    base = dict(
        job_title="Junior IT Analyst – Data & Reporting (f/m/x)",
        link="https://nexus.example/warunki/abc",
        optout_link="https://nexus.example/warunki/abc/wypis",
        recruiter_name="Anna Kowalska",
        rodo_url="https://nexus.example/kariera/rodo",
        logo_url="https://nexus.example/brand/mail/logo.png",
        logo_light_url="https://nexus.example/brand/mail/logo-light.png",
    )
    base.update(kw)
    return t.render_terms_email(**base)


def test_mail_with_link_has_both_parts_and_questions():
    m = _mail()
    assert (
        m.subject
        == "Dziękujemy za zgłoszenie: Junior IT Analyst – Data & Reporting (f/m/x)"
    )
    for part in (m.text_body, m.html_body):
        assert "https://nexus.example/warunki/abc" in part
        assert "Minimalna stawka na B2B" in part
        assert "Anna Kowalska" in part
        assert "/warunki/abc/wypis" in part


def test_thanks_only_mail_has_no_link_and_no_questions():
    m = _mail(link=None, optout_link=None)
    assert "warunki" not in m.text_body and "warunki" not in m.html_body
    assert "Minimalna stawka" not in m.html_body
    assert "Dziękujemy za zgłoszenie" in m.html_body


def test_mail_escapes_title_and_name():
    m = _mail(job_title="<script>x</script>", recruiter_name="<b>Zła</b>")
    assert "<script>" not in m.html_body and "&lt;script&gt;" in m.html_body
    assert "<b>Zła</b>" not in m.html_body


def test_mail_without_title_is_generic():
    m = _mail(job_title="  ")
    assert m.subject == "Dziękujemy za zgłoszenie"
    assert "stanowisko" not in m.text_body


def test_mail_without_recruiter_does_not_promise_a_reply():
    m = _mail(recruiter_name=None)
    assert "Odpowiedz na tego maila" not in m.text_body
    assert "Odpowiedz na tego maila" not in m.html_body


def test_ad_title_from_import_note():
    from app.services.candidate_terms_queue import ad_title_from_note

    assert (
        ad_title_from_note("Źródło: Pracuj.pl — oferta: Data Engineer")
        == "Data Engineer"
    )
    assert (
        ad_title_from_note("Aplikacja przez JustJoin.IT — ogłoszenie: QA (k/m)")
        == "QA (k/m)"
    )
    assert ad_title_from_note("Aplikacja ręczna") is None
    assert ad_title_from_note(None) is None
