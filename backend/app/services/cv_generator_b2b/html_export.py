"""Interaktywne CV jako JEDEN samodzielny plik HTML (do wysyłki mailem).

Odpowiednik DOCX-a z ``docx_renderer`` + warstwa interaktywna — wszystko
inline w jednym pliku: style, dane, mała wanilia JS. Zero zależności
sieciowych (działa offline, po podwójnym kliknięciu, w każdej przeglądarce),
zero backendu — dlatego NIE ma tu chatu (ten żyje na publicznym linku
``/cv/i/{token}``, bo wymaga serwera).

Zawartość:
* dokument CV w układzie szablonu firmowego (te same sekcje, kolory
  ``COLOR_HEADER``/``COLOR_TEXT``, bolding technologii z ``highlight_keywords``,
  klauzula RODO na dole),
* kafelki „Dopasowanie do wymagań" (must/nice-have, klik → dowody-cytaty,
  klik w cytat → scroll + podświetlenie pozycji doświadczenia),
* przełącznik Klasyczne ↔ Interaktywne; druk (Ctrl+P / przycisk) ukrywa
  warstwę interaktywną — na papier/PDF idzie czyste klasyczne CV.

Wejściem jest WYŁĄCZNIE client-safe payload z ``public_view`` (bez
``warnings``, blind zamaskowany) + zapisana mapa wymagań — czyli dokładnie
to, co i tak widzi klient. Każdy tekst przechodzi przez ``html.escape``.
"""

from __future__ import annotations

import html
import re
from typing import Any

from app.services.cv_generator_b2b.docx_renderer import (
    TRANSLATIONS,
    compile_keyword_patterns,
    highlight_spans,
)

_HEADER_COLOR = "#E14F4F"  # COLOR_HEADER z szablonu DOCX
_TEXT_COLOR = "#373535"  # COLOR_TEXT z szablonu DOCX

_UI = {
    "pl": {
        "classic": "Klasyczne",
        "interactive": "Interaktywne",
        "print": "Drukuj / PDF",
        "tiles_title": "Dopasowanie do wymagań",
        "tiles_hint": (
            "Kliknij wymaganie, aby zobaczyć dowody z CV. Kliknięcie cytatu "
            "podświetla pozycję w doświadczeniu."
        ),
        "must": "MUST-HAVE",
        "nice": "NICE-TO-HAVE",
        "met": "Potwierdzone w CV",
        "partial": "Częściowo / pośrednio",
        "no_data": "Brak danych w CV",
        "evidence": "Dowody z CV",
        "no_evidence": "CV nie zawiera informacji o tym wymaganiu.",
    },
    "en": {
        "classic": "Classic",
        "interactive": "Interactive",
        "print": "Print / PDF",
        "tiles_title": "Requirements match",
        "tiles_hint": (
            "Click a requirement to see evidence from the CV. Clicking a "
            "quote highlights the matching experience entry."
        ),
        "must": "MUST-HAVE",
        "nice": "NICE-TO-HAVE",
        "met": "Confirmed in CV",
        "partial": "Partial / indirect",
        "no_data": "No data in CV",
        "evidence": "Evidence from CV",
        "no_evidence": "The CV does not cover this requirement.",
    },
}

_STATUS_CLASS = {"met": "met", "partial": "partial", "no_data": "nodata"}


def _esc(text: Any) -> str:
    return html.escape(str(text or ""), quote=True)


def _bold(text: str, patterns: list[re.Pattern[str]]) -> str:
    """Escapowany HTML z <b> na frazach-technologiach (jak bolding w DOCX)."""
    raw = str(text or "")
    if not patterns:
        return _esc(raw)
    spans = highlight_spans(raw, patterns)
    if not spans:
        return _esc(raw)
    out: list[str] = []
    cursor = 0
    for start, end in spans:
        out.append(_esc(raw[cursor:start]))
        out.append(f"<b>{_esc(raw[start:end])}</b>")
        cursor = end
    out.append(_esc(raw[cursor:]))
    return "".join(out)


