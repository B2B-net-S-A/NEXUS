"""Indeks pasaży — cztery ciche pułapki Fali 2.

Żadna z nich nie objawia się błędem: kolekcja bez kwantyzacji po prostu zajmuje
czterokrotnie więcej RAM-u i zabija kontener; kasowanie po identyfikatorze punktu
usuwa zero punktów i raportuje sukces; upsert bez wcześniejszego kasowania
zostawia w indeksie nieaktualne pasaże. Dlatego wszystkie mają testy.
"""

from types import SimpleNamespace

import pytest
from qdrant_client import models as qmodels

from app.services.passage_index import (
    MAX_PASSAGES_PER_CANDIDATE,
    PAYLOAD_CANDIDATE_ID,
    aggregate_hits_to_candidates,
    build_collection_config,
    candidate_filter,
    delete_candidate_passages,
    point_id_for,
    replace_candidate_passages,
)


def test_collection_is_quantized_and_on_disk():
    """Bez tego kolekcja nie mieści się bezpiecznie w kontenerze.

    Zmierzone: ~254 tys. punktów × 1024 wymiary to 991 MB w f32 przy limicie
    2 GB, z którego 260 MB zajmuje już kolekcja kandydatów. int8 schodzi do
    ~248 MB. To warunek wykonalności, nie strojenie.
    """

    config = build_collection_config()

    assert config["vectors_config"].on_disk is True, (
        "oryginalne wektory muszą leżeć na dysku — w RAM zostaje kwantyzat"
    )
    quant = config["quantization_config"]
    assert isinstance(quant, qmodels.ScalarQuantization)
    assert quant.scalar.type == qmodels.ScalarType.INT8
    assert quant.scalar.always_ram is True, (
        "kwantyzat poza RAM-em oznacza zejście na dysk przy każdym zapytaniu — "
        "zysk pamięciowy kupiony opóźnieniem"
    )


def test_point_ids_never_collide_between_candidates():
    """Identyfikator punktu koduje parę (kandydat, pasaż).

    Kolizja oznaczałaby, że pasaż jednego kandydata nadpisuje pasaż innego —
    czyli ciche wymieszanie CV dwóch osób.
    """

    seen = set()
    for candidate_id in (1, 2, 999, 56_783):
        for index in range(0, 25):
            point = point_id_for(candidate_id, index)
            assert point not in seen, f"kolizja dla ({candidate_id}, {index})"
            seen.add(point)


def test_point_id_rejects_an_index_that_would_collide():
    """Zmierzone maksimum to 21 pasaży; limit odrzuca to, co grozi kolizją.

    Granica jest IMPORTOWANA, nie powtórzona: test z zaszytą liczbą po zmianie
    limitu dalej by przechodził, pilnując granicy, której kod już nie ma — ta
    sama klasa co „test-teatr" z bramki SQL, złapana wcześniej tego samego dnia.
    """

    with pytest.raises(ValueError, match="kolizj"):
        point_id_for(7, MAX_PASSAGES_PER_CANDIDATE)
    assert point_id_for(7, MAX_PASSAGES_PER_CANDIDATE - 1) > 0


def test_point_id_is_deterministic():
    assert point_id_for(42, 3) == point_id_for(42, 3)


class _FakeClient:
    def __init__(self):
        self.deleted: list = []
        self.upserted: list = []
        self.calls: list[str] = []

    def delete(self, collection_name, points_selector):
        self.calls.append("delete")
        self.deleted.append(points_selector)

    def upsert(self, collection_name, points):
        self.calls.append("upsert")
        self.upserted.append(points)


def test_delete_uses_a_filter_not_a_point_id():
    """Pułapka RODO — najgroźniejsza z czterech.

    `delete_candidate_embedding` kasuje `points_selector=[candidate_id]`, bo w
    kolekcji kandydatów punkt ma dokładnie takie id. W kolekcji pasaży takiego
    punktu NIE MA. Ta sama forma wywołania usunęłaby zero punktów, zwróciła
    sukces i zostawiła w indeksie nazwisko oraz fragmenty CV osoby skasowanej.
    """

    client = _FakeClient()
    assert delete_candidate_passages(client, 7) is True

    selector = client.deleted[0]
    assert isinstance(selector, qmodels.FilterSelector), (
        "kasowanie MUSI iść po filtrze; lista identyfikatorów usunie zero punktów"
    )
    condition = selector.filter.must[0]
    assert condition.key == PAYLOAD_CANDIDATE_ID
    assert condition.match.value == 7


class _MissingCollectionClient:
    """Symuluje Qdranta sprzed pierwszego backfillu — kolekcji pasaży nie ma."""

    def delete(self, collection_name, points_selector):
        raise RuntimeError(f"Collection `{collection_name}` doesn't exist!")


