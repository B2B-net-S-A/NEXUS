"""„Dziś" w kodzie aplikacji to dzień w kalendarzu firmy, nie dzień UTC.

Kontenery chodzą w UTC, a firma pracuje w Europe/Warsaw. Między północą
warszawską a UTC (1 h latem, 2 h zimą) `datetime.now(timezone.utc).date()`
i `CURRENT_DATE` bazy (sesja w UTC) zwracają jeszcze wczoraj. Tak alert
„za 7 dni" odpalał się dzień za wcześnie (`job_deadline_alerts`, PR #1778),
a raport anomalii widział kontrakt startujący dziś jako przyszły. Ruff łapie
`date.today()` (DTZ011), ale tych wzorców nie — pilnuje ich ten test.

Właściwe „dziś": `app.core.scheduling.business_today()` (w SQL — parametr
podany z Pythona). Gdy dzień UTC jest zamierzony (np. okno limitu u dostawcy
liczone w UTC), linia albo linia nad nią niesie komentarz
`# dzień UTC celowo: <powód>`.

Test nie importuje aplikacji — czyta pliki, więc działa też lokalnie.
"""

from __future__ import annotations

import io
import re
import tokenize
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parent.parent / "app"

MARKER = re.compile(r"#\s*dzień UTC celowo:\s*\S")

#: (wzorzec, opis dla komunikatu). Szukane w kodzie bez komentarzy, więc
#: wyjaśnienie „nie CURRENT_DATE” w komentarzu nie jest naruszeniem.
PATTERNS = (
    (
        re.compile(
            r"\bnow\(\s*(?:tz\s*=\s*)?(?:[\w.]*\.)?(?:utc|UTC)\s*\)\s*\.date\(\)"
        ),
        "datetime.now(timezone.utc).date()",
    ),
    (re.compile(r"\butcnow\(\)\s*\.date\(\)"), "datetime.utcnow().date()"),
    (re.compile(r"\bCURRENT_DATE\b|\bfunc\.current_date\b"), "SQL CURRENT_DATE"),
)


def _without_comments(source: str) -> str:
    """Źródło z komentarzami zastąpionymi spacjami (numery linii bez zmian)."""
    lines = source.splitlines(keepends=True)
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(source).readline))
    except (tokenize.TokenError, SyntaxError):
        return source
    for token in tokens:
        if token.type != tokenize.COMMENT:
            continue
        row, col = token.start
        line = lines[row - 1]
        end = col + len(token.string)
        lines[row - 1] = line[:col] + " " * (end - col) + line[end:]
    return "".join(lines)


def find_violations(source: str) -> list[tuple[int, str]]:
    """(numer linii, opis) dla każdego dnia UTC bez znacznika `# dzień UTC celowo:`."""
    original = source.splitlines()
    code = _without_comments(source)
    found: list[tuple[int, str]] = []
    for pattern, label in PATTERNS:
        for match in pattern.finditer(code):
            lineno = code.count("\n", 0, match.start()) + 1
            nearby = original[max(0, lineno - 2) : lineno]
            if any(MARKER.search(line) for line in nearby):
                continue
            found.append((lineno, label))
    return sorted(found)


def test_app_has_no_unmarked_utc_calendar_date():
    problems = []
    for path in sorted(APP_ROOT.rglob("*.py")):
        source = path.read_text(encoding="utf-8")
        for lineno, label in find_violations(source):
            rel = path.relative_to(APP_ROOT.parent)
            problems.append(f"{rel}:{lineno}: {label}")
    assert not problems, (
        "Data kalendarzowa liczona w UTC — o 00:30 w Warszawie to jeszcze "
        "wczoraj. Użyj `business_today()` z `app.core.scheduling` (w SQL: "
        "parametr z Pythona zamiast CURRENT_DATE). Jeśli dzień UTC jest "
        "zamierzony, dopisz w tej linii albo nad nią "
        "`# dzień UTC celowo: <powód>`.\n" + "\n".join(problems)
    )


# ── Sam detektor ────────────────────────────────────────────────────────────


def test_flags_utc_date_variants():
    source = (
        "a = datetime.now(timezone.utc).date()\n"
        "b = datetime.now(tz=timezone.utc).date()\n"
        "c = datetime.now(UTC).date()\n"
        "d = datetime.utcnow().date()\n"
        "e = datetime.now(\n    timezone.utc\n).date()\n"
        'f = "WHERE start_date > CURRENT_DATE"\n'
        "g = select(func.current_date())\n"
    )
    assert [lineno for lineno, _ in find_violations(source)] == [1, 2, 3, 4, 5, 8, 9]


def test_marker_on_same_line_or_line_above_allows():
    source = (
        "a = datetime.now(timezone.utc).date()  # dzień UTC celowo: okno dostawcy\n"
        "# dzień UTC celowo: limit dostawcy liczony w UTC\n"
        "b = datetime.now(timezone.utc).date()\n"
    )
    assert find_violations(source) == []


def test_marker_without_reason_does_not_allow():
    source = "a = datetime.now(timezone.utc).date()  # dzień UTC celowo:\n"
    assert [lineno for lineno, _ in find_violations(source)] == [1]


def test_comment_mentioning_pattern_is_not_a_violation():
    source = (
        "# `business_today()`, nie `CURRENT_DATE` ani now(timezone.utc).date()\n"
        "today = business_today()\n"
    )
    assert find_violations(source) == []


def test_timestamp_and_business_today_are_fine():
    source = (
        "stamp = datetime.now(timezone.utc)\n"
        "iso = datetime.now(timezone.utc).isoformat()\n"
        "today = business_today()\n"
        "current_date = today\n"
    )
    assert find_violations(source) == []
