"""Każda ścieżka tworząca kandydata musi zostawić ślad do zaindeksowania.

Rekord bez wektora nie jest „gorzej dopasowany" — on nie bierze udziału.
Rekomendacje, hybrid search i skan Marketplace czytają identyfikatory z
Qdranta, więc kandydat spoza kolekcji nie pojawi się w żadnym z nich. Lista
kandydatów pokazuje go normalnie, więc rekruter nie ma jak zauważyć braku.

Zmierzone na produkcji 2026-07-27: **46 945 z 55 217** kandydatów w kolekcji,
czyli 8 272 osoby istniały w bazie i nie istniały w matchingu. Cztery ścieżki
tworzyły kandydata bez jakiegokolwiek zapisu do indeksu: ``POST /candidates``,
import CSV, tworzenie z LinkedIna i importer Traffita — podczas gdy ``PATCH``
i ścieżki CV indeksowały zawsze.

Test jest strukturalny (AST), bo alternatywa — postawić Qdranta, Voyage'a i
przepuścić przez nie import — nie jest tym, co chroni przed regresją. Regresja
tutaj wygląda tak: ktoś dopisuje piątą ścieżkę tworzenia kandydata i nie wie,
że musi cokolwiek zaindeksować. Wtedy pomaga wyłącznie „ta funkcja nie woła
niczego z rodziny indeksującej".

Do 2026-08-21 ten test chodził WYŁĄCZNIE po ręcznie wypisanej liście czterech
ścieżek — czyli chronił dokładnie te, o których autor poprawki już wiedział,
i nie mógł złapać obiecanej „piątej ścieżki napisanej przez kogoś, kto nie zna
reguły". Nie była to hipoteza: dwie takie ścieżki istniały już w dniu poprawki
(kolejka zgłoszeń z lipca i import wsadowy z panelu), a suite był zielony
wyłącznie dlatego, że ich na liście nie było. Dlatego ścieżki są teraz
ODKRYWANE (każda funkcja, która konstruuje ``Candidate(...)`` i dodaje go do
sesji), a znane dziury stoją w jawnym, porównywanym NA RÓWNOŚĆ rejestrze
``_KNOWN_UNINDEXED`` — dopisanie nowej i naprawienie starej są wtedy tak samo
widoczne w diffie.
"""

from __future__ import annotations

import ast
import pathlib

BACKEND = pathlib.Path(__file__).resolve().parents[1]

# Wywołania, które kończą sprawę: albo embedują (pojedynczy rekord), albo
# zapisują trwałą intencję (ścieżki masowe — jedno wywołanie Voyage'a na wiersz
# zamieniłoby import 55 tys. kandydatów w 55 tys. sekwencyjnych calli).
_INDEXING_CALLS = {
    "schedule_or_embed_candidate",
    "embed_candidate",
    "record_bulk_reindex",
    "_record_new_candidate_index_intent",
}

# (plik, funkcja) — każda ścieżka, która tworzy kandydata.
_WRITE_PATHS = [
    ("app/api/candidates.py", "create_candidate"),
    ("app/api/candidates.py", "create_candidate_from_linkedin"),
    ("app/api/import_export.py", "import_candidates"),
    ("app/services/traffit/importer.py", "import_candidates"),
]


def _function_node(path: str, name: str) -> ast.AST | None:
    tree = ast.parse((BACKEND / path).read_text())
    for node in ast.walk(tree):
        if (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == name
        ):
            return node
    return None


def _calls_indexing(node: ast.AST) -> set[str]:
    found: set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Call):
            fn = child.func
            called = getattr(fn, "id", None) or getattr(fn, "attr", None) or ""
            if called in _INDEXING_CALLS:
                found.add(called)
    return found


def test_every_candidate_write_path_indexes() -> None:
    missing = []
    for path, func_name in _WRITE_PATHS:
        node = _function_node(path, func_name)
        assert node is not None, (
            f"{path}::{func_name} nie istnieje — jeśli ścieżkę przemianowano, "
            "zaktualizuj _WRITE_PATHS zamiast usuwać asercję"
        )
        if not _calls_indexing(node):
            missing.append(f"{path}::{func_name}")

    assert not missing, (
        "Te ścieżki tworzą kandydata, którego nikt nigdy nie zaindeksuje — "
        "rekord będzie na liście i nie będzie istniał w rekomendacjach, "
        "hybrid searchu ani w Marketplace:\n" + "\n".join(f"  {m}" for m in missing)
    )


# ── Odkrywanie ścieżek zapisu ────────────────────────────────────────────────

# Funkcje, które KONSTRUUJĄ kandydata i nie indeksują go. To są DZIURY, nie
# wyjątki — wpis tutaj znaczy „wiemy i jeszcze nie naprawione", nie „wolno tak".
# Porównanie jest na RÓWNOŚĆ w obie strony: nowa dziura wywala test, naprawiona
# dziura też (bo wpis trzeba wtedy usunąć, inaczej rejestr zaczyna kłamać).
_KNOWN_UNINDEXED = {
    # Kolejka zgłoszeń: /applications → „Utwórz kandydata" (POST
    # /api/application-submissions/{id}/resolve, action="create"). Najcieplejsi
    # kandydaci w bazie — ludzie, którzy sami zaaplikowali na ogłoszenie — i
    # żaden z nich nie trafia do matchingu.
    "app/api/application_submissions.py::resolve_application_submission",
    # Import wsadowy z panelu (POST /api/candidates/bulk-import). Ścieżka
    # masowa, więc lekarstwem jest `record_bulk_reindex`, nie embedowanie
    # w pętli (patrz `test_bulk_paths_do_not_embed_inline`).
    "app/api/candidates.py::bulk_import_candidates",
}


