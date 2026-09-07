"""Dwa pokrętła retrievalu, które do 09.2026 nie były pokrętłami.

1. `HYBRID_BM25_POOL_LIMIT` — `_bm25_pool_limit` czytało je przez `getattr`
   z domyślną 200, ale pole NIE BYŁO zadeklarowane w `Settings`. Pydantic
   czyta zmienne środowiskowe wyłącznie dla pól ZADEKLAROWANYCH, więc
   `HYBRID_BM25_POOL_LIMIT=50` w Coolify nie robiło nic. Kod sam to przyznawał
   w komentarzu („do czasu deklaracji pokrętło ma stałą wartość domyślną").

2. `SEARCH_HYBRID_POOL_SIZE` — rozmiar puli trybu semantycznego był stałą
   wbitą w `api/search.py`. To jednocześnie SUFIT liczby wyników widocznej dla
   rekrutera i liczba dokumentów wysyłanych do rerankera przy KAŻDYM żądaniu
   strony. Czy 200 wygrywa ze 100, wie tylko pomiar — a pomiaru nie da się
   zrobić, jeśli zmiana wartości wymaga deployu.

Testy sprawdzają, że wartość DA SIĘ przestawić i że domyślne nic nie zmieniają.
"""

from __future__ import annotations


def test_bm25_pool_limit_is_a_declared_setting():
    """Zadeklarowane pole = zmienna środowiskowa działa. `getattr` to za mało."""
    from app.core.config import Settings

    assert "HYBRID_BM25_POOL_LIMIT" in Settings.model_fields, (
        "pole czytane przez `getattr` musi istnieć w Settings, inaczej env "
        "jest ignorowany i pokrętło jest martwe"
    )


def test_bm25_pool_limit_actually_caps_the_leg(monkeypatch):
    from app.core.config import settings
    from app.services.hybrid_search import _bm25_pool_limit

    monkeypatch.setattr(settings, "HYBRID_BM25_POOL_LIMIT", 50)
    assert _bm25_pool_limit(1000) == 50, "przestawiona wartość musi obowiązywać"

    # Sufit nigdy nie podnosi puli ponad to, o co poprosił wołający.
    assert _bm25_pool_limit(10) == 10


def test_bm25_pool_limit_default_is_unchanged():
    """Kontrola negatywna: sama deklaracja nie może przestawić produkcji."""
    from app.core.config import Settings

    assert Settings.model_fields["HYBRID_BM25_POOL_LIMIT"].default == 200


def test_search_hybrid_pool_size_is_a_declared_setting():
    from app.core.config import Settings

    assert "SEARCH_HYBRID_POOL_SIZE" in Settings.model_fields
    assert Settings.model_fields["SEARCH_HYBRID_POOL_SIZE"].default == 200


def test_search_hybrid_pool_size_is_read_at_call_time(monkeypatch):
    """Czytane przy WYWOŁANIU, nie przy imporcie.

    Wartość zapiekana w stałej modułowej przy imporcie ignorowałaby zmienną
    środowiskową ustawioną później i — co gorsza — byłaby nie do przestawienia
    w teście, więc pomiar 200 vs 100 wymagałby restartu procesu.
    """
    from app.api.search import _hybrid_pool_size
    from app.core.config import settings

    monkeypatch.setattr(settings, "SEARCH_HYBRID_POOL_SIZE", 100)
    assert _hybrid_pool_size() == 100

    monkeypatch.setattr(settings, "SEARCH_HYBRID_POOL_SIZE", 200)
    assert _hybrid_pool_size() == 200


def test_nonsense_pool_size_falls_back_to_the_default(monkeypatch):
    """Zero i wartość ujemna wracają do DOMYŚLNEJ — obie tak samo.

    Asercja jest na konkretną liczbę, nie na `>= 1`. Luźniejszy warunek
    przepuszczał pierwotną wersję tej funkcji, w której `0` i `-5` kończyły
    w DWÓCH różnych miejscach (200 i 1), bo `or` zwierał się przed `max` —
    rozjazd niewidoczny dla testu, który pyta tylko „czy dodatnia".

    Pula 1 nie jest sensowniejsza od zera: wyszukiwarka oglądałaby jedną osobę
    i wyglądałoby to jak pusta baza.
    """
    from app.api.search import _HYBRID_POOL_DEFAULT, _hybrid_pool_size
    from app.core.config import settings

    for nonsense in (0, -5):
        monkeypatch.setattr(settings, "SEARCH_HYBRID_POOL_SIZE", nonsense)
        assert _hybrid_pool_size() == _HYBRID_POOL_DEFAULT, (
            f"{nonsense} ma wrócić do wartości domyślnej"
        )


def test_unparsable_pool_size_falls_back_instead_of_exploding(monkeypatch):
    """Śmieć w zmiennej środowiskowej nie może wywalić wyszukiwarki.

    `SEARCH_HYBRID_POOL_SIZE=dużo` w Coolify to literówka operatora, a nie
    powód, żeby każde wyszukiwanie kończyło się 500-tką.
    """
    from app.api.search import _HYBRID_POOL_DEFAULT, _hybrid_pool_size
    from app.core.config import settings

    monkeypatch.setattr(settings, "SEARCH_HYBRID_POOL_SIZE", "dużo")
    assert _hybrid_pool_size() == _HYBRID_POOL_DEFAULT


def test_structured_pool_settings_are_declared():
    """0278: trzy pokrętła strategii SQL-first muszą być pola Settings, nie
    tylko `getattr` z domyślną — inaczej zmienna środowiskowa w Coolify jest
    ignorowana i pokrętło wygląda na konfigurowalne, a nie jest (ten sam
    defekt co historyczne `HYBRID_BM25_POOL_LIMIT` wyżej w tym pliku)."""
    from app.core.config import Settings

    assert "STRUCTURED_POOL_ENABLED" in Settings.model_fields
    assert Settings.model_fields["STRUCTURED_POOL_ENABLED"].default is False
    assert "STRUCTURED_POOL_LIMIT" in Settings.model_fields
    assert Settings.model_fields["STRUCTURED_POOL_LIMIT"].default == 2000
    assert "STRUCTURED_POOL_MIN_MEMBERS" in Settings.model_fields
    assert Settings.model_fields["STRUCTURED_POOL_MIN_MEMBERS"].default == 20
