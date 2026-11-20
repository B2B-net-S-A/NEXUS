"""Ostrzeżenia na karcie porcji dnia mają napis (20.11.2026).

Porcja oddawała surowe ``entry_meta.cautions`` (``key``, ``city``,
``over_pct``), a karta pokazuje ``label`` — na produkcji 382 ostrzeżenia od
16.11 były pustym prostokątem. Tablica liczyła napis w ``_caution``.
"""

import inspect

from app.api import review_batch as api
from app.services.process_entry_meta import caution_views


def test_raw_snapshot_cautions_get_a_label_and_a_tooltip():
    raw = [
        {"key": "budget", "rate": 120.0, "budget": 110.0, "over_pct": 9},
        {
            "key": "office_city",
            "city": "Copenhagen",
            "office": "Gdynia",
            "required_days": 3,
        },
        {"key": "office_days", "required_days": 3, "candidate_days": 2},
        {
            "key": "office_city",
            "city": "Turek",
            "office": "Warszawa",
            "required_days": 1,
            "km": 196,
        },
    ]
    views = caution_views(raw)
    assert [v["label"] for v in views] == [
        "+9% budżetu",
        "Inne miasto: Copenhagen",
        "Biuro: 2 z 3 dni",
        "Turek · 196 km",
    ]
    assert all(v["title"] for v in views)


def test_unknown_or_broken_cautions_are_dropped():
    assert caution_views(None) == []
    assert caution_views("budget") == []
    assert caution_views([{"key": "budget"}, {"key": "?"}, "x"]) == []


def test_the_batch_queue_sends_labelled_cautions():
    """Strażnik: kolejka porcji nie może wrócić do surowej migawki."""
    source = inspect.getsource(api)
    assert 'caution_views(meta.get("cautions"))' in source
    assert '"cautions": meta.get("cautions") or []' not in source
