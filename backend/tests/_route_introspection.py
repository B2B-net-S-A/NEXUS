"""Wyliczanie tras aplikacji niezależnie od wersji FastAPI.

Do FastAPI 0.115 ``include_router()`` wklejał trasy PŁASKO do ``app.routes``,
więc pętla po tej liście widziała wszystko. Od 0.139 każde wywołanie staje się
obiektem ``_IncludedRouter``: prefiks siedzi w ``include_context.prefix``, a
``original_router.routes`` trzyma ścieżki BEZ niego.

Konsekwencja dla testów, które skanują ``app.routes``, jest cicha i groźna: na
0.139 widzą **4 trasy zamiast 789** i wnioskują, że reszty nie ma. Kontrakt
autoryzacji zgłosił wtedy „148 wpisów baseline'u nie jest już potrzebnych" —
posłuchanie tego komunikatu wypatroszyłoby zabezpieczenie obejmujące 233 trasy.
Dlatego wyliczanie tras jest tu JEDNYM helperem, a nie powtarzaną pętlą: przy
kolejnej zmianie w FastAPI jest jedno miejsce do poprawienia, nie pięć.

Równoważność zmierzona 2026-07-27 na obu kształtach, na tej samej aplikacji:

    FastAPI 0.115.6   pętla po app.routes = 789   helper = 789   zgodne
    FastAPI 0.139.0   pętla po app.routes =   4   helper = 789
    helper(0.115.6) == helper(0.139.0)                           identyczne

Zbiór 789 par ``(metoda, ścieżka)`` jest ten sam, więc podmiana pętli na helper
nie zmienia tego, co testy widzą — zmienia tylko to, czy widzą cokolwiek po
podniesieniu FastAPI. Test ``test_route_introspection.py`` pilnuje tego dalej.
"""

from __future__ import annotations

from typing import Iterator

from fastapi.routing import APIRoute


def iter_api_routes(app) -> Iterator[tuple[str, APIRoute]]:
    """Zwraca ``(pełna_ścieżka, trasa)`` dla każdej ``APIRoute`` w aplikacji.

    Ścieżka jest złożona z prefiksów wszystkich zagnieżdżeń, więc odpowiada
    temu, co widzi klient — a obiekt trasy jest ORYGINALNY, żeby wołający mógł
    dalej sięgać po ``methods``, ``dependant`` czy ``endpoint``.
    """

    def walk(node, prefix: str) -> Iterator[tuple[str, APIRoute]]:
        if isinstance(node, APIRoute):
            yield prefix + node.path, node
            return

        # FastAPI >= 0.139: opakowanie po include_router()
        ctx = getattr(node, "include_context", None)
        if ctx is not None:
            inner = prefix + (getattr(ctx, "prefix", "") or "")
            original = getattr(node, "original_router", None)
            for route in getattr(original, "routes", []):
                yield from walk(route, inner)
            return

        # Router zagnieżdżony bez opakowania (i FastAPI <= 0.115, gdzie
        # app.routes jest już płaskie — pętla po `routes` po prostu nic nie da).
        for route in getattr(node, "routes", []):
            yield from walk(route, prefix)

    for route in app.routes:
        yield from walk(route, "")


def api_route_methods(app) -> set[tuple[str, str]]:
    """Zbiór ``(METODA, ścieżka)`` dla tras ``/api/**``, bez HEAD i OPTIONS.

    Ten sam filtr, którego używa kontrakt autoryzacji — wydzielony, żeby dwa
    testy nie rozjechały się w tym, co uznają za „trasę".
    """
    out: set[tuple[str, str]] = set()
    for path, route in iter_api_routes(app):
        if not path.startswith("/api/"):
            continue
        for method in route.methods or ():
            if method in {"HEAD", "OPTIONS"}:
                continue
            out.add((method, path))
    return out
