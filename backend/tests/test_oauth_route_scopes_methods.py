"""Mapa tras OAuth z metodami (14.10.2026, audyt 29.09 D2-5).

Czyste testy ``decide`` — bez bazy i bez aplikacji. Pilnują dwóch rzeczy naraz:
pięć wywołań scraperów „pracuj.pl + JJIT” przechodzi z właściwym scope'em, a
sąsiednie metody na tych samych szablonach (``DELETE`` kandydata,
``GET /api/notes``) zostają zamknięte, choć szablon jest w mapie.
"""

from __future__ import annotations

import pytest

from app.services.oauth_route_scopes import (
    INSUFFICIENT_SCOPE,
    OAUTH_ROUTE_RESOURCES,
    ROUTE_NOT_EXPOSED,
    decide,
    route_resources,
)

_CANDIDATE = "/api/candidates/{candidate_id}"
_PROFILE_RATE = "/api/candidates/{candidate_id}/profile-rate"
_NOTES = "/api/notes"

#: (metoda, szablon, konkretna ścieżka, tryb) — wywołania scraperów z D2-5.
_SCRAPER_CALLS = [
    ("POST", _NOTES, "/api/notes", "write"),
    ("GET", _CANDIDATE, "/api/candidates/5", "read"),
    ("PATCH", _CANDIDATE, "/api/candidates/5", "write"),
    ("GET", _PROFILE_RATE, "/api/candidates/5/profile-rate", "read"),
    ("PATCH", _PROFILE_RATE, "/api/candidates/5/profile-rate", "write"),
]


@pytest.mark.parametrize(("method", "template", "path", "mode"), _SCRAPER_CALLS)
def test_scraper_calls_pass_with_candidate_write(method, template, path, mode):
    decision = decide(
        method=method, path=path, template=template, scopes=["candidate:write"]
    )

    assert decision.allowed
    assert decision.mode == mode
    assert decision.required == (f"candidate:{mode}",)


@pytest.mark.parametrize(
    ("method", "template", "path"),
    [
        ("GET", _CANDIDATE, "/api/candidates/5"),
        ("GET", _PROFILE_RATE, "/api/candidates/5/profile-rate"),
    ],
)
def test_scraper_reads_pass_with_candidate_read(method, template, path):
    decision = decide(
        method=method, path=path, template=template, scopes=["candidate:read"]
    )

    assert decision.allowed


@pytest.mark.parametrize(
    ("method", "template", "path"),
    [
        ("POST", _NOTES, "/api/notes"),
        ("PATCH", _CANDIDATE, "/api/candidates/5"),
        ("PATCH", _PROFILE_RATE, "/api/candidates/5/profile-rate"),
    ],
)
def test_read_scope_alone_cannot_write_scraper_routes(method, template, path):
    decision = decide(
        method=method, path=path, template=template, scopes=["candidate:read"]
    )

    assert not decision.allowed
    assert decision.reason == INSUFFICIENT_SCOPE
    assert decision.required == ("candidate:write",)


@pytest.mark.parametrize(
    ("method", "template", "path"),
    [
        ("GET", _CANDIDATE, "/api/candidates/5"),
        ("POST", _NOTES, "/api/notes"),
    ],
)
def test_other_resource_scope_does_not_open_scraper_routes(method, template, path):
    decision = decide(method=method, path=path, template=template, scopes=["job:write"])

    assert not decision.allowed
    assert decision.reason == INSUFFICIENT_SCOPE


@pytest.mark.parametrize(
    ("method", "template", "path", "scopes"),
    [
        # Usunięcie kandydata — szablon w mapie, metoda nie.
        ("DELETE", _CANDIDATE, "/api/candidates/5", ["candidate:write"]),
        # Lista notatek (do 4,77 MB na kandydata) — ani odczyt, ani zapis.
        ("GET", _NOTES, "/api/notes", ["candidate:read"]),
        ("GET", _NOTES, "/api/notes", ["candidate:write", "job:write"]),
        # Metody, których te szablony w ogóle nie mają, też nie przechodzą.
        ("PUT", _CANDIDATE, "/api/candidates/5", ["candidate:write"]),
        (
            "DELETE",
            _PROFILE_RATE,
            "/api/candidates/5/profile-rate",
            ["candidate:write"],
        ),
    ],
)
def test_methods_outside_the_entry_are_not_exposed(method, template, path, scopes):
    decision = decide(method=method, path=path, template=template, scopes=scopes)

    assert not decision.allowed
    assert decision.reason == ROUTE_NOT_EXPOSED
    assert decision.required == ()


def test_method_lookup_ignores_case():
    decision = decide(
        method="patch",
        path="/api/candidates/5",
        template=_CANDIDATE,
        scopes=["candidate:write"],
    )

    assert decision.allowed
    assert decision.mode == "write"


@pytest.mark.parametrize("method", ["GET", "POST", "PUT", "PATCH", "DELETE"])
def test_tuple_entries_still_accept_any_method(method):
    """Wpisy sprzed 14.10 (krotka) działają jak dawniej: metoda nie gra roli."""
    template = "/api/candidates/{candidate_id}/sources"
    assert isinstance(OAUTH_ROUTE_RESOURCES[template], tuple)

    decision = decide(
        method=method,
        path="/api/candidates/5/sources",
        template=template,
        scopes=["candidate:write"],
    )

    assert decision.allowed
    assert decision.reason is None


def test_tuple_entry_with_two_resources_still_accepts_either():
    for scope in ("candidate:write", "job:write"):
        decision = decide(
            method="POST",
            path="/api/jobs/7/proposals/bulk",
            template="/api/jobs/{job_id}/proposals/bulk",
            scopes=[scope],
        )
        assert decision.allowed, scope


def test_unmapped_template_is_not_exposed():
    decision = decide(
        method="GET",
        path="/api/candidates/5/notes-insights",
        template="/api/candidates/{candidate_id}/notes-insights",
        scopes=["candidate:write"],
    )

    assert not decision.allowed
    assert decision.reason == ROUTE_NOT_EXPOSED


def test_route_resources_reports_closed_methods_as_empty():
    assert route_resources(_CANDIDATE, "GET") == ("candidate",)
    assert route_resources(_CANDIDATE, "DELETE") == ()
    assert route_resources(_NOTES, "GET") == ()
    assert route_resources(None, "GET") == ()
    assert route_resources("/api/candidates/check-duplicates", "DELETE") == (
        "candidate",
    )


def test_method_keys_are_upper_case():
    """Klucze metod wielkimi literami — ``decide`` porównuje po ``upper()``."""
    lower = sorted(
        (method, template)
        for template, entry in OAUTH_ROUTE_RESOURCES.items()
        if not isinstance(entry, tuple)
        for method in entry
        if method != method.upper()
    )
    assert not lower, lower
