"""Czy twierdzenie zakwestionowane przez kontrolę AI stoi w jej źródłach (D1-A, 17.10.2026).

Pomiar na produkcji 17.10.2026 (docs/qc-no-coverage-measurement.md): 32% uwag
„BRAK POKRYCIA (kontrola AI)” miało cytat dosłownie w oryginale CV, a kolejne
38% — co najmniej 80% słów w źródłach. Recenzent ma regułę „całe pole musi
wynikać z cytatu dla tej samej roli”, więc odrzuca nawet nazwę firmy, której
nie umie zacytować z kontekstem. To jest kod PO modelu, nie zamiast niego:
patrzy tylko na werdykt ``unsupported`` i tylko na tekst, który recenzent
dostał (CV kandydata i notatki bez pytań).

- ``IN_SOURCE`` — krótkie twierdzenie (do ``SHORT_MAX`` znaków: firma,
  stanowisko, daty, umiejętność, certyfikat) stoi w źródłach dosłownie,
  całymi słowami → uwaga znika;
- ``MOSTLY`` — dłuższe twierdzenie stoi w źródłach dosłownie albo co najmniej
  ``MOSTLY_SHARE`` jego słów treści (rdzeń 5 liter) jest w źródłach →
  „WERYFIKUJ” zamiast „BRAK POKRYCIA”, bez „Usuń zdanie” w edytorze i poza
  licznikiem „Do poprawy”;
- ``None`` — uwaga zostaje bez zmian.

Długie zdanie przeniesione dosłownie z innej roli recenzent słusznie
kwestionuje dla tej roli, a kod roli nie widzi — dlatego dosłowna długa treść
nie znika, tylko łagodnieje. Zdania przeczące z notatek nie są dowodem
(„Nie zna Kafki” nie potwierdza „Kafka”).
"""

from __future__ import annotations

import re
from typing import Optional

from app.services.must_text_evidence import drop_negative_sentences

IN_SOURCE = "in_source"
MOSTLY = "mostly"
SHORT_MAX = 60
MOSTLY_SHARE = 0.8

_SPACE = re.compile(r"\s+")
_WORD = re.compile(r"[^\W\d_]{4,}")
_LETTER = re.compile(r"[^\W\d_]")
# Słowa funkcyjne nie świadczą o pokryciu („oraz”, „with”).
_STOP = frozenset(
    "oraz przy przez nad pod jako który która które było były jest with that "
    "this from into have were also their there about".split()
)


def _norm(text: Optional[str]) -> str:
    return _SPACE.sub(" ", text or "").strip().casefold()


def _stems(text: str) -> set[str]:
    return {word[:5] for word in _WORD.findall(text) if word not in _STOP}


class ReviewSources:
    """Źródła recenzenta raz znormalizowane — sprawdzamy wiele twierdzeń."""

    def __init__(self, cv_text: Optional[str], notes: Optional[str] = None) -> None:
        joined = "\n".join(
            part for part in (cv_text or "", drop_negative_sentences(notes)) if part
        )
        self.text = _norm(joined)
        self.stems = _stems(self.text)


def coverage(claim: Optional[str], sources: ReviewSources) -> Optional[str]:
    """``IN_SOURCE`` | ``MOSTLY`` | ``None`` dla jednego twierdzenia."""

    text = _norm(claim).rstrip("…").strip()
    # „5”, „IT”, sama data roku — za mało, żeby cokolwiek przesądzać.
    if len(text) < 3 or (not _LETTER.search(text) and len(text) < 7):
        return None
    if re.search(r"(?<!\w)" + re.escape(text) + r"(?!\w)", sources.text):
        return IN_SOURCE if len(text) <= SHORT_MAX else MOSTLY
    words = _stems(text)
    if words and len(words & sources.stems) / len(words) >= MOSTLY_SHARE:
        return MOSTLY
    return None


def covered_paths(
    paths: list[str],
    statuses: dict[str, str],
    claims: dict[str, str],
    sources: ReviewSources,
) -> dict[str, str]:
    """Ścieżki ``unsupported`` z pokryciem w źródłach: ``{ścieżka: rodzaj}``.

    Ścieżka bez statusu to ``unsupported`` (jak w `final_review`). Werdykty
    ``contradicted``, ``private`` i ``invalid_evidence`` zostają recenzentowi —
    dosłowna obecność nie rozstrzyga sprzeczności ani prywatności.
    """

    out: dict[str, str] = {}
    for path in paths:
        if statuses.get(path, "unsupported") != "unsupported":
            continue
        kind = coverage(claims.get(path), sources)
        if kind is not None:
            out[path] = kind
    return out


def editor_findings(
    paths: list[str],
    statuses: dict[str, str],
    lines: list[str],
    sources: ReviewSources,
) -> dict:
    """Uwagi kontroli AI edytora po kodzie: ścieżki ``/why_points/<i>`` to linie.

    ``IN_SOURCE`` znika z listy, ``MOSTLY`` dostaje status ``weak`` (panel: bez
    „Usuń zdanie”, poza licznikiem). ``count`` liczy tylko uwagi, które zostały
    w mocy — to „N uwag” karty CV do klienta.
    """

    claims: dict[str, str] = {}
    for path in paths:
        index = path.rsplit("/", 1)[-1]
        if index.isdigit() and int(index) < len(lines):
            claims[path] = lines[int(index)]
    found = covered_paths(paths, statuses, claims, sources)
    kept = [path for path in paths if found.get(path) != IN_SOURCE]
    kept_statuses = {
        path: "weak" if found.get(path) == MOSTLY else statuses.get(path, "unsupported")
        for path in kept
    }
    return {
        "paths": kept,
        "statuses": kept_statuses,
        "count": sum(1 for path in kept if kept_statuses[path] != "weak"),
        "code_coverage": found,
    }
