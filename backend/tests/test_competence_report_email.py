"""Mail z raportem kompetencji: czyste rysowanie ze snapshotu, bez bazy.

Dane wyłącznie fikcyjne (repo publiczne).
"""

from __future__ import annotations

import os
import re

import pytest

from app.services import competence_report_email as mail
from app.services import notification_delivery as delivery
from app.services.competence_report_schema import (
    FunnelStep,
    Lever,
    MarketGroup,
    MarketRate,
    MissingTech,
    RatePosition,
    ReportConditions,
    ReportJob,
    ReportOwner,
    ReportProfile,
    ReportSnapshot,
    TechPremium,
)

LINKS = mail.ReportLinks(
    edit_conditions_url="https://example.test/raport/tok123/warunki",
    unsubscribe_url="https://example.test/raport/tok123?wypis=1",
    one_click_unsubscribe_url="https://api.example.test/api/public/competence-report/tok123/opt-out",
)

CLIENT_NAME = "Bank Przykładowy"
JOB_ID = 987654


def full_snapshot(**overrides) -> ReportSnapshot:
    data = dict(
        conditions=ReportConditions(
            rate=150,
            current_rate=135,
            contract="b2b",
            modes=("hybrid",),
            office_days_max=2,
            office_cities=("Kraków",),
            start="1m",
        ),
        profile=ReportProfile(role_label="Java", years=8, city="Kraków"),
        market=MarketRate(
            group=MarketGroup(role_label="Java", years_bucket="8+", city="Kraków"),
            p25=130,
            median=140,
            p75=169,
            n=42,
        ),
        rate_position=RatePosition(
            expected=150,
            expected_vs_median_pct=7,
            current=135,
            current_vs_median_pct=-4,
        ),
        funnel=(
            FunnelStep(key="tech", label="Otwarte projekty z Javą", count=21),
            FunnelStep(key="office_days", label="Biuro do 2 dni", count=11),
            FunnelStep(key="location", label="Kraków albo zdalnie", count=4),
            FunnelStep(key="budget", label="Od 150 zł/h", count=2),
        ),
        levers=(
            Lever(
                key="office_days_plus1",  # gitleaks:allow
                label="3 dni w biurze zamiast 2",
                hint="większość projektów w Krakowie chce 3 dni",
                gain=5,
            ),
            Lever(key="extra_city", label="Warszawa raz w tygodniu", gain=6),
            Lever(key="rate_to_median", label="Stawka od 140 zł/h", gain=1),
        ),
        strongest_tech=TechPremium(name="GCP", premium=15, months=38),
        missing_tech=MissingTech(name="Kubernetes", premium=10, jobs=6, of=21),
        jobs=(
            ReportJob(
                job_id=JOB_ID,
                title="Bankowość · platforma płatności",
                budget_max=155,
                skills=("Java 17", "Spring Boot", "Kafka"),
                place="Kraków, 2 dni w biurze",
                meets=True,
            ),
            ReportJob(
                job_id=JOB_ID + 1,
                title="Ubezpieczenia · obsługa szkód",
                budget_max=160,
                skills=("Java", "SQL"),
                place="Kraków, 3 dni w biurze",
                meets=False,
                miss_reason="o 1 dzień w biurze za dużo",
            ),
        ),
        owner=ReportOwner(user_id=7, name="Opiekun Testowy"),
    )
    data.update(overrides)
    return ReportSnapshot(**data)


def limited_snapshot(**overrides) -> ReportSnapshot:
    data = dict(
        variant="limited",
        conditions=ReportConditions(rate=90, modes=("remote",)),
        profile=ReportProfile(role_label="Analityk biznesowy"),
        owner=ReportOwner(user_id=7, name="Opiekun Testowy"),
    )
    data.update(overrides)
    return ReportSnapshot(**data)


def render(
    snapshot: ReportSnapshot, first_name: str | None = "Ala"
) -> mail.RenderedMail:
    return mail.render_report_email(snapshot, first_name=first_name, links=LINKS)


