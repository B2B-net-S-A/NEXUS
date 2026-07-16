"""Testy silnika 3-way merge (plan §20.2 + regresje P0 z review WIP).

Czysta logika — bez DB i sieci. Najważniejsze przypadki:

- P0: pole nieobecne w odpowiedzi Traffita NIE czyści lokalnej wartości,
- MISSING vs jawny null mają różne znaczenie,
- częściowy patch custom fields zachowuje pozostałe SID-y,
- property (seeded): patch zawiera wyłącznie ścieżki obecne w snapshocie
  źródłowym; merge jest deterministyczny i nie gubi niezmienionych pól.
"""

from __future__ import annotations

import random

from app.services.traffit.merge import (
    MISSING,
    MISSING_TOKEN,
    FieldConflict,
    canonical_json,
    flatten_paths,
    get_path,
    set_path,
    snapshot_hash,
    three_way_merge,
)

# ── Podstawowe reguły (tabela plan §13) ──────────────────────────────────────


def test_no_changes_produces_no_operations():
    base = {"email": "a@x.pl", "city": "Poznań"}
    result = three_way_merge(base, dict(base), dict(base))
    assert result.apply_to_nexus == {}
    assert result.apply_to_traffit == {}
    assert result.conflicts == []
    assert result.merged == base


def test_disjoint_changes_merge_cleanly():
    base = {"email": "a@x.pl", "city": "Poznań"}
    nexus = {"email": "nowy@x.pl", "city": "Poznań"}
    traffit = {"email": "a@x.pl", "city": "Warszawa"}
    result = three_way_merge(base, nexus, traffit)
    assert result.conflicts == []
    assert result.apply_to_traffit == {"email": "nowy@x.pl"}
    assert result.apply_to_nexus == {"city": "Warszawa"}
    assert result.merged == {"email": "nowy@x.pl", "city": "Warszawa"}


def test_same_change_both_sides_reconciles_without_conflict():
    base = {"phone": "111"}
    result = three_way_merge(base, {"phone": "222"}, {"phone": "222"})
    assert result.conflicts == []
    assert result.apply_to_nexus == {}
    assert result.apply_to_traffit == {}
    assert result.merged == {"phone": "222"}


def test_divergent_change_same_field_is_conflict_and_keeps_base():
    base = {"phone": "111"}
    result = three_way_merge(base, {"phone": "222"}, {"phone": "333"})
    assert len(result.conflicts) == 1
    conflict = result.conflicts[0]
    assert conflict.field_path == "phone"
    assert (conflict.base_value, conflict.nexus_value, conflict.traffit_value) == (
        "111",
        "222",
        "333",
    )
    # Konflikt nie nadpisuje żadnej strony — merged zachowuje bazę.
    assert result.merged == {"phone": "111"}
    assert result.apply_to_nexus == {}
    assert result.apply_to_traffit == {}


# ── P0: MISSING nie czyści wartości ──────────────────────────────────────────


def test_p0_missing_fields_in_remote_response_do_not_wipe_local_values():
    # Regresja P0 z WIP: zdalna odpowiedź bez source/city/country/region/
    # availability nie może zmienić tych pól przy aktualizacji emaila.
    base = {
        "email": "a@x.pl",
        "source": "linkedin",
        "city": "Poznań",
        "country": "PL",
        "region": "wielkopolskie",
        "availability": "2026-08-01",
    }
    nexus = dict(base)
    traffit = {"email": "zmieniony@x.pl"}  # partial response — reszta nieobecna
    result = three_way_merge(base, nexus, traffit)
    assert result.conflicts == []
    assert result.apply_to_nexus == {"email": "zmieniony@x.pl"}
    # Żadne z nieobecnych pól nie zostało wyzerowane ani dotknięte.
    for key in ("source", "city", "country", "region", "availability"):
        assert result.merged[key] == base[key], key
    assert result.apply_to_traffit == {}


def test_missing_is_distinct_from_explicit_null():
    base = {"city": "Poznań"}
    # Jawny null = legalne czyszczenie → propaguje się.
    explicit = three_way_merge(base, dict(base), {"city": None})
    assert explicit.apply_to_nexus == {"city": None}
    assert explicit.merged == {"city": None}
    # Brak klucza = brak informacji → nic się nie dzieje.
    absent = three_way_merge(base, dict(base), {})
    assert absent.apply_to_nexus == {}
    assert absent.merged == {"city": "Poznań"}


