"""Wspólny czytnik wywołań w AST — jedna reguła dla wszystkich strażników.

Ta reguła żyła w CZTERECH kopiach (`_calls_in` w test_ai_matches_eligibility,
test_cache_key_invalidation, test_retrieval_pool_and_batching,
test_talent_radar_search). Jedna została naprawiona, trzy zostały ze starą
semantyką — i to nie jest ta sama klasa długu, co czterokrotny helper danych
testowych. Tam rozjechana kopia dawała CZERWIEŃ. Tutaj daje ZIELEŃ na
zakazanym kodzie, więc nikt się nie dowiaduje, że strażnik przestał pilnować.

Dwie rzeczy, które ta reguła musi robić — obie wynikają z realnych pomyłek:

1. LICZYĆ OBIE FORMY WYWOŁANIA. `filter_eligible_candidates(...)` oraz
   `pipeline_eligibility.filter_eligible_candidates(...)` to to samo zdarzenie.
   Dopasowywanie samego ``ast.Name`` wiąże strażnika z jedną SKŁADNIĄ zamiast
   z własnością, której pilnuje — i psuje się w obie strony:

   * fałszywy PASS: dopisanie zakazanego wywołania w formie kwalifikowanej
     przechodzi asercję ``not in`` (odtworzone: dodanie
     ``match_score_cache.bulk_get_or_compute(...)`` do ``talent_radar_search``
     zostawiało test zielony);
   * fałszywy ALARM: bezpieczny refaktor „gołe wywołanie → kwalifikowane"
     zapala asercję ``in``, choć kod jest na miejscu. Ten kierunek jest
     bardziej korozyjny: czerwień naprawia ten, kto jest w środku refaktoru,
     a najtańszą naprawą jest osłabić albo skasować asercję. Strażnik umiera
     wtedy w dniu, w którym NIC nie było zepsute, i brakuje go w dniu, w którym
     coś jest.

2. ROZWINĄĆ JEDEN SKOK W HELPERY TEGO SAMEGO MODUŁU. Handler trasy zwykle
   deleguje: ``/recommendations`` woła filtr wewnątrz
   ``_recommend_candidates_core``, nie w udekorowanej funkcji. Asercja tylko na
   bezpośrednich wywołaniach raportowałaby lukę, której nie ma — i ta pułapka
   jest UZBROJONA DZIŚ, na niezmienionym kodzie.

Zwracany zbiór jest NADZBIOREM tego, co dawały stare kopie. Jeśli po podmianie
któraś asercja ``not in`` sczerwienieje, to jest sygnał DO SPRAWDZENIA, a nie
do wyciszenia: znaczy, że zakazane wywołanie naprawdę tam stoi.
"""

import ast
import pathlib

__all__ = ["calls_in"]

BACKEND = pathlib.Path(__file__).resolve().parent.parent


def _direct_calls(node: ast.AST) -> set[str]:
    """Nazwy funkcji wołanych bezpośrednio przez ``node``, w OBU formach."""
    names: set[str] = set()
    for n in ast.walk(node):
        if not isinstance(n, ast.Call):
            continue
        if isinstance(n.func, ast.Name):
            names.add(n.func.id)
        elif isinstance(n.func, ast.Attribute):
            names.add(n.func.attr)
    return names


def calls_in(module_rel: str, func_name: str) -> set[str]:
    """Wywołania wykonywane przez ``func_name`` w module ``module_rel``.

    Rozwija jeden poziom w helpery zdefiniowane w TYM SAMYM module.
    """
    tree = ast.parse((BACKEND / module_rel).read_text(encoding="utf-8"))
    by_name = {
        n.name: n
        for n in ast.walk(tree)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    target = by_name.get(func_name)
    # Czytelna asercja zamiast gołego `next()`: brak funkcji o tej nazwie to
    # zwykle zmiana nazwy w kodzie produkcyjnym, a `StopIteration` w środku
    # generatora nie mówi ANI której nazwy szukano, ANI w którym pliku.
    assert target is not None, f"{func_name} nie istnieje w {module_rel}"

    calls = _direct_calls(target)
    for name in list(calls):
        helper = by_name.get(name)
        if helper is not None and helper is not target:
            calls |= _direct_calls(helper)
    return calls