def test_full_variant_renders_every_section_in_order():
    out = render(full_snapshot())
    assert out.subject == "Twój raport kompetencji: Java, 8 lat"
    assert out.list_unsubscribe == LINKS.one_click_unsubscribe_url
    order = [
        "Twój raport kompetencji",
        "Coś się nie zgadza?",
        "Twoje 150 zł/h jest realne dla Twojego CV",
        "Projekty na Twoich warunkach",
        "Co otworzy Ci więcej projektów",
        "Najmocniejsza technologia",
        "Czego brakuje w CV",
        "Projekty dla Ciebie",
        "Opiekun Testowy, Twój opiekun",
        "Nie chcę raportów",
        "B2B.NET S.A., Al. Jerozolimskie 180, 02-486 Warszawa",
    ]
    body = out.html.split("Network</p>", 1)[1]  # bez <title> i preheadera
    positions = [body.index(marker) for marker in order]
    assert positions == sorted(positions)
    for chip in (
        "Java · 8 lat",
        "Kraków",
        "hybrydowo, do 2 dni",
        "150 zł/h B2B",
        "start za miesiąc",
    ):
        assert chip in out.html
    assert "Twoje oczekiwania są 7% nad medianą." in out.html
    assert "Dziś zarabiasz 135, czyli poniżej mediany." in out.html
    assert "2 projekty spełniają wszystko." in out.html
    assert "Według CV używasz jej od 3 lat." in out.html
    assert "W wymaganiach 6 z 21 projektów dla Twojej roli." in out.html
    assert "do 155 zł/h" in out.html
    assert "spełnia Twoje warunki" in out.html
    assert "o 1 dzień w biurze za dużo" in out.html
    assert "Odpisz na tę wiadomość" in out.html
    assert "grupa minimum 30 osób" in out.html
    assert "nie obietnica podwyżki" in out.html
    assert LINKS.edit_conditions_url in out.html
    assert LINKS.unsubscribe_url in out.html


def test_html_is_email_safe():
    out = render(full_snapshot()).html
    for banned in (
        "display:flex",
        "display:grid",
        "var(--",
        "position:absolute",
        "<img",
        "@import",
        "fonts.googleapis",
    ):
        assert banned not in out
    assert "max-width:640px" in out
    assert "Segoe UI" in out


def test_limited_variant_has_no_rate_and_no_levers():
    out = render(limited_snapshot(levers=full_snapshot().levers))
    assert out.subject == "Twój raport kompetencji: Analityk biznesowy"
    assert "nie umiemy jeszcze rzetelnie policzyć stawki" in out.html
    assert "Opiekun Testowy, Twój opiekun, zadzwoni" in out.html
    assert "Co otworzy Ci więcej projektów" not in out.html
    assert "mediana" not in out.html
    assert "Ty:" not in out.html
    assert "grupa minimum" not in out.html
    assert "nie umiemy jeszcze rzetelnie policzyć stawki" in out.text


def test_sections_without_data_are_left_out():
    out = render(
        full_snapshot(
            market=None,
            rate_position=None,
            funnel=(),
            levers=(),
            strongest_tech=None,
            missing_tech=None,
            jobs=(),
            owner=None,
        )
    )
    for title in (
        "Stawka",
        "Projekty na Twoich warunkach",
        "Co otworzy Ci więcej projektów",
        "Najmocniejsza technologia",
        "Czego brakuje w CV",
        "Projekty dla Ciebie",
        "Twój opiekun",
        "nie obietnica podwyżki",
    ):
        assert title not in out.html, title
        assert title.upper() not in out.text
    assert "Twój raport kompetencji" in out.html
    assert "Popraw warunki" in out.html


def test_only_one_tech_box_takes_the_full_width():
    out = render(full_snapshot(missing_tech=None)).html
    assert "Najmocniejsza technologia" in out
    assert "Czego brakuje w CV" not in out
    assert 'class="col"' not in out


def test_malicious_strings_are_escaped():
    evil = '<script>alert(1)</script>"><img src=x onerror=alert(1)>'
    snap = full_snapshot(
        profile=ReportProfile(role_label=evil, years=3, city=evil),
        jobs=(
            ReportJob(
                job_id=1,
                title=evil,
                skills=(evil,),
                place=evil,
                meets=False,
                miss_reason=evil,
            ),
        ),
        owner=ReportOwner(user_id=1, name=evil),
        levers=(Lever(key="extra_city", label=evil, hint=evil, gain=2),),
    )
    out = mail.render_report_email(snap, first_name=evil, links=LINKS).html
    assert "<script>" not in out
    assert "<img" not in out
    assert "onerror=alert(1)>" not in out
    assert "&lt;script&gt;" in out


