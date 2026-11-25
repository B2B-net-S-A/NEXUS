"""PDF „Nowego CV” na Poligonie: `frontend/public/poligon/nowe-cv.pdf` (25.11.2026).

Poligon nie renderuje plików, więc podgląd „Nowego CV” (karta „CV do klienta”,
edytor → „Strona 1” → „Jak u klienta”) to statyczny PDF podany przez
`frontend/src/lib/poligon/adapter.ts` (`POLIGON_NEW_CV_PDF`). Plik nie
nadąża sam za zmianami wyglądu, więc po każdej zmianie w
`app/services/cv_new_layout` przegeneruj go tą komendą (z katalogu repo,
dowolny obraz backendu z WeasyPrint; `DEBUG=1`, bo bez sekretów konfiguracja
odmawia startu „jak na produkcji”):

    docker run --rm --network none -e DEBUG=1 --entrypoint python \\
      -v "$PWD:/repo" -w /repo/backend nexus-staging-backend:latest \\
      -m scripts.poligon_new_cv_pdf

Dane biorą się wyłącznie z `frontend/src/lib/poligon/cv-fiction.ts`: HTML
z `cvFictionHtml` i zdania 1–3 strony 1 z `CV_FICTION_WHY` (tak jak
`page1_extras` po biegu generatora w `tools.ts` → `page1Of`). Render idzie
tą samą drogą co trasa podglądu (`cv_new_pdf._render`). Bez nazwiska w
tytule, bo jeden plik pokazuje się przy każdej osobie ćwiczebnej. Klient
fikcyjny nie jest pracodawcą z CV, więc wyróżnik zostaje automatyczny i bez
wieńca. Skrypt nie łączy się z bazą ani siecią.

Na koniec wypisuje „strona 1 mieści się · pismo N pt”: pasek podglądu na
Poligonie bierze te wartości z `POLIGON_NEW_CV_HEADERS` w `adapter.ts`, więc
gdy się zmienią, popraw je tam.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
FICTION = REPO / "frontend/src/lib/poligon/cv-fiction.ts"
OUTPUT = REPO / "frontend/public/poligon/nowe-cv.pdf"

_STRING = r'"(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)*\'|`(?:[^`\\]|\\.)*`'


def _literal(token: str) -> str:
    body = token[1:-1]
    body = body.replace("\\'", "'").replace('\\"', '"').replace('"', '\\"')
    return json.loads('"' + body + '"')


def fiction_html(source: str, full_name: str = "") -> str:
    """Sklejone literały z ciała `cvFictionHtml` (komentarze `//` pominięte)."""
    body = re.search(
        r"function cvFictionHtml\(.*?\{\s*return \((.*?)\);\s*\}", source, re.S
    )
    if not body:
        raise SystemExit("cv-fiction.ts: nie ma funkcji cvFictionHtml")
    code = "\n".join(
        line for line in body.group(1).splitlines() if not line.strip().startswith("//")
    )
    html = "".join(_literal(t) for t in re.findall(_STRING, code))
    if not full_name:  # „Senior Project Manager – ” bez wiszącego myślnika
        html = html.replace(" – ${fullName}", "")
    return html.replace("${fullName}", full_name)


def fiction_why(source: str) -> list[dict]:
    """`CV_FICTION_WHY` jako lista słowników (klucze TS w cudzysłowach, bez `as const`)."""
    found = re.search(r"CV_FICTION_WHY = (\[.*?\]) as const;", source, re.S)
    if not found:
        raise SystemExit("cv-fiction.ts: nie ma CV_FICTION_WHY")

    def token(match: re.Match) -> str:
        if match.group(1):
            return json.dumps(_literal(match.group(1)), ensure_ascii=False)
        return f'"{match.group(2)}":'

    text = re.sub(rf"({_STRING})|\b(\w+)\s*:", token, found.group(1))
    return json.loads(re.sub(r",(\s*[\]}])", r"\1", text))


def render(source: str, full_name: str = ""):
    from app.services.cv_new_pdf import _render

    why = fiction_why(source)
    extras = {"why": [item["text"] for item in why], "why_generated": why}
    return _render(
        fiction_html(source, full_name),
        language="pl",
        blind=False,
        fallback=None,
        extras=extras,
        consent=None,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=OUTPUT)
    args = parser.parse_args(argv)
    result = render(FICTION.read_text(encoding="utf-8"))
    args.out.write_bytes(result.pdf)
    print(
        f"{args.out.relative_to(REPO) if args.out.is_relative_to(REPO) else args.out}: "
        f"{len(result.pdf)} B · strona 1 {'mieści się' if result.fits else 'NIE mieści się'}"
        f" · pismo {result.font_pt:g} pt · kroki dopasowania: {', '.join(result.steps) or '—'}"
        f" · sekcje bez miejsca: {len(result.unmapped_sections)}"
    )
    return 0 if result.fits else 1


if __name__ == "__main__":
    sys.exit(main())
