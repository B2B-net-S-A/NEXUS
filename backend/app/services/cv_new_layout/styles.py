"""Arkusz stylów układu „Nowe CV” (A4, WeasyPrint).

Wersja końcowa makiety Artura z 20–22.11.2026: nagłówek = samo logo, stopka =
wyśrodkowane dane spółki, etykiety sekcji czerwone z linią do prawej krawędzi,
umiejętności z pionowymi kreskami, Poppins + Source Sans 3, wieniec przy dyplomie.
Wolne miejsce strony 1 rozkłada się równo między sekcje.

Runda 37 (Artur 25.11.2026): nagłówek T2 (stanowisko duże czerwone, cienka linia,
imię i nazwisko), wyróżnik z wieńcem bez ramki, stały odstęp między sekcjami
(`SECTION_GAP`), część luzu strony w środek sekcji (`inner_mm`), zdania
„Dlaczego” rosną z pismem strony.
"""

from __future__ import annotations

from app.services.cv_new_layout.assets import LOGO_PATH, LOGO_RATIO, font_face_css

BRAND = "#E73748"
BRAND_DEEP = "#B4232F"
BRAND_TEXT = "#C42536"
INK = "#141414"
BODY = "#373535"
SOFT = "#5C5A55"
SOFT2 = "#6F6A6A"
RULE = "#D9D6CA"
PAST = "#CFC7BD"
LINE = "#D9D4D4"

# Geometria strony w mm (nagłówek i stopka jak w makiecie: str. 1 wyższe, dalej niższe).
PAGE_W, PAGE_H = 210.0, 297.0
SIDE = 15.0
HEAD_1, HEAD_N = 20.0, 13.0
FOOT_1, FOOT_N = 9.0, 8.0
TOP_1 = HEAD_1 + 3.0  # treść str. 1 zaczyna się 3 mm pod nagłówkiem
TOP_N = HEAD_N + 4.0
BOTTOM = FOOT_N + 4.0
# pole treści strony 1; pół milimetra zapasu, bo treść równa polu co do ułamka bywa łamana
PAGE1_HEIGHT = PAGE_H - TOP_1 - BOTTOM - 0.5
# stały odstęp nad każdą sekcją strony 1 — „nie może się zlewać” (Artur 25.11.2026)
SECTION_GAP = 5.5


def _logo_box(head: float, logo_h: float) -> str:
    return (
        f"content:'';width:{logo_h * LOGO_RATIO + 1:.2f}mm;vertical-align:top;"
        f"background:url('{LOGO_PATH.as_uri()}') no-repeat 0 {head * 0.28:.2f}mm/auto {logo_h}mm"
    )


def _footer_box(footer: str, foot: float) -> str:
    text = footer.replace("\\", "\\\\").replace("'", "\\'")
    return (
        f"content:'{text}';vertical-align:bottom;padding-bottom:{foot * 0.32:.2f}mm;"
        f"font:500 5.6pt Poppins,sans-serif;letter-spacing:.01em;color:{SOFT}"
    )


def _inner(inner_mm: float) -> str:
    """Luz strony w środku sekcji: odstępy zdań, wierszy umiejętności, osi i Edukacji."""
    if inner_mm <= 0:
        return ""
    return (
        f"ul.why li{{padding:{2.1 + inner_mm * 0.9:.2f}mm 0}}"
        f".s1r{{padding:{0.9 + inner_mm * 0.45:.2f}mm 0}}"
        f".p1 h2{{margin-bottom:{2.6 + inner_mm * 0.5:.2f}mm}}"
        f".axis{{margin:{inner_mm * 0.9:.2f}mm 0}}"
        f".cl .cli{{padding:{0.9 + inner_mm * 0.45:.2f}mm 0}}"
        f".edi{{margin-bottom:{1.6 + inner_mm * 0.45:.2f}mm}}"
    )


