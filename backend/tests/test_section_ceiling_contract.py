"""Każda zalogowana trasa ``/api/**`` podlega bramce sekcji — albo ma powód.

Audyt 14.09.2026 (F02): router feedbacku z rozmów sprawdzał wyłącznie role
(``require_roles``), więc użytkownik, któremu administrator odebrał sekcję
(``none``), dalej czytał i zapisywał przez API. Przegląd pokazał ok. 20 takich
routerów. Wcześniejsze testy (``test_section_access.py``) sprawdzały RĘCZNĄ
listę routerów, więc nowy router bez bramki po prostu nie był oglądany.

Ten test przechodzi po WSZYSTKICH trasach i wymaga jednej z bramek:

* ``require_section_access`` / ``require_section_access_any`` /
  ``require_section_access_any_read`` (także na poziomie routera),
* guard kandydatów (``require_candidate_roles`` — liczy max(sourcing, pipeline)),
* capability analityczne (``capabilities_for`` przycina je sekcjami),
* wyłącznie admin (admin ma zapis w każdej sekcji),
* scope konta serwisowego.

Trasa bez żadnej z nich trafia do ``_SECTIONLESS_ALLOWLIST`` z POWODEM:
dane wspólne dla każdej sekcji (powiadomienia, słowniki) albo kontrola sekcji
w treści handlera. Nowa trasa z samą bramką roli czerwieni ten test.
"""

from __future__ import annotations

import inspect
from typing import Any

import pytest

from app.models.user import UserRole
from app.services.request_semantics import READ_ONLY_POST_ROUTE_TEMPLATES
from app.services.section_permissions import ProductSection
from tests._route_introspection import iter_api_routes, iter_dependency_calls

_AUTH_CALLS = {"get_current_user", "get_authenticated_user", "require_onboarded_user"}

# Zależności, które same sprawdzają sekcję (bez fabryki `require_section_access`).
_SECTION_AWARE_HELPERS = {
    # contacts.py: `_require_contact_read_section` = Pipeline albo Delivery.
    "require_contact_read_access",
    "require_global_contact_access",
}

