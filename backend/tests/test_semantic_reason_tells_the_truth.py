"""Zerowa warstwa semantyczna musi mówić, DLACZEGO jest zerowa (#414).

`score_semantic(None)` dostawało `None` z DWÓCH powodów: kandydat naprawdę nie
ma wektora ALBO nie udało się zmierzyć (awaria Qdranta/Voyage). Mówiło o obu
„brak embeddingu", czyli przy awarii dostawcy wysyłało diagnozę w stronę
profilu kandydata — a profil był w porządku.

Punkty się NIE zmieniają (0.0 w obu przypadkach), więc żaden ranking nie drga.
Zmienia się to, co widzi człowiek szukający przyczyny, i to, co narzędzie
naprawcze potrafi znaleźć w cache'u.

Oba napisy są KLUCZAMI dopasowywanymi w SQL przez `admin_match_score_repair`.
Wiersze zapisane przed tą zmianą niosą wyłącznie ten pierwszy, więc narzędzie
musi znać oba — na zawsze, nie „do czasu migracji".
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest


def test_no_vector_still_blames_the_missing_embedding():
    """Kontrola negatywna: zmierzyliśmy i wektora nie ma — napis bez zmian.

    Bez tego testu „naprawa" polegająca na przemianowaniu wszystkiego na
    „pomiar niedostępny" przechodzi na zielono i gubi rozróżnienie w drugą
    stronę: kandydat bez CV wyglądałby jak awaria dostawcy.
    """
    from app.services.scoring_service import NO_EMBEDDING_REASON, score_semantic

    layer = score_semantic(None)

    assert layer.points == 0.0
    assert layer.reason == NO_EMBEDDING_REASON


def test_failed_measurement_says_so_instead_of_blaming_the_profile():
    from app.services.scoring_service import (
        SEMANTIC_UNAVAILABLE_REASON,
        score_semantic,
    )

    layer = score_semantic(None, unavailable=True)

    assert layer.points == 0.0, "punkty się nie zmieniają — zmienia się diagnoza"
    assert layer.reason == SEMANTIC_UNAVAILABLE_REASON


def test_a_measured_similarity_is_unaffected_by_the_flag():
    """Flaga dotyczy WYŁĄCZNIE gałęzi `None`. Zmierzony kosinus jej nie widzi."""
    from app.services.scoring_service import score_semantic

    with_flag = score_semantic(0.61, unavailable=True)
    without = score_semantic(0.61)

    assert with_flag.points == without.points
    assert with_flag.reason == without.reason == "sim 0.61"


def test_repair_tool_matches_BOTH_reasons():
    """Narzędzie naprawcze musi znaleźć wiersze zapisane PRZED i PO tej zmianie.

    Szukanie jednego napisu znajduje połowę zatrutych wierszy i raportuje to
    jako komplet — a zero trafień wygląda dokładnie jak „czysto".
    """
    from app.api.admin_match_score_repair import (
        NO_EMBEDDING_REASON,
        SEMANTIC_UNAVAILABLE_REASON,
        ZEROED_SEMANTIC_REASONS,
    )

    assert NO_EMBEDDING_REASON in ZEROED_SEMANTIC_REASONS
    assert SEMANTIC_UNAVAILABLE_REASON in ZEROED_SEMANTIC_REASONS


def test_repair_tool_constants_mirror_the_scorer():
    """Dwa moduły, ta sama para napisów — rozjazd ma być DECYZJĄ, nie wpadką.

    Ten test jest lustrem istniejącego kontraktu dla `NO_EMBEDDING_REASON`,
    rozszerzonym o drugi powód.
    """
    from app.api import admin_match_score_repair as repair
    from app.services import scoring_service

    assert repair.NO_EMBEDDING_REASON == scoring_service.NO_EMBEDDING_REASON
    assert (
        repair.SEMANTIC_UNAVAILABLE_REASON
        == scoring_service.SEMANTIC_UNAVAILABLE_REASON
    )


@pytest.mark.asyncio
async def test_bulk_scoring_threads_the_cause_per_candidate(monkeypatch):
    """`bulk_get_or_compute` rozdziela przyczynę PER KANDYDAT, nie na cały bieg.

    W jednej puli bywają obok siebie kandydat bez wektora i kandydat, którego
    nie zmierzono — jeden wspólny powód dla całego żądania zamazałby tę różnicę
    dokładnie tam, gdzie jest potrzebna.
    """
    import app.services.match_score_cache as msc

    seen: dict[int, bool] = {}

    async def fake_score(candidate, job, db, **kwargs):
        seen[candidate.id] = kwargs.get("semantic_unavailable")
        return SimpleNamespace(
            candidate_id=candidate.id, job_id=job.id, total=0.0, as_dict=lambda: {}
        )

    async def no_rows(*_a, **_k):
        return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: []))

    async def no_context(*_a, **_k):
        return None

    monkeypatch.setattr(msc, "score_candidate_job", fake_score)
    monkeypatch.setattr(msc, "build_job_scoring_context", no_context)
    monkeypatch.setattr(msc, "_persist_breakdowns", lambda *a, **k: None)

    db = SimpleNamespace(execute=no_rows, scalar=lambda *a, **k: None)

    class _Db:
        async def execute(self, *_a, **_k):
            return SimpleNamespace(
                scalars=lambda: SimpleNamespace(all=lambda: [])
            )

        async def scalar(self, *_a, **_k):
            return None

    db = _Db()
    job = SimpleNamespace(id=7)
    candidates = [SimpleNamespace(id=11), SimpleNamespace(id=99)]

    await msc.bulk_get_or_compute(
        job,
        candidates,
        db,
        similarity_map={11: 0.6},
        semantic_unavailable_ids={99},
        allow_cache_write=False,
    )

    assert seen == {11: False, 99: True}
