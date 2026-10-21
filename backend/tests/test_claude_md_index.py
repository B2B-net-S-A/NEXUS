"""``CLAUDE.md`` zostaje krótki, a jego indeks zgadza się z ``docs/claude/``.

``CLAUDE.md`` jest wklejany w całości do kontekstu każdej sesji Claude'a.
10.10.2026 miał 926 KB (ok. 530 tys. tokenów z okna 1 mln): każda sesja
startowała w połowie zapełniona, a po zmianie pliku aplikacja wklejała go
drugi raz — siedem sesji z 09.10 skończyło się błędem „Prompt is too long”,
którego kompaktowanie nie naprawiało. Plik urósł, bo każdy PR dopisywał do
niego sekcję (27 KB 01.08 → 926 KB 10.10).

Reguły modułów leżą teraz w ``docs/claude/<obszar>/``. Ten test pilnuje, żeby
nikt nie wrócił do dopisywania ich do ``CLAUDE.md``.
"""

from __future__ import annotations

from scripts import build_claude_index as index

_FIX = "Uruchom: cd backend && python3 scripts/build_claude_index.py"


def test_claude_md_stays_small() -> None:
    size = index.CLAUDE_MD.stat().st_size
    assert size <= index.MAX_CLAUDE_MD_BYTES, (
        f"CLAUDE.md ma {size} B (limit {index.MAX_CLAUDE_MD_BYTES} B). Ten plik trafia w całości "
        "do kontekstu każdej sesji — nową regułę zapisz w docs/claude/<obszar>/<plik>.md "
        "i odśwież indeks. " + _FIX
    )


def test_index_matches_rule_files() -> None:
    assert index.current() == index.render(), (
        "Indeks w CLAUDE.md nie zgadza się z plikami w docs/claude/ "
        "(nowy plik, zmieniony tytuł albo ręczna edycja indeksu). " + _FIX
    )


def test_every_rule_file_is_listed_once() -> None:
    files = sorted(index.RULES_DIR.rglob("*.md"))
    assert files, "docs/claude/ jest puste — reguły modułów zniknęły."
    listed = index.current()
    missing = [str(p.relative_to(index.REPO_ROOT)) for p in files if listed.count(f"`{p.name}`") < 1]
    assert not missing, "Pliki reguł poza indeksem: " + ", ".join(missing) + ". " + _FIX


def test_core_points_at_the_rules_directory() -> None:
    text = index.CLAUDE_MD.read_text(encoding="utf-8")
    assert "docs/claude/" in text
    assert "build_claude_index.py" in text, "CLAUDE.md ma mówić, jak dopisać regułę bez powiększania go."


def test_index_drops_only_trailing_dates_in_parentheses() -> None:
    strip = index._without_dates
    assert strip("Pliki rekrutacji (0428, 09.10.2026)") == "Pliki rekrutacji (0428)"
    assert strip("Kafelek „Do uzupełnienia” (21.10.2026)") == "Kafelek „Do uzupełnienia”"
    assert strip("Bez typów (decyzja Artura 25.09.2026)") == "Bez typów (decyzja Artura)"
    assert strip("Audyt (13–15.09.2026)") == "Audyt"
    assert strip("Kontakt (09.2026, migracja 0320)") == "Kontakt (migracja 0320)"
    # Data w środku nawiasu albo poza nim jest treścią — zostaje.
    assert strip("Kategorie (od 24.09.2026 CZTERY)") == "Kategorie (od 24.09.2026 CZTERY)"
    assert strip("Audyt 22.09.2026 — reguły") == "Audyt 22.09.2026 — reguły"
    # Nawias bez daty nie zmienia się, łącznie z brakiem spacji przed nim.
    assert strip("Czy sam(a) się zgłosił(a)?") == "Czy sam(a) się zgłosił(a)?"
    assert strip("Role (decyzje Artura 19.08 i 31.08)") == "Role (decyzje Artura 19.08 i 31.08)"
