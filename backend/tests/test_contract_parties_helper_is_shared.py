"""Strażnik: dawca stron umowy ma być JEDEN, nie kopiowany po plikach.

Ten helper żył w czterech kopiach. Dwie zostały naprawione (pomijają umowy po
usuniętym kandydacie, ``candidate_id IS NULL``), dwie zostały z pierwotną
regułą ``items[0]``. Skutek nie był taki, że „dwa pliki są słabsze": czerwień
WĘDROWAŁA. Podział na shardy jest round-robinem po plikach, więc dopisanie
dowolnego pliku testowego przestawia partycję i wystawia następną
nienaprawioną kopię — raz ``test_contract_amendments``, raz
``test_contract_framework_rate_schedule``. Wygląda to jak losowa flaka, a jest
deterministyczne.

Test patrzy w AST, nie w treść pliku: szuka DEFINICJI o tej nazwie, więc nie
wywróci się na własnym docstringu ani na komentarzu, który tę nazwę tylko
wspomina (tak robi ``test_contract_future_termination.py``, seedując własny
kontrakt — i to jest w porządku, bo w ogóle nie pożycza stron).
"""

import ast
import asyncio
import pathlib

import pytest

from tests._contract_parties import pick_parties

TESTS_DIR = pathlib.Path(__file__).resolve().parent
SHARED_MODULE = "tests._contract_parties"


def _local_helper_definitions(tree: ast.AST) -> list[str]:
    return [
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef))
        and node.name in {"_pick_parties", "pick_parties"}
    ]


@pytest.mark.parametrize(
    "path",
    sorted(p for p in TESTS_DIR.glob("test_*.py")),
    ids=lambda p: p.name,
)
def test_no_test_file_defines_its_own_parties_helper(path: pathlib.Path) -> None:
    tree = ast.parse(path.read_text())
    local = _local_helper_definitions(tree)
    assert not local, (
        f"{path.name} definiuje własną kopię {local} zamiast importować z "
        f"{SHARED_MODULE}. Kopia nie zostanie naprawiona razem z resztą, a "
        f"podział na shardy zdecyduje, kiedy to wybuchnie."
    )


def test_shared_helper_skips_contracts_whose_candidate_was_deleted() -> None:
    """Sam strażnik nic nie wart, jeśli wspólna reguła jest zła — sprawdź ją.

    Dowód idzie przez PRAWDZIWY helper (a nie przez powtórzoną tu logikę), więc
    zepsucie ``_contract_parties`` wywala ten test, zamiast go ominąć.
    """

    class _Resp:
        @staticmethod
        def json():
            return {
                "items": [
                    {
                        "candidate_id": None,
                        "client_id": 7,
                    },  # sierota po usuniętym kandydacie
                    {"candidate_id": 42, "client_id": 9},
                ]
            }

    class _Client:
        def __init__(self):
            self.url = None

        async def get(self, url, headers=None):
            self.url = url
            return _Resp()

    client = _Client()
    assert asyncio.run(pick_parties(client, {})) == (42, 9)
    assert "page_size=100" in client.url, (
        "przy page_size=1 jedyny zwrócony wiersz może być właśnie sierotą — "
        "helper oddałby None mimo pełnej bazy umów"
    )


def test_shared_helper_returns_none_when_every_contract_is_orphaned() -> None:
    class _Resp:
        @staticmethod
        def json():
            return {"items": [{"candidate_id": None, "client_id": 7}]}

    class _Client:
        async def get(self, url, headers=None):
            return _Resp()

    assert asyncio.run(pick_parties(_Client(), {})) is None
