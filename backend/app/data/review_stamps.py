"""Stemple przeglądu: przewodniki ekranów Jarvisa i instrukcja zamówień.

Oba mechanizmy robią to samo: zmiana pliku, który opisuje tekst dla
użytkownika, ma wymusić świadomy przegląd tego tekstu. Odcisk z chwili
ostatniego przeglądu leży w repo; test świeżości porównuje go z drzewem.

**Jeden plik stempla na jednostkę przeglądu** (24.09.2026). Wcześniej każdy
mechanizm miał jeden wspólny plik (``screen_guides/stamp.json``,
``procedures/orders_procedure_stamp.json``) plus wspólną datę w treści
instrukcji. Dwa PR-y ruszające RÓŻNE ekrany przepisywały ten sam plik, więc
w kolejce merge'ów drugi z nich dostawał konflikt albo nieaktualny stempel
złożony — 23–24.09.2026 test przewodników wyrzucił z kolejki 34 PR-y z 40,
test instrukcji zamówień 20. Teraz:

- ``screen_guides/stamps/<klucz ekranu>.json`` — odcisk wpisu przewodnika
  i każdego pliku z jego ``sources``;
- ``procedures/orders_stamps/<ścieżka z __ zamiast />.json`` — odcisk jednego
  pliku z ``ORDERS_LOGIC_SOURCES`` albo samej treści instrukcji.

PR ruszający ekran A przepisuje tylko stempel A, więc dwa PR-y z rozłącznymi
ekranami łączą się w dowolnej kolejności bez konfliktu i bez ponownego
stemplowania. Dwa PR-y ruszające TEN SAM ekran nadal się zderzą — i dobrze,
drugi autor musi przejrzeć przewodnik po zmianie pierwszego.

Data w instrukcji zamówień przestała być wspólnym stemplem: skrypt przestawia
ją tylko wtedy, gdy zmieniła się treść instrukcji (jej odcisk to osobny
stempel). Przegląd zakończony wnioskiem „zmiana nie dotyczy treści” daty nie
rusza — widoczna data może więc być starsza od ostatniego potwierdzenia, ale
nigdy nowsza, czyli błąd idzie w bezpieczną stronę.

Moduł jest czystą biblioteką standardową (bez pydantic i bez aplikacji), bo
używają go też ``scripts/check_stamps.py`` z hooka pre-commit i skrypty
stemplujące uruchamiane systemowym ``python3``.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Tuple

from app.data.procedures import ORDERS_LOGIC_SOURCES, ORDERS_PROCEDURE

#: Katalog główny repozytorium — ścieżki w stemplach są względne wobec niego.
REPO_ROOT = Path(__file__).resolve().parents[3]

GUIDES_REL = "backend/app/data/screen_guides/guides.json"
GUIDE_STAMPS_REL = "backend/app/data/screen_guides/stamps"
PROCEDURE_REL = f"backend/app/data/procedures/{ORDERS_PROCEDURE.filename}"
ORDERS_STAMPS_REL = "backend/app/data/procedures/orders_stamps"

GUIDES_HINT = (
    "\n\nCo zrobić:\n"
    "  1. Przeczytaj przewodnik w backend/app/data/screen_guides/guides.json\n"
    "     i sprawdź, czy nazwy przycisków i kroki nadal są prawdą.\n"
    "  2. Popraw wpis (albo nie popraw nic, jeśli zmiana go nie dotyczy).\n"
    "  3. cd backend && python3 scripts/stamp_screen_guides.py\n"
    "  4. Zacommituj przewodnik razem ze stemplem."
)

ORDERS_HINT = (
    "\n\nCo zrobić:\n"
    "  1. Otwórz app/data/procedures/"
    f"{ORDERS_PROCEDURE.filename} i sprawdź, czy nadal opisuje prawdę.\n"
    "  2. Popraw akapity, których zmiana dotyczy (albo nie popraw nic, jeśli nie dotyczy).\n"
    "  3. cd backend && python3 scripts/stamp_orders_procedure.py\n"
    "  4. Zacommituj instrukcję razem ze stemplem."
)

Checkable = Callable[[str], bool]


def _always(_relative: str) -> bool:
    return True


def file_sha256(root: Path, relative: str) -> str:
    """SHA-256 pliku albo ``"missing"`` (test pokaże nazwę zamiast wyjątku)."""
    path = root / relative
    if not path.is_file():
        return "missing"
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _json_sha256(obj: object) -> str:
    return hashlib.sha256(
        json.dumps(obj, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def _read_json(path: Path) -> Optional[dict]:
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict) -> bool:
    """Zapisz tylko przy zmianie — nieruszony stempel nie trafia do diffu."""
    text = json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    if path.is_file() and path.read_text(encoding="utf-8") == text:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return True


# ── przewodniki ekranów ─────────────────────────────────────────────────────


def load_raw_guides(root: Path = REPO_ROOT) -> Dict[str, dict]:
    """Wpisy ``guides.json`` po kluczu, bez walidacji (tę robi pydantic)."""
    raw = json.loads((root / GUIDES_REL).read_text(encoding="utf-8"))
    return {entry["key"]: entry for entry in raw}


def guide_stamp_path(key: str, root: Path = REPO_ROOT) -> Path:
    return root / GUIDE_STAMPS_REL / f"{key}.json"


def guide_fingerprint(key: str, entry: dict, root: Path = REPO_ROOT) -> dict:
    """Odcisk treści wpisu + odciski jego plików źródłowych.

    Treść wchodzi do odcisku, żeby edycja samego przewodnika też wymagała
    świadomego przestemplowania.
    """
    return {
        "guide": key,
        "entry": _json_sha256(entry),
        "sources": {rel: file_sha256(root, rel) for rel in entry.get("sources", [])},
    }


def guide_drift(
    root: Path = REPO_ROOT, checkable: Checkable = _always
) -> Dict[str, List[str]]:
    """Przewodniki, których stempel nie zgadza się z drzewem → powody."""
    drift: Dict[str, List[str]] = {}
    for key, entry in sorted(load_raw_guides(root).items()):
        stamp = _read_json(guide_stamp_path(key, root))
        if stamp is None:
            drift[key] = ["brak stempla"]
            continue
        current = guide_fingerprint(key, entry, root)
        reasons = []
        if stamp.get("entry") != current["entry"]:
            reasons.append("treść przewodnika")
        stamped_sources = stamp.get("sources", {})
        if set(stamped_sources) != set(current["sources"]):
            reasons.append("lista sources")
        reasons.extend(
            rel
            for rel, digest in current["sources"].items()
            if checkable(rel)
            and rel in stamped_sources
            and stamped_sources[rel] != digest
        )
        if reasons:
            drift[key] = reasons
    return drift


def orphan_guide_stamps(root: Path = REPO_ROOT) -> List[str]:
    """Stemple po przewodnikach, których już nie ma."""
    directory = root / GUIDE_STAMPS_REL
    if not directory.is_dir():
        return []
    keys = set(load_raw_guides(root))
    return sorted(p.stem for p in directory.glob("*.json") if p.stem not in keys)


def stamp_guides(
    root: Path = REPO_ROOT, only: Optional[Iterable[str]] = None
) -> List[str]:
    """Przestempluj przewodniki, które się rozjechały (albo tylko ``only``).

    Zwraca klucze, których plik stempla się zmienił. Stemple przewodników bez
    zmian zostają nietknięte — to one gwarantują brak konfliktów w kolejce.
    """
    guides = load_raw_guides(root)
    selected = set(only) if only else set(guides)
    unknown = sorted(selected - set(guides))
    if unknown:
        raise ValueError(f"Nie ma przewodników: {', '.join(unknown)}")
    changed = [
        key
        for key in sorted(selected)
        if _write_json(
            guide_stamp_path(key, root), guide_fingerprint(key, guides[key], root)
        )
    ]
    if not only:
        for key in orphan_guide_stamps(root):
            guide_stamp_path(key, root).unlink()
            changed.append(key)
    return changed


# ── instrukcja zamówień ─────────────────────────────────────────────────────

#: Linia z datą widoczna w treści instrukcji (DD.MM.RRRR, UAT M00-B04).
REVIEWED_LINE = re.compile(
    r"^> \*\*Zgodność z systemem sprawdzona:\*\* (\d{2})\.(\d{2})\.(\d{4})$",
    re.MULTILINE,
)


def orders_watched(sources: Sequence[str] = ORDERS_LOGIC_SOURCES) -> List[str]:
    """Pliki ze stemplem: logika zamówień + sama treść instrukcji."""
    return [*sources, PROCEDURE_REL]


def orders_stamp_path(relative: str, root: Path = REPO_ROOT) -> Path:
    return root / ORDERS_STAMPS_REL / (relative.replace("/", "__") + ".json")


def orders_drift(
    root: Path = REPO_ROOT,
    sources: Sequence[str] = ORDERS_LOGIC_SOURCES,
    checkable: Checkable = _always,
) -> List[str]:
    """Pliki (w tym treść instrukcji), których stempel nie zgadza się z drzewem."""
    drifted = []
    for rel in orders_watched(sources):
        if not checkable(rel):
            continue
        stamp = _read_json(orders_stamp_path(rel, root))
        if stamp is None or stamp.get("sha256") != file_sha256(root, rel):
            drifted.append(rel)
    return sorted(drifted)


def stamped_orders_sources(root: Path = REPO_ROOT) -> List[str]:
    """Ścieżki, dla których leży stempel (z pola ``source``, nie z nazwy)."""
    directory = root / ORDERS_STAMPS_REL
    if not directory.is_dir():
        return []
    return sorted(
        json.loads(p.read_text(encoding="utf-8"))["source"]
        for p in directory.glob("*.json")
    )


def restamp_procedure_date(root: Path, today: date) -> bool:
    """Przestaw datę przeglądu w treści. ``True``, jeśli coś zmieniono."""
    path = root / PROCEDURE_REL
    content = path.read_text(encoding="utf-8")
    if len(REVIEWED_LINE.findall(content)) != 1:
        raise ValueError(
            f"Nie znalazłem dokładnie jednej linii z datą przeglądu w {path.name}.\n"
            "Instrukcja musi zawierać dokładnie jedną linię w formacie:\n"
            "  > **Zgodność z systemem sprawdzona:** DD.MM.RRRR"
        )
    replacement = f"> **Zgodność z systemem sprawdzona:** {today.strftime('%d.%m.%Y')}"
    updated = REVIEWED_LINE.sub(replacement, content)
    if updated == content:
        return False
    path.write_text(updated, encoding="utf-8")
    return True


def stamp_orders(
    root: Path = REPO_ROOT,
    sources: Sequence[str] = ORDERS_LOGIC_SOURCES,
    only: Optional[Iterable[str]] = None,
    today: Optional[date] = None,
) -> Tuple[List[str], bool]:
    """Przestempluj rozjechane pliki. Zwraca ``(zmienione, czy_przestawiono_datę)``.

    Datę w treści przestawia tylko edycja samej instrukcji — przegląd, po
    którym treść się nie zmieniła, nie dotyka wspólnego pliku, więc nie
    zderza się z przeglądem innego PR-a.
    """
    watched = orders_watched(sources)
    selected = sorted(set(only)) if only else orders_drift(root, sources)
    unknown = sorted(set(selected) - set(watched))
    if unknown:
        raise ValueError(f"Poza listą obserwowanych: {', '.join(unknown)}")
    missing = [rel for rel in selected if file_sha256(root, rel) == "missing"]
    if missing:
        raise FileNotFoundError("\n".join(missing))

    date_bumped = False
    if PROCEDURE_REL in selected:
        date_bumped = restamp_procedure_date(root, today or date.today())
    changed = [
        rel
        for rel in selected
        if _write_json(
            orders_stamp_path(rel, root),
            {"source": rel, "sha256": file_sha256(root, rel)},
        )
    ]
    if not only:
        keep = {orders_stamp_path(rel, root).name for rel in watched}
        for path in sorted((root / ORDERS_STAMPS_REL).glob("*.json")):
            if path.name not in keep:
                changed.append(json.loads(path.read_text(encoding="utf-8"))["source"])
                path.unlink()
    return changed, date_bumped
