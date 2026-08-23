"""Awaria wyszukiwania nie może produkować listy „dopasowań" z losowych ofert.

Trzy powierzchnie miały ten sam kształt: `search_jobs_semantic` wołane BEZ
`raise_on_error=True` połykało wyjątek i zwracało `[]` — tę samą wartość co
zdrowe zapytanie bez trafień. Trzy linie niżej stał fallback, który dolewał
arbitralne oferty (100 dla rekomendacji kandydata, 50 dla kokpitu i podglądu
CV), scorowane z PUSTĄ mapą podobieństwa, czyli bez warstwy semantycznej
wartej 60 ze 100 punktów.

Rekruter dostawał HTTP 200 z wiarygodną, NIEPUSTĄ listą i przypisywał kandydata
do oferty wybranej ze zbioru, który z dopasowaniem nie miał nic wspólnego.
Ta sama para kandydat/oferta miała przy zdrowym Qdrancie 80.6 pkt, a przy
awarii ~26 albo znikała z listy — bo jej oferty nie było w tych pierwszych 100.

Testy czytają ŹRÓDŁO, bo odtworzenie wymagałoby wyłączenia Qdranta w środowisku,
w którym inne testy go używają; a mockowanie `search_jobs_semantic` sprawdzałoby
atrapę zamiast tego, czy fallback jest zabramkowany.
"""

import ast
import pathlib

import pytest

BACKEND = pathlib.Path(__file__).resolve().parents[1]


def _calls_with_raise_on_error(tree: ast.AST) -> list[bool]:
    """Dla każdego wywołania `search_jobs_semantic` — czy ma raise_on_error."""
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = (
            node.func.attr
            if isinstance(node.func, ast.Attribute)
            else getattr(node.func, "id", None)
        )
        if name != "search_jobs_semantic":
            continue
        out.append(any(k.arg == "raise_on_error" for k in node.keywords))
    return out


@pytest.mark.parametrize(
    "rel",
    ("app/api/recommendations.py", "app/api/cv_match_preview.py"),
)
def test_every_semantic_search_can_report_its_own_failure(rel: str):
    tree = ast.parse((BACKEND / rel).read_text(encoding="utf-8"))
    flags = _calls_with_raise_on_error(tree)
    assert flags, f"{rel}: nie znaleziono wywołań — zmienił się kształt pliku"
    assert all(flags), (
        f"{rel}: {flags.count(False)} z {len(flags)} wywołań `search_jobs_semantic` "
        "połyka awarię i zwraca [], czyli to samo co zdrowe zero trafień — "
        "fallback niżej dolewa wtedy arbitralne oferty jako „dopasowania"
    )


@pytest.mark.parametrize(
    "rel",
    ("app/api/recommendations.py", "app/api/cv_match_preview.py"),
)
def test_fallback_is_gated_on_the_search_having_answered(rel: str):
    """Fallback wolno odpalić tylko po ODPOWIEDZI, nie po awarii."""
    src = (BACKEND / rel).read_text(encoding="utf-8")
    assert "semantic_unavailable" in src or "cand_semantic_ok" in src, (
        f"{rel}: brak zmiennej odróżniającej awarię od pustego wyniku"
    )
    # każdy `.limit(` fallbacku ma nad sobą warunek o dostępności wyszukiwania
    assert "not semantic_unavailable" in src or "elif cand_semantic_ok" in src, (
        f"{rel}: fallback nie jest zabramkowany — przy awarii nadal dolewa "
        "arbitralne oferty"
    )


@pytest.mark.parametrize(
    "rel",
    ("app/api/recommendations.py", "app/api/cv_match_preview.py"),
)
def test_arbitrary_slice_is_ordered(rel: str):
    """`limit()` bez `order_by` to inny wycinek przy każdym wywołaniu."""
    src = (BACKEND / rel).read_text(encoding="utf-8")
    tree = ast.parse(src)
    unordered = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not (isinstance(node.func, ast.Attribute) and node.func.attr == "limit"):
            continue
        # zejdź po łańcuchu w dół szukając order_by
        chain, cur = [], node.func.value
        while isinstance(cur, ast.Call) and isinstance(cur.func, ast.Attribute):
            chain.append(cur.func.attr)
            cur = cur.func.value
        # `@limiter.limit("20/minute")` to rate limiter, nie zapytanie SQL —
        # ta sama nazwa metody, zupełnie inne API. Dopasowywanie po samej
        # nazwie atrybutu jest za szerokie (pierwsza wersja tego testu
        # zgłaszała 11 dekoratorów jako brak `ORDER BY`).
        base = cur.id if isinstance(cur, ast.Name) else getattr(cur, "attr", "")
        if base == "limiter":
            continue
        if "order_by" not in chain:
            unordered.append(node.lineno)
    assert not unordered, (
        f"{rel}: limit() bez order_by w liniach {unordered} - pierwsze N "
        "to arbitralny wycinek, inny przy kazdym wywolaniu"
    )


