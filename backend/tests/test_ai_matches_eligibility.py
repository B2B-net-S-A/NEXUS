"""`/ai-matches` must contain the same candidates `/recommendations` does.

Both endpoints rank the same corpus for the same job and both are reachable from
the job page. Until 2026-08-11 only `/recommendations` ran the eligibility
filter; `/ai-matches` checked the GLOBAL blacklist and nothing else, so an
active client blacklist, an NDA, a competitor conflict or a standing
hiring-manager veto passed through — into a list rendered with an "add to
pipeline" button on every row.

The frontend calls it unconditionally (`app/jobs/[id]/page.tsx`), with no flag
and no role gate, so this was the default view for every recruiter, not an
admin-only diagnostic.
"""

from __future__ import annotations

import ast
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]


def _calls_in(module_rel: str, func_name: str) -> set[str]:
    """Calls made by `func_name`, following one level into same-module helpers.

    A route handler often delegates: `/recommendations` calls the filter inside
    `_recommend_candidates_core`, not in the decorated function. Asserting only
    on the handler's direct calls would report a containment gap that does not
    exist — so resolve one hop through local helpers before deciding.
    """
    tree = ast.parse((BACKEND / module_rel).read_text(encoding="utf-8"))
    by_name = {
        n.name: n
        for n in ast.walk(tree)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    target = by_name.get(func_name)
    assert target is not None, f"{func_name} not found in {module_rel}"

    def direct(node) -> set[str]:
        """Names of functions called directly by `node`, in BOTH call forms.

        `filter_eligible_candidates(...)` and the module-qualified
        `pipeline_eligibility.filter_eligible_candidates(...)` must count the
        same. Matching only the bare name (`ast.Name`) ties this guard to one
        call SYNTAX rather than to the property it exists to protect.

        The failure that buys is a false ALARM, not a false pass: the assertion
        reads "the name appears among the calls", so an unrecognised call form
        makes it fail while the filter is demonstrably still there. That is the
        more corrosive direction. A guard that goes red on a safe refactor gets
        "fixed" by whoever is mid-refactor — and the cheapest fix is to weaken
        or delete the assertion. The guard then dies quietly on a day when
        nothing was actually wrong, and is missing on the day something is.
        """
        names: set[str] = set()
        for n in ast.walk(node):
            if not isinstance(n, ast.Call):
                continue
            if isinstance(n.func, ast.Name):
                names.add(n.func.id)
            elif isinstance(n.func, ast.Attribute):
                names.add(n.func.attr)
        return names

    calls = direct(target)
    for name in list(calls):
        helper = by_name.get(name)
        if helper is not None and helper is not target:
            calls |= direct(helper)
    return calls


def _endpoint_name(module_rel: str, path_fragment: str) -> str:
    """The handler decorated with a route containing `path_fragment`."""
    tree = ast.parse((BACKEND / module_rel).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for dec in node.decorator_list:
            src = ast.dump(dec)
            if path_fragment in src:
                return node.name
    raise AssertionError(f"no handler for {path_fragment} in {module_rel}")


def test_ai_matches_runs_the_same_eligibility_filter_as_recommendations():
    handler = _endpoint_name("app/api/matching.py", "ai-matches")
    calls = _calls_in("app/api/matching.py", handler)

    assert "filter_eligible_candidates" in calls, (
        "/ai-matches surfaces candidates the recruiter cannot assign — client "
        "blacklist, NDA, competitor conflict, hiring-manager veto — next to an "
        "add-to-pipeline button"
    )


def test_both_ranking_surfaces_share_the_containment_rule():
    """Guard the guard: neither surface may quietly drop the filter."""
    for module, fragment in (
        ("app/api/matching.py", "ai-matches"),
        ("app/api/recommendations.py", "recommendations"),
    ):
        handler = _endpoint_name(module, fragment)
        assert "filter_eligible_candidates" in _calls_in(module, handler), (
            f"{module}:{handler} no longer enforces assignment eligibility"
        )


# ── Wzmocnienie guardu (2026-08-20) ─────────────────────────────────────────
#
# Oba testy wyżej były ZIELONE przez cały czas trwania fail-opena, i to nie
# przez przypadek: odpowiadają na pytanie „czy nazwa występuje wśród wywołań",
# a awarią było „GDZIE występuje". Bramka stała pod `try`, którego `except
# Exception` nie kończył się `raise`, więc jej własny wyjątek spychał request
# do gałęzi tag-fallback — gałęzi, która bramki nie miała. Nazwa była na
# miejscu przez cały czas.
#
# To ta sama zgnilizna co przy `ephemeral-job-attribute-guard-rot`: guard
# ENUMERUJĄCY potrzebuje obok guardu WYKONUJĄCEGO. Testy wykonujące żyją
# w `test_ai_matches_fallback_eligibility.py` (idą przez HTTP i realną bazę);
# te dwa poniżej pilnują KSZTAŁTU, którego tamte nie widzą.


def _handler_node(module_rel: str, path_fragment: str) -> ast.AST:
    tree = ast.parse((BACKEND / module_rel).read_text(encoding="utf-8"))
    name = _endpoint_name(module_rel, path_fragment)
    for node in ast.walk(tree):
        if (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == name
        ):
            return node
    raise AssertionError(f"{name} not found in {module_rel}")


def _calls_within(node: ast.AST) -> set[str]:
    names: set[str] = set()
    for n in ast.walk(node):
        if not isinstance(n, ast.Call):
            continue
        if isinstance(n.func, ast.Name):
            names.add(n.func.id)
        elif isinstance(n.func, ast.Attribute):
            names.add(n.func.attr)
    return names


def _swallowing_tries(handler: ast.AST) -> list[ast.Try]:
    """`try` z gałęzią `except Exception`, która NIE kończy się `raise`.

    Taki blok zamienia dowolny wyjątek w cichą kontynuację. Wszystko, co pod nim
    stoi, jest z definicji fail-open.
    """
    out: list[ast.Try] = []
    for node in ast.walk(handler):
        if not isinstance(node, ast.Try):
            continue
        for h in node.handlers:
            exc = h.type
            catches_broad = exc is None or (
                isinstance(exc, ast.Name) and exc.id in {"Exception", "BaseException"}
            )
            if not catches_broad:
                continue
            reraises = h.body and isinstance(h.body[-1], ast.Raise)
            if not reraises:
                out.append(node)
                break
    return out


def test_gate_cannot_fail_open_into_the_ungated_branch():
    """Bramka nie może stać pod `except Exception`, który ją połyka.

    Stary guard („nazwa występuje") nie odróżniał „bramka działa" od „bramka
    działa w miejscu, z którego jej WŁASNA awaria ją omija". Ten odróżnia.
    """
    handler = _handler_node("app/api/matching.py", "ai-matches")
    for node in _swallowing_tries(handler):
        assert "filter_eligible_candidates" not in _calls_within(node), (
            "bramka dopuszczalności stoi pod `except Exception` bez `raise` — "
            "jej własna awaria (padnięty DB na candidate_conflicts, timeout, "
            "niekompletny `job`) zdegraduje request do gałęzi BEZ bramki"
        )


def test_tag_fallback_branch_gates_too():
    """Kod PO bloku `try` też musi wołać bramkę.

    Do fallbacku wchodzi się także CICHO: gdy `hits` jest puste, `if hits:` jest
    fałszywe i sterowanie po prostu tu schodzi — bez wyjątku, więc żaden test
    na awarii retrievalu tej drogi nie dotyka.

    Zawór bezpieczeństwa: gdy w handlerze nie ma już żadnego `try` (ktoś
    zunifikował gałęzie w jedną pulę z jedną bramką), test przechodzi —
    własności broni wtedy zestaw wykonujący. Guard czerwieniejący na bezpiecznym
    refaktorze zostaje „naprawiony" przez skasowanie, o czym ostrzega docstring
    tego pliku.
    """
    handler = _handler_node("app/api/matching.py", "ai-matches")
    body = list(getattr(handler, "body", []))
    try_idx = [i for i, stmt in enumerate(body) if isinstance(stmt, ast.Try)]
    if not try_idx:
        return  # gałęzie zunifikowane — patrz docstring

    after: set[str] = set()
    for stmt in body[try_idx[-1] + 1 :]:
        after |= _calls_within(stmt)

    assert "filter_eligible_candidates" in after, (
        "gałąź tag-fallback (kod po bloku `try`) nie przepuszcza puli przez "
        "bramkę dopuszczalności — wchodzi się w nią również przy pustym wyniku "
        "Qdranta, czyli bez żadnej awarii"
    )