_SECTIONLESS_ALLOWLIST: dict[str, str] = {
    # ── Sesja i własne konto ────────────────────────────────────────────────
    "GET /api/auth/me": "profil zalogowanego — shell aplikacji potrzebuje go przed sekcjami",
    "POST /api/auth/change-password": "zmiana własnego hasła, niezależna od modułów",
    "POST /api/users/me/onboarding": "obowiązkowy onboarding konta, poprzedza wejście do sekcji",
    "GET /api/users/me/onboarding/jobs": "lista rekrutacji w kroku onboardingu, poprzedza sekcje",
    "GET /api/users/me/preferences": "własne preferencje interfejsu, bez danych domenowych",
    "PATCH /api/users/me/preferences": "zapis własnych preferencji interfejsu",
    "GET /api/users/me/dashboard": "własny układ kafelków pulpitu; dane kafelków mają własne bramki sekcji",
    "PUT /api/users/me/dashboard": "zapis własnego układu kafelków pulpitu, bez danych domenowych",
    "GET /api/settings/candidates-columns": "własny układ kolumn tabeli, bez danych domenowych",
    "GET /api/user-email-templates": "prywatne szablony maili autora, zakres = właściciel",
    "POST /api/user-email-templates": "prywatne szablony maili autora, zakres = właściciel",
    "GET /api/user-email-templates/{template_id}": "prywatny szablon autora, zakres = właściciel",
    "PUT /api/user-email-templates/{template_id}": "prywatny szablon autora, zakres = właściciel",
    "DELETE /api/user-email-templates/{template_id}": "prywatny szablon autora, zakres = właściciel",
    # ── Skrzynka i powiadomienia (filtr sekcji per wiersz) ──────────────────
    "GET /api/notifications": "skrzynka osobista; notification_access filtruje wiersze po sekcjach",
    "GET /api/notifications/count": "licznik skrzynki osobistej, ten sam filtr sekcji per wiersz",
    "GET /api/notifications/preferences": "własne ustawienia powiadomień, lista kategorii z filtrem sekcji",
    "PUT /api/notifications/preferences/{category}": "wyciszenie własnej kategorii powiadomień",
    "PATCH /api/notifications/read-all": "oznaczenie własnych powiadomień jako przeczytane",
    "PUT /api/notifications/read-all": "oznaczenie własnych powiadomień jako przeczytane",
    "PATCH /api/notifications/{notification_id}/read": "oznaczenie własnego powiadomienia",
    "PUT /api/notifications/{notification_id}/read": "oznaczenie własnego powiadomienia",
    "GET /api/dynareporter/competitions/my-notifications": "osobiste powiadomienia konkursowe",
    "PATCH /api/dynareporter/competitions/notifications/{notif_id}/read": "oznaczenie własnego powiadomienia konkursu",
    # ── Dane referencyjne wspólne dla wszystkich sekcji ─────────────────────
    "GET /api/users": "katalog kont do pickerów i wzmianek we wszystkich sekcjach",
    "GET /api/users/mentionable": "lista osób do wzmianek @ w notatkach i czatach każdej sekcji",
    "GET /api/dictionaries/{slug}/items": "słowniki wartości pól formularzy, bez danych osobowych",
    "GET /api/entity-schema/{entity_type}": "definicje pól encji do renderowania formularzy",
    "GET /api/skills": "taksonomia umiejętności, dane referencyjne",
    "GET /api/skills/autocomplete": "podpowiedzi taksonomii umiejętności, dane referencyjne",
    "GET /api/competence-categories": "słownik pięciu kategorii kompetencji",
    "GET /api/competence-categories/{cc_id}/recruiters": "przypisanie osób do kategorii, katalog zespołu",
    "GET /api/fx": "kursy walut NBP, dane publiczne",
    "GET /api/procedures": "moduł Pomoc — procedury czyta każda rola",
    "GET /api/procedures/{id_or_slug}": "moduł Pomoc — procedura czytana przez każdą rolę",
    "GET /api/help-materials": "moduł Pomoc — materiały i wzory dokumentów dla każdej roli",
    "GET /api/required-document-templates": "globalny słownik szablonów wymaganych dokumentów",
    "GET /api/clients/{client_id}/playbook": "karta klienta zastępuje wzory w Pomocy; decyzja: odczyt org-wide",
    "GET /api/settings/client-playbooks": "źródło Pomoc → Klienci; decyzja: odczyt org-wide",
    # ── Kontrola sekcji w treści handlera ───────────────────────────────────
    "GET /api/clients/{client_id}/cv-rule": "_require_shared_rule_section_read: Delivery albo Pipeline w handlerze",
    "GET /api/search/": "wyszukiwarka globalna filtruje każdy kubełek po sekcji w handlerze",
    "GET /api/search/global": "wyszukiwarka globalna filtruje każdy kubełek po sekcji w handlerze",
    "GET /api/dynareporter/board-dashboard/monthly": "_require_board_access sprawdza capability zarządu w handlerze",
    # ── Jarvis (0330) — asystent dostępny dla każdej roli ──────────────────
    "GET /api/jarvis/status": "Jarvis: rozmowy i akcje zawężone do właściciela, bez danych domenowych",
    "POST /api/jarvis/chat": "Jarvis: narzędzia wracają do aplikacji przez trasy z własną bramką sekcji",
    "GET /api/jarvis/conversations": "Jarvis: rozmowy i akcje zawężone do właściciela, bez danych domenowych",
    "GET /api/jarvis/conversations/{conversation_id}": "Jarvis: rozmowy i akcje zawężone do właściciela, bez danych domenowych",
    "DELETE /api/jarvis/conversations/{conversation_id}": "Jarvis: rozmowy i akcje zawężone do właściciela, bez danych domenowych",
    "POST /api/jarvis/actions/{action_id}/confirm": "Jarvis: narzędzia wracają do aplikacji przez trasy z własną bramką sekcji",
    "POST /api/jarvis/actions/{action_id}/reject": "Jarvis: rozmowy i akcje zawężone do właściciela, bez danych domenowych",
    "POST /api/jarvis/conversations/{conversation_id}/cancel": "Jarvis: rozmowy i akcje zawężone do właściciela, bez danych domenowych",
    "POST /api/jarvis/ui-events": "Jarvis: telemetria własnych kliknięć (kod ekranu, bez danych domenowych)",
    "GET /api/help/screens": "przewodniki ekranów — treść pomocy czyta każda rola",
    "GET /api/help/screens/{key}": "przewodnik ekranu — treść pomocy czyta każda rola",
    # ── Sondy integracji bez danych ─────────────────────────────────────────
    "GET /api/autenti/health": "stan konfiguracji integracji podpisów, bez danych domenowych",
    "GET /api/signing/health": "stan konfiguracji podpisu kwalifikowanego, bez danych domenowych",
}


def _routes() -> list[tuple[str, str, Any]]:
    from app.main import app

    out = []
    for path, route in iter_api_routes(app):
        if not path.startswith("/api/"):
            continue
        for method in sorted(route.methods or ()):
            if method in {"HEAD", "OPTIONS"}:
                continue
            out.append((method, path, route))
    return out


def _classify(route: Any) -> str:
    calls = iter_dependency_calls(route)
    names = [getattr(call, "__qualname__", "") for call in calls]
    if not any(
        name in _AUTH_CALLS or "require_service_scope" in name for name in names
    ):
        return "unauthenticated"
    for call, name in zip(calls, names):
        if "require_section_access" in name or name in _SECTION_AWARE_HELPERS:
            return "section"
        if "require_candidate_roles" in name or name == "require_candidate_finance_read":
            return "section"
        if "require_capability" in name or "require_dynareporter_section" in name:
            return "section"
        if "require_service_scope" in name:
            return "section"
    for call, name in zip(calls, names):
        if "require_roles" in name:
            roles = inspect.getclosurevars(call).nonlocals.get("roles")
            if roles == (UserRole.admin,):
                return "section"
    return "role_only"


def _key(method: str, path: str) -> str:
    return f"{method} {path}"


