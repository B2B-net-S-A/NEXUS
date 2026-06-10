"""Per-klient nadpisania treści paragrafów umowy B2B.

Niektórzy Klienci wymagają specyficznych zapisów (np. rozszerzony § 10 o
odpowiedzialności za sankcje Klienta będącego jednostką Skarbu Państwa). Zamiast
modyfikować szablon, podmieniamy wybrany paragraf w JUŻ wyrenderowanym dokumencie:

  - DOCX: ``apply_p10_docx`` usuwa akapity § 10 (od nagłówka „§ 10" do akapitu
    przed „§ 11") i wstawia akapity z override (zachowując styl/wyrównanie/wcięcia
    oryginału — patrz inspekcja: styl „Default", nagłówki CENTER+bold, klauzule
    JUSTIFY + wcięcie 0.25").
  - HTML (podgląd / PDF): ``apply_p10_html`` podmienia blok ``<h2>§ 10</h2>…``
    (do ``<h2>§ 11</h2>``) na HTML override.

Domyślny § 10 (dla pozostałych Klientów) NIE jest ruszany — brak override =
render bez zmian. Override dotyczy obecnie tylko języka PL (brak treści EN).

Rozszerzanie: dopisz Klienta w ``_CLIENT_DESCRIPTORS`` (match po znormalizowanej
nazwie) — treść § 10 obu Klientów jest identyczna poza opisem Klienta w ust. 6.
"""

from __future__ import annotations

import html
import re

# Blok = (kind, text). kind: "h" nagłówek §, "sub" podtytuł (bold, wyśrodkowany),
# "p" klauzula numerowana, "i" podpunkt a)/b) (wcięcie), "b" wypunktowanie.
Block = tuple[str, str]


def _norm(name: str) -> str:
    """Normalizuj nazwę klienta do dopasowania (lower, zwiń białe znaki)."""
    return re.sub(r"\s+", " ", (name or "").strip().lower())


# Znormalizowane wzorce nazw → opis Klienta wstawiany w ust. 6 § 10.
_CLIENT_DESCRIPTORS: tuple[tuple[tuple[str, ...], str], ...] = (
    (
        ("pfron", "rehabilitacji osób niepełnosprawnych"),
        "Państwowy Fundusz Rehabilitacji Osób Niepełnosprawnych tzw. PFRON",
    ),
    (
        ("centrum e-zdrowia", "e-zdrowia"),
        "Skarb Państwa – Centrum e-Zdrowia",
    ),
)

_BULLETS_7 = (
    "opóźnienia w rozpoczęciu świadczenia usług,",
    "nienależytego wykonania usług,",
    "nieusprawiedliwionej nieobecności Partnera,",
    "niezłożenia wymaganych dokumentów lub oświadczeń,",
    "naruszenia zasad poufności,",
    "użycia wadliwego, niekompletnego lub nieuprawnionego kodu źródłowego,",
    "odmowy współpracy przy przekazaniu obowiązków,",
    "innych zawinionych uchybień wpływających negatywnie na realizację usług.",
)


