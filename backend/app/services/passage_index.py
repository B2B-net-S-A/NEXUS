"""Indeks pasaży CV w Qdrancie — osobna kolekcja, Fala 2.

DLACZEGO OSOBNA KOLEKCJA, A NIE PRZEBUDOWA ISTNIEJĄCEJ. `embed_candidate` ustawia
`point.id == candidate_id`, a DZIEWIĘĆ modułów opiera się na tym 1:1
(`recommendations`, `matching`, `search`, `hybrid_search`, `marketplace_service`,
`match_justification_service`, `compute_proposals`, `talent_radar_search` oraz
sonda w `main`). Wpuszczenie pasaży do `nexus_candidates` zepsułoby wszystkie
naraz — jeden kandydat przestałby być jednym punktem.

PAMIĘĆ JEST TU OGRANICZENIEM PIERWSZORZĘDNYM, NIE OPTYMALIZACJĄ. Kontener
Qdranta ma twardy limit 2 GB (`docker-compose.prod.yml`), a obecna kolekcja
zajmuje ~260 MB. Zmierzone na rozkładzie długości CV z produkcji: ~50 tys.
kandydatów × średnio 5,1 pasażu = ~254 tys. punktów, czyli **991 MB** wektorów
f32. Zmieściłoby się to w limicie tylko nominalnie — bez zapasu na graf HNSW,
payload i skoki, a OOM Qdranta gasi całe wyszukiwanie semantyczne. Kwantyzacja
int8 schodzi do ~248 MB i dopiero to jest bezpieczne.

Dlatego `on_disk=True` + int8 `always_ram` są ustawione PRZY TWORZENIU kolekcji:
zmiana tego po zapisaniu ćwierć miliona punktów wymaga przebudowy indeksu.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from qdrant_client import models as qmodels

from app.core.config import settings

logger = logging.getLogger(__name__)

_DEFAULT_PASSAGES_COLLECTION = "nexus_cv_passages"
VECTOR_SIZE = 1024

# Granica bezpieczeństwa identyfikatorów punktów: `point_id_for` koduje parę
# (kandydat, pasaż) jako `candidate_id * MAX + index`, więc przekroczenie tej
# liczby oznaczałoby kolizję z pasażami INNEGO kandydata. Zmierzone maksimum
# w korpusie to 21 pasaży na CV — zapas jest wielokrotny. Na poziomie modułu,
# żeby test asertował tę samą wartość, którą egzekwuje kod, zamiast powtarzać
# liczbę, która po zmianie granicy cicho przestaje jej pilnować.
MAX_PASSAGES_PER_CANDIDATE = 1000

# Klucz payloadu, po którym kasujemy pasaże kandydata. Bez indeksu na nim filtr
# jest liniowy po ćwierć miliona punktów — a kasowanie musi być szybkie, bo
# wchodzi w ścieżkę usuwania kandydata (RODO).
PAYLOAD_CANDIDATE_ID = "candidate_id"


def passages_collection_name() -> str:
    return (
        getattr(settings, "QDRANT_PASSAGES_COLLECTION", None)
        or _DEFAULT_PASSAGES_COLLECTION
    )


def passages_enabled() -> bool:
    """Fala 2 jest domyślnie WYŁĄCZONA — włącza ją jawna flaga.

    Kolekcja może istnieć i być wypełniona, a mimo to nie brać udziału w
    retrievalu. To rozdzielenie jest celowe: pozwala zbudować i ZMIERZYĆ indeks
    na produkcji, zanim cokolwiek zacznie z niego czytać.
    """

    return bool(getattr(settings, "CV_PASSAGES_ENABLED", False))


def build_collection_config() -> dict[str, Any]:
    """Parametry kolekcji pasaży — wydzielone, żeby dało się je asertować w teście.

    Gdyby siedziały wprost w wywołaniu `create_collection`, jedynym sposobem na
    sprawdzenie kwantyzacji byłoby postawienie Qdranta w teście. A to jest
    dokładnie ta własność, której NIE wolno zgubić: bez niej kolekcja wchodzi w
    RAM czterokrotnie większa i zabiera kontener.
    """

    return {
        "vectors_config": qmodels.VectorParams(
            size=VECTOR_SIZE,
            distance=qmodels.Distance.COSINE,
            # Oryginały na dysku — w RAM zostaje wyłącznie forma skwantyzowana.
            on_disk=True,
        ),
        "quantization_config": qmodels.ScalarQuantization(
            scalar=qmodels.ScalarQuantizationConfig(
                type=qmodels.ScalarType.INT8,
                # Kwantyzat MUSI zostać w RAM — inaczej każde zapytanie schodzi
                # na dysk i zysk pamięciowy kupujemy opóźnieniem.
                always_ram=True,
            )
        ),
    }


def ensure_passages_collection(client) -> bool:
    """Utwórz kolekcję pasaży, jeśli jej nie ma. Idempotentne.

    Zwraca True, gdy kolekcja istnieje po wywołaniu. NIE dotyka kolekcji
    kandydatów ani ofert.
    """

    try:
        name = passages_collection_name()
        existing = {c.name for c in client.get_collections().collections}
        if name not in existing:
            client.create_collection(collection_name=name, **build_collection_config())
            logger.info(
                "[Qdrant] Kolekcja pasaży '%s' utworzona (int8 always_ram, on_disk).",
                name,
            )

        # Indeks payloadu — bez niego kasowanie po `candidate_id` skanuje liniowo.
        # `create_payload_index` jest idempotentne po stronie serwera.
        client.create_payload_index(
            collection_name=name,
            field_name=PAYLOAD_CANDIDATE_ID,
            field_schema=qmodels.PayloadSchemaType.INTEGER,
        )
        return True
    except Exception as exc:  # noqa: BLE001 - brak Qdranta nie może wywalić startu
        logger.warning("[Qdrant] ensure_passages_collection nie powiodło się: %s", exc)
        return False


def candidate_filter(candidate_id: int) -> qmodels.Filter:
    """Filtr „wszystkie pasaże tego kandydata"."""

    return qmodels.Filter(
        must=[
            qmodels.FieldCondition(
                key=PAYLOAD_CANDIDATE_ID,
                match=qmodels.MatchValue(value=candidate_id),
            )
        ]
    )


