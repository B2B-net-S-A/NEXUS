"""Strażnik: reguły współdzielone przez pliki testowe mają być JEDNE, nie kopiowane.

Dwa razy w tym repo ta sama reguła żyła w czterech kopiach, część naprawiona,
część nie — i za każdym razem skutek był inny, oba złe:

* ``_pick_parties`` (dawca stron umowy): rozjechane kopie dawały CZERWIEŃ, która
  WĘDROWAŁA. Podział na shardy jest round-robinem po plikach, więc dopisanie
  dowolnego pliku testowego przestawiało partycję i wystawiało następną
  nienaprawioną kopię. Wygląda jak losowa flaka, jest deterministyczne.
* ``_calls_in`` (czytnik wywołań w AST): rozjechane kopie dawały ZIELEŃ na
  zakazanym kodzie. Trzy z czterech liczyły wywołania wyłącznie przez
  ``ast.Name``, więc wywołanie kwalifikowane (``modul.funkcja(...)``) było dla
  nich niewidoczne — asercja ``not in`` przechodziła przy zakazanej rzeczy
  stojącej w kodzie. Ten kierunek jest groźniejszy, bo nikt się nie dowiaduje,
  że strażnik przestał pilnować.

Test patrzy w AST, nie w treść pliku: szuka DEFINICJI o danej nazwie, więc nie
wywraca się na własnym docstringu ani na komentarzu, który nazwę tylko
wspomina (tak robi ``test_contract_future_termination.py``, seedując własny
kontrakt — i to jest w porządku, bo w ogóle nie pożycza stron).

DODAJĄC nowy wspólny helper — dopisz go do ``SHARED_HELPERS``. Rejestr jest
tym, co odróżnia strażnika od jednorazowej łatki: bez wpisu następna kopia
przejdzie niezauważona, dokładnie tak jak ``_calls_in`` przeszedł obok
strażnika napisanego wyłącznie pod ``_pick_parties``.
"""

import ast
import pathlib

import pytest

from tests._ast_calls import calls_in
from tests._contract_parties import pick_parties

TESTS_DIR = pathlib.Path(__file__).resolve().parent

# nazwa helpera -> moduł, z którego ma być importowany
SHARED_HELPERS: dict[str, str] = {
    "_pick_parties": "tests._contract_parties",
    "pick_parties": "tests._contract_parties",
    "_calls_in": "tests._ast_calls",
    "calls_in": "tests._ast_calls",
}


def _local_definitions(tree: ast.AST) -> list[str]:
    return [
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef))
        and node.name in SHARED_HELPERS
    ]


@pytest.mark.parametrize(
    "path",
    sorted(p for p in TESTS_DIR.glob("test_*.py")),
    ids=lambda p: p.name,
)
def test_no_test_file_defines_a_shared_helper(path: pathlib.Path) -> None:
    tree = ast.parse(path.read_text())
    local = _local_definitions(tree)
    assert not local, (
        f"{path.name} definiuje własną kopię {local} zamiast importować z "
        f"{ {n: SHARED_HELPERS[n] for n in local} }. Kopia nie zostanie "
        f"naprawiona razem z resztą, a podział na shardy zdecyduje, kiedy to "
        f"wybuchnie — albo, gorzej, kopia po cichu przestanie pilnować."
    )


# ── Same reguły też muszą być sprawdzone ────────────────────────────────────
# Strażnik zakazujący kopii jest bezwartościowy, jeśli JEDYNA pozostała kopia
# ma złą regułę. Dowód idzie przez PRAWDZIWE helpery (import wyżej), a nie
# przez logikę powtórzoną w tym pliku — inaczej zepsucie wspólnego modułu
# ominęłoby ten test zamiast go zapalić.


# Reguła helpera zmieniła się 2026-08-25 (PR #1259, blokada duplikatu
# kontraktora): dawca stron NIE MOŻE już żerować na istniejących umowach —
# para z umową w żywym statusie jest z definicji bezużyteczna (POST → 409
# duplicate_contractor). Dowodzimy więc nowej własności: każde wywołanie
# seeduje świeżą, istniejącą w bazie parę, a dwa wywołania nigdy nie dzielą
# stron. Testy są async na wspólnej pętli — `asyncio.run` w teście sync
# tworzyłby DRUGĄ pętlę wokół współdzielonego engine'a (błędy puli połączeń).


@pytest.mark.asyncio
async def test_pick_parties_seeds_a_fresh_usable_pair() -> None:
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate
    from app.models.client import Client

    candidate_id, client_id = await pick_parties(None, {})
    async with AsyncSessionLocal() as db:
        assert await db.get(Candidate, candidate_id) is not None
        assert await db.get(Client, client_id) is not None


@pytest.mark.asyncio
async def test_pick_parties_returns_distinct_pairs_per_call() -> None:
    """Wspólna para między wołającymi wskrzesiłaby wędrującą czerwień:
    pierwszy test zakłada umowę, drugi na tej samej parze dostaje 409."""
    first = await pick_parties(None, {})
    second = await pick_parties(None, {})
    assert first[0] != second[0]
    assert first[1] != second[1]


def test_calls_in_counts_both_call_forms(tmp_path, monkeypatch) -> None:
    """Gołe i kwalifikowane wywołanie muszą liczyć się TAK SAMO.

    To jest dokładnie ta własność, której brakowało trzem kopiom: wstawienie
    zakazanego wywołania w formie ``modul.funkcja(...)`` przechodziło asercję
    ``not in``, bo stara reguła widziała wyłącznie ``ast.Name``.
    """
    module = tmp_path / "probe.py"
    module.write_text(
        "def target():\n    bare_call()\n    some_module.qualified_call()\n"
    )
    monkeypatch.setattr("tests._ast_calls.BACKEND", tmp_path)
    found = calls_in("probe.py", "target")
    assert "bare_call" in found
    assert "qualified_call" in found, (
        "wywołanie kwalifikowane niewidoczne — asercje `not in` przepuszczą "
        "zakazany kod, a asercje `in` zapalą się na bezpiecznym refaktorze"
    )


def test_calls_in_follows_one_hop_into_same_module_helpers(
    tmp_path, monkeypatch
) -> None:
    """Handler trasy zwykle deleguje — bez tego skoku strażnik zgłasza lukę, której nie ma."""
    module = tmp_path / "probe.py"
    module.write_text(
        "def helper():\n    the_thing_we_guard()\n\ndef handler():\n    helper()\n"
    )
    monkeypatch.setattr("tests._ast_calls.BACKEND", tmp_path)
    assert "the_thing_we_guard" in calls_in("probe.py", "handler")


def test_calls_in_names_the_missing_function(tmp_path, monkeypatch) -> None:
    """Brak funkcji ma dać czytelny komunikat, nie StopIteration z wnętrza generatora."""
    module = tmp_path / "probe.py"
    module.write_text("def other():\n    pass\n")
    monkeypatch.setattr("tests._ast_calls.BACKEND", tmp_path)
    with pytest.raises(AssertionError, match="nie_ma_takiej.*probe.py"):
        calls_in("probe.py", "nie_ma_takiej")
