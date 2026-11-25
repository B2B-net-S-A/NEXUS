"""Plakat A4 z kodem QR do linku rekrutacji (etap 3 linków, 19.10.2026).

Rekruter wiesza go na uczelni, meetupie albo tablicy ogłoszeń. Treść bierze
WYŁĄCZNIE z opublikowanej wersji opisu (``jpp.published_version``) — tej, która
przeszła kontrolę klienta, kwot, kontaktów i kodów. Kanałów nie rozróżniamy:
kod QR prowadzi na ten sam adres co link do skopiowania.

Makieta: https://claude.ai/artifact/8aVZkzVxkVnkVVNBUDgL4h (plansza 3). Od
24.11.2026 jeden wygląd jak nagłówek oferty na nowej stronie kariery (wariant
G1 „Czerwona”, decyzja Artura): czerwone tło, biały tytuł, jasny pas z kodem QR.
Szablony rekrutacji (Grafit, Terminal, Jasny) go nie zmieniają.
"""

from __future__ import annotations

import html
from typing import Any, Optional

_REMOTE_LABEL = {"remote": "Zdalnie", "hybrid": "Hybryda", "onsite": "Stacjonarnie"}
_MAX_MUST = 3


def poster_tagline(params: dict[str, Any]) -> str:
    """„Warszawa · Hybryda · B2B” — jak linia faktów w grafice posta."""
    parts = [
        params.get("city"),
        _REMOTE_LABEL.get(params.get("remote_policy") or ""),
        params.get("contract"),
    ]
    shown = [str(p).strip() for p in parts if p and str(p).strip()]
    return " · ".join(shown)


def qr_data_uri(url: str) -> str:
    """Kod QR jako ``data:`` SVG — renderer PDF nie pobiera niczego z sieci."""
    import segno  # noqa: WPS433 (leniwy import: tylko przy generowaniu plakatu)

    return segno.make(url, error="m").svg_data_uri(scale=8, border=2)


# Kolory strony kariery, wariant 5 „Czerwień w gradientach tech” (decyzja
# Artura 25.11.2026): czerwień #C42329 w gradiencie bordo › czerwień › ciepły
# blask, jak nagłówek strony. Biały na #C42329 ma 5,8:1, ale drobny tekst
# (adres, wezwanie) dalej stoi na jasnym pasie Snow, a na czerwieni duże litery.
_RED = "#C42329"
_RED_TECH = "linear-gradient(90deg, #961621 0%, #C42329 52%, #D43424 100%)"
_RED_TEXT = "#B0222A"
_SNOW = "#FAF6F4"
_INK = "#1F1115"


def poster_html(payload: dict[str, Any], url: str) -> str:
    """Dokument HTML plakatu. Każde pole z opisu idzie przez ``html.escape``."""
    esc = html.escape
    title = esc(str(payload.get("title") or "Rekrutacja"))
    subtitle = payload.get("subtitle")
    must = [str(item["name"]) for item in payload.get("must") or []][:_MAX_MUST]
    tagline = poster_tagline(payload.get("params") or {})
    must_html = "".join(f"<li>{esc(name)}</li>" for name in must)
    return f"""<!doctype html>
<html lang="pl"><head><meta charset="utf-8"><title>{title}</title>
<style>
@page {{ size: A4; margin: 0; }}
html, body {{ margin: 0; background: {_RED}; color: #FFFFFF; }}
.page {{ background: {_RED_TECH}; }}
body {{ font-family: "DejaVu Sans", Arial, sans-serif; }}
.page {{ position: relative; width: 210mm; height: 297mm; box-sizing: border-box;
  padding: 20mm 20mm 0; }}
.brand {{ font-size: 13pt; font-weight: 700; letter-spacing: 0.04em; }}
h1 {{ margin: 22mm 0 6mm; font-size: 48pt; line-height: 1.02; font-weight: 800;
  letter-spacing: -0.02em; }}
.sub {{ font-size: 17pt; line-height: 1.4; font-weight: 700; margin: 0 0 7mm; }}
.tag {{ font-size: 16pt; font-weight: 700; padding: 3mm 0; border-top: 0.4mm solid #FFFFFF;
  border-bottom: 0.4mm solid #FFFFFF; }}
ul {{ padding: 0 0 0 6mm; margin: 8mm 0 0; font-size: 15pt; line-height: 1.6;
  font-weight: 700; }}
/* Jasny pas na dole: drobny tekst na Snow, nie na czerwieni. Bez flexa
   (WeasyPrint obsługuje go tylko częściowo) — tabela. */
.foot {{ position: absolute; left: 0; right: 0; bottom: 0; background: {_SNOW};
  color: {_INK}; padding: 12mm 20mm 14mm; }}
.foot table {{ width: 100%; border-collapse: collapse; }}
.foot td {{ vertical-align: middle; padding: 0; }}
.foot td.q {{ width: 62mm; }}
.qr {{ display: block; width: 52mm; height: 52mm; background: #FFFFFF; padding: 3mm;
  border: 0.3mm solid {_INK}; }}
.cta {{ font-size: 22pt; font-weight: 800; color: {_RED_TEXT}; margin-bottom: 3mm; }}
.hint {{ font-size: 12pt; margin-bottom: 3mm; }}
.url {{ font-family: "DejaVu Sans Mono", monospace; font-size: 10pt; color: {_INK};
  word-break: break-all; }}
</style></head>
<body><div class="page">
<div class="brand">B2Bnetwork · Kariera</div>
<h1>{title}</h1>
{f'<p class="sub">{esc(str(subtitle))}</p>' if subtitle else ""}
{f'<div class="tag">{esc(tagline)}</div>' if tagline else ""}
{f"<ul>{must_html}</ul>" if must_html else ""}
<div class="foot"><table><tr>
<td class="q"><img class="qr" src="{esc(qr_data_uri(url), quote=True)}" alt="Kod QR"></td>
<td><div class="cta">Zeskanuj i wyślij CV</div>
<div class="hint">Wystarczy samo CV, imię i e-mail odczytamy z pliku.</div>
<div class="url">{esc(url)}</div></td>
</tr></table></div>
</div></body></html>"""


def render_poster_pdf(payload: dict[str, Any], url: str) -> bytes:
    """PDF A4. Renderer blokuje każdy zasób spoza ``data:`` (SSRF — wzór
    ``autenti/pdf_renderer``), choć dokument i tak żadnego nie ma."""
    from weasyprint import HTML  # noqa: WPS433 (leniwy import)
    from weasyprint.urls import URLFetcher  # noqa: WPS433

    class _DataOnlyFetcher(URLFetcher):
        def fetch(self, url: str, headers: Optional[dict] = None):
            if url.startswith("data:"):
                return super().fetch(url, headers)
            raise ValueError(f"blocked external resource in poster PDF: {url[:64]!r}")

    pdf = HTML(
        string=poster_html(payload, url), url_fetcher=_DataOnlyFetcher()
    ).write_pdf()
    if pdf is None:
        raise RuntimeError("WeasyPrint returned no PDF bytes")
    return pdf
