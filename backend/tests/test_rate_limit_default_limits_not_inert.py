"""Limit globalny bez ``SlowAPIMiddleware`` jest ATRAPĄ, nie ochroną.

Regresja jest CICHA w najgorszy możliwy sposób: konfiguracja czyta się jak
„cała aplikacja ma 60 zapytań na minutę", a slowapi nie sprawdza wtedy niczego.

Mechanizm (zweryfikowany w źródle zainstalowanej wersji slowapi, nie z pamięci):
``Limiter._check_request_limit`` sięga po ``self._application_limits`` wyłącznie
gdy ``in_middleware=True``. Ta wartość jest prawdziwa TYLKO w wywołaniu
z ``SlowAPIMiddleware``. Ścieżka dekoratora ``@limiter.limit`` woła ją
z ``in_middleware=False`` i globalne limity pomija.

Test jest wykonujący, nie deklaratywny: sam odczytuje źródło slowapi, więc
przestanie chronić dopiero wtedy, gdy zmieni się BIBLIOTEKA — a wtedy ma paść
i kazać komuś przeczytać nowy kod, zamiast dalej zapewniać o nieistniejącym
związku.
"""

from __future__ import annotations

import inspect

from slowapi import Limiter
from slowapi.middleware import SlowAPIMiddleware

from app.core.rate_limit import limiter
from app.main import app


def _middleware_classes() -> set[type]:
    return {m.cls for m in app.user_middleware}


def test_global_limits_declared_only_together_with_the_middleware() -> None:
    """Albo obie rzeczy naraz, albo żadna — stan pośredni to fałszywa ochrona."""
    has_global_limits = bool(limiter._application_limits)
    has_middleware = SlowAPIMiddleware in _middleware_classes()

    if has_global_limits and not has_middleware:
        raise AssertionError(
            "`default_limits` w app/core/rate_limit.py jest ustawione, ale "
            "`SlowAPIMiddleware` nie jest zamontowane w app/main.py — slowapi "
            "NIE sprawdzi tych limitów. Dodaj middleware w tym samym commicie "
            "albo skasuj limity; patrz komentarz nad `limiter = Limiter(...)`."
        )


def test_slowapi_still_gates_global_limits_on_the_middleware_flag() -> None:
    """Gdyby biblioteka to zmieniła, komentarz w rate_limit.py stałby się fałszem."""
    src = inspect.getsource(Limiter._check_request_limit)
    assert "in_middleware" in src, "slowapi nie rozróżnia już ścieżki middleware"
    assert "_application_limits" in src
    # Odczyt globalnych limitów jest w tej wersji warunkowany ``in_middleware``.
    assert "if in_middleware" in src or "in_middleware\n" in src, (
        "sprawdź ręcznie, czy _application_limits nadal wisi na in_middleware"
    )


def test_decorator_limits_still_work_without_the_middleware() -> None:
    """Kontrapunkt: brak middleware NIE psuje jawnych `@limiter.limit`.

    Bez tej asercji ktoś mógłby „naprawić" powyższe dokładając middleware
    w przekonaniu, że dopiero ono włącza limity logowania — a te działają
    od zawsze przez ``_route_limits`` i mają własne, wąskie progi.
    """
    assert limiter._route_limits, (
        "żadna trasa nie ma jawnego limitu — to znaczy, że rate limiting "
        "przestał obowiązywać w ogóle (np. /api/auth/*)"
    )
