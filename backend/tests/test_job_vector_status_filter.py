"""Rekomendacje miały sufit ~9 ofert, bo indeks to w 95,4% rekrutacje zamknięte.

Audyt 18.09.2026: `top_k=50` → 9 wyników. Wyszukiwanie w Qdrancie szło BEZ
filtra, a `published|draft` nakładał się dopiero w SQL na już pobraną pulę —
więc `top_k` opisywał najbliższe punkty w kolekcji, w której prawie wszystko
jest zamknięte. Payload punktu oferty nie zawierał nawet `status`, więc filtr
po stronie Qdranta był NIEMOŻLIWY.
"""

from __future__ import annotations

from app.services import embedding_service


def test_job_point_payload_carries_status():
    """Bez `status` w payloadzie filtrowanie po stronie Qdranta nie istnieje."""
    source = open(embedding_service.__file__, encoding="utf-8").read()
    payload_block = source[source.index('"industry": job.industry or ""') :][:1200]
    assert '"status": getattr(job.status' in payload_block


def test_status_filter_lets_legacy_points_through():
    """`should` (OR) z `IsEmptyCondition`, nigdy twardy `must`.

    Punkty sprzed tej zmiany nie mają `status`. Twardy `must` odciąłby CAŁĄ
    dzisiejszą kolekcję i zamienił ~9 rekomendacji w ZERO — regresję gorszą
    niż defekt, który naprawiamy. Filtr staje się w pełni skuteczny dopiero
    wtedy, gdy reconciler przeindeksuje oferty, i żaden moment tego przejścia
    nie jest gorszy od stanu sprzed zmiany.
    """
    source = open(embedding_service.__file__, encoding="utf-8").read()
    block = source[source.index("def search_jobs_semantic") :]
    block = block[: block.index("hits = client.search")]
    assert "should=[" in block, "filtr statusu musi być OR, nie AND"
    assert "IsEmptyCondition" in block
    assert "must=[" not in block


def test_recommendations_pass_the_same_statuses_they_filter_in_sql():
    """Filtr wektorowy i filtr SQL muszą znaczyć to samo.

    Dwie listy statusów rozjechałyby się przy pierwszej zmianie jednej z nich,
    a objaw byłby cichy: pula mniejsza, niż wołający zamówił.
    """
    source = open("app/api/recommendations.py", encoding="utf-8").read()
    assert "statuses=[s.value for s in _RECOMMENDABLE_STATUSES]" in source


def test_search_accepts_no_statuses_and_then_filters_nothing():
    """`statuses=None` = zachowanie sprzed zmiany (pełna kolekcja).

    Wołający, dla którego pusta odpowiedź jest gorsza niż zamknięta oferta
    w puli (podgląd CV, Targ), zostaje przy dotychczasowym kontrakcie.
    """
    import inspect

    sig = inspect.signature(embedding_service.search_jobs_semantic)
    assert sig.parameters["statuses"].default is None
    assert sig.parameters["statuses"].kind is inspect.Parameter.KEYWORD_ONLY