def _tiles_html(
    items: list[dict[str, Any]], ui: dict[str, str], patterns: list[re.Pattern[str]]
) -> str:
    if not items:
        return ""
    groups: list[str] = []
    for kind in ("must", "nice"):
        kind_items = [i for i in items if i.get("kind") == kind]
        if not kind_items:
            continue
        tiles: list[str] = []
        for item in kind_items:
            status = str(item.get("status") or "no_data")
            css = _STATUS_CLASS.get(status, "nodata")
            note = _esc(item.get("note")) if item.get("note") else ""
            evidence = item.get("evidence") or []
            # experience_index: _sanitize_items gwarantuje None|int, ale ta
            # inwariancja jest niewidoczna stąd — twardy cast na wypadek
            # ręcznie wstawionego wiersza (defense-in-depth, atrybut HTML).
            ev_html = "".join(
                (
                    f'<button type="button" class="quote" '
                    f'data-exp="{ev["experience_index"] if isinstance(ev.get("experience_index"), int) else ""}">'
                    f"„{_esc(ev.get('quote'))}”</button>"
                )
                for ev in evidence
                if isinstance(ev, dict) and ev.get("quote")
            )
            detail_parts = [
                f'<p class="status-label">{_esc(ui[status if status in ui else "no_data"])}</p>'
            ]
            if note:
                detail_parts.append(f'<p class="note">{note}</p>')
            if ev_html:
                detail_parts.append(
                    f'<p class="ev-label">{_esc(ui["evidence"])}</p>{ev_html}'
                )
            elif status == "no_data":
                detail_parts.append(f'<p class="note">{_esc(ui["no_evidence"])}</p>')
            tiles.append(
                f'<div class="tile {css}">'
                f'<button type="button" class="tile-head">'
                f'<span class="dot"></span>'
                f"<span>{_bold(str(item.get('requirement') or ''), patterns)}</span>"
                f'<span class="chev">▾</span></button>'
                f'<div class="tile-body" hidden>{"".join(detail_parts)}</div>'
                f"</div>"
            )
        groups.append(
            f'<p class="tiles-group">{_esc(ui[kind])}</p>'
            f'<div class="tiles-grid">{"".join(tiles)}</div>'
        )
    return (
        f'<section id="tiles" class="no-print">'
        f"<h2>{_esc(ui['tiles_title'])}</h2>"
        f'<p class="hint">{_esc(ui["tiles_hint"])}</p>'
        f"{''.join(groups)}</section>"
    )