def test_missing_on_nexus_side_does_not_generate_traffit_patch():
    base = {"city": "Poznań"}
    result = three_way_merge(base, {}, dict(base))
    assert result.apply_to_traffit == {}
    assert result.merged == {"city": "Poznań"}


def test_field_new_on_one_side_only_propagates():
    base: dict = {}
    result = three_way_merge(base, {"linkedin": "in/abc"}, {})
    assert result.apply_to_traffit == {"linkedin": "in/abc"}
    assert result.apply_to_nexus == {}
    assert result.merged == {"linkedin": "in/abc"}


def test_conflict_payload_encodes_missing_distinctly():
    # Pole dodane różnie po obu stronach przy pustej bazie → konflikt,
    # a base w payloadzie musi być odróżnialny od null.
    result = three_way_merge({}, {"x": 1}, {"x": 2})
    assert len(result.conflicts) == 1
    assert result.conflicts[0].base_value == MISSING_TOKEN
    assert result.conflicts[0].base_value is not None


# ── Nested paths / custom fields ─────────────────────────────────────────────


def test_partial_custom_field_patch_preserves_other_sids():
    # P0: częściowy payload custom fields nie może usunąć pozostałych kluczy.
    base = {"custom_fields": {"_100": "A", "_200": "B", "_300": "C"}}
    nexus = {"custom_fields": {"_100": "A", "_200": "B", "_300": "C"}}
    traffit = {"custom_fields": {"_200": "ZMIENIONE"}}
    result = three_way_merge(base, nexus, traffit)
    assert result.conflicts == []
    # Patch jest zagnieżdżonym merge-patchem, nie replacementem.
    assert result.apply_to_nexus == {"custom_fields": {"_200": "ZMIENIONE"}}
    assert result.merged["custom_fields"] == {
        "_100": "A",
        "_200": "ZMIENIONE",
        "_300": "C",
    }


def test_nested_conflict_reports_dotted_path():
    base = {"custom_fields": {"_9": "x"}}
    result = three_way_merge(
        base,
        {"custom_fields": {"_9": "n"}},
        {"custom_fields": {"_9": "t"}},
    )
    assert [c.field_path for c in result.conflicts] == ["custom_fields._9"]


def test_lists_are_atomic():
    base = {"languages": ["pl", "en"]}
    nexus = {"languages": ["pl", "en", "de"]}
    traffit = {"languages": ["pl", "en"]}
    result = three_way_merge(base, nexus, traffit)
    assert result.apply_to_traffit == {"languages": ["pl", "en", "de"]}
    # Rozbieżne listy → jeden konflikt na całą listę (brak stabilnych ID).
    divergent = three_way_merge(base, nexus, {"languages": ["pl"]})
    assert [c.field_path for c in divergent.conflicts] == ["languages"]


# ── Kontrakt ścieżek i ignorowane pola ───────────────────────────────────────


def test_paths_outside_contract_are_untouched():
    base = {"email": "a@x.pl", "internal_only": "sekret"}
    nexus = {"email": "a@x.pl", "internal_only": "zmieniony-lokalnie"}
    traffit = {"email": "b@x.pl", "internal_only": "zdalny-śmieć"}
    result = three_way_merge(base, nexus, traffit, contract_paths=["email"])
    assert result.apply_to_nexus == {"email": "b@x.pl"}
    assert result.apply_to_traffit == {}
    assert result.conflicts == []
    # Poza kontraktem: merged zachowuje bazę, brak patchy.
    assert result.merged["internal_only"] == "sekret"


def test_ignored_fields_and_their_children_are_skipped():
    base = {"audit": {"a": 1}, "email": "a@x.pl"}
    result = three_way_merge(
        base,
        {"audit": {"a": 2}, "email": "a@x.pl"},
        {"audit": {"a": 3}, "email": "a@x.pl"},
        ignored_fields=["audit"],
    )
    assert result.conflicts == []
    assert result.apply_to_nexus == {}
    assert result.apply_to_traffit == {}


# ── Helpery ──────────────────────────────────────────────────────────────────


def test_get_set_path_roundtrip_nested():
    target: dict = {}
    set_path(target, "custom_fields._55", {"v": 1})
    assert target == {"custom_fields": {"_55": {"v": 1}}}
    assert get_path(target, "custom_fields._55") == {"v": 1}
    assert get_path(target, "custom_fields._nope", MISSING) is MISSING


