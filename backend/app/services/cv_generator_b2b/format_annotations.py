"""Text runs for browsers, computed by the DOCX/HTML keyword matcher.

Runs carry literal strings instead of offsets: Python code points and JavaScript
UTF-16 indexes differ for emoji. Only annotate the already sanitized public view.
"""

from typing import Any

from app.services.cv_generator_b2b.docx_renderer import (
    compile_keyword_patterns,
    highlight_spans,
)


def text_annotations(public_payload: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    patterns = compile_keyword_patterns(public_payload.get("highlight_keywords") or [])
    result: dict[str, list[dict[str, Any]]] = {}

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                if key not in {"highlight_keywords", "text_runs"}:
                    visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)
            if value and all(isinstance(item, str) for item in value):
                visit(", ".join(value))
        elif isinstance(value, str) and value not in result:
            spans = highlight_spans(value, patterns)
            if not spans:
                return
            runs: list[dict[str, Any]] = []
            cursor = 0
            for start, end in spans:
                if start > cursor:
                    runs.append({"text": value[cursor:start], "bold": False})
                runs.append({"text": value[start:end], "bold": True})
                cursor = end
            if cursor < len(value):
                runs.append({"text": value[cursor:], "bold": False})
            result[value] = runs

    visit(public_payload)
    return result
