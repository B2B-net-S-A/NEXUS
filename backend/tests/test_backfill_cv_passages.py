"""Skrypt wypełniający pasaże — własności bezpieczeństwa trybu pomiaru.

Tryb pomiaru ma być bezpieczny do uruchomienia na produkcji w dowolnym momencie:
nie zapisuje, nie płaci i nie dotyka indeksu. To nie jest deklaracja w docstringu
— to jest sprawdzane.
"""

import ast
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/backfill_cv_passages.py"


def _function(name: str) -> ast.AST:
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    return next(
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == name
    )


def _names_used(node: ast.AST) -> set[str]:
    used: set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Name):
            used.add(child.id)
        elif isinstance(child, ast.Attribute):
            used.add(child.attr)
        elif isinstance(child, (ast.Import, ast.ImportFrom)):
            module = getattr(child, "module", "") or ""
            used.add(module)
            for alias in child.names:
                used.add(alias.name)
    return used


def test_measure_never_embeds_and_never_writes():
    """Pomiar musi być darmowy i bezskutkowy.

    Gdyby liczył embeddingi, „sprawdzenie, ile to będzie" kosztowałoby tyle samo
    co zapis — a wtedy nikt by go nie uruchamiał przed decyzją.
    """

    used = _names_used(_function("measure"))

    forbidden = {
        "QdrantClient",
        "_voyage_embed_batch",
        "_voyage_embed",
        "replace_candidate_passages",
        "ensure_passages_collection",
        "upsert",
    }
    leaked = used & forbidden
    assert not leaked, (
        f"tryb pomiaru sięga po {leaked} — przestaje być darmowy i bezpieczny"
    )


def test_dry_run_is_the_default_mode():
    """`--commit` musi być świadomym wyborem, nie domyślnym zachowaniem."""

    main = _function("main")
    source = ast.get_source_segment(SCRIPT.read_text(encoding="utf-8"), main) or ""
    assert "if args.commit:" in source, (
        "zapis musi być gałęzią jawnie wybieraną; domyślnie ma iść pomiar"
    )


def test_iteration_uses_keyset_not_all():
    """`.all()` na całym zakresie to gigabajty w procesie dzielącym event loop.

    Scope to ~50 tys. wierszy z PEŁNYM tekstem CV — to jest ten sam błąd, który
    plan odnotował w `extractor_cv_llm`.
    """

    iterator = _function("_iter_candidates")
    source = ast.get_source_segment(SCRIPT.read_text(encoding="utf-8"), iterator) or ""
    assert ".limit(" in source, "brak stronicowania"
    assert "Candidate.id > cursor" in source, "brak kursora keyset"


def test_backfill_is_resumable():
    """Coolify restartuje kontener przy KAŻDYM pushu na main.

    Bieg bez kursora zaczynałby od zera po każdym wdrożeniu i przy odpowiednio
    częstych deployach mógłby nigdy nie dojść do końca — dokładnie ta pułapka
    trzymała latami lukę w plikach Traffita.
    """

    source = SCRIPT.read_text(encoding="utf-8")
    assert "--after-id" in source, "brak wznawiania"
    backfill = ast.get_source_segment(source, _function("backfill")) or ""
    assert "last_id" in backfill and "--after-id" in source, (
        "zapis musi raportować, od czego wznowić"
    )