def test_canonical_json_and_hash_are_order_insensitive():
    a = {"b": 1, "a": {"y": 2, "x": 3}}
    b = {"a": {"x": 3, "y": 2}, "b": 1}
    assert canonical_json(a) == canonical_json(b)
    assert snapshot_hash(a) == snapshot_hash(b)


def test_flatten_preserves_explicit_empty_mapping():
    flat = flatten_paths({"custom_fields": {}})
    assert flat == {"custom_fields": {}}


def test_shape_flip_is_atomic():
    # Kolizja kształtu (scalar↔mapa na tej samej ścieżce) = schema drift —
    # pole porównywane atomowo, bez sprzecznego merged per-subpath.
    base = {"city": {"n": 1}}
    nexus = {"city": "Poznań"}
    traffit = {"city": {"n": 1}}
    result = three_way_merge(base, nexus, traffit)
    assert result.conflicts == []
    assert result.apply_to_traffit == {"city": "Poznań"}
    assert result.merged == {"city": "Poznań"}
    # Rozbieżny flip po obu stronach → jeden atomowy konflikt.
    divergent = three_way_merge(base, {"city": "Poznań"}, {"city": {"n": 2}})
    assert [c.field_path for c in divergent.conflicts] == ["city"]
    assert divergent.merged == {"city": {"n": 1}}


# ── Property-based (seeded, deterministyczne) ────────────────────────────────


def _random_snapshot(rng: random.Random) -> dict:
    # Shape-stable jak kanoniczna projekcja: pole skalarne nigdy nie staje
    # się mapą między snapshotami (zmiana typu = schema drift → quarantine,
    # testowana osobno w test_shape_flip_is_atomic).
    fields = ["email", "phone", "city", "source", "region"]
    snap: dict = {}
    for name in fields:
        roll = rng.random()
        if roll < 0.3:
            continue  # pole nieobecne
        if roll < 0.4:
            snap[name] = None  # jawny null
        else:
            snap[name] = rng.choice(["a", "b", "c", 1, 2, ["x"]])
    if rng.random() < 0.5:
        snap["custom_fields"] = {
            f"_{i}": rng.choice(["v1", "v2", None]) for i in range(rng.randint(1, 3))
        }
    return snap


def test_property_patches_only_reference_paths_present_in_source():
    # Inwariant P0: projekcja nie może wygenerować patcha dla ścieżki
    # nieobecnej w snapshocie strony źródłowej.
    rng = random.Random(42)
    for _ in range(300):
        base = _random_snapshot(rng)
        nexus = _random_snapshot(rng)
        traffit = _random_snapshot(rng)
        result = three_way_merge(base, nexus, traffit)
        for path in flatten_paths(result.apply_to_nexus):
            assert path in flatten_paths(traffit), (path, traffit)
        for path in flatten_paths(result.apply_to_traffit):
            assert path in flatten_paths(nexus), (path, nexus)


def test_property_merge_is_deterministic_and_preserves_untouched_fields():
    rng = random.Random(7)
    for _ in range(200):
        base = _random_snapshot(rng)
        nexus = _random_snapshot(rng)
        traffit = _random_snapshot(rng)
        first = three_way_merge(base, nexus, traffit)
        second = three_way_merge(base, nexus, traffit)
        assert first.merged == second.merged
        assert first.apply_to_nexus == second.apply_to_nexus
        assert first.apply_to_traffit == second.apply_to_traffit
        assert [c.field_path for c in first.conflicts] == [
            c.field_path for c in second.conflicts
        ]
        # Pole obecne w bazie i nietknięte po obu stronach nigdy nie ginie.
        base_flat = flatten_paths(base)
        nexus_flat = flatten_paths(nexus)
        traffit_flat = flatten_paths(traffit)
        merged_flat = flatten_paths(first.merged)
        for path, value in base_flat.items():
            n = nexus_flat.get(path, MISSING)
            t = traffit_flat.get(path, MISSING)
            untouched_n = n is MISSING or n == value
            untouched_t = t is MISSING or t == value
            if untouched_n and untouched_t:
                assert merged_flat.get(path) == value, path


def test_conflict_dataclass_is_frozen():
    conflict = FieldConflict("f", 1, 2, 3)
    try:
        conflict.field_path = "x"  # type: ignore[misc]
    except AttributeError:
        pass
    else:  # pragma: no cover
        raise AssertionError("FieldConflict powinien być frozen")