def test_every_authenticated_route_has_a_section_ceiling() -> None:
    uncovered = sorted(
        _key(method, path)
        for method, path, route in _routes()
        if _classify(route) == "role_only"
        and _key(method, path) not in _SECTIONLESS_ALLOWLIST
    )
    assert not uncovered, (
        "Trasy sprawdzające wyłącznie role — użytkownik z odebraną sekcją nadal "
        "je wywoła (F02). Dodaj bramkę z app.api.section_access albo wpis do "
        "_SECTIONLESS_ALLOWLIST z powodem:\n  " + "\n  ".join(uncovered)
    )


def test_allowlist_has_no_stale_entries() -> None:
    by_key = {_key(method, path): route for method, path, route in _routes()}
    missing = sorted(key for key in _SECTIONLESS_ALLOWLIST if key not in by_key)
    covered = sorted(
        key
        for key in _SECTIONLESS_ALLOWLIST
        if key in by_key and _classify(by_key[key]) != "role_only"
    )
    assert not missing, f"Wpisy dla nieistniejących tras: {missing}"
    assert not covered, f"Te trasy mają już bramkę — usuń je z listy: {covered}"


def test_allowlist_reasons_are_meaningful() -> None:
    weak = [key for key, reason in _SECTIONLESS_ALLOWLIST.items() if len(reason) < 20]
    assert not weak, f"Powód wyjątku musi coś wyjaśniać: {weak}"


def _sections_of(route: Any) -> set[ProductSection]:
    sections: set[ProductSection] = set()
    for call in iter_dependency_calls(route):
        name = getattr(call, "__qualname__", "")
        if "require_section_access" not in name:
            continue
        nonlocals = inspect.getclosurevars(call).nonlocals
        if "section" in nonlocals:
            sections.add(nonlocals["section"])
        sections.update(nonlocals.get("sections", ()))
    return sections


S, P, D, INS, F = (
    ProductSection.sourcing,
    ProductSection.pipeline,
    ProductSection.delivery,
    ProductSection.insights,
    ProductSection.finance,
)

_EXPECTED_SECTIONS = [
    ("POST", "/api/rejection-emails/{rejection_email_id}/cancel", {P}),
    ("GET", "/api/presence/{resource_type}/{resource_id}/viewers", {S, P}),
    ("POST", "/api/champion/preview", {S, P}),
    ("POST", "/api/fireflies/sync", {S}),
    ("GET", "/api/cortex/supply-demand", {INS}),
    ("GET", "/api/kpis/me/today", {INS}),
    ("POST", "/api/priority-work/demands", {P}),
    ("GET", "/api/scoring-weights", {INS}),
    ("GET", "/api/settings/event-history", {F}),
    ("GET", "/api/admin/client-portfolio/import-runs", {F}),
    ("GET", "/api/admin/global-chats", {P, S}),
    ("GET", "/api/dashboard/stats", {INS}),
    ("GET", "/api/dashboard/v2/delivery-lead", {D}),
    ("GET", "/api/dashboard/v2/head-of-recruitment", {INS}),
    ("GET", "/api/dashboard/v2/my-work", {P}),
    ("GET", "/api/dashboard/v2/recruitment-stats", {INS}),
    ("PUT", "/api/dashboard/v2/recruitment-operations/{job_id}/favorite", {P}),
    ("GET", "/api/dashboard/v2/recruitment-activity", {P}),
    ("GET", "/api/activities/stats", {INS}),
    ("GET", "/api/activities/feed", {S, P, D}),
    ("POST", "/api/team-structure/sourcer-categories", {P}),
    ("POST", "/api/team-structure/dl-clients", {D, P}),
    ("GET", "/api/team-structure/my-team", {D, P}),
    ("GET", "/api/clients-lookup", {S, P, D, INS, F}),
    ("GET", "/api/jobs-lookup", {P, S, INS}),
    ("GET", "/api/dynareporter/kpi/sales/my", {INS}),
    ("POST", "/api/dynareporter/upload/excel", {INS}),
]


@pytest.mark.parametrize(
    ("method", "path", "expected"),
    _EXPECTED_SECTIONS,
    ids=[f"{m} {p}" for m, p, _ in _EXPECTED_SECTIONS],
)
def test_fixed_routes_require_the_expected_sections(
    method: str, path: str, expected: set[ProductSection]
) -> None:
    matches = [route for m, p, route in _routes() if m == method and p == path]
    assert matches, f"trasa nie istnieje: {method} {path}"
    assert _sections_of(matches[0]) == expected


def test_fireflies_sync_is_not_a_get() -> None:
    """Synchronizacja zapisuje notatki — jako GET omijała bramkę zapisu sekcji
    i tryb podglądu tylko do odczytu."""
    methods = {m for m, p, _ in _routes() if p == "/api/fireflies/sync"}
    assert methods == {"POST"}


def test_read_only_post_templates_point_to_registered_post_routes() -> None:
    posts = {p for m, p, _ in _routes() if m == "POST"}
    stale = sorted(t for t in READ_ONLY_POST_ROUTE_TEMPLATES if t not in posts)
    assert not stale, f"Wzorce read-only POST bez trasy: {stale}"