def _iter_source_files():
    for path in sorted((BACKEND / "app").rglob("*.py")):
        yield path


def _discover_candidate_write_paths() -> dict[str, set[str]]:
    """{"plik::funkcja" -> wywołania indeksujące} dla każdej ścieżki tworzącej
    kandydata.

    Wykrywanie: funkcja konstruuje ``Candidate(...)`` i gdziekolwiek w swoim
    ciele dodaje coś do sesji (``db.add`` / ``add_all``). To celowo szerokie
    sito — fałszywe trafienie kosztuje jedną linię w rejestrze, a przeoczenie
    kosztuje kandydata niewidocznego w całym matchingu.
    """
    found: dict[str, set[str]] = {}
    for path in _iter_source_files():
        source = path.read_text()
        try:
            tree = ast.parse(source)
        except SyntaxError:
            # Plik nieparsowalny dla TEGO interpretera (np. nowsza składnia
            # f-stringów). Milczące pominięcie może ukryć ścieżkę zapisu, więc
            # przepuszczamy tylko pliki, które kandydata w ogóle nie tworzą.
            assert "Candidate(" not in source, (
                f"{path} nie parsuje się, a konstruuje kandydata — nie da się "
                "sprawdzić, czy go indeksuje"
            )
            continue
        rel = str(path.relative_to(BACKEND))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            calls = {
                getattr(c.func, "id", None) or getattr(c.func, "attr", None) or ""
                for c in ast.walk(node)
                if isinstance(c, ast.Call)
            }
            if "Candidate" in calls and ({"add", "add_all"} & calls):
                found[f"{rel}::{node.name}"] = calls & _INDEXING_CALLS
    return found


def test_discovery_sees_the_known_good_paths() -> None:
    """Zabezpieczenie przed testem, który przechodzi, bo nic nie znalazł."""
    discovered = _discover_candidate_write_paths()
    assert discovered.get("app/api/candidates.py::create_candidate"), (
        "detektor przestał widzieć ścieżkę, o której WIEMY, że tworzy i "
        "indeksuje kandydata — reszta tego pliku jest wtedy pusta"
    )


def test_no_undeclared_unindexed_candidate_write_path() -> None:
    discovered = _discover_candidate_write_paths()
    unindexed = {name for name, calls in discovered.items() if not calls}

    undeclared = sorted(unindexed - _KNOWN_UNINDEXED)
    assert not undeclared, (
        "Nowa ścieżka tworzy kandydata, którego nikt nigdy nie zaindeksuje — "
        "rekord będzie na liście kandydatów i NIE BĘDZIE ISTNIAŁ w "
        "rekomendacjach, hybrid searchu ani w Marketplace. Dopisz wywołanie "
        "z rodziny indeksującej (`schedule_or_embed_candidate` dla pojedynczego "
        "rekordu, `record_bulk_reindex` dla ścieżki masowej):\n"
        + "\n".join(f"  {m}" for m in undeclared)
    )

    repaired = sorted(_KNOWN_UNINDEXED - unindexed)
    assert not repaired, (
        "Te ścieżki już indeksują — usuń je z `_KNOWN_UNINDEXED`, bo rejestr "
        "znanych dziur przestał opisywać rzeczywistość:\n"
        + "\n".join(f"  {m}" for m in repaired)
    )


def test_bulk_paths_do_not_embed_inline() -> None:
    """Import masowy nie może wołać Voyage'a per wiersz.

    ``record_bulk_reindex`` zapisuje intencję (INSERT), ``embed_candidate``
    woła API. Pomylenie ich zamienia import CSV w tyle sekwencyjnych calli, ile
    jest wierszy — i pojedynczy timeout kosztuje kandydata.
    """
    for path, func_name in [
        ("app/api/import_export.py", "import_candidates"),
        ("app/services/traffit/importer.py", "import_candidates"),
    ]:
        node = _function_node(path, func_name)
        assert node is not None
        calls = _calls_indexing(node)
        assert "embed_candidate" not in calls, (
            f"{path}::{func_name} embeduje inline — to jedno wywołanie Voyage'a "
            "na wiersz w pętli importu"
        )
        assert calls, f"{path}::{func_name} nie zapisuje żadnej intencji"


def test_bulk_recorder_computes_a_real_revision() -> None:
    """``entity_revision=0`` cicho gubiłby aktualizacje.

    ``_superseded`` uznaje zdarzenie za załatwione, gdy istnieje NOWSZA
    zaindeksowana rewizja — a ma ją każdy wcześniej zaindeksowany kandydat.
    Zdarzenie z rewizją 0 dla ZMIENIONEGO wiersza zostałoby więc odrzucone jako
    „superseded" i zmiana nigdy nie trafiłaby do indeksu.
    """
    src = (BACKEND / "app/services/index_outbox_service.py").read_text()
    tree = ast.parse(src)
    fn = next(
        n
        for n in ast.walk(tree)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
        and n.name == "record_bulk_reindex"
    )
    calls = {
        getattr(c.func, "id", None) or getattr(c.func, "attr", None) or ""
        for c in ast.walk(fn)
        if isinstance(c, ast.Call)
    }
    assert "desired_state" in calls, (
        "record_bulk_reindex przestało liczyć prawdziwą rewizję — zdarzenia dla "
        "zaktualizowanych wierszy będą odrzucane jako superseded"
    )
