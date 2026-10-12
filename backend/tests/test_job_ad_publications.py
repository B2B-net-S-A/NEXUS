"""Oznaczenia publikacji ogłoszenia (0431) — czyste funkcje, bez bazy."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.services.job_ad import publications
from app.services.job_ad_publication_schema import PORTALS, URL_MAX

_CONTENT = {"title": "Java Developer", "about": "Opis.", "requirements": ["Java 17"]}
_TECH = [{"name": "Java", "level": "must"}]


def test_hash_is_stable_and_ignores_key_order():
    first = publications.content_hash("pl", _CONTENT, _TECH)
    reordered = dict(reversed(list(_CONTENT.items())))
    assert first == publications.content_hash("pl", reordered, _TECH)
    assert len(first) == 64


@pytest.mark.parametrize(
    "lang,content,tech",
    [
        ("en", _CONTENT, _TECH),
        ("pl", {**_CONTENT, "about": "Opis po poprawce."}, _TECH),
        ("pl", {**_CONTENT, "requirements": ["Java 21"]}, _TECH),
        ("pl", _CONTENT, [{"name": "Java", "level": "critical"}]),
        ("pl", _CONTENT, []),
    ],
)
def test_any_change_of_the_saved_ad_changes_the_hash(lang, content, tech):
    assert publications.content_hash(lang, content, tech) != publications.content_hash(
        "pl", _CONTENT, _TECH
    )


@pytest.mark.parametrize(
    "portal,url",
    [
        ("pracuj", "https://www.pracuj.pl/praca/java-developer-warszawa,oferta,1004"),
        ("pracuj", "https://pracuj.pl/praca/x"),
        ("jjit", "https://justjoin.it/job-offer/firma-java-developer-warszawa"),
        ("jjit", "http://justjoin.it/job-offer/x"),
    ],
)
def test_a_link_to_the_portal_is_kept_as_typed(portal, url):
    assert publications.clean_url(f"  {url} ", portal) == url


@pytest.mark.parametrize("value", [None, "", "   "])
def test_an_empty_link_means_no_link(value):
    assert publications.clean_url(value, "pracuj") is None


@pytest.mark.parametrize(
    "portal,url",
    [
        # Link z listy rekrutacji prowadzi prosto na portal — nie na cudzą stronę.
        ("pracuj", "https://pracuj.pl.przyklad.example/oferta"),
        ("pracuj", "https://zlypracuj.pl/oferta"),
        ("pracuj", "https://justjoin.it/job-offer/x"),
        ("jjit", "https://www.pracuj.pl/praca/x"),
        ("jjit", "javascript:alert(1)"),
        ("jjit", "justjoin.it/job-offer/x"),
        ("jjit", "https://ktos:haslo@justjoin.it/job-offer/x"),
        ("jjit", "https://justjoin.it/job offer"),
        ("jjit", "https://justjoin.it/x\u200b"),
        ("pracuj", "https://www.pracuj.pl/" + "a" * URL_MAX),
    ],
)
def test_anything_else_is_refused_in_polish(portal, url):
    with pytest.raises(ValueError) as error:
        publications.clean_url(url, portal)
    assert "Pracuj.pl" in str(error.value) or "JustJoin.IT" in str(error.value)


def test_publications_come_in_portal_order():
    now = datetime.now(timezone.utc)
    items = [
        publications.Publication(portal, None, False, now)
        for portal in reversed(PORTALS)
    ]
    assert [item.portal for item in publications._sorted(items)] == list(PORTALS)