def _p10_blocks(client_descriptor: str) -> tuple[Block, ...]:
    """Zbuduj § 10 (Klauzule Antykonkurencyjne i Kary Umowne) dla Klienta.

    Treść identyczna dla wszystkich Klientów wymagających rozszerzonego § 10,
    poza opisem Klienta w ust. 6 (``client_descriptor``)."""
    blocks: list[Block] = [
        ("h", "§ 10"),
        ("sub", "Klauzule Antykonkurencyjne i Kary Umowne"),
        (
            "p",
            "1. W okresie obowiązywania Umowy oraz przez okres 12 (dwunastu) "
            "miesięcy po jej rozwiązaniu lub wygaśnięciu, Partner zobowiązuje się "
            "powstrzymać od:",
        ),
        (
            "i",
            "a) świadczenia usług bezpośrednio na rzecz Klienta B2BNET wskazanego "
            "w Załączniku nr 3, z pominięciem B2BNET., w zakresie objętym "
            "Segmentem Rynku,",
        ),
        (
            "i",
            "b) podejmowania zatrudnienia lub innej współpracy z Klientem B2BNET "
            "bez uprzedniej pisemnej zgody B2BNET.",
        ),
        (
            "p",
            "2. Zakaz konkurencji określony w ust. 1 nie obejmuje: a) współpracy "
            "z klientami B2BNET innymi niż Klienci wskazani w Załączniku nr 3, "
            "b) prowadzenia działalności gospodarczej lub świadczenia usług na "
            "rzecz podmiotów trzecich, które nie są Klientem Projektu, nawet jeśli "
            "działają w tym samym Segmencie Rynku, c) usług świadczonych poza "
            "Segmentem Rynku.",
        ),
        (
            "p",
            "3. W przypadku naruszenia przez Partnera postanowień § 8 (Informacje "
            "Poufne), Partner zapłaci B2BNET karę umowną w wysokości 50.000,00 zł "
            "(słownie: pięćdziesiąt tysięcy złotych).",
        ),
        (
            "p",
            "4. W przypadku naruszenia przez Partnera postanowień ust. 1 "
            "niniejszego paragrafu (Zakaz Konkurencji), Partner zapłaci B2BNET karę "
            "umowną w wysokości 100.000,00 zł (słownie: sto tysięcy złotych).",
        ),
        (
            "p",
            "5. Zapłata kary umownej nie wyłącza prawa B2BNET do dochodzenia "
            "odszkodowania przewyższającego wysokość zastrzeżonej kary na zasadach "
            "ogólnych Kodeksu Cywilnego.",
        ),
        (
            "p",
            "6. Postanowienia ust. 7–10 poniżej znajdują zastosowanie w przypadku, "
            "gdy działania lub zaniechania Partnera podczas świadczenia usług na "
            f"rzecz Klienta B2BNET ({client_descriptor}), skutkują nałożeniem na "
            "B2BNET przez Klienta kar umownych, odszkodowań lub innych sankcji "
            "finansowych.",
        ),
        (
            "p",
            "7. Partner ponosi wobec B2BNET odpowiedzialność finansową w pełnej "
            "wysokości za wszelkie sankcje nałożone na B2BNET przez Klienta B2BNET, "
            "jeżeli wynikają one z zawinionego działania lub zaniechania Partnera, "
            "w tym w szczególności z:",
        ),
    ]
    blocks.extend(("b", f"•  {item}") for item in _BULLETS_7)
    blocks.extend(
        [
            (
                "p",
                "8. W razie zaistnienia sytuacji, o których mowa powyżej, Partner "
                "zobowiązuje się do zwrotu na rzecz B2BNET pełnej kwoty zapłaconych "
                "przez B2BNET kar umownych, odszkodowań lub innych świadczeń "
                "sankcyjnych, w terminie 7 (siedmiu) dni od dnia doręczenia "
                "wezwania do zapłaty.",
            ),
            (
                "p",
                "9. W przypadku opóźnienia w zapłacie, Partner zobowiązany jest do "
                "zapłaty odsetek ustawowych za opóźnienie zgodnie z art. 481 "
                "Kodeksu cywilnego.",
            ),
            (
                "p",
                "10. Postanowienia ust. 6–9 nie ograniczają prawa B2BNET do "
                "dochodzenia od Partnera odszkodowania przewyższającego wysokość "
                "zapłaconych kar, jeżeli poniesiona szkoda przekracza wartość tych "
                "świadczeń.",
            ),
        ]
    )
    return tuple(blocks)


def override_for_client(
    client_name: str | None, language: str
) -> tuple[Block, ...] | None:
    """§ 10 override dla Klienta (lub None — render domyślny).

    Tylko PL (brak treści EN). Dopasowanie po znormalizowanej nazwie Klienta."""
    if not client_name or (language or "pl").lower().startswith("en"):
        return None
    n = _norm(client_name)
    for needles, descriptor in _CLIENT_DESCRIPTORS:
        if any(needle in n for needle in needles):
            return _p10_blocks(descriptor)
    return None


