"""Korpus czytnika poczty rozliczeń na bieżącym kodzie (Postgres).

Każdy przypadek z ``tests/corpus/rozliczenia/`` to prawdziwy błąd z poprawki:
maile z plikami, osoby i klienci, a w oczekiwaniach rodzaj, osoba i okres
zapisanego dokumentu. Test woła ``mailbox.run_once`` tak samo jak
``scripts/eval_reader.py``: w osobnej bazie ze schematem z ``Base.metadata``
(baza testów ma dane innych testów, a czytnik szuka osób po całej kartotece),
każdy przypadek w transakcji cofanej na końcu.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
from sqlalchemy.engine import make_url

from app.core.config import settings

pytestmark = pytest.mark.not_static

CORPUS = Path(__file__).resolve().parent / "corpus" / "rozliczenia"
RUNNER = Path(__file__).resolve().parent.parent / "scripts" / "eval_reader_runner.py"


def _runner():
    spec = importlib.util.spec_from_file_location("eval_reader_runner", RUNNER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def test_przypadki_rozliczen_przechodza_na_biezacym_kodzie() -> None:
    runner = _runner()
    cases = [c for c in runner.load_cases([str(CORPUS)]) if not c.get("znany_blad")]
    assert cases, "korpus rozliczeń jest pusty"
    base = make_url(settings.DATABASE_URL)
    url = base.set(database=f"{base.database}_korpus").render_as_string(
        hide_password=False
    )
    units = await runner.run_settlements(cases, url)
    failing = [unit for unit in units if not unit["ok"]]
    assert not failing, "\n".join(
        f"{u['id']} · {u['pole']}: oczekiwane {u['oczekiwane']}, jest {u['jest']}"
        + (f" ({u['blad']})" if u.get("blad") else "")
        for u in failing
    )