def render_interactive_html(
    public_payload: dict[str, Any],
    requirement_items: list[dict[str, Any]] | None,
    *,
    document_only: bool = False,
) -> str:
    """Zbuduj kompletny, samodzielny dokument HTML (string)."""
    p = public_payload
    lang = "en" if p.get("language") == "en" else "pl"
    t = TRANSLATIONS[lang]
    ui = _UI[lang]
    blind = bool(p.get("blind"))
    patterns = compile_keyword_patterns(p.get("highlight_keywords") or [])
    items = [i for i in (requirement_items or []) if isinstance(i, dict)]

    name = _esc(p.get("candidate_name"))
    position = _esc(p.get("position"))
    doc_header = position if blind else f"{position} – {name}"
    why_title = ("Summary" if lang == "en" else "Podsumowanie") if blind else t["why"]

    sections: list[str] = []

    if p.get("why_points"):
        bullets = "".join(
            f"<li>{_bold(w, patterns)}</li>" for w in p.get("why_points", [])
        )
        sections.append(f"<h2>{_esc(why_title)}</h2><ul>{bullets}</ul>")

    if p.get("education"):
        rows = "".join(
            (
                f'<div class="edu"><span class="edu-dates">{_esc(e.get("dates"))}</span>'
                f"<span><b>{_esc(e.get('institution'))}</b>"
                + (f" — {_esc(e.get('degree'))}" if e.get("degree") else "")
                + (f" · {_esc(e.get('location'))}" if e.get("location") else "")
                + "</span></div>"
            )
            for e in p.get("education", [])
        )
        sections.append(f"<h2>{_esc(t['education'])}</h2>{rows}")

    if p.get("skills"):
        rows = "".join(
            (
                '<p class="skill">'
                + (
                    f"<b>{_esc(re.sub(r':+\s*$', '', str(g.get('label'))))}: </b>"
                    if g.get("label")
                    else ""
                )
                + _bold(str(g.get("content") or ""), patterns)
                + "</p>"
            )
            for g in p.get("skills", [])
        )
        sections.append(f"<h2>{_esc(t['skills'])}</h2>{rows}")

    if p.get("certifications"):
        bullets = "".join(f"<li>{_esc(c)}</li>" for c in p.get("certifications", []))
        sections.append(f"<h2>{_esc(t['certifications'])}</h2><ul>{bullets}</ul>")

    if p.get("languages"):
        sections.append(
            f"<h2>{_esc(t['languages'])}</h2>"
            f"<p>{_esc(' · '.join(p.get('languages', [])))}</p>"
        )

    if p.get("experience"):
        jobs: list[str] = []
        for i, job in enumerate(p.get("experience", [])):
            resp = "".join(
                f"<li>{_bold(r, patterns)}</li>"
                for r in job.get("responsibilities", [])
            )
            tech = ", ".join(job.get("technologies", []))
            jobs.append(
                f'<div class="job" id="exp-{i}">'
                f'<div class="job-head"><b>{_esc(job.get("position"))}</b>'
                f'<span class="job-dates">{_esc(job.get("dates"))}</span></div>'
                f'<p class="job-co">{_esc(job.get("company"))}'
                + (f" · {_esc(job.get('industry'))}" if job.get("industry") else "")
                + "</p>"
                + (
                    f'<p class="lbl">{_esc(t["responsibilities"])}</p><ul>{resp}</ul>'
                    if resp
                    else ""
                )
                + (
                    f'<p class="lbl">{_esc(t["technologies"])} '
                    f'<span class="tech">{_bold(tech, patterns)}</span></p>'
                    if tech
                    else ""
                )
                + "</div>"
            )
        sections.append(f"<h2>{_esc(t['experience'])}</h2>{''.join(jobs)}")

    considered = (
        (
            f'<p class="considered"><b>{_esc(t["considered_for"])}</b> '
            f"{_esc(p.get('considered_for'))}</p>"
        )
        if p.get("considered_for")
        else ""
    )

    # Editor import uses exactly the document body, without scripts, controls,
    # matching tiles or their diagnostic text. The same body is used by export.
    document = (
        f'<article class="cv"><h1>{doc_header}</h1>{considered}<hr>'
        f'{"".join(sections)}<p class="rodo">{_esc(t["rodo"])}</p></article>'
    )
    if document_only:
        return document

    has_tiles = bool(items)
    default_mode = "interactive" if has_tiles else "classic"
    toggle = (
        (
            '<div class="switch" role="tablist">'
            f'<button type="button" data-mode="classic">{_esc(ui["classic"])}</button>'
            f'<button type="button" data-mode="interactive">{_esc(ui["interactive"])}</button>'
            "</div>"
        )
        if has_tiles
        else ""
    )

    return f"""<!DOCTYPE html>
<html lang="{lang}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{doc_header}</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: 'Montserrat', 'Segoe UI', Arial, sans-serif; color: {_TEXT_COLOR};
         background: #f4f4f4; padding: 16px; }}
  .page {{ max-width: 860px; margin: 0 auto; }}
  .topbar {{ display: flex; justify-content: flex-end; gap: 8px; margin-bottom: 12px; }}
  .switch {{ display: inline-flex; border: 1px solid #ddd; border-radius: 8px;
             background: #fff; padding: 3px; }}
  .switch button {{ border: 0; background: transparent; padding: 6px 14px; font: inherit;
                    font-size: 13px; border-radius: 6px; cursor: pointer; color: #777; }}
  .switch button.on {{ background: {_HEADER_COLOR}; color: #fff; }}
  .printbtn {{ border: 1px solid #ddd; background: #fff; border-radius: 8px;
               padding: 6px 14px; font: inherit; font-size: 13px; cursor: pointer; }}
  #tiles {{ background: #fff; border: 1px solid #e5e5e5; border-radius: 10px;
            padding: 18px 22px; margin-bottom: 14px; }}
  #tiles h2 {{ color: {_HEADER_COLOR}; font-size: 14px; letter-spacing: .04em; }}
  #tiles .hint {{ font-size: 12px; color: #888; margin: 4px 0 10px; }}
  .tiles-group {{ font-size: 11px; font-weight: 700; letter-spacing: .08em;
                  color: #999; margin: 10px 0 6px; }}
  .tiles-grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
                 gap: 8px; }}
  .tile {{ border: 1px solid; border-radius: 8px; overflow: hidden; }}
  .tile.met {{ border-color: #b7e0c8; background: #eefaf2; color: #1c6b3c; }}
  .tile.partial {{ border-color: #f0d9a6; background: #fdf6e5; color: #8a6414; }}
  .tile.nodata {{ border-color: #e0e0e0; background: #f7f7f7; color: #777; }}
  .tile-head {{ display: flex; align-items: center; gap: 8px; width: 100%; border: 0;
                background: transparent; padding: 9px 12px; font: inherit; font-size: 14px;
                font-weight: 600; cursor: pointer; color: inherit; text-align: left; }}
  .tile-head .chev {{ margin-left: auto; transition: transform .15s; }}
  .tile.open .tile-head .chev {{ transform: rotate(180deg); }}
  .dot {{ width: 9px; height: 9px; border-radius: 50%; flex: none; background: currentColor; }}
  .tile-body {{ padding: 0 12px 11px; font-size: 13px; }}
  .status-label {{ font-size: 10px; font-weight: 700; letter-spacing: .07em;
                   text-transform: uppercase; opacity: .8; margin-bottom: 4px; }}
  .ev-label {{ font-size: 10px; font-weight: 700; letter-spacing: .07em;
               text-transform: uppercase; opacity: .8; margin: 8px 0 4px; }}
  .note {{ margin-bottom: 2px; }}
  .quote {{ display: block; width: 100%; text-align: left; font: inherit; font-size: 13px;
            font-style: italic; background: rgba(255,255,255,.65); border: 1px solid
            rgba(0,0,0,.08); border-radius: 6px; padding: 6px 9px; margin-top: 5px;
            cursor: pointer; color: inherit; }}
  .quote:hover {{ border-color: {_HEADER_COLOR}; }}
  .cv {{ background: #fff; border: 1px solid #e5e5e5; border-radius: 10px;
         padding: 34px 40px; }}
  .cv h1 {{ color: {_HEADER_COLOR}; font-size: 26px; font-weight: 600; }}
  .considered {{ font-size: 12px; margin-top: 4px; }}
  .considered b {{ color: {_HEADER_COLOR}; font-weight: 600; }}
  .cv hr {{ border: 0; border-top: 2px solid {_HEADER_COLOR}; margin: 12px 0 4px; }}
  .cv h2 {{ color: {_HEADER_COLOR}; font-size: 15px; font-weight: 600;
            letter-spacing: .03em; margin: 18px 0 7px; }}
  .cv ul {{ list-style: none; }}
  .cv ul li {{ font-size: 13.5px; margin: 3px 0; padding-left: 16px; position: relative; }}
  .cv ul li::before {{ content: "•"; color: {_HEADER_COLOR}; position: absolute; left: 2px; }}
  .edu {{ display: flex; gap: 14px; font-size: 13.5px; margin: 3px 0; }}
  .edu-dates {{ flex: 0 0 92px; color: #808080; }}
  .skill {{ font-size: 13.5px; margin: 3px 0; }}
  .job {{ margin: 0 0 15px; padding: 6px 8px; margin-left: -8px; border-radius: 8px;
          transition: background .4s, box-shadow .4s; }}
  .job.flash {{ background: #fdeeee; box-shadow: 0 0 0 2px {_HEADER_COLOR}66; }}
  .job-head {{ display: flex; justify-content: space-between; gap: 12px;
               font-size: 14.5px; }}
  .job-dates {{ color: #808080; font-size: 12px; white-space: nowrap; }}
  .job-co {{ font-size: 13px; color: #808080; margin: 1px 0 4px; }}
  .lbl {{ font-size: 12px; font-weight: 600; margin-top: 5px; }}
  .tech {{ font-weight: 400; }}
  .rodo {{ font-size: 8.5px; color: #9a9a9a; line-height: 1.35; margin-top: 26px;
           border-top: 1px solid #eee; padding-top: 10px; text-align: justify; }}
  body.classic #tiles {{ display: none; }}
  @media print {{
    body {{ background: #fff; padding: 0; }}
    .no-print, .topbar, #tiles {{ display: none !important; }}
    .cv {{ border: 0; border-radius: 0; padding: 0; }}
    .job {{ break-inside: avoid; }}
  }}
</style>
</head>
<body class="{default_mode}">
<div class="page">
  <div class="topbar no-print">
    {toggle}
    <button type="button" class="printbtn" onclick="window.print()">{_esc(ui["print"])}</button>
  </div>
  {_tiles_html(items, ui, patterns)}
  {document}
</div>
<script>
(function () {{
  var body = document.body;
  document.querySelectorAll(".switch button").forEach(function (btn) {{
    btn.addEventListener("click", function () {{
      body.className = btn.dataset.mode;
      sync();
    }});
  }});
  function sync() {{
    document.querySelectorAll(".switch button").forEach(function (b) {{
      b.classList.toggle("on", b.dataset.mode === body.className);
    }});
  }}
  sync();
  document.querySelectorAll(".tile-head").forEach(function (head) {{
    head.addEventListener("click", function () {{
      var tile = head.parentElement;
      var open = tile.classList.toggle("open");
      tile.querySelector(".tile-body").hidden = !open;
    }});
  }});
  var flashTimer = null;
  document.querySelectorAll(".quote").forEach(function (q) {{
    q.addEventListener("click", function () {{
      var idx = q.dataset.exp;
      if (idx === "None" || idx === "" || idx == null) return;
      var el = document.getElementById("exp-" + idx);
      if (!el) return;
      el.scrollIntoView({{ behavior: "smooth", block: "center" }});
      document.querySelectorAll(".job.flash").forEach(function (j) {{
        j.classList.remove("flash");
      }});
      el.classList.add("flash");
      if (flashTimer) clearTimeout(flashTimer);
      flashTimer = setTimeout(function () {{ el.classList.remove("flash"); }}, 2500);
    }});
  }});
}})();
</script>
</body>
</html>
"""
