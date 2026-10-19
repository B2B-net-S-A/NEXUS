"""Plakat A4 z kodem QR do linku rekrutacji (etap 3 linków, 19.10.2026).

Rekruter wiesza go na uczelni, meetupie albo tablicy ogłoszeń. Treść bierze
WYŁĄCZNIE z opublikowanej wersji opisu (``jpp.published_version``) — tej, która
przeszła kontrolę klienta, kwot, kontaktów i kodów. Kanałów nie rozróżniamy:
kod QR prowadzi na ten sam adres co link do skopiowania.

Makieta: https://claude.ai/artifact/8aVZkzVxkVnkVVNBUDgL4h (plansza 3).
"""

from __future__ import annotations

import html
from typing import Any, Optional

from app.services.career_theme import DEFAULT_THEME, POSTER_COLORS

_REMOTE_LABEL = {"remote": "zdalnie", "hybrid": "hybryda", "onsite": "stacjonarnie"}
_MAX_MUST = 3


def poster_tagline(params: dict[str, Any]) -> str:
    """„[warszawa · hybryda · b2b]” — jak na stronie i w grafice OG."""
    parts = [
        params.get("city"),
        _REMOTE_LABEL.get(params.get("remote_policy") or ""),
        params.get("contract"),
    ]
    shown = [str(p).strip().lower() for p in parts if p and str(p).strip()]
    return f"[{' · '.join(shown)}]" if shown else ""


def qr_data_uri(url: str) -> str:
    """Kod QR jako ``data:`` SVG — renderer PDF nie pobiera niczego z sieci."""
    import segno  # noqa: WPS433 (leniwy import: tylko przy generowaniu plakatu)

    return segno.make(url, error="m").svg_data_uri(scale=8, border=2)


def poster_html(payload: dict[str, Any], url: str, theme: str = DEFAULT_THEME) -> str:
    """Dokument HTML plakatu. Każde pole z opisu idzie przez ``html.escape``.

    Kolory z szablonu rekrutacji (0478) — ten sam, co strona i grafika OG.
    """
    esc = html.escape
    c = POSTER_COLORS.get(theme) or POSTER_COLORS[DEFAULT_THEME]
    title = esc(str(payload.get("title") or "Rekrutacja"))
    subtitle = payload.get("subtitle")
    must = [str(item["name"]) for item in payload.get("must") or []][:_MAX_MUST]
    tagline = poster_tagline(payload.get("params") or {})
    must_html = "".join(
        f'<li><span class="mk">›</span> {esc(name)}</li>' for name in must
    )
    return f"""<!doctype html>
<html lang="pl"><head><meta charset="utf-8"><title>{title}</title>
<style>
@page {{ size: A4; margin: 0; }}
html, body {{ margin: 0; background: {c["bg"]}; color: {c["text"]}; }}
body {{ font-family: "DejaVu Sans", Arial, sans-serif; }}
.page {{ position: relative; width: 210mm; height: 297mm; box-sizing: border-box;
  padding: 22mm 20mm; }}
.mono {{ font-family: "DejaVu Sans Mono", monospace; color: {c["muted"]}; font-size: 10pt; }}
h1 {{ margin: 14mm 0 6mm; font-size: 46pt; line-height: 1.02; font-weight: 800;
  color: {c["text"]}; }}
.sub {{ font-size: 15pt; line-height: 1.45; color: {c["muted"]}; margin: 0 0 6mm; }}
ul {{ list-style: none; padding: 0; margin: 8mm 0 0;
  font-family: "DejaVu Sans Mono", monospace; font-size: 12pt; line-height: 1.8;
  color: {c["muted"]}; }}
.mk {{ color: {c["accent"]}; }}
/* Stopka bez flexa: WeasyPrint obsługuje go tylko częściowo. */
.foot {{ position: absolute; left: 20mm; right: 20mm; bottom: 22mm;
  display: table; width: 170mm; }}
.foot > div {{ display: table-cell; vertical-align: bottom; }}
.foot > div:first-child {{ width: 62mm; }}
.qr {{ display: block; width: 52mm; height: 52mm; background: #fff; padding: 3mm;
  border: 0.3mm solid {c["muted"]}; }}
.cta {{ font-size: 18pt; font-weight: 700; color: {c["text"]}; margin-bottom: 3mm; }}
.url {{ font-family: "DejaVu Sans Mono", monospace; font-size: 10pt;
  color: {c["accent"]}; word-break: break-all; }}
</style></head>
<body><div class="page">
<div class="mono">~/kariera</div>
<h1>{title}</h1>
{f'<p class="sub">{esc(str(subtitle))}</p>' if subtitle else ""}
{f'<div class="mono">{esc(tagline)}</div>' if tagline else ""}
{f"<ul>{must_html}</ul>" if must_html else ""}
<div class="foot">
<div><img class="qr" src="{esc(qr_data_uri(url), quote=True)}" alt="Kod QR"></div>
<div><div class="cta">Zeskanuj i aplikuj w 2 minuty</div>
<div class="url">{esc(url)}</div></div>
</div>
</div></body></html>"""


def render_poster_pdf(
    payload: dict[str, Any], url: str, theme: str = DEFAULT_THEME
) -> bytes:
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
        string=poster_html(payload, url, theme), url_fetcher=_DataOnlyFetcher()
    ).write_pdf()
    if pdf is None:
        raise RuntimeError("WeasyPrint returned no PDF bytes")
    return pdf