def stylesheet(
    *, font_pt: float, footer: str, block_gap_mm: float = 0.0, inner_mm: float = 0.0
) -> str:
    """CSS całego dokumentu. `block_gap_mm` = wolne miejsce strony 1 podzielone
    równo między sekcje (Artur 20.11: pusty dół wygląda brzydko). Liczone z pomiaru,
    nie flexem: `justify-content: space-between` w kolumnie WeasyPrint 70 rozciąga
    bloki zamiast rozsuwać."""
    return f"""{font_face_css()}
@page{{size:A4;margin:{TOP_N}mm {SIDE}mm {BOTTOM}mm;
 @top-left{{{_logo_box(HEAD_N, 4.8)}}}
 @bottom-center{{{_footer_box(footer, FOOT_N)}}}}}
@page:first{{margin-top:{TOP_1}mm;
 @top-left{{{_logo_box(HEAD_1, 7.2)}}}
 @bottom-center{{{_footer_box(footer, FOOT_1)}}}}}
*{{box-sizing:border-box}}
html,body{{margin:0;padding:0}}
body{{font-family:Poppins,sans-serif;color:{BODY};font-size:8.6pt;line-height:1.32}}
b{{font-weight:600}}
ul{{margin:0;padding-left:4mm;list-style:none}}li{{margin:0 0 .6mm;position:relative}}
li::before{{content:'';position:absolute;left:-3.4mm;top:.48em;width:1.1mm;height:1.1mm;border-radius:50%;background:{BRAND}}}
table{{border-collapse:collapse;width:100%}}
h1,h2{{break-after:avoid}}
.cap{{font-size:7.8pt;color:{SOFT};margin-top:1mm}}

/* ---------- strona 1 ---------- */
.p1{{font-family:'Source Sans 3',Poppins,sans-serif;font-size:{font_pt}pt}}
.p1>.blk{{display:flow-root;margin-top:{block_gap_mm:.2f}mm;padding-top:{SECTION_GAP}mm}}
.p1 h2{{display:flex;align-items:center;margin:0 0 2.6mm;padding:0;border:0;color:{BRAND};
 text-transform:uppercase;letter-spacing:.1em;font:600 8.4pt Poppins,sans-serif}}
.p1 h2 span{{background:{BRAND};color:#fff;padding:.9mm 2.8mm;border-radius:1.2mm}}
.p1 h2::after{{content:'';flex:1;height:0;margin-left:2.4mm;border-top:.3mm solid {BRAND}}}
.trow{{display:flex;flex-wrap:wrap;align-items:baseline;justify-content:space-between}}
.trow .tcol{{flex:1 1 100mm;margin-right:6mm}}
h1.title{{font:600 17pt/1.15 Poppins,sans-serif;color:{BRAND};margin:0;letter-spacing:-.01em}}
h1.title .nm{{white-space:nowrap}}
.pills{{display:flex;flex-wrap:wrap;justify-content:flex-end}}
.pill{{display:inline-block;margin-left:1.4mm;border:1px solid {BRAND};color:{BRAND};border-radius:5mm;
 padding:.45mm 2.4mm;font:500 .86em Poppins,sans-serif;white-space:nowrap}}
.pill b{{font-weight:800}}
/* Trzy zdania bez punktorów, oddzielone cienkimi liniami (Artur 23.11.2026, W1) */
ul.why{{list-style:none;margin:0;padding:0}}
ul.why li{{position:relative;margin:0;padding:2.1mm 0;font-size:{font_pt * 1.04:.2f}pt;line-height:1.38;color:#2b2926;
 border-top:.3mm solid {RULE}}}
ul.why li:last-child{{border-bottom:.3mm solid {RULE}}}
ul.why li::before{{display:none}}
ul.why li b{{color:{INK};font-weight:700}}
.axis{{display:block}}
.s1r{{display:grid;grid-template-columns:31mm minmax(0,1fr);column-gap:3mm;padding:.9mm 0;
 border-top:1px solid {RULE};break-inside:avoid}}
.s1r:last-child{{border-bottom:1px solid {RULE}}}
.s1c{{font:700 .84em/1.3 Poppins,sans-serif;padding-top:.3mm}}
.s1i{{font-size:.936em;line-height:1.34;overflow-wrap:anywhere;min-width:0}}
.s1i .it{{white-space:nowrap}}.s1i .it.k{{font-weight:700}}
.s1i .it.sep::after{{content:'';display:inline-block;width:.3mm;height:.85em;background:#C9C1B7;
 margin:0 2.2mm;vertical-align:-.08em}}
.s1i .more{{color:{SOFT};font-weight:600;white-space:nowrap}}
.ed{{display:grid;grid-template-columns:92mm minmax(0,1fr);column-gap:7mm;align-items:center}}
.wb{{display:flex;align-items:center}}
.wb svg{{flex:none;margin-right:3.5mm}}
.wdl{{font:600 .72em Poppins,sans-serif;letter-spacing:.16em;text-transform:uppercase;color:{BRAND_TEXT};margin-bottom:.5mm}}
.wtt{{font:700 1.05em/1.25 Poppins,sans-serif;margin:0 0 .6mm}}
.wts2{{font-size:.88em;color:#6B655D;line-height:1.3;margin-top:.6mm}}
.ce{{font-family:'Source Sans 3',sans-serif;font-size:.95em}}
.ce .ceh,.ce .cer{{display:grid;grid-template-columns:11mm 1fr}}
.ce.noy .ceh,.ce.noy .cer{{grid-template-columns:1fr}}
.ce .ceh{{color:{SOFT};font-size:.82em;font-weight:600;padding-bottom:.8mm;border-bottom:.3mm solid #CFC8BE}}
.ce .cer{{padding:.9mm 0;border-bottom:1px solid {RULE};line-height:1.3;break-inside:avoid}}
.ce .cey{{color:{SOFT};font-variant-numeric:tabular-nums}}

/* ---------- tytuł, miasto, edukacja (Artur 23.11.2026) ---------- */
.trow{{align-items:flex-start}}
/* Nagłówek T2 (Artur 25.11.2026): stanowisko duże czerwone, cienka linia, pod nią imię i nazwisko */
h1.title{{font:700 19pt/1.12 Poppins,sans-serif;color:{BRAND};letter-spacing:-.015em}}
.trow .nm{{display:inline-block;white-space:nowrap;font:500 12pt/1.2 Poppins,sans-serif;color:{INK};
 margin-top:1.6mm;padding-top:1.6mm;border-top:.3mm solid {RULE}}}
/* Wyróżnik: wieniec, etykieta, zdanie — bez ramki i tła */
.hl{{display:flex;align-items:center;margin-top:4mm}}
.hl .hlw{{flex:none;margin-right:2.4mm}}
.hlk{{font:700 .74em Poppins,sans-serif;letter-spacing:.14em;text-transform:uppercase;color:{BRAND_TEXT};margin-bottom:.6mm}}
.hlt{{font-size:1.1em;line-height:1.35;color:#2b2926}}.hlt b{{color:{INK};font-weight:700}}
/* Edukacja bez wieńca (wariant ED): dwie kolumny z ikonami */
.edp{{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);column-gap:8mm}}
.edh{{display:flex;align-items:center;font:700 .78em Poppins,sans-serif;letter-spacing:.12em;text-transform:uppercase;
 color:{BRAND_TEXT};margin-bottom:1.6mm}}
.edh .ic{{width:5mm;height:5mm;margin-right:1.8mm}}
.edi{{border-left:.6mm solid {BRAND};padding:.2mm 0 .2mm 2.6mm;margin:0 0 1.6mm .8mm;break-inside:avoid}}
.edi.c{{border-left-color:#D9D1C7}}
.edf{{font:700 1em/1.25 Poppins,sans-serif;color:{INK}}}
.edd{{font-size:.9em;color:{BRAND_TEXT};font-weight:600}}.edi.c .edd{{color:{SOFT}}}
.edu{{font-size:.9em;color:{SOFT}}}
.pills{{padding-top:1.2mm}}
.pill.loc{{display:inline-flex;align-items:center}}
.pill .pin{{width:1.05em;height:1.05em;margin:0 .8mm 0 -.6mm}}
.sublab{{font:700 .8em Poppins,sans-serif;letter-spacing:.12em;text-transform:uppercase;color:{BRAND_TEXT};
 padding-bottom:1mm;margin-bottom:1.6mm;border-bottom:.3mm solid {BRAND}}}
.ed{{align-items:start}}
.gap{{height:2mm}}
.sch{{font-size:.95em;line-height:1.35}}.sch b{{font:700 1em Poppins,sans-serif;color:{INK}}}
.cl .cli{{display:grid;grid-template-columns:11mm 1fr;padding:.9mm 0;border-bottom:1px solid {RULE};line-height:1.3;break-inside:avoid}}
.cl .cly{{color:{BRAND_TEXT};font:700 .9em Poppins,sans-serif;font-variant-numeric:tabular-nums;padding-top:.15mm}}
.cl .cln{{font-weight:600;color:{INK};grid-column:2}}
.cl.noy .cli{{grid-template-columns:1fr}}.cl.noy .cln{{grid-column:1}}

/* ---------- od strony 2 ---------- */
.rest{{break-before:page}}
.rest h2{{font:600 10.5pt Poppins,sans-serif;color:{BRAND};text-transform:uppercase;letter-spacing:.02em;
 margin:2.6mm 0 1.1mm;padding-top:1.1mm;border-top:.45mm solid {BRAND}}}
table.role{{margin-bottom:4.5mm;break-inside:avoid}}
table.role th,table.role td{{border:.25mm solid #CCCCCC;padding:.8mm 2mm}}
table.role th{{background:#F1F1F1;width:30mm;text-align:left;font-weight:600;vertical-align:top;white-space:nowrap}}
table.role tr{{break-inside:avoid}}table.role tr.h{{break-after:avoid}}
table.edu{{font-size:8.3pt;table-layout:fixed;break-inside:avoid;margin-bottom:4mm}}
table.edu th{{background:#E8E8E8;font-weight:600;text-align:left;padding:.8mm 2mm;border:.25mm solid #CCCCCC;font-size:7.8pt}}
table.edu td{{padding:.9mm 2mm;border:.25mm solid #CCCCCC;vertical-align:top}}
table.edu td.n{{white-space:nowrap;font-variant-numeric:tabular-nums}}
.consent{{margin-top:5mm;break-inside:avoid}}
.consent h4{{margin:0 0 2mm;font-size:8pt;font-weight:600;color:{SOFT2}}}
.consent img{{max-width:95mm;max-height:130mm;border:.25mm solid {LINE}}}
.rodo{{margin-top:6mm;font-size:6.6pt;color:{SOFT2};border-top:.25mm solid {LINE};padding-top:2mm;break-inside:avoid}}
.rodo p{{margin:0 0 1mm}}
{_inner(inner_mm)}
"""
