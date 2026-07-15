"""Repository gate: provider SDKs stay behind app.ai adapters."""

import ast
from pathlib import Path


def test_generative_provider_sdks_are_confined_to_ai_adapters():
    app_root = Path(__file__).parents[1] / "app"
    violations: list[str] = []
    for path in app_root.rglob("*.py"):
        relative = path.relative_to(app_root).as_posix()
        if relative.startswith("ai/"):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                providers = [
                    alias.name
                    for alias in node.names
                    if alias.name.split(".", 1)[0] in {"anthropic", "openai"}
                ]
            elif isinstance(node, ast.ImportFrom):
                providers = (
                    [node.module]
                    if (node.module or "").split(".", 1)[0] in {"anthropic", "openai"}
                    else []
                )
            else:
                providers = []
            if providers:
                violations.append(
                    f"{relative}:{getattr(node, 'lineno', 0)} imports {providers}"
                )
    assert violations == []
