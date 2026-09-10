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
    if " ".join(value.split()) in " ".join(quote.split()):
        return True

    # PDF soft hyphens and letter-only end-of-line hyphenation are layout.
    # Do not erase hyphens within lines, change case or concatenate dates.
    def unwrap(text):
        text = re.sub(r"(?<=[^\W\d_])[-\u00ad][ \t]*\r?\n[ \t]*(?=[^\W\d_])", "", text)
        return " ".join(text.split())

    return unwrap(value) in unwrap(quote)


_NUMERIC_DATE = (
    r"(?:\d{1,2}[./-]\d{1,2}[./-]\d{4}|"
    r"\d{4}[./-]\d{1,2}[./-]\d{1,2}|"
    r"\d{1,2}[./-]\d{4}|\d{4}[./-]\d{1,2}|\d{4})"
)
_END_DATE = rf"(?:{_NUMERIC_DATE}|now|present|current|obecnie|nadal|aktualnie)"
_COLUMN_RANGE = re.compile(
    rf"(?P<start>{_NUMERIC_DATE})\s*[-–—]\s*(?P<end>{_END_DATE})", re.I
)
_COLUMN_START = re.compile(rf"^\s*({_NUMERIC_DATE})\s*[-–—].*$")
_COLUMN_END = re.compile(rf"^\s*({_END_DATE})(?![\w./-])", re.I)


def source_column_dates(value: str, quote: str) -> bool:
    """Bind a split date column without changing either endpoint's precision.

    A PDF row may read '01.2020- Company\n12.2021 Responsibilities'. Only
    date fields can use this bounded layout rule. Evidence itself remains an
    exact source span; unrelated strings cannot be assembled from fragments.
    """
    date_range = _COLUMN_RANGE.fullmatch(value.strip())
    if date_range is None:
        return False
    lines = quote.splitlines()
    for index, line in enumerate(lines):
        start = _COLUMN_START.match(line)
        if start is None or start[1] != date_range["start"]:
            continue
        # Some PDF readers place the company on a line between the endpoints.
        for following in lines[index + 1 : index + 3]:
            end = _COLUMN_END.match(following)
            if end is not None:
                return end[1] == date_range["end"]
            if _COLUMN_START.match(following):
                break  # Never borrow an endpoint from the next employment row.
    return False


def source_role_text(quote: str) -> str:
    """Keep role prose in order when the date column interrupts its first lines."""
    lines = quote.splitlines(keepends=True)
    for index, line in enumerate(lines):
        start = _COLUMN_START.match(line.rstrip("\r\n"))
        if start is None or _COLUMN_RANGE.match(line.lstrip()):
            continue
        for following in range(index + 1, min(index + 3, len(lines))):
            if _COLUMN_START.match(lines[following].rstrip("\r\n")):
                break
            end = _COLUMN_END.match(lines[following])
            if end is not None:
                lines[following] = lines[following][end.end() :].lstrip(" \t")
                break
    return "".join(lines)
