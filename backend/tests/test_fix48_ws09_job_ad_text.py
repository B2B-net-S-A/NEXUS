"""Ogłoszenie na portale i strona kariery — poprawki po audycie 48 h (13.10.2026).

Bez bazy. Kontrakty:

- punkt listy zdejmuje „1.” albo „2)”, ale nie część liczby („3.5 roku”,
  „2.5+ years”, „10.000”) — także przy ręcznym zapisie;
- decyzja A (14.10.2026): liczba przy „budżet / widełki / wynagrodzenie /
  salary / pensja / zarobki” blokuje kopiowanie ogłoszenia jak na stronie
  kariery; liczba przy „stawka” / „rate” zostaje uwagą;
- kontrola kariery łapie „180,- zł”, „30 tyś. zł” i „30tyś PLN”.
"""

from __future__ import annotations

import pytest

from app.services.job_ad import generate, lint
from app.services.public_profile_lint import lint_public_texts

# ── Punkt listy a liczba z kropką ───────────────────────────────────────────

_NUMBERS = [
    "3.5 roku doświadczenia w Javie",
    "2.5+ years of experience with Kubernetes",
    "10.000 transakcji na sekundę",
    "4.2 GHz to za mało",
]


def test_clean_list_keeps_a_number_with_a_dot():
    assert generate.clean_list(_NUMBERS, 10) == _NUMBERS


@pytest.mark.parametrize(
    "item,expected",
    [
        ("1. rozwój mikroserwisów", "rozwój mikroserwisów"),
        ("2) przeglądy kodu", "przeglądy kodu"),
        ("10. testy wydajności", "testy wydajności"),
        ("- 3.5 roku z Javą", "3.5 roku z Javą"),
        ("• 2.5+ years of Go", "2.5+ years of Go"),
        ("1. 3.5 roku z Javą", "3.5 roku z Javą"),
    ],
)
def test_clean_list_still_drops_list_markers(item, expected):
    assert generate.clean_list([item], 10) == [expected]


def test_manual_edit_keeps_a_number_with_a_dot():
    """``PUT /portal-ad`` czyści treść tą samą funkcją — poprawka rekrutera
    nie może zostać zepsuta przy zapisie."""
    content = generate.clean_content(
        {"requirements": _NUMBERS, "responsibilities": ["1.5 roku utrzymania"]},
        title="Java Developer",
    )
    assert content["requirements"] == _NUMBERS
    assert content["responsibilities"] == ["1.5 roku utrzymania"]


# ── Decyzja A: kwota przy słowie o wynagrodzeniu blokuje ────────────────────


def _content(**overrides) -> dict:
    base = {
        "title": "DevOps Engineer",
        "lead": "Szukamy osoby do zespołu utrzymania platformy kredytowej.",
        "about": "Rola łączy CI/CD, monitoring i integrację systemów.",
        "start": "listopad 2026",
        "duration": "12 miesięcy",
        "language": "polski",
        "responsibilities": ["budowa i utrzymanie pipeline'ów CI/CD w Jenkinsie"],
        "requirements": ["min. 4 lata pracy z Kubernetesem i Dockerem"],
        "nice_to_have": [],
        "offer": [],
    }
    base.update(overrides)
    return base


def _lint(content):
    return lint.lint_ad(content, [], client_names=["Kwarcowy Bank"], person_names=[])


@pytest.mark.parametrize(
    "text",
    [
        "Budżet klienta: 25 000 miesięcznie.",
        "Widełki 20-25k, B2B.",
        "Wynagrodzenie do 18000 na B2B.",
        "Salary up to 25k.",
        "Pensja 9000 na rękę.",
        "Zarobki do 30 000 miesięcznie.",
    ],
)
def test_a_number_near_a_pay_word_blocks_the_copy(text):
    findings = _lint(_content(about=text))
    assert [(f.code, f.severity, f.field) for f in findings] == [
        ("money", lint.SEVERITY_BLOCK, "about")
    ]
    assert lint.has_blocking(findings)
    assert "polu wynagrodzenia portalu" in findings[0].message
    # Strona kariery blokuje to samo zdanie — jedno źródło reguł.
    assert [f.code for f in lint_public_texts([text])] == ["money"]


@pytest.mark.parametrize(
    "text",
    ["Stawka 150-170.", "rate limiting i throttling w Java 17"],
)
def test_a_number_near_the_rate_word_still_only_advises(text):
    findings = _lint(_content(about=text))
    assert [(f.code, f.severity) for f in findings] == [
        (lint.CODE_POSSIBLE_MONEY, lint.SEVERITY_ADVISE)
    ]
    assert not lint.has_blocking(findings)


def test_a_rate_word_does_not_hide_a_pay_word_in_the_same_sentence():
    findings = _lint(_content(about="Stawka do ustalenia, widełki 20-25k."))
    assert lint.has_blocking(findings)
    assert lint.CODE_POSSIBLE_MONEY not in [f.code for f in findings]


