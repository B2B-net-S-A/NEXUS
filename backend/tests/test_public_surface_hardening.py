"""Kontrakty powierzchni publicznej: limit na KAŻDEJ trasie, sekrety poza URL-em
i uzasadnienia bezpieczeństwa poza publikowanym `/openapi.json`.

Wszystkie trzy regresje są ciche:

* brak `@limiter.limit` niczego nie psuje — `rate_limit.py` ma
  `default_limits=[]` i nie ma `SlowAPIMiddleware`, więc nic nie wyłapie
  trasy, która wypadła z konwencji (tak przeżył `champion-card` i cały
  `public_engagement`, którego docstring powoływał się na nieistniejący
  „globalny slowapi");
* poświadczenie przyjmowane jako parametr QUERY działa dokładnie tak samo jak
  w ciele — różnica widać dopiero w access logu uvicorna, w Loki i w Refererze;
* docstring handlera FastAPI kopiuje do publicznej specyfikacji, więc
  uzasadnienie („break-glass", „to znany brak") wychodzi na zewnątrz bez
  żadnego sygnału w kodzie.

Sprawdzane AST-em po ŹRÓDLE, nie po wewnętrznych strukturach slowapi — tamte
zmieniają się z wersją biblioteki, a niezmiennik dotyczy tego, co pisze autor.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest
from httpx import AsyncClient

_APP = Path(__file__).resolve().parents[1] / "app"

_V1_MODULES = tuple(
    f"api/integrations_v1/{name}.py"
    for name in (
        "meta",
        "clients",
        "contracts",
        "contract_writes",
        "orders",
        "order_writes",
        "md",
        "finance",
        "invoices",
        "recruitments",
        "recruitment_writes",
        "candidates",
        "candidate_writes",
        "recruitment_create",
        "cv",
        "calendar",
        "applications",
        "insights",
        "academy",
        "absences",
        "equipment",
        "events",
    )
)

# Moduły, w których KAŻDA trasa musi nieść jawny limit.
_RATE_LIMITED_MODULES = (
    "api/public_share.py",
    "api/public_engagement.py",
    "api/oauth_token.py",
    # Eksport dla COMPASSA: trasa wystawiona drugiej aplikacji, uwierzytelniana
    # kluczem API. Ta lista jest hard-kodowana, więc nowy moduł NIE jest
    # chroniony domyślnie — bez tego wpisu nikt nie zauważy ani zdjęcia
    # `@limiter.limit`, ani dopisania `from __future__ import annotations`
    # (to drugie zamienia guard `Annotated` w parametr QUERY, czyli 422 na
    # poprawnym żądaniu).
    "api/integrations_compass.py",
    # „Ludzie w NEXUSIE”: publiczny link do podpisu protokołu sprzętu (token).
    "api/equipment_public.py",
    "api/champion_intake.py",
    # Własna metryka pulpitu: każde wywołanie liczy agregat po bazie.
    "api/dashboard_metrics.py",
    # Strona kariery (0339): publiczne GET-y i formularz multipart.
    "api/public_career.py",
    # Odczyt requestu klienta na /jobs/new: każde wywołanie to płatny model.
    "api/job_request_intake.py",
    # Przepięcie (Pipeline v4): podpowiedzi Luny — każde wywołanie to płatny model.
    "api/screening_reassign.py",
    # QC CV: każde wywołanie liczy QC (pobranie i odczyt CV), poprawki = model.
    "api/cv_qc.py",
    # Strony CV jako PDF (Edytor CV 3): każda zamiana to LibreOffice na serwerze.
    "api/cv_pdf_preview.py",
    # Konto JustJoin.IT/RocketJobs (0381): callback OAuth bez sesji NEXUSA.
    "api/job_board_connection.py",
    # „Champion po ludzku” (0403): odświeżenie = płatny model i research w internecie.
    "api/plain_brief_refresh.py",
    # Karta z notatki i „Ułóż w zdanie” (0421): każde wywołanie to płatny model.
    "api/recommendation_card_assist.py",
    # Pliki rekrutacji (0428): upload do 20 MB na żądanie.
    "api/job_files.py",
    # AI na zaznaczeniu w edytorze CV (0433): każde wywołanie to płatny model.
    "api/cv_editor_ai.py",
    # Podgląd importu Worda w edytorze CV: upload do 10 MB i konwersja na żądanie.
    "api/cv_editor_import.py",
    # API integracyjne v1 (0443): powierzchnia dla automatyzacji na kluczach
    # API — limit per konto serwisowe na każdej trasie.
    *_V1_MODULES,
)

# Moduły, których docstringi tras trafiają do publicznego /openapi.json.
# v1: docstringi tras trafiają do publikowanej specyfikacji integratora.
_DOCSTRING_MODULES = ("api/auth.py", "api/candidates.py", *_V1_MODULES)

_FORBIDDEN_IN_PUBLIC_DOCSTRING = re.compile(
    r"break[\s_-]?glass|no .{0,20}rate limit|znany brak|bez sprawdzenia HMAC",
    re.IGNORECASE,
)


def _route_functions(path: Path) -> list[ast.FunctionDef | ast.AsyncFunctionDef]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for dec in node.decorator_list:
            target = dec.func if isinstance(dec, ast.Call) else dec
            if (
                isinstance(target, ast.Attribute)
                and isinstance(target.value, ast.Name)
                and target.value.id == "router"
            ):
                out.append(node)
                break
    return out


def _has_limiter(node) -> bool:
    for dec in node.decorator_list:
        target = dec.func if isinstance(dec, ast.Call) else dec
        if (
            isinstance(target, ast.Attribute)
            and target.attr == "limit"
            and isinstance(target.value, ast.Name)
            and target.value.id == "limiter"
        ):
            return True
    return False


@pytest.mark.parametrize("module", _RATE_LIMITED_MODULES)
def test_every_public_route_carries_an_explicit_rate_limit(module: str) -> None:
    path = _APP / module
    routes = _route_functions(path)
    assert routes, f"{module}: nie znaleziono żadnej trasy — test przestał mierzyć"
    missing = [node.name for node in routes if not _has_limiter(node)]
    assert not missing, (
        f"{module}: trasy bez @limiter.limit — nic ich nie przykrywa, bo "
        f"rate_limit.py ma default_limits=[]: {missing}"
    )


@pytest.mark.parametrize("module", _RATE_LIMITED_MODULES + _DOCSTRING_MODULES)
def test_limiter_modules_do_not_use_future_annotations(module: str) -> None:
    # AST, nie grep po treści: docstringi tych modułów OSTRZEGAJĄ przed tym
    # importem, więc skan tekstowy wywalałby się na własnym ostrzeżeniu.
    tree = ast.parse((_APP / module).read_text(encoding="utf-8"))
    offenders = [
        alias.name
        for node in tree.body
        if isinstance(node, ast.ImportFrom) and node.module == "__future__"
        for alias in node.names
        if alias.name == "annotations"
    ]
    assert not offenders, (
        f"{module}: `from __future__ import annotations` jest niekompatybilne "
        "z @limiter.limit (422 na poprawnym body)"
    )


@pytest.mark.parametrize("module", _DOCSTRING_MODULES)
def test_route_docstrings_do_not_publish_security_rationale(module: str) -> None:
    path = _APP / module
    offenders = []
    for node in _route_functions(path):
        doc = ast.get_docstring(node) or ""
        match = _FORBIDDEN_IN_PUBLIC_DOCSTRING.search(doc)
        if match:
            offenders.append(f"{node.name} (linia {node.lineno}): {match.group(0)!r}")
    assert not offenders, (
        f"{module}: docstring handlera jest publikowany w /openapi.json — "
        f"uzasadnienia bezpieczeństwa przenieś do komentarza `#`: {offenders}"
    )


async def test_refresh_accepts_the_token_in_the_body(app_client: AsyncClient) -> None:
    """Poświadczenie o 30-dniowym życiu nie może wymagać jazdy w URL-u.

    Asertujemy 401 (token jest bezsensowny), a NIE 422 — 422 znaczyłoby, że
    ciało nie zostało w ogóle przeczytane i jedyną drogą pozostaje query.
    """
    resp = await app_client.post(
        "/api/auth/refresh", json={"refresh_token": "nie-jest-jwt"}
    )
    assert resp.status_code == 401, resp.text


async def test_refresh_without_any_token_is_rejected(app_client: AsyncClient) -> None:
    resp = await app_client.post("/api/auth/refresh", json={})
    assert resp.status_code == 422, resp.text
