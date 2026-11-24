"""`.date()` na parametrze `now` to dzień w kalendarzu firmy tylko wtedy,
gdy wołający podał „teraz” w Warszawie.

Audyt 24.11.2026: `candidate_terms_apply.apply_answer(now=...)` robił
`now.date()`, a trasa podawała `datetime.now(timezone.utc)` — o 00:30
w Warszawie to jeszcze wczoraj. `test_no_utc_calendar_date` widzi „teraz”
w UTC tylko w obrębie jednej funkcji; gdy przychodzi parametrem, z samej
funkcji nie widać, w jakiej jest strefie. Dlatego funkcja z parametrem `now`
liczy dzień przez `business_date(now)` z `app.core.scheduling` albo najpierw
przelicza `now = now.astimezone(<strefa>)`. Gdy dzień UTC jest zamierzony,
linia albo linia nad nią niesie `# dzień UTC celowo: <powód>`.

Test nie importuje aplikacji — czyta pliki, więc działa też lokalnie.
"""

from __future__ import annotations

import ast
from pathlib import Path

from tests import test_no_utc_calendar_date as calendar_guard

APP_ROOT = Path(__file__).resolve().parent.parent / "app"
PARAM = "now"


def _is_zoned(value: ast.AST) -> bool:
    """`now.astimezone(<strefa inna niż UTC>)` — po nim `.date()` jest lokalne."""
    return any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "astimezone"
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == PARAM
        and bool(node.args)
        and not any(
            isinstance(arg, (ast.Attribute, ast.Name))
            and getattr(arg, "attr", getattr(arg, "id", None)) in ("utc", "UTC")
            for arg in node.args
        )
        for node in ast.walk(value)
    )


def _rezoned(func: ast.AST) -> bool:
    for node in ast.walk(func):
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == PARAM for t in node.targets
        ):
            if _is_zoned(node.value):
                return True
    return False


def _param_date_lines(source: str) -> list[int]:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    hits: set[int] = set()
    for func in ast.walk(tree):
        if not isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        args = func.args
        params = {a.arg for a in (*args.posonlyargs, *args.args, *args.kwonlyargs)}
        if PARAM not in params or _rezoned(func):
            continue
        for node in ast.walk(func):
            if (
                isinstance(node, ast.Call)
                and not node.args
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "date"
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == PARAM
            ):
                hits.add(node.lineno)
    return sorted(hits)


def find_violations(source: str) -> list[int]:
    original = source.splitlines()
    found = []
    for lineno in _param_date_lines(source):
        nearby = original[max(0, lineno - 2) : lineno]
        if any(calendar_guard.MARKER.search(line) for line in nearby):
            continue
        found.append(lineno)
    return found


def test_app_has_no_unmarked_date_of_now_parameter():
    problems = []
    for path in sorted(APP_ROOT.rglob("*.py")):
        for lineno in find_violations(path.read_text(encoding="utf-8")):
            problems.append(f"{path.relative_to(APP_ROOT.parent)}:{lineno}")
    assert not problems, (
        "`now.date()` na parametrze `now`: wołający może podać UTC, a o 00:30 "
        "w Warszawie to jeszcze wczoraj. Użyj `business_date(now)` z "
        "`app.core.scheduling` albo przelicz `now = now.astimezone(<strefa>)`. "
        "Jeśli dzień UTC jest zamierzony, dopisz w tej linii albo nad nią "
        "`# dzień UTC celowo: <powód>`.\n" + "\n".join(problems)
    )


# ── Sam detektor ────────────────────────────────────────────────────────────


def test_flags_date_of_now_parameter_and_respects_rezoning_and_marker():
    source = (
        "async def a(db, now):\n"
        "    return now.date()\n"
        "def b(*, now=None):\n"
        "    now = now or local_now()\n"
        "    today = now.date()\n"
        "def c(now):\n"
        "    now = now.astimezone(ZoneInfo(DEFAULT_TZ))\n"
        "    return now.date()\n"
        "def d(now):\n"
        "    now = now.astimezone(timezone.utc)\n"
        "    return now.date()\n"
        "def e(now):\n"
        "    # dzień UTC celowo: limit dostawcy liczony w UTC\n"
        "    return now.date()\n"
        "def f(now):\n"
        "    return business_date(now), now.isoformat()\n"
        "def g(moment):\n"
        "    return moment.date()\n"
        "def h():\n"
        "    now = local_now()\n"
        "    return now.date()\n"
        "def i(now):\n"
        "    return now.date(2026)\n"
    )
    assert find_violations(source) == [2, 5, 11]


def test_marker_without_reason_does_not_allow():
    source = "def a(now):\n    return now.date()  # dzień UTC celowo:\n"
    assert find_violations(source) == [2]
