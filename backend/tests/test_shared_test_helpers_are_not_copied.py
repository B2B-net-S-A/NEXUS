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
from decimal import Decimal

import pytest

from tests._ast_calls import calls_in
from tests._contract_parties import pick_parties
from tests._ranking_anchor import RATE_CEILING, anchor_contract, ranking_anchor

TESTS_DIR = pathlib.Path(__file__).resolve().parent

# nazwa helpera -> moduł, z którego ma być importowany
SHARED_HELPERS: dict[str, str] = {
    "_pick_parties": "tests._contract_parties",
    "pick_parties": "tests._contract_parties",
    "_calls_in": "tests._ast_calls",
    "calls_in": "tests._ast_calls",
    "_ranking_anchor": "tests._ranking_anchor",
    "ranking_anchor": "tests._ranking_anchor",
    "_anchor_contract": "tests._ranking_anchor",
    "anchor_contract": "tests._ranking_anchor",
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


# Reguła kotwicy rankingu — dowód idzie przez PRAWDZIWY helper (import wyżej).
# Endpointy podmienione na atrapę, bo dowodzona własność dotyczy TEGO, którą
# liczbę z okna helper wybiera, a nie tego, czy baza ją zwróci.


class _FakeRankedResponse:
    def __init__(self, rows: list[dict]) -> None:
        self.status_code = 200
        self.text = ""
        self._rows = rows

    def json(self) -> list[dict]:
        return self._rows


class _FakeRankedClient:
    """Oba rankowane endpointy zwracają to samo okno."""

    def __init__(self, rows: list[dict]) -> None:
        self._rows = rows

    async def get(self, path: str, headers=None) -> _FakeRankedResponse:
        del path, headers
        return _FakeRankedResponse(self._rows)


def _window(*margins: float) -> list[dict]:
    return [{"total_monthly_margin": m} for m in margins]


@pytest.mark.asyncio
async def test_ranking_anchor_targets_the_cutoff_not_the_maximum() -> None:
    """Pojedyncza wartość odstająca NIE MOŻE windować kotwicy.

    To jest dokładnie ta własność, której brak wywrócił pierwszą wersję:
    `test_raw_analytics` zasiewa 99 999 999 dziennie w EUR (~9,4 mld po
    normalizacji i przewalutowaniu), więc kotwica liczona od MAKSIMUM nie
    mieściła się w `NUMERIC(16, 6)` kolumny stawki — zapis kończył się
    przepełnieniem, a nie czerwonym testem.
    """

    rows = _window(9_400_000_000.0, *([50.0] * 19))
    anchor = await ranking_anchor(_FakeRankedClient(rows), {}, limit=20)

    assert anchor == Decimal("1050"), "kotwica ma wyjść od progu odcięcia (50)"
    assert anchor < RATE_CEILING


@pytest.mark.asyncio
async def test_ranking_anchor_stays_minimal_when_the_window_is_not_full() -> None:
    """Niepełne okno = nic nie wypada, więc kotwica nie wypycha cudzych wierszy.

    Gdyby rosła i tutaj, naprawa jednego testu psułaby sąsiednie — a te pytają
    endpointy z domyślnym oknem 20 i konkurują marżami rzędu tysięcy.
    """

    rows = _window(*([500.0] * 5))
    assert await ranking_anchor(_FakeRankedClient(rows), {}, limit=20) == Decimal(
        "1000"
    )


def test_ranking_anchor_refuses_to_guess_the_window() -> None:
    """`limit` jest wymagany: endpoint bez `?limit=` zwraca 20, z jawnym — sto.

    Kotwica policzona na innym oknie niż to, o które test potem pyta, jest cicho
    za mała. Domyślna wartość zamieniłaby ten błąd w kolejną wędrującą flakę
    zamiast w błąd wywołania.
    """

    with pytest.raises(TypeError):
        ranking_anchor(_FakeRankedClient([]), {})


def test_anchor_contract_contributes_exactly_its_margin() -> None:
    """Kotwica wnosi JEDNĄ znaną liczbę i nie zakłada nowego kubełka roli.

    Noga kosztowa albo `job_id` sprawiłyby, że wołający musi odjąć coś jeszcze
    — a wtedy kotwica przestaje być przezroczysta dla asercji o walutach
    (`test_contract_analytics_fx`) i dla `role_totals` (`test_contract_analytics`).
    """

    contract = anchor_contract(candidate_id=1, client_id=2, margin=Decimal("1050"))

    assert contract.rate_client == Decimal("1050")
    assert contract.rate_candidate == Decimal("0")
    assert contract.currency == "PLN"
    assert contract.job_id is None
