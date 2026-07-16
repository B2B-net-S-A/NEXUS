"""Deterministyczny 3-way merge dla integracji dwukierunkowej Traffit.

Czysta logika, niezależna od SQLAlchemy i transportu. Oba kierunki (inbound
i outbound) porównują kanoniczne snapshoty NEXUS i Traffit z ostatnią wspólną
bazą (``base_snapshot`` z ``traffit_entity_links``):

- pole zmienione tylko po jednej stronie propaguje się na drugą,
- pole zmienione różnie po obu stronach staje się jawnym konfliktem admina,
- pole NIEOBECNE w snapshocie (``MISSING``) nie jest zmianą i nigdy nie
  czyści wartości — to naprawa P0 z prototypu WIP, gdzie brak klucza w
  odpowiedzi Traffita bywał interpretowany jako ``null`` i zerował lokalne
  pola kandydata przy niezwiązanej aktualizacji (plan 2026-07-16, §4.1).

Twarde inwarianty (plan §7 pkt 2-4):

1. ``MISSING`` ≠ ``null`` — jawny ``None`` to legalne czyszczenie (o ile
   kontrakt pola potwierdza semantykę), brak klucza to brak informacji.
2. Patch dla strony może zawierać wyłącznie ścieżki OBECNE w snapshocie
   źródłowym (żadna projekcja nie wygeneruje zapisu z niczego).
3. Konflikt nie nadpisuje żadnej strony — ``merged`` zachowuje bazę.

Zagnieżdżone mapy (w tym ``custom_fields._<SID>``) są porównywane po
ścieżkach kropkowych, więc częściowy patch custom fields zachowuje pozostałe
klucze (merge patch, nie replacement całego JSON-a). Listy są atomowe —
Traffit nie daje stabilnych ID elementów dla wszystkich typów multi-value.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Optional


class _MissingType:
    """Sentinel „pole nieobecne w snapshocie" — jawnie różny od ``None``."""

    _instance: Optional["_MissingType"] = None

    def __new__(cls) -> "_MissingType":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return "MISSING"

    def __bool__(self) -> bool:
        return False


MISSING = _MissingType()

# Reprezentacja MISSING w payloadach JSONB (konflikty) — string-sentinel,
# bo JSON nie rozróżnia "brak klucza" od null po serializacji płaskiej listy.
MISSING_TOKEN = "__MISSING__"


def canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def snapshot_hash(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def flatten_paths(value: Mapping[str, Any], prefix: str = "") -> dict[str, Any]:
    """Spłaszcz zagnieżdżoną mapę do ścieżek kropkowych.

    Jawnie pusta mapa jest znaczącą wartością (``{}``), nie brakiem klucza.
    """
    result: dict[str, Any] = {}
    for key, child in value.items():
        path = f"{prefix}.{key}" if prefix else str(key)
        if isinstance(child, Mapping):
            nested = flatten_paths(child, path)
            if nested:
                result.update(nested)
            else:
                result[path] = {}
        else:
            result[path] = child
    return result


def get_path(source: Mapping[str, Any], path: str, default: Any = None) -> Any:
    """Odczyt po ścieżce kropkowej (wspólny helper — P1 custom fields)."""
    cursor: Any = source
    for part in path.split("."):
        if not isinstance(cursor, Mapping) or part not in cursor:
            return default
        cursor = cursor[part]
    return cursor


def set_path(target: dict[str, Any], path: str, value: Any) -> None:
    """Zapis po ścieżce kropkowej — buduje zagnieżdżony obiekt, nie płaski
    klucz (P1 z review WIP: decyzja dla ``custom_fields._SID`` musi utworzyć
    ``{"custom_fields": {"_SID": value}}``)."""
    parts = path.split(".")
    cursor = target
    for part in parts[:-1]:
        nested = cursor.get(part)
        if not isinstance(nested, dict):
            nested = {}
            cursor[part] = nested
        cursor = nested
    cursor[parts[-1]] = value


def public_value(value: Any) -> Any:
    """Wartość bezpieczna do JSONB payloadu konfliktu.

    ``MISSING`` jest kodowane string-sentinelem, NIE ``None`` — inaczej
    admin w modalu konfliktu nie odróżni „pole nieobecne" od „jawnie puste".
    """
    return MISSING_TOKEN if value is MISSING else value


@dataclass(frozen=True)
class FieldConflict:
    field_path: str
    base_value: Any
    nexus_value: Any
    traffit_value: Any
    conflict_type: str = "field_conflict"


@dataclass
class MergeResult:
    merged: dict[str, Any] = field(default_factory=dict)
    conflicts: list[FieldConflict] = field(default_factory=list)
    apply_to_nexus: dict[str, Any] = field(default_factory=dict)
    apply_to_traffit: dict[str, Any] = field(default_factory=dict)

    @property
    def is_conflicted(self) -> bool:
        return bool(self.conflicts)


def three_way_merge(
    base: Mapping[str, Any],
    nexus: Mapping[str, Any],
    traffit: Mapping[str, Any],
    *,
    ignored_fields: Iterable[str] = (),
    contract_paths: Optional[Iterable[str]] = None,
) -> MergeResult:
    """Scal snapshoty zachowując konflikty zamiast wybierać zwycięzcę.

    Reguły per ścieżka (plan §13):

    ======================  ======================  =========================
    NEXUS vs BASE           TRAFFIT vs BASE         wynik
    ======================  ======================  =========================
    bez zmiany              bez zmiany              brak operacji
    zmiana                  bez zmiany              NEXUS wygrywa → patch Traffit
    bez zmiany              zmiana                  Traffit wygrywa → apply NEXUS
    ta sama zmiana          ta sama zmiana          uzgodnij bez konfliktu
    różne zmiany            różne zmiany            konflikt (merged = base)
    ``MISSING``             dowolne                 brak implikowanego czyszczenia
    ======================  ======================  =========================

    ``MISSING`` po którejkolwiek stronie znaczy „strona nic nie mówi o tym
    polu" i jest traktowane jak brak zmiany względem bazy. Dzięki temu patch
    nigdy nie zawiera ścieżki nieobecnej w snapshocie źródłowym — a więc
    częściowa odpowiedź API nie wyzeruje żadnego pola.

    ``contract_paths`` (opcjonalne) ogranicza merge do kanonicznego zestawu
    synchronizowanych ścieżek — ścieżki spoza kontraktu są ignorowane w
    całości (bez patcha i bez konfliktu).
    """
    base_flat = flatten_paths(base)
    nexus_flat = flatten_paths(nexus)
    traffit_flat = flatten_paths(traffit)
    ignored = set(ignored_fields)
    union = set(base_flat) | set(nexus_flat) | set(traffit_flat)

    # Kolizja kształtu: ta sama ścieżka jest liściem w jednym snapshocie,
    # a kontenerem w innym (np. ``city`` scalar vs ``city.n``). Porównanie
    # per-ścieżka dałoby sprzeczny ``merged`` (nadpisywanie się nawzajem),
    # więc całe pole traktujemy atomowo — wartości czytamy z ORYGINALNYCH
    # map przez get_path. Kanoniczna projekcja gwarantuje stabilne kształty,
    # więc to ścieżka defensywna (schema drift tenanta).
    mixed_roots = {
        p for p in union if any(q != p and q.startswith(f"{p}.") for q in union)
    }
    # Zostaw tylko najpłytsze korzenie (zagnieżdżone pokrywa przodek).
    mixed_roots = {
        p
        for p in mixed_roots
        if not any(r != p and p.startswith(f"{r}.") for r in mixed_roots)
    }
    leaf_paths = {
        p
        for p in union
        if p not in mixed_roots and not any(p.startswith(f"{r}.") for r in mixed_roots)
    }
    paths = sorted(leaf_paths | mixed_roots)
    allowed = None if contract_paths is None else set(contract_paths)
    result = MergeResult()

    def _value(flat: Mapping[str, Any], source: Mapping[str, Any], path: str) -> Any:
        if path in mixed_roots:
            return get_path(source, path, MISSING)
        return flat.get(path, MISSING)

    for path in paths:
        if path in ignored or any(path.startswith(f"{item}.") for item in ignored):
            continue
        if allowed is not None and path not in allowed:
            # Poza kontraktem — zachowaj bazę w merged, żadnych operacji.
            b_out = _value(base_flat, base, path)
            if b_out is not MISSING:
                set_path(result.merged, path, b_out)
            continue

        b = _value(base_flat, base, path)
        n = _value(nexus_flat, nexus, path)
        t = _value(traffit_flat, traffit, path)

        # MISSING = brak informacji = brak zmiany względem bazy.
        n_eff = b if n is MISSING else n
        t_eff = b if t is MISSING else t

        if n_eff == t_eff:
            chosen = n_eff
        elif n_eff == b:
            # Zmiana tylko po stronie Traffit. Ścieżka jest na pewno obecna
            # w snapshocie Traffita (inaczej t_eff == b), więc patch nigdy
            # nie powstaje "z niczego".
            chosen = t_eff
            set_path(result.apply_to_nexus, path, t_eff)
        elif t_eff == b:
            chosen = n_eff
            set_path(result.apply_to_traffit, path, n_eff)
        else:
            result.conflicts.append(
                FieldConflict(
                    field_path=path,
                    base_value=public_value(b),
                    nexus_value=public_value(n),
                    traffit_value=public_value(t),
                )
            )
            chosen = b

        if chosen is not MISSING:
            set_path(result.merged, path, chosen)

    return result
