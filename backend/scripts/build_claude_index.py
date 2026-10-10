"""Indeks reguł w ``CLAUDE.md`` powstaje z plików ``docs/claude/<obszar>/*.md``.

``CLAUDE.md`` jest wklejany w całości do kontekstu każdej sesji Claude'a.
10.10.2026 miał 926 KB (ok. 530 tys. tokenów z okna 1 mln): sesja startowała
w połowie zapełniona, a po każdej zmianie pliku aplikacja wklejała go drugi
raz i sesje kończyły się błędem „Prompt is too long”, którego kompaktowanie
nie naprawiało. Dlatego reguły modułów leżą w ``docs/claude/``, a w
``CLAUDE.md`` zostaje krótki rdzeń i ten indeks (tytuł pliku = pierwsza linia
``# …``; opcjonalna podpowiedź w linii ``<!-- indeks: … -->``).

Użycie (z katalogu ``backend/``)::

    python3 scripts/build_claude_index.py            # przepisz indeks w CLAUDE.md
    python3 scripts/build_claude_index.py --check    # tylko sprawdź (kod wyjścia 1 przy rozjeździe)
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CLAUDE_MD = REPO_ROOT / "CLAUDE.md"
RULES_DIR = REPO_ROOT / "docs" / "claude"

START = "<!-- INDEKS:START (generuje backend/scripts/build_claude_index.py — nie edytuj ręcznie) -->"
END = "<!-- INDEKS:END -->"
HINT_PREFIX = "<!-- indeks:"

# Limit całego CLAUDE.md w bajtach. Nowa reguła idzie do docs/claude/, nie tutaj.
MAX_CLAUDE_MD_BYTES = 40_000

# (katalog, nagłówek w indeksie, kiedy czytać). Kolejność = kolejność w indeksie.
GROUPS: tuple[tuple[str, str, str], ...] = (
    (
        "podstawy",
        "Podstawy, wdrożenie, CI",
        "Deploy przez Coolify, `/api/health`, zmienne środowiskowe, CI i kolejka merge'ów, "
        "obciążenie, klucze API kont serwisowych, obsługa błędów API.",
    ),
    (
        "uprawnienia",
        "Role i uprawnienia",
        "Role, dziewięć uprawnień, bramki sekcji i tras, zakres Delivery Leada, kto widzi kwoty, "
        "rejestracja kont.",
    ),
    (
        "ui",
        "Interfejs i design",
        "Design system i tokeny, responsywność, nazewnictwo w interfejsie, Ustawienia, pulpit, "
        "wygląd tabel.",
    ),
    (
        "rekrutacja-tworzenie",
        "Rekrutacja: tworzenie i Profil Championa",
        "`/jobs/new`, odczyt requestu, wiersze wymagań i umiejętności krytyczne, Profil Championa, "
        "przekazanie do searchu, pliki, portale ogłoszeń, strona kariery.",
    ),
    (
        "rekrutacja-tablica",
        "Rekrutacja: lista, Tablica, panel osoby",
        "Lista `/jobs`, Tablica, ruch kart i bramki, panel osoby, QC CV i Cpro, przegląd DL, "
        "podobne rekrutacje, przydział rekruterów, dzwonki przekazań.",
    ),
    (
        "screening-notatki",
        "Screening, notatki, stawki kandydata",
        "Formularz i widok screeningu, karta rekomendacji, rodzaje notatek, wzmianki, "
        "„Stawka od” i zmiana stawki w procesie.",
    ),
    (
        "kandydaci-wyszukiwanie",
        "Kandydaci i wyszukiwanie",
        "Lista i profil kandydata, słowa kluczowe, kolejność „Dopasowanie”, Talent Radar, "
        "kategorie kompetencji, indeks wektorowy, „Moi ludzie”, podgląd CV.",
    ),
    (
        "generator-cv",
        "Generator CV i automaty",
        "Generator CV, reguły CV klienta, zgoda RODO, interaktywne CV, automaty rekrutacji "
        "(nocny przegląd bazy, auto-match, auto-CV).",
    ),
    (
        "ai-jarvis",
        "AI i Jarvis",
        "Rejestr modeli per funkcja, brak limitów AI, Jarvis (narzędzia, przewodniki ekranów, "
        "pamięć, umowy ramowe).",
    ),
    (
        "klienci",
        "Klienci",
        "Profil i karta klienta, scalanie i usuwanie klientów, Historia zdarzeń, Centrum e-Zdrowia.",
    ),
    (
        "kontrakty",
        "Kontrakty i umowy B2B",
        "Generator umów B2B, cykl życia kontraktu, zakończenie i cofnięcie, synchronizacja "
        "kontrakt ↔ zamówienia, dokumenty, zakładki rejestru.",
    ),
    (
        "zamowienia",
        "Zamówienia i poczta zamówień",
        "Poczta zamówień i odczyt PDF per klient, zamówienia MD, kosztowe i okresowe, import "
        "zużycia MD, alerty Delivery Leada, instrukcja zamówień.",
    ),
    (
        "finanse-insights",
        "Finanse i Insights",
        "Finanse → Zmiany w zamówieniach, Zamówienia PDF, Insights (Rywalizacja, Zespół, Firma, raporty).",
    ),
    (
        "powiadomienia",
        "Powiadomienia i maile",
        "Dzwonek, kategorie i wyciszenia, powiadomienia dla ról, okienko „Czaty”, maile do zespołu.",
    ),
    (
        "integracje",
        "Integracje",
        "Traffit, COMPASS, CloudTalk, kalendarz i rozmowy u klienta, prepy w Teams, archiwum pytań.",
    ),
    (
        "programy",
        "Programy",
        "Akademia i program praktykanta („Telefony na dziś”).",
    ),
    (
        "audyty",
        "Audyty przekrojowe",
        "Reguły po audytach 22–25.09.2026 — przeczytaj przed zmianą w poczcie zamówień, MD, "
        "kontraktach, bezpieczeństwie albo integracjach.",
    ),
)


class RuleIndexError(RuntimeError):
    """Pliki reguł nie dają się złożyć w indeks (komunikat mówi, co poprawić)."""


def _title_and_hint(path: Path) -> tuple[str, str]:
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines or not lines[0].startswith("# "):
        raise RuleIndexError(
            f"{path.relative_to(REPO_ROOT)}: pierwsza linia ma być tytułem „# …” — z niej powstaje indeks."
        )
    hint = ""
    for line in lines[1:6]:
        stripped = line.strip()
        if stripped.startswith(HINT_PREFIX) and stripped.endswith("-->"):
            hint = stripped[len(HINT_PREFIX) : -3].strip()
            break
    return lines[0][2:].strip(), hint


def render() -> str:
    """Tekst indeksu między znacznikami START/END (ze znacznikami)."""
    known = {name for name, _, _ in GROUPS}
    found = {p.name for p in RULES_DIR.iterdir() if p.is_dir()}
    unknown = sorted(found - known)
    if unknown:
        raise RuleIndexError(
            "Nowy katalog w docs/claude/ bez opisu: "
            + ", ".join(unknown)
            + ". Dopisz go do GROUPS w backend/scripts/build_claude_index.py."
        )
    loose = sorted(p.name for p in RULES_DIR.glob("*.md"))
    if loose:
        raise RuleIndexError(
            "Pliki reguł leżą w docs/claude/<obszar>/, nie bezpośrednio w docs/claude/: " + ", ".join(loose)
        )

    out: list[str] = [START, ""]
    for name, heading, when in GROUPS:
        files = sorted((RULES_DIR / name).glob("*.md"))
        if not files:
            continue
        out.append(f"### {heading} — `docs/claude/{name}/`")
        out.append("")
        out.append(when)
        out.append("")
        for path in files:
            title, hint = _title_and_hint(path)
            line = f"- `{path.name}` — {title}"
            if hint:
                line += f" · {hint}"
            out.append(line)
        out.append("")
    out.append(END)
    return "\n".join(out)


def current(text: str | None = None) -> str:
    """Indeks zapisany dziś w CLAUDE.md (ze znacznikami)."""
    text = CLAUDE_MD.read_text(encoding="utf-8") if text is None else text
    start = text.find(START)
    end = text.find(END)
    if start == -1 or end == -1 or end < start:
        raise RuleIndexError("CLAUDE.md nie ma znaczników INDEKS:START / INDEKS:END.")
    return text[start : end + len(END)]


def write() -> bool:
    """Przepisz indeks w CLAUDE.md. Zwraca True, gdy plik się zmienił."""
    text = CLAUDE_MD.read_text(encoding="utf-8")
    old = current(text)
    new = render()
    if old == new:
        return False
    CLAUDE_MD.write_text(text.replace(old, new), encoding="utf-8")
    return True


def main(argv: list[str]) -> int:
    try:
        if "--check" in argv:
            if current() != render():
                print(
                    "Indeks w CLAUDE.md nie zgadza się z docs/claude/. "
                    "Uruchom: cd backend && python3 scripts/build_claude_index.py",
                    file=sys.stderr,
                )
                return 1
            return 0
        changed = write()
    except RuleIndexError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    size = CLAUDE_MD.stat().st_size
    print(f"CLAUDE.md: {'zaktualizowany' if changed else 'bez zmian'}, {size} B (limit {MAX_CLAUDE_MD_BYTES} B)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