def test_missing_collection_is_a_vacuous_delete_success():
    """Nie ma kolekcji ⇒ nie ma pasaży ⇒ nie ma czego zapominać.

    Ta funkcja wisi na ścieżce usuwania KAŻDEGO kandydata, a kolekcja pasaży
    powstaje dopiero przy pierwszym backfillu. Bez tej gałęzi każde usunięcie
    kandydata na prodzie logowałoby fałszywy warning, a `replace_*` odmawiałby
    zapisu tam, gdzie wystarczy utworzyć kolekcję.
    """

    assert delete_candidate_passages(_MissingCollectionClient(), 7) is True


def test_replace_deletes_before_upserting():
    """Pułapka zombie-pasaży.

    CV skrócone z sześciu pasaży do trzech nadpisuje przy upsercie indeksy 0-2,
    a 3-5 żyją dalej ze starą treścią i nadal wypadają w wynikach. Kolejność
    operacji jest tu treścią, nie stylem.
    """

    client = _FakeClient()
    points = [
        qmodels.PointStruct(id=point_id_for(7, i), vector=[0.0] * 4, payload={})
        for i in range(3)
    ]
    assert replace_candidate_passages(client, 7, points) is True
    assert client.calls == ["delete", "upsert"], (
        f"upsert przed kasowaniem zostawia zombie: {client.calls}"
    )


def test_replace_with_no_passages_still_clears_the_index():
    """CV usunięte albo puste — stare pasaże nie mogą zostać."""

    client = _FakeClient()
    assert replace_candidate_passages(client, 7, []) is True
    assert client.calls == ["delete"]


def _hit(candidate_id: int, score: float, index: int, text: str = "x"):
    return SimpleNamespace(
        score=score,
        payload={
            PAYLOAD_CANDIDATE_ID: candidate_id,
            "passage_index": index,
            "text": text,
        },
    )


def test_best_passage_wins_and_long_cvs_are_not_punished():
    """Agregacja przez maksimum, nie średnią.

    Kandydat pasuje, jeśli JAKIŚ fragment jego doświadczenia pasuje. Uśrednienie
    po wszystkich pasażach karałoby długie CV — czyli osoby z najbogatszym
    doświadczeniem — i odtwarzałoby uśrednianie, przed którym uciekamy.
    """

    hits = [
        _hit(1, 0.91, 4, "FastAPI i PostgreSQL"),
        _hit(1, 0.20, 0),
        _hit(1, 0.15, 1),
        _hit(1, 0.10, 2),
        _hit(2, 0.80, 0),
    ]
    ranked = aggregate_hits_to_candidates(hits, top_k=10)

    assert [r["candidate_id"] for r in ranked] == [1, 2]
    assert ranked[0]["score"] == 0.91
    assert ranked[0]["passage_index"] == 4
    assert ranked[0]["passage_text"] == "FastAPI i PostgreSQL", (
        "trafiony pasaż to gotowy dowód dla rekrutera — bez niego wynik jest "
        "liczbą bez uzasadnienia"
    )


def test_aggregation_respects_top_k_and_skips_payloadless_hits():
    hits = [_hit(i, 1.0 - i / 100, 0) for i in range(1, 6)]
    hits.append(SimpleNamespace(score=0.99, payload={}))
    ranked = aggregate_hits_to_candidates(hits, top_k=3)
    assert len(ranked) == 3
    assert all(r["candidate_id"] is not None for r in ranked)


def test_candidate_filter_shape():
    flt = candidate_filter(11)
    assert flt.must[0].key == PAYLOAD_CANDIDATE_ID
    assert flt.must[0].match.value == 11


def test_candidate_deletion_path_also_removes_passages():
    """Pasaże kasują się TĄ SAMĄ ścieżką co wektor kandydata.

    Osobna funkcja, o której trzeba pamiętać, prędzej czy później zostałaby
    pominięta. Sprawdzane na źródle, bo chodzi o to, że wywołanie w ogóle jest
    w tym miejscu — a jedyne alternatywne dowody to postawienie Qdranta albo
    zamockowanie klienta tak głęboko, że test przestałby cokolwiek znaczyć.
    """

    import ast
    from pathlib import Path

    source = (
        Path(__file__).resolve().parents[1] / "app/services/embedding_service.py"
    ).read_text(encoding="utf-8")
    tree = ast.parse(source)

    target = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == "delete_candidate_embedding"
    )
    called = {
        node.func.id
        for node in ast.walk(target)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert "delete_candidate_passages" in called, (
        "usunięcie kandydata musi kasować też jego pasaże — inaczej w indeksie "
        "zostaje nazwisko i fragmenty CV osoby skasowanej"
    )
