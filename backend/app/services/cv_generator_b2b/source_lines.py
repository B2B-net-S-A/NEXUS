"""Model-selected line ranges resolve to original text, never retyped quotations."""

from pydantic import BaseModel, ConfigDict, Field

from app.services.cv_generator_b2b.source_quotes import source_quote_span


class SourceReference(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    start_line: int | None = Field(default=None, ge=1)
    end_line: int | None = Field(default=None, ge=1)
    # Accept the previous response format when validating historical fixtures.
    # The live provider schema below only asks for line references.
    quote: str | None = Field(default=None, min_length=1, max_length=16000)


def numbered_sources(sources: dict[str, str]) -> dict[str, list[dict]]:
    return {
        key: [
            {"line": index, "text": line}
            for index, line in enumerate(value.splitlines(keepends=True), 1)
        ]
        for key, value in sources.items()
    }


def reference_span(source: str, reference: SourceReference) -> tuple[int, int] | None:
    if reference.quote is not None:
        if reference.start_line is not None or reference.end_line is not None:
            return None
        return source_quote_span(source, reference.quote)
    first, last = reference.start_line, reference.end_line
    lines = source.splitlines(keepends=True)
    if first is None or last is None or not 1 <= first <= last <= len(lines):
        return None
    start = sum(map(len, lines[: first - 1]))
    end = start + sum(map(len, lines[first - 1 : last]))
    if not source[start:end].strip():
        return None
    return start, end


def line_response_schema(schema: dict) -> dict:
    """Ask the provider for range integers only; retain strict local validation."""
    from anthropic import transform_schema

    schema = transform_schema(schema)
    for definition in schema.get("$defs", {}).values():
        properties = definition.get("properties", {})
        if "start_line" not in properties or "end_line" not in properties:
            continue
        properties.pop("quote", None)
        for field in ("start_line", "end_line"):
            properties[field] = {"type": "integer"}
        definition["required"] = list(properties)
    return schema
