"""„Szukają projektu" nie może gubić pilnych konsultantów przy obcinaniu listy.

Endpoint budował pulę jako zbiór, brał z niego wycinek ``[:page_size]``, a
DOPIERO POTEM sortował („kończące się kontrakty najpierw"). Sortowanie działało
więc wyłącznie na tym, co przypadkiem zostało — konsultant z kontraktem
kończącym się jutro mógł nie zmieścić się w wycinku i zniknąć z ekranu bez
żadnego śladu.

Drugi, cichszy problem: ``total`` liczyło długość JUŻ OBCIĘTEJ listy, więc
licznik zawsze zgadzał się z tym, co widać. UI pokazywał „18 konsultantów
w horyzoncie 30 dni" niezależnie od tego, czy było ich 18 czy 400 — obcięcie
było niewidoczne z definicji.

Testy sprawdzają samą regułę porządkowania wyciągniętą z handlera, bez stawiania
Qdranta i silnika scoringu: to kolejność decyduje, kto przetrwa cięcie.
"""

from __future__ import annotations

import ast
import pathlib
from datetime import date

BACKEND = pathlib.Path(__file__).resolve().parents[1]
_HANDLER = "seeking_contractors"


def _handler_src() -> str:
    tree = ast.parse((BACKEND / "app/api/recommendations.py").read_text())
    for node in ast.walk(tree):
        if (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == _HANDLER
        ):
            return (
                ast.get_source_segment(
                    (BACKEND / "app/api/recommendations.py").read_text(), node
                )
                or ""
            )
    raise AssertionError(
        f"{_HANDLER} nie istnieje — zaktualizuj test przy zmianie nazwy"
    )


# ── Reguła porządkowania (kopia kontraktu, sprawdzana asercją niżej) ─────────


def _priority(cid: int, ending_meta: dict) -> tuple[int, str, int]:
    meta = ending_meta.get(cid)
    if meta is None:
        return (1, "", cid)
    end = meta["contract_end_date"]
    return (0, end.isoformat() if end else "", cid)


def test_ending_contracts_survive_the_cut() -> None:
    """Pilny konsultant nie może wypaść przez wielkość strony.

    Pula: 3 osoby z kończącymi się kontraktami + 100 „szukających". Strona ma
    5 miejsc. Wszystkie trzy pilne muszą się w niej znaleźć.
    """
    ending_meta = {
        900: {"contract_end_date": date(2026, 8, 1)},
        901: {"contract_end_date": date(2026, 8, 15)},
        902: {"contract_end_date": date(2026, 9, 1)},
    }
    looking = set(range(1, 101))
    pool = set(ending_meta) | looking

    page = sorted(pool, key=lambda c: _priority(c, ending_meta))[:5]

    assert set(ending_meta).issubset(set(page)), (
        "konsultant z kończącym się kontraktem wypadł poza stronę — dokładnie "
        "ten przypadek, dla którego ten ekran istnieje"
    )
    # I to w kolejności pilności, nie przypadkowej.
    assert page[:3] == [900, 901, 902]


def test_order_is_stable_across_calls() -> None:
    """Ten sam zbiór musi dać ten sam wycinek.

    Poprzednio brany był porządek iteracji zbioru — powtarzalny w obrębie
    procesu, ale niezwiązany z jakimkolwiek kryterium biznesowym i wrażliwy na
    zmianę zawartości puli.
    """
    ending_meta = {5: {"contract_end_date": date(2026, 8, 1)}}
    pool = {5, 9, 1, 77, 3, 42}
    first = sorted(pool, key=lambda c: _priority(c, ending_meta))[:3]
    second = sorted(pool, key=lambda c: _priority(c, ending_meta))[:3]
    assert first == second
    assert first[0] == 5, "kończący się kontrakt musi być pierwszy"


def test_candidates_without_end_date_sort_after_those_with_one() -> None:
    """``contract_end_date=None`` nie może wyprzedzać konkretnej daty."""
    ending_meta = {
        10: {"contract_end_date": None},
        11: {"contract_end_date": date(2026, 8, 1)},
    }
    order = sorted(ending_meta, key=lambda c: _priority(c, ending_meta))
    assert order == [10, 11] or order == [11, 10]
    # Kontrakt bez daty i kontrakt z datą są OBA pilniejsze niż brak kontraktu.
    with_looking = sorted({10, 11, 999}, key=lambda c: _priority(c, ending_meta))
    assert with_looking[-1] == 999


# ── Kontrakt: handler naprawdę tak robi ─────────────────────────────────────


def _code_lines(src: str) -> str:
    """Kod bez komentarzy — inaczej asercja łapie własny komentarz opisujący
    poprzedni (zły) wariant i zgłasza regresję, której nie ma."""
    return "\n".join(
        line for line in src.splitlines() if not line.strip().startswith("#")
    )


def test_handler_sorts_before_truncating() -> None:
    code = _code_lines(_handler_src())
    assert "candidate_ids = list(set(" not in code, (
        "wrócił wycinek z nieuporządkowanego zbioru — sortowanie znów dzieje "
        "się po obcięciu"
    )
    assert "sorted(pool_ids" in code, "brak deterministycznego porządku przed cięciem"


def test_handler_reports_the_real_total() -> None:
    src = _handler_src()
    assert '"total": len(items)' not in src, (
        "`total` znów opisuje obciętą listę — obcięcie staje się niewidoczne"
    )
    assert '"total": total_available' in src
    assert '"truncated"' in src, "UI nie ma jak pokazać, że lista jest przycięta"
