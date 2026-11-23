"""Parametry tras bez nieznanych argumentów FastAPI.

FastAPI 0.162 (Dependabot #3713) usunął przyjmowanie dowolnych argumentów
w ``Query()``/``Path()`` itd. ``Query("month", enum=[...])`` w
``app/api/reports.py`` wywracał wtedy import całej aplikacji
(``TypeError: Query() got an unexpected keyword argument 'enum'``).
Lista dozwolonych wartości ma iść przez ``json_schema_extra``.
"""

import ast
from pathlib import Path

from fastapi import FastAPI

APP_DIR = Path(__file__).resolve().parents[1] / "app"
PARAM_FUNCS = {"Query", "Path", "Body", "Form", "Header", "Cookie", "File"}
REMOVED_KWARGS = {"enum"}


def _offending_calls():
    for path in sorted(APP_DIR.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = (
                func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
            )
            if name not in PARAM_FUNCS:
                continue
            for kw in node.keywords:
                if kw.arg in REMOVED_KWARGS:
                    yield f"{path.relative_to(APP_DIR.parent)}:{node.lineno} {name}({kw.arg}=...)"


def test_no_route_param_uses_removed_extra_kwargs():
    offending = list(_offending_calls())
    assert not offending, "Użyj json_schema_extra={'enum': [...]}: " + ", ".join(
        offending
    )


def test_report_period_still_lists_allowed_values_in_openapi():
    from app.api.reports import router

    app = FastAPI()
    app.include_router(router)
    schema = app.openapi()
    params = schema["paths"]["/recruitment"]["get"]["parameters"]
    period = next(p for p in params if p["name"] == "period")
    assert period["schema"]["enum"] == ["week", "month", "quarter", "year"]
    assert period["schema"]["default"] == "month"