# ── Render HTML (podgląd / PDF) ──────────────────────────────────────────────


def render_p10_html(blocks: tuple[Block, ...]) -> str:
    """Wyrenderuj bloki § 10 do HTML (markup zgodny z resztą szablonu)."""
    out: list[str] = []
    for kind, text in blocks:
        esc = html.escape(text)
        if kind == "h":
            out.append(f"<h2>{esc}</h2>")
        elif kind == "sub":
            out.append(f"<p><strong>{esc}</strong></p>")
        elif kind == "i":
            out.append(f'<p style="margin-left:1.5em">{esc}</p>')
        elif kind == "b":
            out.append(f'<p style="margin-left:2.5em">{esc}</p>')
        else:  # "p"
            out.append(f"<p>{esc}</p>")
    return "\n".join(out) + "\n"


_HTML_P10_RE = re.compile(
    r"<h2>\s*§\s*10\s*</h2>.*?(?=<h2>\s*§\s*11\s*</h2>)", re.DOTALL
)


def apply_p10_html(rendered_html: str, blocks: tuple[Block, ...]) -> str:
    """Podmień blok § 10 w wyrenderowanym HTML na override (jeśli wzorzec trafi)."""
    new_html, n = _HTML_P10_RE.subn(
        lambda _m: render_p10_html(blocks), rendered_html, count=1
    )
    return new_html if n else rendered_html


# ── Render DOCX (post-processing wyrenderowanego dokumentu) ──────────────────


def apply_p10_docx(doc, blocks: tuple[Block, ...]) -> bool:
    """Podmień § 10 w wyrenderowanym dokumencie DOCX (python-docx ``Document``).

    Usuwa akapity od nagłówka „§ 10" do akapitu przed „§ 11" i wstawia akapity
    override przed „§ 11", zachowując styl/wyrównanie/wcięcia oryginału. Zwraca
    True, gdy podmieniono (False = nie znaleziono granic → render bez zmian)."""
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Inches

    paras = doc.paragraphs
    start = end = None
    for idx, p in enumerate(paras):
        t = (p.text or "").strip()
        if start is None and re.fullmatch(r"§\s*10", t):
            start = idx
        elif start is not None and re.fullmatch(r"§\s*11", t):
            end = idx
            break
    if start is None or end is None:
        return False

    base_style = paras[start].style
    # Czcionka (rozmiar/nazwa) z reprezentatywnych runów oryginału — by override
    # wyglądał spójnie z resztą umowy.
    head_font = _ref_font(paras[start])
    body_font = _ref_font(paras[start + 2]) if start + 2 < end else head_font
    anchor = paras[end]  # akapit „§ 11" — kotwica wstawiania

    for p in paras[start:end]:
        p._element.getparent().remove(p._element)

    for kind, text in blocks:
        np = anchor.insert_paragraph_before()
        np.style = base_style
        pf = np.paragraph_format
        run = np.add_run(text)
        if kind in ("h", "sub"):
            run.bold = True
            np.alignment = WD_ALIGN_PARAGRAPH.CENTER
            _apply_font(run, head_font)
        else:
            np.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
            pf.left_indent = Inches(0.5 if kind in ("i", "b") else 0.25)
            _apply_font(run, body_font)
    return True


def _ref_font(paragraph) -> tuple[object, object]:
    """(rozmiar, nazwa) pierwszego runu akapitu — do skopiowania na override."""
    if paragraph.runs:
        f = paragraph.runs[0].font
        return (f.size, f.name)
    return (None, None)


def _apply_font(run, font: tuple[object, object]) -> None:
    size, name = font
    if size is not None:
        run.font.size = size
    if name is not None:
        run.font.name = name
