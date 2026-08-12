"""Czytnik pasaży — spójność flipa i czwarta pułapka Fali 2.

Flaga `CV_PASSAGES_ENABLED` przełącza OBA wejścia retrievalu naraz (pulę
z `search_candidates_semantic` i kanbanowe `similarity_for_candidate_ids`),
bo zasilają ten sam cache score'ów, którego klucz nie ma pola powierzchni —
rozjazd mieszałby dwie skale semantyczne w jednym wierszu. A sama flaga MUSI
wchodzić do wersji algorytmu scoringu, inaczej prod po flipie serwowałby
score'y policzone na starej skali i ewaluacja pokazałaby brak efektu.
"""

import ast
from pathlib import Path
from types import SimpleNamespace

from qdrant_client import models as qmodels

from app.services.passage_index import (
    PAYLOAD_CANDIDATE_ID,
    best_passage_scores_for_ids,
    merge_candidate_hits,
)

BACKEND = Path(__file__).resolve().parents[1]


def test_cache_version_covers_the_passages_flag(monkeypatch):
    """CZWARTA PUŁAPKA PLANU — jednolinijkowa i najważniejsza integracja.

    Bez `CV_PASSAGES_ENABLED` w `_SCORING_CACHE_INPUTS` flip flagi nie
    inwalidowałby cache'u: prod serwowałby score'y policzone na STAREJ skali
    semantycznej, ewaluacja pokazałaby brak efektu, a wnioskiem byłoby
    „chunkowanie nie działa". Ten mechanizm był już ratowany ręcznie dwa razy
    (migracje 0143 i 0150).
    """

    from app.core.config import settings
    from app.services.scoring_service import scoring_algorithm_version

    monkeypatch.setattr(settings, "CV_PASSAGES_ENABLED", False, raising=False)
    version_off = scoring_algorithm_version()
    monkeypatch.setattr(settings, "CV_PASSAGES_ENABLED", True, raising=False)
    version_on = scoring_algorithm_version()

    assert version_off != version_on, (
        "flip flagi pasaży musi zmienić wersję algorytmu — inaczej stare "
        "score'y nigdy się nie unieważnią"
    )


def test_union_takes_the_max_and_admits_passage_only_candidates():
    """Unia, nie podmiana: pasaże UZUPEŁNIAJĄ wektor kandydata.

    Kandydat widoczny tylko przez pasaż (bo jego uśredniony wektor utopił
    sygnał sprzed pięciu lat) musi wejść do puli — po to jest cała fala.
    Kandydat lepszy w wektorze zostaje przy swoim wyniku.
    """

    base = [
        {"candidate_id": 1, "score": 0.80, "payload": {}},
        {"candidate_id": 2, "score": 0.60, "payload": {}},
    ]
    passages = [
        {"candidate_id": 2, "score": 0.90, "passage_index": 3, "passage_text": "Kafka"},
        {"candidate_id": 3, "score": 0.70, "passage_index": 0, "passage_text": "SQL"},
    ]

    merged = merge_candidate_hits(base, passages, top_k=10)
    by_id = {row["candidate_id"]: row for row in merged}

    assert [row["candidate_id"] for row in merged] == [2, 1, 3], (
        "sortowanie po maksimum"
    )
    assert by_id[1]["score"] == 0.80 and "passage_text" not in by_id[1], (
        "wygrana wektora nie może nosić cudzego dowodu pasażowego"
    )
    assert by_id[2]["score"] == 0.90 and by_id[2]["passage_text"] == "Kafka", (
        "wygrany pasaż niesie dowód dla rekrutera"
    )
    assert by_id[3]["score"] == 0.70, "kandydat pasażowy wchodzi do puli"


def test_union_respects_top_k():
    base = [
        {"candidate_id": i, "score": 1.0 - i / 100, "payload": {}} for i in range(1, 6)
    ]
    merged = merge_candidate_hits(base, [], top_k=3)
    assert len(merged) == 3


def test_flag_off_is_an_exact_rollback_in_both_paths():
    """Wyłączona flaga = bajt w bajt dzisiejsze zachowanie.

    Sprawdzane na AST obu funkcji: każde wywołanie pasażowe siedzi wewnątrz
    gałęzi bramkowanej `passages_enabled` — nic pasażowego nie wykonuje się
    bezwarunkowo. To jest własność odwracalności całej fali.
    """

    source = (BACKEND / "app/services/embedding_service.py").read_text(encoding="utf-8")
    tree = ast.parse(source)

    passage_calls = {
        "search_passage_hits",
        "best_passage_scores_for_ids",
        "aggregate_hits_to_candidates",
        "merge_candidate_hits",
    }

    def guarded_by_flag(node: ast.If) -> bool:
        return any(
            isinstance(n, ast.Name) and n.id == "passages_enabled"
            for n in ast.walk(node.test)
        )

    for fn_name in ("search_candidates_semantic", "similarity_for_candidate_ids"):
        fn = next(
            n
            for n in ast.walk(tree)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
            and n.name == fn_name
        )
        all_passage_calls = [
            n
            for n in ast.walk(fn)
            if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Name)
            and n.func.id in passage_calls
        ]
        guarded: set[int] = set()
        for if_node in (n for n in ast.walk(fn) if isinstance(n, ast.If)):
            if not guarded_by_flag(if_node):
                continue
            for n in ast.walk(if_node):
                if (
                    isinstance(n, ast.Call)
                    and isinstance(n.func, ast.Name)
                    and n.func.id in passage_calls
                ):
                    guarded.add(id(n))
        unguarded = [n.func.id for n in all_passage_calls if id(n) not in guarded]
        assert all_passage_calls, (
            f"{fn_name}: brak integracji pasażowej — flip nie objąłby tej ścieżki"
        )
        assert not unguarded, (
            f"{fn_name}: wywołania pasażowe poza bramką passages_enabled: {unguarded} — "
            "wyłączenie flagi przestaje być rollbackiem"
        )


class _RecordingClient:
    def __init__(self, hits):
        self._hits = hits
        self.last_filter = None

    def search(
        self,
        collection_name,
        query_vector,
        query_filter=None,
        limit=0,
        with_payload=True,
    ):
        self.last_filter = query_filter
        return self._hits


def _passage_hit(candidate_id: int, score: float):
    return SimpleNamespace(score=score, payload={PAYLOAD_CANDIDATE_ID: candidate_id})


def test_scores_for_ids_filters_by_payload_not_point_id():
    """`MatchAny` po payloadzie, NIE `HasIdCondition` po id punktu.

    Identyfikatory punktów tej kolekcji są pochodnymi (kandydat, pasaż) —
    filtr po id punktu nie znalazłby niczego. Ta sama pułapka co przy kasowaniu.
    """

    client = _RecordingClient(
        [_passage_hit(7, 0.5), _passage_hit(7, 0.9), _passage_hit(8, 0.4)]
    )
    scores = best_passage_scores_for_ids(client, [0.0] * 4, [7, 8])

    condition = client.last_filter.must[0]
    assert condition.key == PAYLOAD_CANDIDATE_ID
    assert isinstance(condition.match, qmodels.MatchAny)
    assert set(condition.match.any) == {7, 8}
    assert scores == {7: 0.9, 8: 0.4}, "maksimum per kandydat, nie pierwsze trafienie"


def test_scores_for_empty_ids_never_touch_qdrant():
    class _Exploding:
        def search(self, *a, **k):  # pragma: no cover - nie może być wywołane
            raise AssertionError("pusta lista nie może kosztować zapytania")

    assert best_passage_scores_for_ids(_Exploding(), [0.0] * 4, []) == {}