def delete_candidate_passages(client, candidate_id: int) -> bool:
    """Usuń WSZYSTKIE pasaże kandydata — po filtrze, nie po identyfikatorze punktu.

    To jest pułapka, przez którą ta funkcja w ogóle istnieje.
    `delete_candidate_embedding` kasuje `points_selector=[candidate_id]`, bo w
    kolekcji kandydatów punkt ma dokładnie takie id. W kolekcji pasaży punktu o
    takim id NIE MA — identyfikatory są pochodnymi `(kandydat, indeks pasażu)`.
    Ta sama forma wywołania usunęłaby więc ZERO punktów, zwróciła sukces i
    zalogowała powodzenie, zostawiając w indeksie nazwisko i fragmenty CV osoby,
    która została skasowana. Prawo do bycia zapomnianym przeciekałoby po cichu.
    """

    try:
        client.delete(
            collection_name=passages_collection_name(),
            points_selector=qmodels.FilterSelector(
                filter=candidate_filter(candidate_id)
            ),
        )
        return True
    except Exception as exc:  # noqa: BLE001
        # Brak kolekcji to sukces PRÓŻNIOWY, nie awaria: nie ma kolekcji, więc
        # nie ma pasaży, więc nie ma czego zapominać. To nie jest kosmetyka —
        # ta funkcja wisi na ścieżce usuwania KAŻDEGO kandydata, a kolekcja
        # pasaży powstaje dopiero przy pierwszym backfillu. Bez tej gałęzi
        # każde usunięcie kandydata na prodzie logowałoby fałszywy warning,
        # a `replace_candidate_passages` odmawiałby zapisu tam, gdzie
        # wystarczyłoby utworzyć kolekcję (robi to `ensure_passages_collection`,
        # wołane przez skrypt backfillu PRZED pierwszym zapisem).
        status = getattr(exc, "status_code", None)
        message = str(exc).lower()
        if status == 404 or "not found" in message or "doesn't exist" in message:
            logger.debug(
                "[Qdrant] kolekcja pasaży nie istnieje — nie ma czego usuwać "
                "(kandydat %s).",
                candidate_id,
            )
            return True
        logger.warning(
            "[Qdrant] nie udało się usunąć pasaży kandydata %s: %s", candidate_id, exc
        )
        return False


