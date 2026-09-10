"""Match PDF layout whitespace while retaining offsets in the original source."""

import re


def source_quote_span(source: str, quote: str) -> tuple[int, int] | None:
    if not quote.strip():
        return None
    start = source.find(quote)
    if start >= 0:
        return start, start + len(quote)
    # Preserve every non-whitespace character: no fuzzy matching, spelling,
    # punctuation, case, negation or date changes are accepted.
    normalized, offsets = [], []
    for match in re.finditer(r"\s+|\S", source):
        normalized.append(" " if match.group().isspace() else match.group())
        offsets.append(match.span())
    needle = " ".join(quote.split())
    start = "".join(normalized).find(needle)
    if start < 0:
        return None
    return offsets[start][0], offsets[start + len(needle) - 1][1]


def same_source_value(value: str, quote: str) -> bool:
    return " ".join(value.split()) in " ".join(quote.split())