def test_a_pay_word_false_alarm_blocks_but_says_how_to_get_out():
    """Koszt decyzji A: system płacowy z liczbą przy „wynagrodzenia” też
    blokuje (jak na stronie kariery). Komunikat mówi, jak to przeredagować;
    pewna kwota z walutą tej podpowiedzi nie dostaje."""
    findings = _lint(
        _content(
            responsibilities=["obsługa modułu wynagrodzenia dla 10 tys. pracowników"]
        )
    )
    assert [(f.code, f.severity) for f in findings] == [("money", lint.SEVERITY_BLOCK)]
    assert "napisz zdanie bez liczby przy tym słowie" in findings[0].message

    certain = _lint(_content(about="Wynagrodzenie 25 000 PLN miesięcznie."))
    assert [f.code for f in certain] == ["money"]
    assert "bez liczby przy tym słowie" not in certain[0].message


def test_fixed_blocks_refuse_a_number_near_a_pay_word():
    """Stały blok trafia do każdego ogłoszenia — tam też blokuje."""
    findings = lint.lint_fixed_blocks(["Wynagrodzenie do 18000 na B2B."])
    assert [f.code for f in findings] == ["money"]


# ── Strona kariery: zapisy kwot, które przechodziły ─────────────────────────


@pytest.mark.parametrize(
    "text",
    [
        "Oferujemy 180,- zł/h na B2B.",
        "Oferujemy 180,-zł.",
        "Oferujemy 180.- PLN za godzinę.",
        "Oferujemy 180,- złotych za godzinę.",
        "Oferujemy 30 tyś. zł miesięcznie.",
        "Oferujemy 30 tyś. Zł miesięcznie.",
        "Oferujemy 30 tyś. netto.",
        "Oferujemy 30tyś PLN.",
        "Oferujemy 30 tyś PLN.",
    ],
)
def test_career_check_catches_amounts_written_around_the_rules(text):
    assert [f.code for f in lint_public_texts([text])] == ["money"]


@pytest.mark.parametrize(
    "text",
    [
        "Wersja 2.0-RC i Java 8,-XX:+UseG1GC w konfiguracji.",
        "Zespół 5-osobowy, 30 tyś. linii kodu do przeglądu.",
    ],
)
def test_career_check_ignores_dashes_and_thousands_without_money(text):
    assert lint_public_texts([text]) == []


# ── Trasy bez bazy: kolejność kontroli ──────────────────────────────────────


class _FakeDb:
    """Sesja, która zna jeden wiersz i niczego nie zapisuje."""

    def __init__(self, row=None):
        self.row = row
        self.added: list = []

    async def get(self, model, key, **kwargs):
        return self.row

    def add(self, obj):
        self.added.append(obj)
        self.row = obj

    async def commit(self):
        return None

    async def refresh(self, obj):
        return None


async def test_prepare_without_a_version_on_an_existing_ad_is_409_before_the_model(
    monkeypatch,
):
    """Okno, które nie widziało ogłoszenia, wysyła pustą wersję. Przy
    istniejącym ogłoszeniu to 409 — model nie jest wołany, nic nie znika."""
    from datetime import datetime, timezone
    from types import SimpleNamespace

    from fastapi import HTTPException

    from app.api import job_ads
    from app.schemas.job_ad import AdGenerateRequest

    async def load_job(db, user, job_id):
        return SimpleNamespace(id=job_id)

    async def material(db, job):
        return None

    async def model_called(*args, **kwargs):
        raise AssertionError("model nie może zostać zawołany")

    monkeypatch.setattr(job_ads, "_load_job", load_job)
    monkeypatch.setattr(job_ads, "_material", material)
    monkeypatch.setattr(job_ads.generate, "generate_content", model_called)
    saved = SimpleNamespace(
        updated_at=datetime(2026, 10, 13, 9, 0, tzinfo=timezone.utc)
    )

    with pytest.raises(HTTPException) as refused:
        await job_ads.generate_portal_ad(
            7,
            AdGenerateRequest(lang="pl", expected_updated_at=None),
            SimpleNamespace(id=1),
            _FakeDb(saved),
        )
    assert refused.value.status_code == 409
    assert refused.value.detail["code"] == "job_ad_changed"
    assert "przygotował" in refused.value.detail["message"]


async def test_career_description_is_saved_without_direction_overrides(monkeypatch):
    """„‮łz 081‬” przeglądarka pokazuje jako „180 zł”, a kontrola
    porównuje tekst bez znaków formatujących („łz 081”) i go przepuszczała."""
    from types import SimpleNamespace

    from app.api import career_links
    from app.schemas.invite_link import PublicProfileUpdate

    async def load_job(db, user, job_id):
        return SimpleNamespace(id=job_id)

    async def response(db, user, job, profile):
        return profile

    monkeypatch.setattr(career_links, "_load_job", load_job)
    monkeypatch.setattr(career_links, "_profile_response", response)
    profile = await career_links.put_public_profile(
        7,
        PublicProfileUpdate(
            public_title="Java‮ Developer",
            subtitle="Platforma ‮łz 081‬ płatności",
            about="Oferujemy ‮łz 081‬ na⁦ godzinę.\n\nZespół 6 osób.",
        ),
        SimpleNamespace(id=1),
        _FakeDb(),
    )
    assert profile.public_title == "Java Developer"
    assert profile.subtitle == "Platforma łz 081 płatności"
    assert profile.about == "Oferujemy łz 081 na godzinę.\n\nZespół 6 osób."