def test_degraded_flag_reaches_the_response():
    """Sama detekcja nic nie daje, jeśli nie wychodzi z endpointu."""
    for rel in ("app/api/recommendations.py", "app/api/cv_match_preview.py"):
        src = (BACKEND / rel).read_text(encoding="utf-8")
        assert '"degraded"' in src, f"{rel}: flaga nie trafia do odpowiedzi"
        assert '"semantic_unavailable"' in src, (
            f"{rel}: brak rozróżnienia powodu — front nie odróżni awarii od zera"
        )


# ── Test WYKONANIOWY dla `seeking_contractors` ──────────────────────────────
# Testy wyżej sprawdzają KSZTAŁT źródła i nie zobaczą zmiany nazwy flagi ani
# rozluźnienia warunku fallbacku w tej jednej pętli. `seeking_contractors` ma
# osobną logikę (iteruje po kandydatach i bramkuje `cand_semantic_ok`), więc
# dostaje własny dowód przez wykonanie.


@pytest.mark.asyncio
async def test_seeking_contractors_reports_outage_instead_of_random_jobs(
    app_client, app_auth_headers, monkeypatch
):
    from app.api import recommendations as rec
    from app.services.embedding_service import SemanticSearchUnavailable

    async def _down(*_a, **_kw):
        raise SemanticSearchUnavailable("qdrant down")

    monkeypatch.setattr(rec, "search_jobs_semantic", _down)

    resp = await app_client.get(
        "/api/recommendations/seeking-contractors?horizon_days=30",
        headers=app_auth_headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()

    meta = body.get("meta")
    assert meta is not None, "brak meta - awaria nie ma jak wyjsc z endpointu"
    assert meta.get("degraded") is True, (
        "kokpit nie mowi, ze jest niepelny - pusty wiersz przy awarii czyta "
        "sie jak 'dla tej osoby nie ma nic sensownego'"
    )
    assert meta.get("reason") == "semantic_unavailable"

    # I najwazniejsze: ZERO sfabrykowanych propozycji.
    #
    # UCZCIWIE o sile tej asercji: nosna jest czesc o `meta.degraded`
    # (kontrola negatywna: usuniecie `bulk_degraded = True` ja zapala).
    # Ponizsza petla jest SLABSZA - w bazie testowej zaden kandydat nie
    # przekracza progu, wiec `top_matches` bywa puste takze po rozbramkowaniu
    # fallbacku. Zostaje jako siatka na srodowisko z bogatszymi danymi; nie
    # traktuj jej jako dowodu. Pusta lista `items` czyni ja calkiem
    # bezprzedmiotowa, wiec wtedy jawnie pomijamy - test przechodzacy pusto
    # jest gorszy niz jego brak, bo sprzedaje pewnosc, ktorej nie ma.
    items = body.get("items", [])
    if not items:
        pytest.skip(
            "brak kontraktorow w oknie 30 dni w tej bazie - nie ma na czym "
            "sprawdzic, czy awaria fabrykuje dopasowania"
        )
    for item in items:
        assert not item.get("top_matches"), (
            "podczas awarii wrocily 'dopasowania' - to arbitralny wycinek ofert "
            "scorowany bez warstwy semantycznej, nie dopasowanie"
        )


def test_no_fake_of_search_jobs_semantic_is_narrower_than_the_real_one():
    """Atrapa musi przyjmowac to, co przyjmuje prawdziwa funkcja.

    Atrapa o wezszej sygnaturze zamienia zmiane kontraktu w `TypeError`
    zamiast w czerwona asercje - komunikat mowi wtedy o atrapie, nie o kodzie,
    a diagnoza idzie w zla strone. Zdarzylo sie DWA razy przy tej samej
    zmianie, w dwoch plikach, i za pierwszym razem naprawilem tylko ten plik,
    ktory akurat swiecil na czerwono (policzylem faile zamiast KOPII).

    Straznik liczy kopie, nie faile: przemiata wszystkie atrapy podstawiane
    pod `search_jobs_semantic` i wymaga `**kwargs`.
    """
    import ast

    offenders = []
    for path in sorted((BACKEND / "tests").glob("test_*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue

        targets: set[str] = set()
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            fname = (
                node.func.attr
                if isinstance(node.func, ast.Attribute)
                else getattr(node.func, "id", None)
            )
            if fname not in ("setattr", "patch"):
                continue
            args = node.args
            mentions = any(
                isinstance(a, ast.Constant) and "search_jobs_semantic" in str(a.value)
                for a in args
            )
            if not mentions:
                continue
            for cand in list(args[-1:]) + [
                kw.value for kw in node.keywords if kw.arg == "new"
            ]:
                name = (
                    cand.id
                    if isinstance(cand, ast.Name)
                    else getattr(cand, "attr", None)
                )
                if name:
                    targets.add(name)

        for node in ast.walk(tree):
            if (
                isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name in targets
                and node.args.kwarg is None
            ):
                offenders.append(f"{path.name}:{node.lineno} {node.name}()")

    assert not offenders, (
        "atrapy o wezszej sygnaturze niz prawdziwa funkcja: "
        + ", ".join(offenders)
        + ". Dodaj **kwargs - inaczej kolejna zmiana kontraktu wybuchnie "
        "TypeError-em wskazujacym na test zamiast na kod."
    )
