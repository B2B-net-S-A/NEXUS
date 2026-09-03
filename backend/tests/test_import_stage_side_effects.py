"""Skutki uboczne dla etapów z importu — wąsko i bez maili.

Import pisze do `candidate_stages` surowym SQL-em, więc dotąd nie odpalał
ŻADNEJ automatyzacji poza kolejką kontaktu. Skutek: automatyzacje pipeline'u
dotyczyły 0,4% ruchu (131 z 32 872 w 90 dniach).

Najważniejszy test w tym pliku to ten, który pilnuje, czego tu NIE MA:
`maybe_schedule` wysyła maile do kandydatów, a `dispatch` sprawdza wyłącznie,
czy bieżący etap pary to nadal `rejected` — historyczne odrzucenia ten warunek
PRZECHODZĄ. Włączenie wysłałoby maile do tysięcy osób odrzuconych miesiące
temu, i to jest nieodwracalne.
"""

from __future__ import annotations

import ast
import pathlib

from app.services.traffit.stage_side_effects import apply_imported_stage_side_effects

_MODULE = (
    pathlib.Path(__file__).resolve().parents[1]
    / "app"
    / "services"
    / "traffit"
    / "stage_side_effects.py"
)


def _called_names() -> set[str]:
    """Nazwy WYWOŁYWANE w module — czytane z AST, nie z tekstu.

    Grep po treści złapałby też wzmianki w docstringu, czyli test przechodziłby
    albo padał na komentarzu zamiast na kodzie.
    """
    tree = ast.parse(_MODULE.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name):
                names.add(func.id)
            elif isinstance(func, ast.Attribute):
                names.add(func.attr)
    return names


def test_rejection_emails_are_never_triggered_from_the_import_path():
    """Jedyny nieodwracalny skutek z tej rodziny — musi zostać poza importem."""
    called = _called_names()
    assert "maybe_schedule" not in called, (
        "Import odpalałby maile odrzucające. `dispatch` sprawdza tylko, czy "
        "BIEŻĄCY etap to nadal `rejected`, więc historyczne odrzucenia "
        "przechodzą — poszłyby maile do osób odrzuconych miesiące temu."
    )


def test_contract_drafts_stay_out_until_the_409s_are_decided():
    """`ensure_b2b_employment_draft` odmawia na dwóch klasach danych historycznych."""
    assert "ensure_b2b_employment_draft" not in _called_names()


def test_only_the_idempotent_effects_are_wired():
    called = _called_names()
    assert "on_candidate_stage_change" in called
    assert "auto_add_on_cv_sent" in called


async def test_disabled_by_default_does_nothing(monkeypatch):
    """Domyślnie wyłączone — włączenie ma być decyzją, nie skutkiem deployu."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "TRAFFIT_IMPORT_SIDE_EFFECTS_ENABLED", False)

    applied = await apply_imported_stage_side_effects(
        db=None,  # nie zostanie dotknięte — guard jest przed użyciem sesji
        rows=[{"candidate_id": 1, "job_id": 2, "stage_legacy_enum": "cv_sent"}],
    )

    assert applied == {"risk": 0, "talent_pool": 0}


async def test_empty_batch_is_a_no_op(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "TRAFFIT_IMPORT_SIDE_EFFECTS_ENABLED", True)

    assert await apply_imported_stage_side_effects(db=None, rows=[]) == {
        "risk": 0,
        "talent_pool": 0,
    }


def test_importer_calls_the_hook_after_the_stage_commit():
    """Skutek ma być ZA commitem — inaczej jego awaria cofa zaimportowany etap."""
    importer = (
        pathlib.Path(__file__).resolve().parents[1]
        / "app"
        / "services"
        / "traffit"
        / "importer.py"
    ).read_text(encoding="utf-8")

    tree = ast.parse(importer)
    flush = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "_flush_stage_batch"
    )
    lines_with_commit = [
        node.lineno
        for node in ast.walk(flush)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "commit"
    ]
    hook_lines = [
        node.lineno
        for node in ast.walk(flush)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "apply_imported_stage_side_effects"
    ]
    assert hook_lines, "Hook nie jest wołany z `_flush_stage_batch`."
    assert min(hook_lines) > min(lines_with_commit), (
        "Hook stoi PRZED commitem etapów — jego awaria cofnęłaby import."
    )


async def test_the_hook_can_raise_so_the_callers_guard_is_not_dead(monkeypatch):
    """Zewnętrzny `try/except` w importerze NIE jest martwy.

    Hook łapie własne wyjątki per wiersz, ale parsowanie payloadu i zbiorczy
    odczyt ofert stoją POZA tamtymi blokami. Zniekształcony wsad przechodzi
    tędy — i dlatego wywołujący musi mieć własny guard.
    """
    import pytest

    from app.core.config import settings

    monkeypatch.setattr(settings, "TRAFFIT_IMPORT_SIDE_EFFECTS_ENABLED", True)

    with pytest.raises(Exception):
        await apply_imported_stage_side_effects(
            db=None,
            rows=[{"job_id": 1, "stage_legacy_enum": "cv_sent"}],  # brak candidate_id
        )
