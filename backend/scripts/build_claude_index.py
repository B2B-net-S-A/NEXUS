"""Indeks reguł z plików ``docs/claude/<obszar>/*.md``: obszary w ``CLAUDE.md``, pliki z hooka.

``CLAUDE.md`` jest wklejany w całości do kontekstu każdej sesji Claude'a.
10.10.2026 miał 926 KB (ok. 530 tys. tokenów z okna 1 mln): sesja startowała
w połowie zapełniona, a po każdej zmianie pliku aplikacja wklejała go drugi
raz i sesje kończyły się błędem „Prompt is too long”, którego kompaktowanie
nie naprawiało. Dlatego reguły modułów leżą w ``docs/claude/``.

Do 25.10.2026 ``CLAUDE.md`` trzymał też listę wszystkich plików reguł. Dwa PR-y,
które dopisywały regułę w tym samym obszarze, dopisywały linię w tym samym
miejscu i miały konflikt w kolejce merge'ów (25.10: #2648 z #2653; 50 z 360
commitów maina od 15.10 dotykało ``CLAUDE.md``). Teraz w ``CLAUDE.md`` jest tylko
lista obszarów (zmienia się przy nowym katalogu), a pliki każdego obszaru
wypisują hooki ``SessionStart`` z ``.claude/settings.json`` (``--print --part N``).
Hook ma twardy limit 10 000 znaków kontekstu, dlatego wypis to same nazwy plików,
bez tytułów, w ``HOOK_PARTS`` częściach.

Użycie (z katalogu ``backend/``)::

    python3 scripts/build_claude_index.py            # przepisz listę obszarów w CLAUDE.md
    python3 scripts/build_claude_index.py --check    # tylko sprawdź (kod wyjścia 1 przy rozjeździe)
    python3 scripts/build_claude_index.py --print --part 1   # pliki reguł, część 1 z HOOK_PARTS (hook SessionStart)
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CLAUDE_MD = REPO_ROOT / "CLAUDE.md"
RULES_DIR = REPO_ROOT / "docs" / "claude"

START = "<!-- INDEKS:START (generuje backend/scripts/build_claude_index.py — nie edytuj ręcznie) -->"
END = "<!-- INDEKS:END -->"

# Limit całego CLAUDE.md w bajtach. Nowa reguła idzie do docs/claude/, nie tutaj.
MAX_CLAUDE_MD_BYTES = 40_000

# Wyjście hooka SessionStart ponad 10 000 znaków Claude Code zapisuje do pliku
# i daje sesji tylko ścieżkę i 2 000 znaków podglądu. Limit jest na hook, więc
# wypis idzie w HOOK_PARTS częściach (tyle hooków w .claude/settings.json).
# 25.10.2026 całość miała 9,4 tys. znaków i rosła o ~1,4 tys. tygodniowo
# (34 nowe pliki reguł w tygodniu); test pada, gdy część przekroczy limit.
HOOK_MAX_CHARS = 9_500
HOOK_PARTS = 3

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
        "Ikony paska, kategorie i wyciszenia, powiadomienia dla ról, maile do zespołu.",
    ),
    (
        "integracje",
        "Integracje",
        "Traffit, COMPASS, CloudTalk, kalendarz i rozmowy u klienta, prepy w Teams, archiwum pytań.",
    ),
    (
        "sprzedaz",
        "Sprzedaż (dawny Atlas)",
        "Uprawnienia Sprzedaży, kartoteka firm sprzedaży, szanse, „Kogo znamy”, daty per firma, "
        "powiązanie z klientem, leady, import z Atlasa.",
    ),
    (
        "ludzie",
        "Ludzie w NEXUSIE",
        "Moduły przeniesione z Compassa (bez Akademii) i sprzęt recepcji.",
    ),
    (
        "programy",
        "Programy",
        "Akademia i program praktykanta — oba ukryte z UI od 17.10.2026.",
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


def _check_tree() -> None:
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


def render() -> str:
    """Lista obszarów między znacznikami START/END (ze znacznikami)."""
    _check_tree()
    out: list[str] = [START, ""]
    for name, heading, when in GROUPS:
        if not any((RULES_DIR / name).glob("*.md")):
            continue
        out.append(f"- **{heading}** — `{name}/`: {when}")
    out += ["", END]
    return "\n".join(out)


def _area_lines() -> list[str]:
    _check_tree()
    lines = []
    for name, _heading, _when in GROUPS:
        stems = [p.stem for p in sorted((RULES_DIR / name).glob("*.md"))]
        if stems:
            lines.append(f"{name}/: " + ", ".join(stems))
    return lines


def render_files(part: int, parts: int = HOOK_PARTS) -> str:
    """Część ``part`` (od 1) wypisu plików reguł per obszar — wyjście hooka.

    Obszary w kolejności GROUPS, cięte na ``parts`` kolejnych kawałków
    o zbliżonej długości (obszar nie dzieli się między części).
    """
    if not 1 <= part <= parts:
        raise RuleIndexError(f"--part {part} poza zakresem 1..{parts}")
    lines = _area_lines()
    total = sum(len(line) + 1 for line in lines)
    chunks: list[list[str]] = [[] for _ in range(parts)]
    done = 0
    for line in lines:
        index = min(parts - 1, int(done * parts / total))
        chunks[index].append(line)
        done += len(line) + 1
    head = (
        f"Pliki reguł NEXUSA, część {part}/{parts} (docs/claude/<obszar>/<nazwa>.md; "
        "tytuł w pierwszej linii). Przed zmianą w obszarze przeczytaj pasujące pliki w całości."
    )
    return "\n".join([head, *chunks[part - 1]])


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
        if "--print" in argv:
            part = int(argv[argv.index("--part") + 1]) if "--part" in argv else 1
            print(render_files(part))
            return 0
        if "--check" in argv:
            if current() != render():
                print(
                    "Lista obszarów w CLAUDE.md nie zgadza się z docs/claude/. "
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
