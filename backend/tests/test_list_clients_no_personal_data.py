"""``scripts.list_clients`` i jego wywołanie z CI nie wypisują danych osób
(runda 6 audytu, W2).

Wyjście skryptu trafia do logu GitHub Actions (``coolify-ops.yml`` →
``client-lookup``), a repo jest PUBLICZNE — log widzi każdy. Do 26.09.2026
``--with-links`` drukował nazwisko konsultanta przy kontrakcie, nazwę Partnera
umowy B2B i tytuł zamówienia (tytuł niesie zwykle imię i nazwisko), a krok
sprzątający przy porażce wypisywał surowe wykonania do 1500 znaków.
Zostają identyfikatory, statusy i liczby — to wystarcza, żeby wskazać wiersz
do poprawki.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from scripts import list_clients

_WORKFLOW = Path(__file__).resolve().parents[2] / ".github/workflows/coolify-ops.yml"


class _Rows:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _FakeSession:
    """Zwraca po jednym wierszu na zapytanie, z wartością „SECRET_<kolumna>”."""

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def execute(self, stmt):
        row = []
        for column in stmt.selected_columns:
            name = getattr(column, "key", None) or getattr(column, "name", "col")
            if name in {
                "id",
                "client_id",
                "contract_id",
                "job_id",
                "order_group_id",
                "candidate_id",
            }:
                row.append(7)
            else:
                row.append(f"SECRET_{name}")
        return _Rows([tuple(row)])


async def test_with_links_prints_ids_not_people(monkeypatch, capsys):
    monkeypatch.setattr(list_clients, "AsyncSessionLocal", _FakeSession)

    await list_clients.print_links([7])

    out = capsys.readouterr().out
    for leaked in (
        "SECRET_lastname",
        "SECRET_name",
        "SECRET_partner_name",
        "SECRET_title",
    ):
        assert leaked not in out, f"{leaked} w wyjściu:\n{out}"
    # identyfikatory i liczby zostają — po nich wskazuje się wiersz do poprawki
    assert "contract=7" in out
    assert "b2b=7" in out
    assert "order=7" in out


def _cleanup_run(job: str) -> str:
    workflow = yaml.safe_load(_WORKFLOW.read_text(encoding="utf-8"))
    steps = workflow["jobs"][job]["steps"]
    step = next(s for s in steps if s.get("name") == "Skasuj zadanie jednorazowe")
    return step["run"]


def test_failed_lookup_cleanup_does_not_dump_raw_executions():
    for job in ("lookup", "receipts"):
        run = _cleanup_run(job)
        assert "[0:1500]" not in run, (
            f"{job}: surowe wykonanie (do 1500 znaków) w publicznym logu Actions"
        )
        assert '(.message // "") | .[0:' not in run, job
