"""Rejestr mowi ZAWCZASU, ktorych rekrutacji nie da sie otworzyc.

Rejestr `/api/jobs` jest SWIADOMIE ogolnofirmowy - komentarz przy budowie
zapytania mowi wprost, ze pusty graf relacji nie moze zamienic go w "Brak
rekrutacji". Ale detal `/api/jobs/{id}` egzekwuje dokladny zakres klient-TAC,
wiec Delivery Lead bez przypisan widzial pelna liste i dostawal 403 przy
KAZDYM kliknieciu.

Komunikat po 403 jest dobry (audyt F-20 - "Rekrutacja istnieje, popros
o dodanie Cie do zespolu"), ale przychodzi PO kliknieciu. Dla DL bez przypisan
znaczy to dwadziescia klikniec i dwadziescia slepych zaulkow.

`can_open` nie ujawnia niczego nowego: te wiersze i tak sa na liscie.
Zmienia sie wylacznie moment, w ktorym uzytkownik sie dowiaduje.
"""

import ast
import pathlib

BACKEND = pathlib.Path(__file__).resolve().parents[1]


def _list_jobs_source() -> str:
    src = (BACKEND / "app/api/jobs.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    fn = next(
        n
        for n in ast.walk(tree)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
        and n.name == "list_jobs"
    )
    return ast.get_source_segment(src, fn) or ""


def test_list_marks_every_row_with_can_open():
    body = _list_jobs_source()
    assert '"can_open"' in body, (
        "wiersze nie niosa `can_open` - DL dowiaduje sie o braku dostepu "
        "dopiero po kliknieciu, przy kazdym wierszu osobno"
    )


def test_pairs_are_resolved_once_not_per_row():
    """Zapytanie o pary raz na strone, nie raz na wiersz.

    Przy 100 wierszach na strone wywolanie per wiersz to 100 zapytan
    o te sama odpowiedz.
    """
    body = _list_jobs_source()
    assert body.count("_delivery_lead_job_pairs(") == 1, (
        f"pary liczone {body.count('_delivery_lead_job_pairs(')} razy - "
        "powinny byc raz dla calej strony"
    )


def test_can_open_is_true_when_scope_does_not_apply():
    """`None` (admin, HoR, role spoza DL) znaczy BRAK ograniczenia, nie brak dostepu.

    Odwrocenie tego warunku wygasiloby caly rejestr adminowi - czyli
    dokladnie ta klasa, ktorej ta zmiana ma zapobiegac.
    """
    body = _list_jobs_source()
    i = body.index('"can_open"')
    expr = body[i : i + 260]
    assert "delivery_lead_pairs is None" in expr, (
        "brak galezi dla `None` - admin i HoR zobaczyliby caly rejestr jako niedostepny"
    )


def test_frontend_row_is_not_clickable_when_it_cannot_be_opened():
    """Sama flaga w API nic nie daje, jesli wiersz nadal udaje link.

    Asercja jest zwiazana z KONKRETNYM wyrazeniem, a nie z obecnoscia napisu
    gdziekolwiek w pliku: `pointer-events-none` wystepuje tu tez w innych
    miejscach, wiec "czy napis jest" przechodzilo mimo zdjecia go z tej
    galezi (sprawdzone kontrola negatywna).
    """
    tsx = (
        BACKEND.parent / "frontend/src/components/v2/pages/JobsListV2.tsx"
    ).read_text(encoding="utf-8")
    assert "can_open === false" in tsx, "front nie czyta flagi"
    assert "aria-disabled" in tsx, "czytnik ekranu nadal oglasza wiersz jako link"

    # wytnij wyrazenie warunkowe budujace className dla niedostepnego wiersza
    i = (
        tsx.index("can_open === false\n")
        if "can_open === false\n" in tsx
        else tsx.index("can_open === false")
    )
    window = tsx[i : i + 700]
    guarded = [
        seg
        for seg in window.split("can_open === false")
        if "pointer-events-none" in seg
    ]
    assert guarded, (
        "wiersz bez dostepu nie ma `pointer-events-none` w swojej galezi - "
        "nadal jest klikalny i uzytkownik i tak trafi w 403"
    )