def test_no_job_id_and_no_client_name_in_output():
    out = render(full_snapshot())
    for body in (out.html, out.text, out.subject):
        assert str(JOB_ID) not in body
        assert str(JOB_ID + 1) not in body
        assert CLIENT_NAME not in body
        assert "job_id" not in body


def test_widened_group_is_named_honestly():
    snap = full_snapshot(
        market=MarketRate(
            group=MarketGroup(
                role_label="Java", years_bucket="8+", city=None, widened=True
            ),
            p25=125,
            median=140,
            p75=165,
            n=31,
        )
    )
    out = render(snap)
    assert "mniej niż 30 osób, więc porównujemy dla całej Polski" in out.html
    assert "Java, 8+ lat, cała Polska" in out.html
    assert "porównujemy dla całej Polski" in out.text


def test_rate_below_and_above_market_wording():
    above = full_snapshot(
        rate_position=RatePosition(expected=200, expected_vs_median_pct=43),
        conditions=ReportConditions(rate=200),
    )
    assert "jest powyżej typowych stawek" in render(above).html
    below = full_snapshot(
        rate_position=RatePosition(expected=110, expected_vs_median_pct=-21),
        conditions=ReportConditions(rate=110),
    )
    out = render(below)
    assert "jest poniżej typowych stawek" in out.html
    assert "21% pod medianą" in out.html
    assert "Dziś zarabiasz" not in out.html


def test_rate_scale_cells_sum_to_100_percent():
    html = render(full_snapshot()).html
    start = html.index("table-layout:fixed")
    row = html[start : html.index("</tr>", start)]
    widths = [int(w) for w in re.findall(r'<td width="(\d+)%"', row)]
    assert sum(widths) == 100
    assert all(w >= 1 for w in widths)


def test_funnel_with_nothing_left_points_to_levers():
    snap = full_snapshot(
        funnel=(
            FunnelStep(key="tech", label="Otwarte projekty z Javą", count=0),
            FunnelStep(key="budget", label="Od 150 zł/h", count=0),
        )
    )
    assert (
        "Dziś żaden projekt nie spełnia wszystkich warunków. Niżej zobaczysz"
        in render(snap).html
    )


def test_plain_text_has_the_key_numbers():
    text = render(full_snapshot()).text
    assert text.startswith("Dzień dobry, Ala.")
    for needle in (
        "130–169 zł/h",
        "mediana 140",
        "7% nad medianą",
        "Otwarte projekty z Javą: 21",
        "Od 150 zł/h: 2",
        "3 dni w biurze zamiast 2: +5",
        "GCP +15 zł/h",
        "Kubernetes. +10 zł/h.",
        "do 155 zł/h",
        LINKS.edit_conditions_url,
        LINKS.unsubscribe_url,
        mail.COMPANY_LINE,
    ):
        assert needle in text, needle
    assert "<" not in text


def test_no_name_greeting_and_polish_numbers():
    assert render(full_snapshot(), first_name=None).text.startswith("Dzień dobry.\n")
    assert mail.fmt_num(12500) == "12 500"
    assert (
        mail._years(1) == "1 rok"
        and mail._years(3) == "3 lata"
        and mail._years(12) == "12 lat"
    )
    assert mail._projects(22) == "22 projekty" and mail._projects(15) == "15 projektów"


@pytest.mark.parametrize(
    ("raw", "email", "allowed"),
    [
        ("", "ktos@example.test", True),
        ("a@example.test, B@example.test", "b@example.test", True),
        ("a@example.test", "ktos@example.test", False),
        ("a@example.test", "", False),
        ("", None, False),
    ],
)
def test_trial_recipients_narrow_who_gets_mail(monkeypatch, raw, email, allowed):
    monkeypatch.delattr(mail.settings, mail.TEST_RECIPIENTS_SETTING, raising=False)
    monkeypatch.setitem(os.environ, mail.TEST_RECIPIENTS_SETTING, raw)
    assert mail.recipient_allowed(email) is allowed


def test_kind_is_a_candidate_mail_decided_by_admin():
    assert mail.KIND in delivery.ROUTINE_KINDS
    assert mail.KIND in delivery.CANDIDATE_KINDS
    assert mail.KIND not in delivery.REQUIRED_KINDS
    assert "25.11.2026" in delivery.ADMIN_DECIDES[mail.KIND]
    # Domyślnie wyłączony: pusta polityka niczego nie wpuszcza.
    assert not delivery.DeliveryPolicy.from_value(None).allows(mail.KIND, None)
