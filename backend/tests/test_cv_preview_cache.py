"""Ograniczona pamięć odczytów CV (`app/services/cv_preview_cache.py`).

`app/core/cache.py` nie ma limitu ani sprzątania — tekst CV nie może tam
trafić. Tu: najwyżej N wpisów (najdawniej użyty wypada), TTL, zamiatanie
wygasłych przy zapisie, zbyt długi tekst nie jest trzymany.
"""

from __future__ import annotations

from app.services.cv_preview_cache import CvPreviewCache


class _Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_inserting_more_than_max_evicts_the_oldest() -> None:
    cache = CvPreviewCache(max_entries=3, ttl_seconds=60, clock=_Clock())
    for index in range(4):
        cache.set(f"sha{index}", parsed={"i": index}, raw_text="tekst")
    assert len(cache) == 3
    assert cache.get("sha0") is None
    assert cache.get("sha3").parsed == {"i": 3}


def test_recently_read_entry_survives_eviction() -> None:
    cache = CvPreviewCache(max_entries=2, ttl_seconds=60, clock=_Clock())
    cache.set("a", parsed={}, raw_text="x")
    cache.set("b", parsed={}, raw_text="x")
    assert cache.get("a") is not None  # „a” staje się najświeższe
    cache.set("c", parsed={}, raw_text="x")
    assert "a" in cache
    assert "b" not in cache


def test_expired_entries_are_swept_on_insert_and_ignored_on_read() -> None:
    clock = _Clock()
    cache = CvPreviewCache(max_entries=10, ttl_seconds=60, clock=clock)
    cache.set("old1", parsed={}, raw_text="x")
    cache.set("old2", parsed={}, raw_text="x")
    clock.now += 61
    assert cache.get("old1") is None
    cache.set("new", parsed={}, raw_text="x")
    assert "old2" not in cache
    assert len(cache) == 1


def test_long_raw_text_is_not_kept_but_the_parse_is() -> None:
    cache = CvPreviewCache(
        max_entries=4, ttl_seconds=60, max_raw_text_chars=10, clock=_Clock()
    )
    cache.set("long", parsed={"first_name": "Anna"}, raw_text="x" * 11)
    cache.set("short", parsed={}, raw_text="krótki")
    assert cache.get("long").raw_text is None
    assert cache.get("long").parsed == {"first_name": "Anna"}
    assert cache.get("short").raw_text == "krótki"


def test_disabled_ttl_stores_nothing() -> None:
    cache = CvPreviewCache(max_entries=4, ttl_seconds=0, clock=_Clock())
    cache.set("a", parsed={}, raw_text="x")
    assert len(cache) == 0