def replace_candidate_passages(
    client,
    candidate_id: int,
    points: list[qmodels.PointStruct],
) -> bool:
    """Zamień komplet pasaży kandydata: NAJPIERW skasuj, potem zapisz.

    Kolejność jest tu treścią, nie stylem. CV skrócone z sześciu pasaży do trzech
    nadpisuje przy upsercie indeksy 0-2, a 3-5 ŻYJĄ DALEJ ze starą treścią i
    nadal wypadają w wynikach wyszukiwania. Indeks zaśmiecałby się przy każdej
    edycji CV, a kandydat dopasowywałby się do technologii, których dawno nie ma
    w jego dokumencie.
    """

    if not delete_candidate_passages(client, candidate_id):
        return False
    if not points:
        return True
    try:
        client.upsert(collection_name=passages_collection_name(), points=points)
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "[Qdrant] nie udało się zapisać pasaży kandydata %s: %s", candidate_id, exc
        )
        return False


def point_id_for(candidate_id: int, passage_index: int) -> int:
    """Stabilny identyfikator punktu dla pary (kandydat, indeks pasażu).

    Deterministyczny, żeby ponowne przetworzenie tego samego CV NADPISYWAŁO te
    same punkty zamiast mnożyć duplikaty. Mnożnik z zapasem: `MAX_PASSAGES_PER_CANDIDATE` jest
    wyższy niż zmierzone maksimum (21 pasaży na CV), więc identyfikatory dwóch
    kandydatów nie mogą na siebie wejść.
    """

    if not 0 <= passage_index < MAX_PASSAGES_PER_CANDIDATE:
        raise ValueError(
            f"indeks pasażu {passage_index} poza zakresem "
            f"0..{MAX_PASSAGES_PER_CANDIDATE - 1} — przekroczenie oznaczałoby "
            "kolizję identyfikatorów między kandydatami"
        )
    return candidate_id * MAX_PASSAGES_PER_CANDIDATE + passage_index


def aggregate_hits_to_candidates(
    hits: list[Any], top_k: int
) -> list[dict[str, Optional[float]]]:
    """Zwiń trafienia pasaży do kandydatów — najlepszy pasaż wygrywa.

    Zaczynamy od maksimum, nie od średniej: kandydat pasuje do roli, jeśli
    JAKIŚ fragment jego doświadczenia pasuje. Uśrednienie po wszystkich pasażach
    karałoby długie CV, czyli dokładnie osoby z najbogatszym doświadczeniem — i
    odtwarzałoby uśrednianie, przed którym ta zmiana ucieka.

    Zwracamy też, KTÓRY pasaż trafił: to jest gotowy dowód dla rekrutera
    („pasuje, bo w latach 2019-2022 robił X"), a bez niego wynik jest liczbą
    bez uzasadnienia.
    """

    best: dict[int, dict[str, Any]] = {}
    for hit in hits:
        payload = getattr(hit, "payload", None) or {}
        candidate_id = payload.get(PAYLOAD_CANDIDATE_ID)
        if candidate_id is None:
            continue
        score = float(getattr(hit, "score", 0.0) or 0.0)
        current = best.get(candidate_id)
        if current is None or score > current["score"]:
            best[candidate_id] = {
                "candidate_id": int(candidate_id),
                "score": score,
                "passage_index": payload.get("passage_index"),
                "passage_text": payload.get("text"),
            }

    ranked = sorted(best.values(), key=lambda row: row["score"], reverse=True)
    return ranked[:top_k]
