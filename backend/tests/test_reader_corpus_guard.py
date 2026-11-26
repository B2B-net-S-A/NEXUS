"""Korpus czytników (``tests/corpus/``): porządek przypadków i odczyt CV na HEAD.

Przypadki są prawdziwymi błędami czytników z poprawek (rozliczenia, CV), zapisanymi
tak, żeby ``scripts/eval_reader.py`` liczył je na dowolnej rewizji. Ten strażnik
pilnuje, żeby korpus w repo był zanonimizowany (repo jest publiczne) i żeby każdy
przypadek CV przechodził na bieżącym kodzie; przypadki rozliczeń liczy
``test_reader_corpus_settlements_db.py`` na bazie.
"""

from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.static

CORPUS = Path(__file__).resolve().parent / "corpus"
RUNNER = Path(__file__).resolve().parent.parent / "scripts" / "eval_reader_runner.py"

# Domeny fikcyjne i domeny klientów, które czytnik rozpoznaje z rejestru
# ``known_clients`` (adres koordynatora u klienta to nie dana osobowa).
_FICTIONAL = re.compile(r"(^|\.)example\.(com|pl|org)$")
_PUBLIC_MAIL = {
    "gmail.com",
    "googlemail.com",
    "wp.pl",
    "o2.pl",
    "onet.pl",
    "interia.pl",
}
_EMAIL = re.compile(r"[\w.+-]+@([\w-]+(?:\.[\w-]+)+)")
_PESEL = re.compile(r"(?<!\d)\d{11}(?!\d)")
_IBAN = re.compile(r"\bPL\d{26}\b")


def _runner():
    spec = importlib.util.spec_from_file_location("eval_reader_runner", RUNNER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _readers() -> dict:
    return json.loads((CORPUS / "czytniki.json").read_text(encoding="utf-8"))[
        "czytniki"
    ]


def _cases(reader: str) -> list[dict]:
    return _runner().load_cases([str(CORPUS / reader)])


def _client_domains() -> set[str]:
    from app.services.order_policies import known_clients

    return (
        set(known_clients.KNOWN_SENDER_DOMAINS)
        | set(getattr(known_clients, "SHARED_SENDER_DOMAINS", {}))
        | set(getattr(known_clients, "SUBDOMAIN_SENDER_DOMAINS", ()))
    )


@pytest.mark.parametrize("reader", sorted(_readers()))
def test_przypadki_maja_id_poprawke_i_opis(reader: str) -> None:
    cases = _cases(reader)
    assert cases, f"korpus {reader} jest pusty"
    ids = [case.get("id") for case in cases]
    assert all(ids), "przypadek bez id"
    assert len(ids) == len(set(ids)), (
        f"powtórzone id: {sorted({i for i in ids if ids.count(i) > 1})}"
    )
    for case in cases:
        assert re.fullmatch(r"[0-9a-f]{7,40} #\d+", case.get("poprawka") or ""), case[
            "id"
        ]
        assert (case.get("opis") or "").strip(), f"{case['id']}: brak opisu"


@pytest.mark.parametrize("reader", sorted(_readers()))
def test_korpus_w_repo_jest_zanonimizowany(reader: str) -> None:
    """Adresy tylko fikcyjne, publiczne skrzynki z fikcyjną nazwą albo domeny klientów
    z rejestru; bez numerów PESEL i kont. Pełne przypadki z produkcji leżą
    w ``~/.nexus-staging/corpus/`` na laptopie."""

    allowed = _client_domains() | _PUBLIC_MAIL
    problems = []
    for path in sorted((CORPUS / reader).rglob("*.json")):
        text = path.read_text(encoding="utf-8")
        for domain in {m.group(1).lower() for m in _EMAIL.finditer(text)}:
            known = domain in allowed or any(domain.endswith("." + d) for d in allowed)
            if not (_FICTIONAL.search(domain) or known):
                problems.append(f"{path.name}: domena {domain}")
        if _PESEL.search(text):
            problems.append(f"{path.name}: 11 cyfr jak PESEL")
        if _IBAN.search(text):
            problems.append(f"{path.name}: numer konta")
    assert not problems, "\n".join(problems)


def test_rejestr_czytnikow_wskazuje_istniejace_pliki() -> None:
    root = CORPUS.parent.parent.parent
    for name, spec in _readers().items():
        assert spec["pola"], name
        for pattern in spec["sciezki"]:
            if "*" in pattern:
                base = root / pattern.split("*")[0]
                assert base.exists(), f"{name}: {pattern}"
            else:
                assert (root / pattern).is_file(), f"{name}: {pattern}"


def test_przypadki_cv_przechodza_na_biezacym_kodzie() -> None:
    runner = _runner()
    cases = [case for case in _cases("cv") if not case.get("znany_blad")]
    failing = [unit for unit in runner.run_cv(cases) if not unit["ok"]]
    assert not failing, "\n".join(
        f"{u['id']} · {u['pole']}: oczekiwane {u['oczekiwane']}, jest {u['jest']}"
        + (f" ({u['blad']})" if u.get("blad") else "")
        for u in failing
    )
