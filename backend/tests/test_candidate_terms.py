"""Warunki od kandydata: kto dostaje link, przeliczenie stawki, treść maila."""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from html import unescape
from html.parser import HTMLParser

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
        assert (
            "dziękujemy za CV na stanowisko „Junior IT Analyst – Data & Reporting (f/m/x)”. "
            "Jeśli chcesz, daj nam znać, jaka stawka Ci odpowiada, jak wolisz pracować "
            "i kiedy możesz zacząć."
        ) in unescape(part)
        assert "30 sekund" in part
        assert "nie odpowiadaj na nią" in part
        assert "/warunki/abc/wypis" in part


def test_thanks_only_mail_has_no_link_and_no_questions():
    m = _mail(link=None, optout_link=None)
    assert "warunki" not in m.text_body and "warunki" not in m.html_body
    assert "Minimalna stawka" not in m.html_body
    assert "Dziękujemy za zgłoszenie" in m.html_body


def test_mail_escapes_title_and_name():
    m = _mail(job_title="<script>x</script>")
    assert "<script>" not in m.html_body and "&lt;script&gt;" in m.html_body


def test_mail_without_title_is_generic():
    m = _mail(job_title="  ")
    assert m.subject == "Dziękujemy za zgłoszenie"
    for part in (m.text_body, m.html_body):
        assert "dziękujemy za CV. Jeśli chcesz" in part
        assert "stanowisko" not in part


def test_mail_never_invites_replies():
    """Decyzja Artura 17.11.2026: kandydat wypełnia formularz, nie odpisuje."""
    for m in (_mail(), _mail(link=None, optout_link=None)):
        assert "Odpowiedz na tego maila" not in m.text_body + m.html_body
        assert "nie odpowiadaj na nią" in m.text_body


@pytest.mark.parametrize("with_request", [True, False])
def test_mail_ends_with_footer_and_nothing_after_it(with_request):
    """Gmail zwija powtarzającą się stopkę w kolejnych mailach wątku (T3b 18.11).

    Wypis, informacja o danych i dane spółki są na końcu, bez logo ani obrazu
    pod nimi; logo jest tylko w nagłówku.
    """

    class MessageOrder(HTMLParser):
        def __init__(self):
            super().__init__()
            self.items = []
            self._skip = False

        def handle_starttag(self, tag, attrs):
            attrs = dict(attrs)
            self._skip = tag in {"style", "title"}
            if tag in {"a", "img"}:
                self.items.append(attrs.get("href") or attrs.get("src"))

        def handle_endtag(self, tag):
            self._skip = False

        def handle_data(self, data):
            if data.strip() and not self._skip:
                self.items.append(data.strip())

    message = _mail(**({} if with_request else {"link": None, "optout_link": None}))
    parsed = MessageOrder()
    parsed.feed(message.html_body)
    logos = [i for i, item in enumerate(parsed.items) if item and item.endswith(".png")]
    rodo = parsed.items.index("https://nexus.example/kariera/rodo")
    assert logos and max(logos) < rodo
    assert any(
        "nie odpowiadaj na nią" in item for item in parsed.items[rodo - 2 : rodo]
    )
    assert parsed.items[-1].startswith("B2B.NET S.A.")
    if with_request:
        optout = parsed.items.index("https://nexus.example/warunki/abc/wypis")
        assert parsed.items.index("https://nexus.example/warunki/abc") < optout < rodo


def test_progress_bar_only_when_terms_are_missing():
    """Pasek „Zgłoszenie ✓ · CV ✓ · Twoje warunki” tylko w mailu z linkiem."""
    assert "Tyle dzieli Twoje zgłoszenie od kompletu" in _mail().html_body
    thanks = _mail(link=None, optout_link=None)
    assert "30 sekund" not in thanks.html_body + thanks.text_body
    assert "kompletu" not in thanks.html_body


def test_dark_mode_swaps_to_light_logo():
    html_body = _mail().html_body
    assert 'content="light dark"' in html_body
    assert "prefers-color-scheme: dark" in html_body
    assert (
        'class="dk" src="https://nexus.example/brand/mail/logo-light.png"' in html_body
    )


def test_mail_uses_variant5_palette_without_gradients():
    """Kolory wariantu 5 (decyzja Artura 25.11.2026): czerwień #C42329,
    burgund-obsydian #1F1115 zamiast grafitu, bez starej czerwieni i gradientów.
    W ciemnym trybie kropka i zaliczone odcinki biorą #D43424 (kontrast 3:1)."""
    for m in (_mail(), _mail(link=None, optout_link=None)):
        html_body = m.html_body.upper()
        for old in ("#D62E40", "#1A1816", "#B3202F", "#0E0E0D", "#181715", "#F4F3F0"):
            assert old not in html_body
        assert "#C42329" in html_body and "#1F1115" in html_body
        assert "GRADIENT" not in html_body
        assert ".RD{COLOR:#D43424!IMPORTANT}" in html_body
        assert 'CLASS="RD"' in html_body
    assert ".SGD{BACKGROUND:#D43424!IMPORTANT" in _mail().html_body.upper()


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


def test_one_click_unsubscribe_points_at_the_api_opt_out():
    assert t.one_click_unsubscribe_url("https://api.example.com/", "tok") == (
        "https://api.example.com/api/public/candidate-terms/tok/opt-out"
    )
    # Samo podziękowanie nie ma tokenu, więc nie ma też wypisu jednym kliknięciem.
    assert t.one_click_unsubscribe_url("https://api.example.com", None) is None


@pytest.mark.asyncio
async def test_start_now_is_today_in_the_company_calendar(monkeypatch):
    """Odpowiedź „od zaraz” o 00:30 w Warszawie (23:30 UTC) to już 25.11,
    a nie dzień UTC (audyt 24.11.2026)."""
    from types import SimpleNamespace

    from app.services import candidate_terms_apply as apply
    from app.services import match_score_cache

    async def _no_edits(*_a, **_kw):
        return set()

    async def _noop(*_a, **_kw):
        return None

    monkeypatch.setattr(apply, "_recent_human_edits", _no_edits)
    monkeypatch.setattr(
        apply.candidate_audit, "record_candidate_audit", lambda *a, **kw: None
    )
    monkeypatch.setattr(match_score_cache, "mark_stale_for_candidate", _noop)
    candidate = SimpleNamespace(
        id=1, availability_date=None, notice_period=2, notice_period_unit="months"
    )
    result = await apply.apply_answer(
        None,
        candidate,
        apply.TermsAnswer(start_kind="now"),
        now=datetime(2026, 11, 24, 23, 30, tzinfo=timezone.utc),
        request_id=1,
    )
    assert result["saved"] == ["start"]
    assert candidate.availability_date == date(2026, 11, 25)
    assert (candidate.notice_period, candidate.notice_period_unit) == (0, "days")
